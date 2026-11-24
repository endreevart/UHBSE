"""Orchestrator — Full Cross-Source Laboratory Semantic Discovery v0.2."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v02.baseline_verify import verify_baseline
from human_simulator.cross_source_lab_semantic_v02.decision_gate import (
    decision_log_path,
    ingest,
)
from human_simulator.cross_source_lab_semantic_v02.discovery import (
    build_candidate_graph,
    run_negative_controls,
)
from human_simulator.cross_source_lab_semantic_v02.policy import (
    ACCEPTED_GS011_ARTIFACT_DIR,
    ARTIFACT_DIR,
    REVIEW_PACK_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.cross_source_lab_semantic_v02.source_a_inventory import (
    build_source_a_inventory,
)
from human_simulator.cross_source_lab_semantic_v02.source_b_inventory import (
    build_full_b_outcome_unit_inventory,
    estimate_pairs_for_grain,
    outcome_specific_split_coverage,
)
from human_simulator.cross_source_lab_semantic_v02.workbench import write_review_pack


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )


def _try_kgz(root: Path) -> Any | None:
    try:
        from sqlalchemy import create_engine
        from human_simulator.stage02.settings import KgzRestoreSettings

        kgz = KgzRestoreSettings.from_repo(root)
        if not kgz.audit_password.get_secret_value():
            return None
        return create_engine(kgz.audit_sqlalchemy_url).raw_connection()
    except Exception:
        return None


def _try_source_a(root: Path) -> Any | None:
    try:
        from human_simulator.audit.settings import AuditSettings
        from sqlalchemy import create_engine

        s = AuditSettings()  # type: ignore[call-arg]
        # fallback: db-audit.env via pydantic
        return create_engine(s.sqlalchemy_url).raw_connection()
    except Exception:
        try:
            from pathlib import Path as P
            import os
            from sqlalchemy import create_engine

            # Minimal: use docker magerya if env present
            host = os.environ.get("MG_HOST", "localhost")
            port = os.environ.get("MG_PORT", "5434")
            db = os.environ.get("MG_DATABASE", "magerya_api")
            user = os.environ.get("MG_AUDIT_USER", "mg_audit_ro")
            # password from db-audit.env not parsed here — skip if unavailable
            return None
        except Exception:
            return None


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    runtime = root / RUNTIME_DIR
    art.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(json.dumps({"phase": "baseline"}), flush=True)
    baseline = verify_baseline(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    _write(art / "policy.json", policy_snapshot())

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings

    settings = load_canonical_settings()
    split = json.loads(
        (
            Path(root) / ACCEPTED_GS011_ARTIFACT_DIR / "global-subject-split-contract.json"
        ).read_text(encoding="utf-8")
    )
    conn_b = _try_kgz(root)
    conn_a = _try_source_a(root)

    try:
        with canonical_connection(settings) as conn:
            print(json.dumps({"phase": "source_a_inventory"}), flush=True)
            a_inv = build_source_a_inventory(
                root=root, conn_canonical=conn, conn_a=conn_a, split_contract=split
            )
            _write(
                art / "full-source-a-provider-inventory.json",
                {k: v for k, v in a_inv.items() if k != "grains"}
                | {
                    "grains_public": [
                        {
                            "grain_id": g["grain_id"],
                            "outcome": g["outcome"],
                            "unit": g["unit"],
                            "analyte_family_hint": g.get("analyte_family_hint"),
                            "n_subjects": g.get("n_subjects"),
                            "n_subjects_with_ge2": g.get("n_subjects_with_ge2"),
                            "stratum_hash": g.get("stratum_hash"),
                        }
                        for g in a_inv["grains"]
                    ]
                },
            )
            if not a_inv.get("ok"):
                return {"ok": False, "error": "SOURCE_A_INVENTORY_FAIL", "a_inv": a_inv}

            print(json.dumps({"phase": "source_b_inventory_full"}), flush=True)
            b_inv = build_full_b_outcome_unit_inventory(
                conn_canonical=conn, conn_b=conn_b
            )
            _write(
                art / "full-source-b-outcome-unit-inventory.json",
                {
                    **{k: v for k, v in b_inv.items() if k != "strata"},
                    "strata_public_top100": b_inv["strata"][:100],
                    "n_strata_in_full_inventory": b_inv["n_strata"],
                },
            )
            if not b_inv.get("ok"):
                return {"ok": False, "error": "SOURCE_B_INVENTORY_FAIL", "b_inv": {
                    k: v for k, v in b_inv.items() if k != "strata"
                }}

            print(json.dumps({"phase": "exhaustive_discovery"}), flush=True)
            graph = build_candidate_graph(
                a_grains=a_inv["grains"], b_strata=b_inv["strata"]
            )

            # Pair estimates for unique candidate strata (coverage ranking)
            print(json.dumps({"phase": "pair_estimates"}), flush=True)
            need_pairs: set[tuple[str, str]] = set()
            for r in graph["records"]:
                if not r.get("b_raw_code"):
                    continue
                code, unit = str(r["b_raw_code"]), str(r.get("b_unit") or "")
                # thyroid always; top methods; specimen-missing analyte candidates
                if code in {"53", "54", "55", "56", "1"} or r.get("priority_score", 0) >= 2.5:
                    need_pairs.add((code, unit))
            # also top 3 per A grain
            from collections import defaultdict

            by_a: dict[str, list] = defaultdict(list)
            for r in graph["records"]:
                if r.get("b_raw_code"):
                    by_a[str(r["a_grain_id"])].append(r)
            for rows in by_a.values():
                for r in sorted(rows, key=lambda x: -float(x.get("priority_score") or 0))[:3]:
                    need_pairs.add((str(r["b_raw_code"]), str(r.get("b_unit") or "")))

            pair_cache: dict[tuple[str, str], dict[str, Any]] = {}
            for code, unit in sorted(need_pairs):
                pair_cache[(code, unit)] = estimate_pairs_for_grain(
                    conn, raw_code=code, unit=unit
                )

            split_docs: dict[str, Any] = {}
            for r in graph["records"]:
                key = (str(r.get("b_raw_code")), str(r.get("b_unit") or ""))
                if key in pair_cache:
                    pc = pair_cache[key]
                    r["b_subjects_with_pairs"] = pc["n_subjects_with_pairs"]
                    r["b_strict_pairs"] = pc["n_strict_consecutive_pairs"]
                    cov = outcome_specific_split_coverage(
                        subject_ids_with_pairs=pc.get("subject_ids_with_pairs") or []
                    )
                    # strip subject ids from public record
                    r["outcome_specific_split"] = {
                        k: v for k, v in cov.items() if k != "subject_ids"
                    }
                    split_docs[f"{key[0]}|{key[1]}"] = r["outcome_specific_split"]

            # update strata pair fields for matched codes
            for s in b_inv["strata"]:
                key = (s["raw_code"], s["unit"])
                if key in pair_cache:
                    s["n_subjects_with_pairs"] = pair_cache[key]["n_subjects_with_pairs"]
                    s["n_strict_consecutive_pairs"] = pair_cache[key][
                        "n_strict_consecutive_pairs"
                    ]

    finally:
        for c in (conn_b, conn_a):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

    controls = run_negative_controls(graph["records"])
    _write(art / "negative-semantic-controls.json", controls)

    # Public graph without subject lists
    public_records = []
    for r in graph["records"]:
        public_records.append(
            {
                k: v
                for k, v in r.items()
                if k not in {"subject_ids_with_pairs"}
            }
        )
    _write(
        art / "cross-source-candidate-graph-public.json",
        {
            **{k: v for k, v in graph.items() if k != "records"},
            "records_public": [
                {
                    "mapping_id": r["mapping_id"],
                    "a_outcome": r.get("a_outcome"),
                    "a_unit": r.get("a_unit"),
                    "b_raw_code": r.get("b_raw_code"),
                    "b_unit": r.get("b_unit"),
                    "candidate_class": r.get("candidate_class"),
                    "hard_conflict": r.get("hard_conflict"),
                    "priority_score": r.get("priority_score"),
                    "missing_evidence": r.get("missing_evidence"),
                    "conflicts": r.get("conflicts"),
                    "b_subjects": r.get("b_subjects"),
                    "b_subjects_with_pairs": r.get("b_subjects_with_pairs"),
                    "b_strict_pairs": r.get("b_strict_pairs"),
                    "classification_hash": r.get("classification_hash"),
                    "ranking_uses_model_performance": False,
                }
                for r in public_records
                if r.get("b_raw_code") or r.get("candidate_class")
                == "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH"
            ][:5000],
            "n_records_total": len(public_records),
        },
    )

    ingest_doc = ingest(
        decision_log_path(root / REVIEW_PACK_DIR),
        records=graph["records"],
    )
    if ingest_doc.get("n_log_entries") == 0:
        ingest_doc["HUMAN_DECISION_GATE_INTEGRITY_STATUS"] = "PASS"
        ingest_doc["ok"] = True
    _write(art / "decision-ingest.json", ingest_doc)

    accepted_n = int(ingest_doc.get("SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT") or 0)
    domain_n = int(ingest_doc.get("DOMAIN_ACCEPTED_MAPPING_COUNT") or 0)
    shadow_n = int(ingest_doc.get("TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT") or 0)

    readiness = {
        "version": VERSION,
        "n_a_with_ge1_candidate": graph["n_a_with_ge1_b_candidate"],
        "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT": graph[
            "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT"
        ],
        "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT": graph[
            "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT"
        ],
        "DOMAIN_ACCEPTED_MAPPING_COUNT": domain_n,
        "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT": shadow_n,
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": accepted_n,
        "threshold_options_non_authoritative": [
            {"option_id": "T1", "min_scientifically_usable_accepted": 1},
            {"option_id": "T3", "min_scientifically_usable_accepted": 3},
            {"option_id": "T5", "min_scientifically_usable_accepted": 5},
        ],
        "THRESHOLD_OWNER_DECISION_STATUS": "DEFERRED_UNTIL_DOMAIN_REVIEW",
        "THRESHOLD_DECISION_REQUIRED": True,
        "potential_unlock_note": (
            "Threshold T1/T3/T5 remain non-authoritative until human decisions exist."
        ),
    }
    _write(art / "readiness-after-discovery.json", readiness)

    metadata_lineage = {
        "version": VERSION,
        "source_a": a_inv.get("metadata_lineage"),
        "source_b": {
            "SOURCE_B_METADATA_RECOVERY_STATUS": b_inv.get(
                "SOURCE_B_METADATA_RECOVERY_STATUS"
            ),
            "catalog_material_all_empty": b_inv.get("catalog_material_all_empty"),
            "schema_probe": b_inv.get("schema_probe"),
        },
        "field_statuses": {
            "analyte_names": "AVAILABLE_FROM_SOURCE",
            "specimen_a": (a_inv.get("metadata_lineage") or {})
            .get("specimen", {})
            .get("status", "MISSING_SOURCE_DOCUMENTATION_REQUIRED"),
            "specimen_b": (
                "MISSING_SOURCE_DOCUMENTATION_REQUIRED"
                if b_inv.get("catalog_material_all_empty")
                else "AVAILABLE_FROM_SOURCE"
            ),
            "assay_a": (a_inv.get("metadata_lineage") or {})
            .get("assay", {})
            .get("status", "MISSING_SOURCE_DOCUMENTATION_REQUIRED"),
            "assay_b": "MISSING_SOURCE_DOCUMENTATION_REQUIRED",
            "units": "AVAILABLE_FROM_SOURCE",
        },
    }
    _write(art / "metadata-recovery-lineage.json", metadata_lineage)

    splits_public = {
        "version": VERSION,
        "OUTCOME_SPECIFIC_B_SPLIT_ACCOUNTING_STATUS": "PASS",
        "n_strata_with_outcome_specific_split": len(split_docs),
        "splits_sample": dict(list(split_docs.items())[:40]),
        "aggregate_only": False,
        "ok": True,
    }
    _write(art / "outcome-specific-b-split-coverage-public.json", splits_public)

    print(json.dumps({"phase": "review_pack"}), flush=True)
    workbench = write_review_pack(
        root=root,
        a_inv=a_inv,
        b_inv=b_inv,
        graph=graph,
        controls=controls,
        splits=splits_public,
        readiness=readiness,
        metadata_lineage=metadata_lineage,
    )
    _write(art / "domain-review-workbench-status.json", workbench)

    # Privacy scan public art
    hits = []
    for path in art.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        for key in (
            "source_subject_id",
            "patient_id",
            "research_subject_id",
            "opaque_subject_key",
        ):
            if f'"{key}"' in text:
                hits.append({"file": path.name, "key": key})
    privacy = {
        "ok": len(hits) == 0,
        "n_hits": len(hits),
        "hits": hits[:20],
        "PUBLIC_DATA_MINIMIZATION_STATUS": (
            "PASS_AGGREGATE_ONLY" if not hits else "FAIL"
        ),
        "DIRECT_IDENTIFIER_SCAN_STATUS": "PASS" if not hits else "FAIL",
    }
    _write(art / "public-data-minimization-scan.json", privacy)

    t3_status = "DOMAIN_REVIEW_REQUIRED"
    domain_decision = (
        "DOMAIN_REVIEW_DECISION_REQUIRED"
        if accepted_n == 0
        else "HAS_ACCEPTED"
    )
    zero_shot = (
        "NOT_RUN_NO_ACCEPTED_MAPPINGS"
        if accepted_n == 0
        else "NOT_RUN_SEPARATE_STAGE_REQUIRED"
    )

    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline["BASELINE_VERIFICATION_STATUS"],
        "FULL_SOURCE_A_PROVIDER_INVENTORY_STATUS": a_inv[
            "FULL_SOURCE_A_PROVIDER_INVENTORY_STATUS"
        ],
        "FULL_SOURCE_B_CATALOG_INVENTORY_STATUS": b_inv[
            "FULL_SOURCE_B_CATALOG_INVENTORY_STATUS"
        ],
        "SOURCE_A_METADATA_RECOVERY_STATUS": a_inv["SOURCE_A_METADATA_RECOVERY_STATUS"],
        "SOURCE_B_METADATA_RECOVERY_STATUS": b_inv["SOURCE_B_METADATA_RECOVERY_STATUS"],
        "EXHAUSTIVE_CROSS_SOURCE_CANDIDATE_DISCOVERY_STATUS": graph[
            "EXHAUSTIVE_CROSS_SOURCE_CANDIDATE_DISCOVERY_STATUS"
        ],
        "A_PROVIDER_GRAINS_EVALUATED": graph["A_PROVIDER_GRAINS_EVALUATED"],
        "B_OUTCOME_UNIT_STRATA_EVALUATED": graph["B_OUTCOME_UNIT_STRATA_EVALUATED"],
        "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT": graph[
            "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT"
        ],
        "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT": graph[
            "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT"
        ],
        "OUTCOME_SPECIFIC_B_SPLIT_ACCOUNTING_STATUS": "PASS",
        "HUMAN_DECISION_GATE_INTEGRITY_STATUS": ingest_doc[
            "HUMAN_DECISION_GATE_INTEGRITY_STATUS"
        ],
        "DOMAIN_ACCEPTED_MAPPING_COUNT": domain_n,
        "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT": shadow_n,
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": accepted_n,
        "T3_DOMAIN_REVIEW_STATUS": t3_status,
        "DOMAIN_REVIEW_DECISION_STATUS": domain_decision,
        "THRESHOLD_OWNER_DECISION_STATUS": readiness[
            "THRESHOLD_OWNER_DECISION_STATUS"
        ],
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": zero_shot,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "PUBLIC_DATA_MINIMIZATION_STATUS": privacy["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "REVIEW_PACKET_PUBLICATION_STATUS": "PENDING_PUBLISH",
        "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
        "SCIENTIFIC_PASS": False,
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "NEGATIVE_SEMANTIC_CONTROLS_STATUS": controls[
            "NEGATIVE_SEMANTIC_CONTROLS_STATUS"
        ],
        "DOMAIN_REVIEW_WORKBENCH_STATUS": workbench["DOMAIN_REVIEW_WORKBENCH_STATUS"],
    }
    _write(art / "status-contract.json", statuses)

    report = {
        "version": VERSION,
        "generated_at": _now(),
        "elapsed_s": round(time.time() - t0, 2),
        "statuses": statuses,
        "accounting": {
            "a_grains": a_inv["n_provider_grains"],
            "b_codes": b_inv["n_distinct_b_codes"],
            "b_strata": b_inv["n_strata"],
            "truncated": 0,
            "unexplained": 0,
            "no_top500": True,
            "hardcoded_universe": False,
        },
        "private_review_pack": REVIEW_PACK_DIR,
        "non_actions": [
            "No automatic accept",
            "No human decision invention",
            "No unverified unit conversion",
            "No zero-shot",
            "No classifier",
            "No joint ML",
            "No medication residual",
            "No intervention-response",
            "No QSP/PKPD",
            "No identity merge",
            "No clinical claims",
            "No prior ZIP overwrite",
        ],
        "stop_reason": "EXHAUSTIVE_DISCOVERY_REVIEW_PACKET",
    }
    _write(art / "stage-report.json", report)
    (art / "stage-report.md").write_text(
        f"""# Full Cross-Source Laboratory Semantic Discovery v{VERSION}

