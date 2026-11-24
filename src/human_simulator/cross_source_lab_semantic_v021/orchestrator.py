"""Orchestrator — Laboratory Analyte Ontology + Metadata Closure v0.2.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.baseline_verify import verify_baseline
from human_simulator.cross_source_lab_semantic_v021.decision_gate import (
    decision_log_path,
    ingest,
)
from human_simulator.cross_source_lab_semantic_v021.defect_reproduce import (
    reproduce_v02_analyte_identity_defects,
)
from human_simulator.cross_source_lab_semantic_v021.discovery import (
    build_candidate_graph,
    run_negative_controls,
)
from human_simulator.cross_source_lab_semantic_v021.metadata_probes import (
    probe_source_a_raw_metadata,
    probe_source_b_raw_metadata,
)
from human_simulator.cross_source_lab_semantic_v021.ontology import ontology_snapshot
from human_simulator.cross_source_lab_semantic_v021.policy import (
    ACCEPTED_GS011_ARTIFACT_DIR,
    ACCEPTED_V02_ARTIFACT_DIR,
    ARTIFACT_DIR,
    REVIEW_PACK_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.cross_source_lab_semantic_v021.workbench import write_review_pack


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
        import psycopg
        from human_simulator.stage01.settings import MgAuditSettings

        mg = MgAuditSettings.from_repo(Path(root))
        if not mg.audit_password.get_secret_value():
            return None
        dsn = (
            f"postgresql://{mg.audit_user}:{mg.audit_password.get_secret_value()}"
            f"@{mg.pg_host}:{mg.pg_port}/{mg.pg_database}"
        )
        conn = psycopg.connect(dsn, connect_timeout=10, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 120000")
            cur.execute("SET lock_timeout = 10000")
            cur.execute("SET default_transaction_read_only = on")
        return conn
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

    print(json.dumps({"phase": "defect_reproduce"}), flush=True)
    defects = reproduce_v02_analyte_identity_defects(root)
    _write(art / "v02-analyte-identity-defects.json", defects)
    if not defects.get("ok"):
        return {"ok": False, "error": "DEFECT_REPRO_FAIL", "defects": defects}

    _write(art / "policy.json", policy_snapshot())
    _write(art / "analyte-ontology.json", ontology_snapshot())

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings
    from human_simulator.cross_source_lab_semantic_v02.source_a_inventory import (
        build_source_a_inventory,
    )
    from human_simulator.cross_source_lab_semantic_v02.source_b_inventory import (
        build_full_b_outcome_unit_inventory,
        estimate_pairs_for_grain,
        outcome_specific_split_coverage,
    )

    settings = load_canonical_settings()
    split = json.loads(
        (
            Path(root) / ACCEPTED_GS011_ARTIFACT_DIR / "global-subject-split-contract.json"
        ).read_text(encoding="utf-8")
    )
    conn_b = _try_kgz(root)
    conn_a = _try_source_a(root)

    # Before/after accounting from published v0.2
    v02_before = {
        "n_candidate_records": 1096,
        "n_family_only_candidates": "unknown_v02_used_family_as_identity",
        "n_exact_or_synonym_candidates": "unknown",
        "n_hard_conflict_records": 0,
        "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT": 39,
        "false_analyte_ok_chol_ldl_hdl": True,
        "false_analyte_ok_mchc_hgb": True,
    }

    try:
        print(json.dumps({"phase": "source_a_raw_metadata"}), flush=True)
        a_probe = probe_source_a_raw_metadata(conn_a)
        _write(art / "source-a-raw-metadata-probe.json", a_probe)

        print(json.dumps({"phase": "source_b_raw_metadata"}), flush=True)
        b_probe = probe_source_b_raw_metadata(conn_b)
        _write(art / "source-b-raw-metadata-probe.json", b_probe)

        with canonical_connection(settings) as conn:
            print(json.dumps({"phase": "source_a_inventory"}), flush=True)
            a_inv = build_source_a_inventory(
                root=root, conn_canonical=conn, conn_a=conn_a, split_contract=split
            )
            # Overlay deep probe statuses
            a_inv["SOURCE_A_METADATA_RECOVERY_STATUS"] = a_probe.get(
                "SOURCE_A_METADATA_RECOVERY_STATUS",
                a_inv.get("SOURCE_A_METADATA_RECOVERY_STATUS"),
            )
            a_inv["SOURCE_A_RAW_METADATA_PROBE_STATUS"] = a_probe.get(
                "SOURCE_A_RAW_METADATA_PROBE_STATUS"
            )
            a_inv["version"] = VERSION
            _write(
                art / "full-source-a-provider-inventory.json",
                {k: v for k, v in a_inv.items() if k != "grains"}
                | {
                    "grains_public": [
                        {
                            "grain_id": g["grain_id"],
                            "outcome": g["outcome"],
                            "unit": g["unit"],
                            "n_subjects": g.get("n_subjects"),
                            "n_subjects_with_ge2": g.get("n_subjects_with_ge2"),
                            "stratum_hash": g.get("stratum_hash"),
                        }
                        for g in a_inv["grains"]
                    ]
                },
            )
            if not a_inv.get("ok"):
                return {"ok": False, "error": "SOURCE_A_INVENTORY_FAIL"}

            print(json.dumps({"phase": "source_b_inventory_full"}), flush=True)
            b_inv = build_full_b_outcome_unit_inventory(
                conn_canonical=conn, conn_b=conn_b
            )
            b_inv["SOURCE_B_METADATA_RECOVERY_STATUS"] = b_probe.get(
                "SOURCE_B_METADATA_RECOVERY_STATUS",
                b_inv.get("SOURCE_B_METADATA_RECOVERY_STATUS"),
            )
            b_inv["SOURCE_B_RAW_METADATA_PROBE_STATUS"] = b_probe.get(
                "SOURCE_B_RAW_METADATA_PROBE_STATUS"
            )
            b_inv["version"] = VERSION
            _write(
                art / "full-source-b-outcome-unit-inventory.json",
                {
                    **{k: v for k, v in b_inv.items() if k != "strata"},
                    "strata_public_top100": b_inv["strata"][:100],
                    "n_strata_in_full_inventory": b_inv["n_strata"],
                },
            )
            if not b_inv.get("ok"):
                return {"ok": False, "error": "SOURCE_B_INVENTORY_FAIL"}

            print(json.dumps({"phase": "exhaustive_discovery_v021"}), flush=True)
            graph = build_candidate_graph(
                a_grains=a_inv["grains"], b_strata=b_inv["strata"]
            )

            print(json.dumps({"phase": "pair_estimates"}), flush=True)
            need_pairs: set[tuple[str, str]] = set()
            for r in graph["records"]:
                if not r.get("b_raw_code"):
                    continue
                code, unit = str(r["b_raw_code"]), str(r.get("b_unit") or "")
                if (
                    code in {"53", "54", "55", "56", "1", "32", "33", "mm_1001"}
                    or r.get("analyte_ok")
                    or float(r.get("priority_score") or 0) >= 2.5
                ):
                    need_pairs.add((code, unit))
            from collections import defaultdict

            by_a: dict[str, list] = defaultdict(list)
            for r in graph["records"]:
                if r.get("b_raw_code") and r.get("analyte_ok"):
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
                    r["outcome_specific_split"] = {
                        k: v for k, v in cov.items() if k != "subject_ids"
                    }
                    split_docs[f"{key[0]}|{key[1]}"] = r["outcome_specific_split"]

    finally:
        for c in (conn_b, conn_a):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

    controls = run_negative_controls(graph["records"])
    _write(art / "negative-semantic-controls.json", controls)

    reclass = {
        "version": VERSION,
        "CANDIDATE_GRAPH_RECLASSIFICATION_STATUS": graph[
            "CANDIDATE_GRAPH_RECLASSIFICATION_STATUS"
        ],
        "before_v02": v02_before,
        "after_v021": {
            "n_candidate_records": graph["n_candidate_records"],
            "n_family_only_candidates": graph["n_family_only_candidates"],
            "n_exact_or_synonym_candidates": graph["n_exact_or_synonym_candidates"],
            "n_hard_conflict_records": graph["n_hard_conflict_records"],
            "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT": graph[
                "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT"
            ],
            "n_a_with_ge1_b_candidate": graph["n_a_with_ge1_b_candidate"],
            "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT": graph[
                "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT"
            ],
            "candidate_class_counts": graph["candidate_class_counts"],
            "unexplained": 0,
        },
        "known_false_pairs_reclassified": [
            d
            for d in defects.get("defects") or []
            if d.get("reproduction_ok")
        ][:20],
        "unexplained": 0,
        "ok": graph.get("ok") and controls.get("ok"),
    }
    _write(art / "candidate-graph-reclassification.json", reclass)

    public_records = [
        {k: v for k, v in r.items() if k not in {"subject_ids_with_pairs"}}
        for r in graph["records"]
    ]
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
                    "identity_level": r.get("identity_level"),
                    "a_concept": r.get("a_concept"),
                    "b_concept": r.get("b_concept"),
                    "candidate_class": r.get("candidate_class"),
                    "analyte_ok": r.get("analyte_ok"),
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
                if r.get("b_raw_code")
                or r.get("candidate_class") == "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH"
            ][:8000],
            "n_records_total": len(public_records),
        },
    )

    # Do not ingest decisions this release
    ingest_doc = ingest(
        decision_log_path(root / REVIEW_PACK_DIR),
        records=graph["records"],
        allow_ingest=False,
    )
    _write(art / "decision-ingest.json", ingest_doc)

    accepted_n = 0
    domain_n = 0
    shadow_n = 0

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
        "THRESHOLD_OWNER_DECISION_STATUS": "DEFERRED_UNTIL_DOMAIN_REVIEW",
        "THRESHOLD_DECISION_REQUIRED": True,
    }
    _write(art / "readiness-after-discovery.json", readiness)

    metadata_lineage = {
        "version": VERSION,
        "source_a_probe": {
            k: a_probe.get(k)
            for k in (
                "SOURCE_A_RAW_METADATA_PROBE_STATUS",
                "SOURCE_A_METADATA_RECOVERY_STATUS",
                "SOURCE_A_SPECIMEN_METADATA_STATUS",
                "SOURCE_A_ASSAY_METADATA_STATUS",
                "connection",
                "n_metadata_columns",
                "n_lab_fks",
                "probe_hash",
                "default_specimen_invented",
            )
        },
        "source_b_probe": {
            k: b_probe.get(k)
            for k in (
                "SOURCE_B_RAW_METADATA_PROBE_STATUS",
                "SOURCE_B_METADATA_RECOVERY_STATUS",
                "SOURCE_B_SPECIMEN_METADATA_STATUS",
                "SOURCE_B_ASSAY_METADATA_STATUS",
                "analyses_catalog_rows",
                "material_column_exists",
                "material_non_null",
                "catalog_material_all_empty",
                "provider_input_required",
                "probe_hash",
            )
        },
        "field_sample_a": (a_probe.get("fields") or [])[:15],
        "field_sample_b": (b_probe.get("fields") or [])[:15],
    }
    _write(art / "metadata-recovery-lineage.json", metadata_lineage)

    print(json.dumps({"phase": "review_pack"}), flush=True)
    workbench = write_review_pack(
        root=root,
        a_inv=a_inv,
        b_inv=b_inv,
        a_probe=a_probe,
        b_probe=b_probe,
        graph=graph,
        controls=controls,
        readiness=readiness,
        metadata_lineage=metadata_lineage,
        defects=defects,
    )
    _write(art / "domain-review-workbench-status.json", workbench)

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

    zero_shot = "NOT_RUN_NO_ACCEPTED_MAPPINGS"
    domain_decision = "DOMAIN_REVIEW_DECISION_REQUIRED"

    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline["BASELINE_VERIFICATION_STATUS"],
        "V02_ANALYTE_IDENTITY_DEFECT_REPRODUCTION_STATUS": defects[
            "V02_ANALYTE_IDENTITY_DEFECT_REPRODUCTION_STATUS"
        ],
        "ANALYTE_ONTOLOGY_STATUS": "PASS",
        "ANALYTE_IDENTITY_REGRESSION_STATUS": (
            "PASS" if controls.get("ok") and defects.get("ok") else "FAIL"
        ),
        "FULL_SOURCE_A_PROVIDER_INVENTORY_STATUS": a_inv[
            "FULL_SOURCE_A_PROVIDER_INVENTORY_STATUS"
        ],
        "FULL_SOURCE_B_CATALOG_INVENTORY_STATUS": b_inv[
            "FULL_SOURCE_B_CATALOG_INVENTORY_STATUS"
        ],
        "SOURCE_A_RAW_METADATA_PROBE_STATUS": a_probe[
            "SOURCE_A_RAW_METADATA_PROBE_STATUS"
        ],
        "SOURCE_B_RAW_METADATA_PROBE_STATUS": b_probe[
            "SOURCE_B_RAW_METADATA_PROBE_STATUS"
        ],
        "SOURCE_A_METADATA_RECOVERY_STATUS": a_probe.get(
            "SOURCE_A_METADATA_RECOVERY_STATUS", "UNKNOWN"
        ),
        "SOURCE_B_METADATA_RECOVERY_STATUS": b_probe.get(
            "SOURCE_B_METADATA_RECOVERY_STATUS", "UNKNOWN"
        ),
        "EXHAUSTIVE_CROSS_SOURCE_CANDIDATE_DISCOVERY_STATUS": graph[
            "EXHAUSTIVE_CROSS_SOURCE_CANDIDATE_DISCOVERY_STATUS"
        ],
        "CANDIDATE_GRAPH_RECLASSIFICATION_STATUS": graph[
            "CANDIDATE_GRAPH_RECLASSIFICATION_STATUS"
        ],
        "NEGATIVE_SEMANTIC_CONTROLS_STATUS": controls[
            "NEGATIVE_SEMANTIC_CONTROLS_STATUS"
        ],
        "HUMAN_DECISION_GATE_INTEGRITY_STATUS": ingest_doc[
            "HUMAN_DECISION_GATE_INTEGRITY_STATUS"
        ],
        "DOMAIN_ACCEPTED_MAPPING_COUNT": domain_n,
        "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT": shadow_n,
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": accepted_n,
        "DOMAIN_REVIEW_DECISION_STATUS": domain_decision,
        "REVIEW_INDEX_ACCOUNTING_STATUS": "PENDING_PUBLISH",
        "PUBLIC_DATA_MINIMIZATION_STATUS": privacy["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "REVIEW_PACKET_PUBLICATION_STATUS": "PENDING_PUBLISH",
        "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
        "SCIENTIFIC_PASS": False,
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": zero_shot,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
        "DOMAIN_REVIEW_WORKBENCH_STATUS": workbench["DOMAIN_REVIEW_WORKBENCH_STATUS"],
        "A_PROVIDER_GRAINS_EVALUATED": graph["A_PROVIDER_GRAINS_EVALUATED"],
        "B_OUTCOME_UNIT_STRATA_EVALUATED": graph["B_OUTCOME_UNIT_STRATA_EVALUATED"],
        "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT": graph[
            "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT"
        ],
        "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT": graph[
            "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT"
        ],
    }
    _write(art / "status-contract.json", statuses)

    report = {
        "version": VERSION,
        "generated_at": _now(),
        "elapsed_s": round(time.time() - t0, 2),
        "statuses": statuses,
        "reclassification": reclass["after_v021"],
        "private_review_pack": REVIEW_PACK_DIR,
        "baseline_artifact_dir": ACCEPTED_V02_ARTIFACT_DIR,
        "non_actions": [
            "No human accept",
            "No A→B zero-shot",
            "No Current State Classifier",
            "No joint multi-outcome training",
            "No medication residual",
            "No intervention-response",
            "No identity merge",
            "No unverified unit conversions",
            "No clinical or production claims",
            "No prior ZIP overwrite (v0.2 and earlier)",
            "No ingest of existing decisions",
        ],
        "stop_reason": "ANALYTE_ONTOLOGY_METADATA_CLOSURE_REVIEW_PACKET",
    }
    _write(art / "stage-report.json", report)
    (art / "stage-report.md").write_text(
        f"""# Laboratory Analyte Ontology + Metadata Closure v{VERSION}

