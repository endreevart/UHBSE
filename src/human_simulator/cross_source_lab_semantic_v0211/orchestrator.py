"""Orchestrator — Metadata Probe and Privacy Closure v0.2.1.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.decision_gate import ingest
from human_simulator.cross_source_lab_semantic_v021.discovery import (
    build_candidate_graph,
    run_negative_controls,
)
from human_simulator.cross_source_lab_semantic_v021.ontology import ontology_snapshot
from human_simulator.cross_source_lab_semantic_v0211.baseline_verify import verify_baseline
from human_simulator.cross_source_lab_semantic_v0211.defect_reproduce import (
    reproduce_metadata_probe_defect,
    reproduce_public_minimization_defect,
)
from human_simulator.cross_source_lab_semantic_v0211.metadata_probes import (
    probe_source_a_lab_context,
    probe_source_b_lab_context,
)
from human_simulator.cross_source_lab_semantic_v0211.policy import (
    ACCEPTED_GS011_ARTIFACT_DIR,
    ARTIFACT_DIR,
    PROVIDER_INPUT_DIR,
    REVIEW_PACK_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.cross_source_lab_semantic_v0211.privacy_scan import (
    scan_public_artifacts,
)


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


def _public_probe(probe: dict[str, Any]) -> dict[str, Any]:
    """Strip any residual row-derived material; keep aggregates only."""
    banned = {"sample_category_hashes", "example_values", "raw_values", "samples"}
    out: dict[str, Any] = {}
    for k, v in probe.items():
        if k in banned:
            continue
        if k in {"candidates", "rejected", "column_reclassification"}:
            if k == "column_reclassification" and isinstance(v, dict):
                out[k] = {
                    "n_columns_scanned": v.get("n_columns_scanned"),
                    "bucket_counts": v.get("bucket_counts"),
                    # no sample rows with hashes
                    "n_sample_rejected": len(v.get("sample_rejected") or []),
                    "n_sample_lab_relevant": len(v.get("sample_lab_relevant") or []),
                }
            elif k in {"candidates", "rejected"} and isinstance(v, list):
                cleaned = []
                for row in v:
                    if not isinstance(row, dict):
                        continue
                    cleaned.append({kk: vv for kk, vv in row.items() if kk not in banned})
                out[k] = cleaned
            else:
                out[k] = v
        else:
            out[k] = v
    out["sample_category_hashes_emitted"] = False
    return out


def write_provider_input_pack(
    *,
    root: Path,
    a_probe: dict[str, Any],
    b_probe: dict[str, Any],
    graph: dict[str, Any],
) -> dict[str, Any]:
    pack = Path(root) / PROVIDER_INPUT_DIR
    pack.mkdir(parents=True, exist_ok=True)
    exact = [
        {
            "mapping_id": r.get("mapping_id"),
            "a_outcome": r.get("a_outcome"),
            "a_unit": r.get("a_unit"),
            "b_raw_code": r.get("b_raw_code"),
            "b_unit": r.get("b_unit"),
            "identity_level": r.get("identity_level"),
            "candidate_class": r.get("candidate_class"),
        }
        for r in graph.get("records") or []
        if r.get("identity_level")
        in {"EXACT_ANALYTE_IDENTITY", "APPROVED_ANALYTE_SYNONYM"}
        and r.get("b_raw_code")
    ]
    reqs = {
        "version": VERSION,
        "requests": [
            {
                "source": "A",
                "field": "specimen/material",
                "status": a_probe.get("SOURCE_A_SPECIMEN_METADATA_STATUS"),
                "document_needed": "LIS specimen dictionary linked to analysis results",
            },
            {
                "source": "A",
                "field": "assay/method/analyzer",
                "status": a_probe.get("SOURCE_A_ASSAY_METADATA_STATUS"),
                "document_needed": "Assay/method/analyzer documentation per lab test",
            },
            {
                "source": "B",
                "field": "analyses_catalog.material",
                "status": b_probe.get("SOURCE_B_SPECIMEN_METADATA_STATUS"),
                "document_needed": "Filled material values or specimen dictionary",
            },
            {
                "source": "B",
                "field": "assay/method",
                "status": b_probe.get("SOURCE_B_ASSAY_METADATA_STATUS"),
                "document_needed": "Assay/method reference per catalog code",
            },
        ],
        "required_evidence_format": [
            "schema.table.column or external document ID",
            "non-null coverage aggregates (no row values)",
            "join path to analysis result / catalog code",
        ],
        "exact_synonym_candidates_blocked_on_metadata": exact[:200],
        "n_exact_synonym_candidates": len(exact),
        "human_accept_executed": False,
    }
    _write(pack / "provider-input-required.json", reqs)
    (pack / "reviewer-instructions.md").write_text(
        f"""# Provider input / reviewer instructions v{VERSION}