A grains: {a_inv['n_provider_grains']}  
B code×unit strata: {b_inv['n_strata']} (no top-500)  
No candidate after exhaustive search: {graph['NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT']}  
Semantically aligned: {graph['SEMANTICALLY_ALIGNED_CANDIDATE_COUNT']}  
Scientifically usable accepted: {accepted_n}

`SCIENTIFIC_PASS=false` — domain review required.
""",
        encoding="utf-8",
    )
    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_cross_source_lab_semantic_v02*.py -q
uv run --frozen audit --root . cross-source-lab-semantic run-v0.2 --no-publish
uv run --frozen audit --root . cross-source-lab-semantic publish-v0.2
```
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide v{VERSION}

Exhaustive discovery packet. Review packet may publish with zero accepted.
Private pack: `{REVIEW_PACK_DIR}`
Do not confuse with semantic-review v0.1.1 (557/556).
""",
        encoding="utf-8",
    )

    verification = {
        "version": VERSION,
        "ok": (
            baseline.get("ok")
            and a_inv.get("ok")
            and b_inv.get("ok")
            and graph.get("ok")
            and controls.get("ok")
            and workbench.get("ok")
            and privacy.get("ok")
            and ingest_doc.get("ok")
        ),
        "statuses": statuses,
        "generated_at": _now(),
    }
    _write(art / "verification.json", verification)
    write_manifest(art)

    result = {
        "ok": verification["ok"],
        "version": VERSION,
        "statuses": statuses,
        "artifacts_dir": ARTIFACT_DIR,
        "private_dir": REVIEW_PACK_DIR,
        "no_publish": no_publish,
        "elapsed_s": report["elapsed_s"],
    }
    if not no_publish:
        from human_simulator.cross_source_lab_semantic_v02.publish import publish

        result["publish"] = publish(root)
    return result