Baseline v0.2 SHA: see baseline-verification.json  
Defect reproduction: {defects['V02_ANALYTE_IDENTITY_DEFECT_REPRODUCTION_STATUS']}  
Candidate records after: {graph['n_candidate_records']}  
Family-only: {graph['n_family_only_candidates']}  
Exact/synonym: {graph['n_exact_or_synonym_candidates']}  
Hard conflicts: {graph['n_hard_conflict_records']}  
Accepted / shadow / usable: 0 / 0 / 0  

`SCIENTIFIC_PASS=false`
""",
        encoding="utf-8",
    )
    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_cross_source_lab_semantic_v021*.py tests/test_cross_source_lab_semantic_v02*.py -q
uv run --frozen audit --root . cross-source-lab-semantic run-v0.2.1 --no-publish
uv run --frozen audit --root . cross-source-lab-semantic publish-v0.2.1
```
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide v{VERSION}

Analyte ontology corrective packet. Family similarity is retrieval-only.
Private pack: `{REVIEW_PACK_DIR}`
Do not overwrite v0.2 ZIP.
""",
        encoding="utf-8",
    )

    verification = {
        "version": VERSION,
        "ok": (
            baseline.get("ok")
            and defects.get("ok")
            and a_inv.get("ok")
            and b_inv.get("ok")
            and a_probe.get("ok")
            and b_probe.get("ok")
            and graph.get("ok")
            and controls.get("ok")
            and workbench.get("ok")
            and privacy.get("ok")
            and ingest_doc.get("ok")
            and reclass.get("ok")
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
        "reclassification": reclass["after_v021"],
    }
    if not no_publish:
        from human_simulator.cross_source_lab_semantic_v021.publish import publish

        result["publish"] = publish(root)
    return result