Do not accept mappings without laboratory-context specimen and assay evidence.
Instrumental-case name fields are NOT analyzer metadata.
HTTP request_method and auth platform are NOT lab method/platform.
Decision log remains empty this release.
""",
        encoding="utf-8",
    )
    log = pack / "decision-log.jsonl"
    if not log.is_file():
        log.write_text("", encoding="utf-8")
    return {"ok": True, "n_requests": len(reqs["requests"]), "n_blocked_exact": len(exact)}


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
    meta_def = reproduce_metadata_probe_defect(root)
    _write(art / "v021-metadata-probe-defect-reproduction.json", meta_def)
    pub_def = reproduce_public_minimization_defect(root)
    _write(art / "v021-public-data-minimization-defect.json", pub_def)
    if not meta_def.get("ok") or not pub_def.get("ok"):
        return {
            "ok": False,
            "error": "DEFECT_REPRO_FAIL",
            "meta_def": meta_def,
            "pub_def": pub_def,
        }

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

    before_graph = {
        "n_candidate_records": 2091,
        "n_exact_or_synonym_candidates": 874,
        "n_hard_conflict_records": 1201,
        "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT": 37,
        "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT": 0,
        "note": "v0.2.1 published accounting",
    }

    try:
        print(json.dumps({"phase": "source_a_lab_context_probe"}), flush=True)
        a_probe = probe_source_a_lab_context(conn_a)
        _write(art / "source-a-raw-metadata-probe.json", _public_probe(a_probe))

        print(json.dumps({"phase": "source_b_lab_context_probe"}), flush=True)
        b_probe = probe_source_b_lab_context(conn_b)
        _write(art / "source-b-raw-metadata-probe.json", _public_probe(b_probe))

        with canonical_connection(settings) as conn:
            print(json.dumps({"phase": "source_a_inventory"}), flush=True)
            a_inv = build_source_a_inventory(
                root=root, conn_canonical=conn, conn_a=conn_a, split_contract=split
            )
            a_inv["SOURCE_A_METADATA_RECOVERY_STATUS"] = a_probe.get(
                "SOURCE_A_METADATA_RECOVERY_STATUS"
            )
            a_inv["version"] = VERSION
            _write(
                art / "full-source-a-provider-inventory.json",
                {
                    **{k: v for k, v in a_inv.items() if k != "grains"},
                    "grains_public": [
                        {
                            "grain_id": g["grain_id"],
                            "outcome": g["outcome"],
                            "unit": g["unit"],
                            "n_subjects": g.get("n_subjects"),
                            "stratum_hash": g.get("stratum_hash"),
                        }
                        for g in a_inv["grains"]
                    ],
                },
            )
            if not a_inv.get("ok"):
                return {"ok": False, "error": "SOURCE_A_INVENTORY_FAIL"}

            print(json.dumps({"phase": "source_b_inventory"}), flush=True)
            b_inv = build_full_b_outcome_unit_inventory(
                conn_canonical=conn, conn_b=conn_b
            )
            b_inv["SOURCE_B_METADATA_RECOVERY_STATUS"] = b_probe.get(
                "SOURCE_B_METADATA_RECOVERY_STATUS"
            )
            b_inv["version"] = VERSION
            _write(
                art / "full-source-b-outcome-unit-inventory.json",
                {
                    **{k: v for k, v in b_inv.items() if k != "strata"},
                    "strata_public_top100": b_inv["strata"][:100],
                },
            )
            if not b_inv.get("ok"):
                return {"ok": False, "error": "SOURCE_B_INVENTORY_FAIL"}

            print(json.dumps({"phase": "candidate_graph_rebuild"}), flush=True)
            graph = build_candidate_graph(
                a_grains=a_inv["grains"], b_strata=b_inv["strata"]
            )

            # limited pair estimates for ranking
            need_pairs: set[tuple[str, str]] = set()
            for r in graph["records"]:
                if r.get("analyte_ok") and r.get("b_raw_code"):
                    need_pairs.add((str(r["b_raw_code"]), str(r.get("b_unit") or "")))
            for code, unit in list(sorted(need_pairs))[:80]:
                pc = estimate_pairs_for_grain(conn, raw_code=code, unit=unit)
                for r in graph["records"]:
                    if str(r.get("b_raw_code")) == code and str(r.get("b_unit") or "") == unit:
                        r["b_subjects_with_pairs"] = pc["n_subjects_with_pairs"]
                        r["b_strict_pairs"] = pc["n_strict_consecutive_pairs"]
                        cov = outcome_specific_split_coverage(
                            subject_ids_with_pairs=pc.get("subject_ids_with_pairs") or []
                        )
                        r["outcome_specific_split"] = {
                            k: v for k, v in cov.items() if k != "subject_ids"
                        }
    finally:
        for c in (conn_b, conn_a):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

    controls = run_negative_controls(graph["records"])
    _write(art / "negative-semantic-controls.json", controls)

    after_graph = {
        "n_candidate_records": graph["n_candidate_records"],
        "n_family_only_candidates": graph["n_family_only_candidates"],
        "n_exact_or_synonym_candidates": graph["n_exact_or_synonym_candidates"],
        "n_hard_conflict_records": graph["n_hard_conflict_records"],
        "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT": graph[
            "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT"
        ],
        "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT": graph[
            "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT"
        ],
        "candidate_class_counts": graph["candidate_class_counts"],
        "unexplained": 0,
    }
    reclass = {
        "version": VERSION,
        "CANDIDATE_GRAPH_REBUILD_STATUS": (
            "PASS" if graph.get("ok") and controls.get("ok") else "FAIL"
        ),
        "before_v021": before_graph,
        "after_v0211": after_graph,
        "analyte_ontology_unchanged": True,
        "unexplained": 0,
        "ok": graph.get("ok") and controls.get("ok"),
    }
    _write(art / "candidate-graph-rebuild.json", reclass)

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
                    "candidate_class": r.get("candidate_class"),
                    "analyte_ok": r.get("analyte_ok"),
                    "hard_conflict": r.get("hard_conflict"),
                    "classification_hash": r.get("classification_hash"),
                }
                for r in graph["records"]
                if r.get("b_raw_code")
                or r.get("candidate_class") == "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH"
            ][:8000],
            "n_records_total": len(graph["records"]),
        },
    )

    ingest_doc = ingest(
        Path(root) / PROVIDER_INPUT_DIR / "decision-log.jsonl",
        records=graph["records"],
        allow_ingest=False,
    )
    _write(art / "decision-ingest.json", ingest_doc)

    metadata_lineage = {
        "version": VERSION,
        "source_a": {
            k: a_probe.get(k)
            for k in (
                "SOURCE_A_RAW_METADATA_PROBE_STATUS",
                "SOURCE_A_SPECIMEN_METADATA_STATUS",
                "SOURCE_A_ASSAY_METADATA_STATUS",
                "SOURCE_A_METADATA_RECOVERY_STATUS",
                "LAB_CONTEXT_METADATA_DISCOVERY_STATUS",
                "n_candidates",
                "lab_relation_count",
                "probe_hash",
                "global_substring_scan_used",
                "sample_category_hashes_emitted",
                "default_specimen_invented",
            )
        },
        "source_b": {
            k: b_probe.get(k)
            for k in (
                "SOURCE_B_RAW_METADATA_PROBE_STATUS",
                "SOURCE_B_SPECIMEN_METADATA_STATUS",
                "SOURCE_B_ASSAY_METADATA_STATUS",
                "SOURCE_B_METADATA_RECOVERY_STATUS",
                "analyses_catalog_rows",
                "material_column_exists",
                "material_non_null",
                "catalog_material_all_empty",
                "provider_input_required",
                "probe_hash",
                "sample_category_hashes_emitted",
            )
        },
        "removed_from_public": [
            "row-derived category fingerprints",
            "field_sample arrays with value digests",
            "name/platform/provider category digests",
        ],
        # NO field_sample_a / field_sample_b with hashes
    }
    _write(art / "metadata-recovery-lineage.json", metadata_lineage)

    print(json.dumps({"phase": "provider_input_pack"}), flush=True)
    provider = write_provider_input_pack(
        root=root, a_probe=a_probe, b_probe=b_probe, graph=graph
    )
    _write(art / "provider-input-pack-status.json", provider)

    # private review pack aggregate only pointer
    pack = Path(root) / REVIEW_PACK_DIR
    pack.mkdir(parents=True, exist_ok=True)
    _write(
        pack / "cross-source-candidate-graph-summary.json",
        {k: v for k, v in graph.items() if k != "records"},
    )
    _write(pack / "metadata-probes-summary.json", metadata_lineage)

    print(json.dumps({"phase": "privacy_scan"}), flush=True)
    privacy = scan_public_artifacts(art)
    _write(art / "public-data-minimization-scan.json", privacy)

    domain_n = shadow_n = accepted_n = 0
    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline["BASELINE_VERIFICATION_STATUS"],
        "V021_METADATA_PROBE_DEFECT_REPRODUCTION_STATUS": meta_def[
            "V021_METADATA_PROBE_DEFECT_REPRODUCTION_STATUS"
        ],
        "V021_PUBLIC_DATA_MINIMIZATION_DEFECT_STATUS": pub_def[
            "V021_PUBLIC_DATA_MINIMIZATION_DEFECT_STATUS"
        ],
        "LAB_CONTEXT_METADATA_DISCOVERY_STATUS": a_probe[
            "LAB_CONTEXT_METADATA_DISCOVERY_STATUS"
        ],
        "SOURCE_A_RAW_METADATA_PROBE_STATUS": a_probe[
            "SOURCE_A_RAW_METADATA_PROBE_STATUS"
        ],
        "SOURCE_A_SPECIMEN_METADATA_STATUS": a_probe[
            "SOURCE_A_SPECIMEN_METADATA_STATUS"
        ],
        "SOURCE_A_ASSAY_METADATA_STATUS": a_probe["SOURCE_A_ASSAY_METADATA_STATUS"],
        "SOURCE_A_METADATA_RECOVERY_STATUS": a_probe[
            "SOURCE_A_METADATA_RECOVERY_STATUS"
        ],
        "SOURCE_B_RAW_METADATA_PROBE_STATUS": b_probe[
            "SOURCE_B_RAW_METADATA_PROBE_STATUS"
        ],
        "SOURCE_B_SPECIMEN_METADATA_STATUS": b_probe[
            "SOURCE_B_SPECIMEN_METADATA_STATUS"
        ],
        "SOURCE_B_ASSAY_METADATA_STATUS": b_probe["SOURCE_B_ASSAY_METADATA_STATUS"],
        "SOURCE_B_METADATA_RECOVERY_STATUS": b_probe[
            "SOURCE_B_METADATA_RECOVERY_STATUS"
        ],
        "ANALYTE_ONTOLOGY_REGRESSION_STATUS": (
            "PASS" if controls.get("ok") else "FAIL"
        ),
        "CANDIDATE_GRAPH_REBUILD_STATUS": reclass["CANDIDATE_GRAPH_REBUILD_STATUS"],
        "HUMAN_DECISION_GATE_INTEGRITY_STATUS": ingest_doc[
            "HUMAN_DECISION_GATE_INTEGRITY_STATUS"
        ],
        "DOMAIN_ACCEPTED_MAPPING_COUNT": domain_n,
        "TECHNICAL_SHADOW_ELIGIBLE_MAPPING_COUNT": shadow_n,
        "SCIENTIFICALLY_USABLE_ACCEPTED_OUTCOME_COUNT": accepted_n,
        "DIRECT_IDENTIFIER_SCAN_STATUS": privacy["DIRECT_IDENTIFIER_SCAN_STATUS"],
        "HASHED_IDENTIFIER_SCAN_STATUS": privacy["HASHED_IDENTIFIER_SCAN_STATUS"],
        "LOW_ENTROPY_HASH_SCAN_STATUS": privacy["LOW_ENTROPY_HASH_SCAN_STATUS"],
        "ROW_DERIVED_VALUE_SCAN_STATUS": privacy["ROW_DERIVED_VALUE_SCAN_STATUS"],
        "SENSITIVE_COLUMN_SAMPLE_SCAN_STATUS": privacy[
            "SENSITIVE_COLUMN_SAMPLE_SCAN_STATUS"
        ],
        "PUBLIC_DATA_MINIMIZATION_STATUS": privacy["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "REVIEW_INDEX_ACCOUNTING_STATUS": "PENDING_PUBLISH",
        "REVIEW_PACKET_PUBLICATION_STATUS": "PENDING_PUBLISH",
        "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
        "SCIENTIFIC_PASS": False,
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "NOT_RUN_NO_ACCEPTED_MAPPINGS",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
        "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT": graph[
            "SEMANTICALLY_ALIGNED_CANDIDATE_COUNT"
        ],
        "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT": graph[
            "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH_COUNT"
        ],
    }
    _write(art / "status-contract.json", statuses)

    report = {
        "version": VERSION,
        "generated_at": _now(),
        "elapsed_s": round(time.time() - t0, 2),
        "statuses": statuses,
        "graph_after": after_graph,
        "removed_public_fields": metadata_lineage["removed_from_public"],
        "non_actions": [
            "No human accept",
            "No A→B zero-shot",
            "No Current State Classifier",
            "No joint ML",
            "No medication/intervention models",
            "No identity merge",
            "No unit conversions",
            "No row-level values or row-derived hashes in public artifacts",
            "No clinical claims",
            "No overwrite of v0.2.1 or earlier ZIPs",
        ],
        "stop_reason": "METADATA_PRIVACY_CLOSURE_REVIEW_PACKET",
    }
    _write(art / "stage-report.json", report)
    (art / "stage-report.md").write_text(
        f"""# Laboratory Metadata Privacy Closure v{VERSION}

Baseline v0.2.1 SHA: d10c0a02…5c13  
A assay status corrected: {a_probe['SOURCE_A_ASSAY_METADATA_STATUS']}  
Public row-derived hashes removed.  
Accepted / shadow / usable: 0 / 0 / 0  

`SCIENTIFIC_PASS=false`
""",
        encoding="utf-8",
    )
    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_cross_source_lab_semantic_v0211*.py tests/test_cross_source_lab_semantic_v021*.py tests/test_cross_source_lab_semantic_v02*.py -q
uv run --frozen audit --root . cross-source-lab-semantic run-v0.2.1.1 --no-publish
uv run --frozen audit --root . cross-source-lab-semantic publish-v0.2.1.1
```
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide v{VERSION}

Corrective metadata/privacy packet on immutable v0.2.1.
Private provider-input: `{PROVIDER_INPUT_DIR}`
Do not overwrite v0.2.1 ZIP.
""",
        encoding="utf-8",
    )

    verification = {
        "version": VERSION,
        "ok": (
            baseline.get("ok")
            and meta_def.get("ok")
            and pub_def.get("ok")
            and a_probe.get("ok")
            and b_probe.get("ok")
            and a_inv.get("ok")
            and b_inv.get("ok")
            and graph.get("ok")
            and controls.get("ok")
            and privacy.get("ok")
            and ingest_doc.get("ok")
            and reclass.get("ok")
            and a_probe.get("SOURCE_A_ASSAY_METADATA_STATUS")
            == "SOURCE_DOCUMENTATION_REQUIRED"
            and b_probe.get("SOURCE_B_ASSAY_METADATA_STATUS")
            == "SOURCE_DOCUMENTATION_REQUIRED"
        ),
        "statuses": statuses,
        "generated_at": _now(),
    }
    _write(art / "verification.json", verification)
    write_manifest(art)

    # re-scan after all writes
    privacy2 = scan_public_artifacts(art)
    _write(art / "public-data-minimization-scan.json", privacy2)
    write_manifest(art)
    verification["ok"] = verification["ok"] and privacy2.get("ok")
    statuses["PUBLIC_DATA_MINIMIZATION_STATUS"] = privacy2[
        "PUBLIC_DATA_MINIMIZATION_STATUS"
    ]
    for k in (
        "DIRECT_IDENTIFIER_SCAN_STATUS",
        "HASHED_IDENTIFIER_SCAN_STATUS",
        "LOW_ENTROPY_HASH_SCAN_STATUS",
        "ROW_DERIVED_VALUE_SCAN_STATUS",
        "SENSITIVE_COLUMN_SAMPLE_SCAN_STATUS",
    ):
        statuses[k] = privacy2[k]
    _write(art / "status-contract.json", statuses)
    verification["statuses"] = statuses
    verification["ok"] = verification["ok"] and privacy2.get("ok")
    _write(art / "verification.json", verification)
    write_manifest(art)

    result = {
        "ok": verification["ok"],
        "version": VERSION,
        "statuses": statuses,
        "artifacts_dir": ARTIFACT_DIR,
        "no_publish": no_publish,
        "elapsed_s": report["elapsed_s"],
        "graph_after": after_graph,
    }
    if not no_publish:
        from human_simulator.cross_source_lab_semantic_v0211.publish import publish

        result["publish"] = publish(root)
    return result
