"""Orchestrator — Unified A+B Materialized Research Layer v0.3.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v031.accounting import build_accounting
from human_simulator.unified_research_layer_v031.baseline_verify import verify_baseline
from human_simulator.unified_research_layer_v031.classification import classify_inventory
from human_simulator.unified_research_layer_v031.connections import (
    connect_source_a,
    connect_source_b,
)
from human_simulator.unified_research_layer_v031.defect_reproduction import (
    reproduce_v03_defects,
)
from human_simulator.unified_research_layer_v031.inventory import (
    inventory_canonical,
    inventory_source_a,
    inventory_source_b,
)
from human_simulator.unified_research_layer_v031.materialize import materialize_all
from human_simulator.unified_research_layer_v031.overlap_split import build_overlap_and_split
from human_simulator.unified_research_layer_v031.policy import (
    ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_research_layer_v031.privacy_scan import (
    scan_private_materialized,
    scan_public_artifacts,
)
from human_simulator.unified_research_layer_v031.provider_pack import write_provider_and_lab
from human_simulator.unified_research_layer_v031.state_input import build_state_input_layer
from human_simulator.unified_research_layer_v031.temporal import build_temporal_report


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


def _public_inventory(inv: dict[str, Any]) -> dict[str, Any]:
    """Strip full relation lists to aggregates for public artifacts."""
    rels = inv.get("relations") or []
    return {
        k: v
        for k, v in inv.items()
        if k != "relations"
    } | {
        "n_relations_listed": len(rels),
        "relation_names": [f"{r['schema']}.{r['relation']}" for r in rels],
        "exact_clinical_counts": inv.get("exact_clinical_counts"),
    }


def _public_classification(clf: dict[str, Any]) -> dict[str, Any]:
    rels = []
    for r in clf.get("relations") or []:
        rels.append(
            {
                "schema": r["schema"],
                "relation": r["relation"],
                "primary_disposition": r["primary_disposition"],
                "primary_domain": r["primary_domain"],
                "support_status": r["support_status"],
                "secondary_roles": r.get("secondary_roles"),
                "evidence": r.get("evidence"),
                "exact_row_count": r.get("exact_row_count"),
            }
        )
    return {**clf, "relations": rels}


def run_full(root: Path, *, no_publish: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    art.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(json.dumps({"phase": "baseline"}), flush=True)
    baseline = verify_baseline(root)
    _write(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    print(json.dumps({"phase": "v03_defect_reproduction"}), flush=True)
    defects = reproduce_v03_defects(root)
    _write(art / "v03-claim-defect-reproduction.json", defects)

    _write(art / "policy.json", policy_snapshot())
    _write(
        art / "integration-first-contract.json",
        {
            "version": VERSION,
            "INTEGRATION_FIRST_CONTRACT_STATUS": "PASS",
            "INTEGRATION_FIRST_BEFORE_NEW_MODELING": True,
            "no_new_model_training_this_stage": True,
            "ok": True,
        },
    )

    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings

    settings = load_canonical_settings()
    conn_a = connect_source_a(root)
    conn_b = connect_source_b(root)

    try:
        with canonical_connection(settings) as conn:
            print(json.dumps({"phase": "canonical_inventory"}), flush=True)
            canonical = inventory_canonical(conn)
            _write(art / "canonical-subject-inventory.json", canonical)

            print(json.dumps({"phase": "full_source_a_inventory"}), flush=True)
            a_inv = inventory_source_a(conn_a)
            _write(art / "full-source-a-schema-inventory.json", _public_inventory(a_inv))

            print(json.dumps({"phase": "full_source_b_inventory"}), flush=True)
            b_inv = inventory_source_b(conn_b)
            # attach canonical B subject pin
            b_inv["canonical_subject_count"] = canonical.get("source_b_subjects")
            b_inv["canonical_subject_matches_pin"] = (
                canonical.get("source_b_subjects") == 49564
            )
            _write(art / "full-source-b-schema-inventory.json", _public_inventory(b_inv))

            print(json.dumps({"phase": "classification"}), flush=True)
            clf_a = classify_inventory(
                root=root, inventory=a_inv, source_system="magerya_api"
            )
            clf_b = classify_inventory(
                root=root, inventory=b_inv, source_system="kgz_raw"
            )
            # classification of B alone must see users/consultations
            clf_combined_ok = clf_a.get("ok") and clf_b.get("ok")
            _write(art / "curated-domain-classification-a.json", _public_classification(clf_a))
            _write(art / "curated-domain-classification-b.json", _public_classification(clf_b))
            _write(
                art / "curated-domain-classification.json",
                {
                    "version": VERSION,
                    "CURATED_DOMAIN_CLASSIFICATION_STATUS": (
                        "PASS" if clf_combined_ok else "FAIL"
                    ),
                    "source_a": {
                        k: v for k, v in clf_a.items() if k != "relations"
                    },
                    "source_b": {
                        k: v for k, v in clf_b.items() if k != "relations"
                    },
                    "ok": clf_combined_ok,
                },
            )

            print(json.dumps({"phase": "materialize"}), flush=True)
            materialization = materialize_all(
                root=root,
                conn_canonical=conn,
                conn_a=conn_a,
                conn_b=conn_b,
                canonical_inv=canonical,
            )
            # public status only — no row payloads
            _write(
                art / "materialization-status.json",
                {
                    k: v
                    for k, v in materialization.items()
                    if k != "domain_proof"
                }
                | {
                    "domain_proof_summary": {
                        dk: {
                            kk: vv
                            for kk, vv in dv.items()
                            if kk
                            not in {
                                # keep all aggregate proof fields
                            }
                        }
                        for dk, dv in (materialization.get("domain_proof") or {}).items()
                    }
                },
            )
            _write(art / "domain-materialization-proof.json", materialization.get("domain_proof"))

            print(json.dumps({"phase": "accounting"}), flush=True)
            accounting = build_accounting(
                a_inv=a_inv,
                b_inv=b_inv,
                classification_a=clf_a,
                classification_b=clf_b,
                materialization=materialization,
                canonical=canonical,
            )
            _write(art / "exact-multi-domain-accounting.json", accounting)

            print(json.dumps({"phase": "temporal"}), flush=True)
            event_rows = (
                (materialization.get("datasets") or {})
                .get("research_event", {})
                .get("rows")
                or 0
            )
            temporal = build_temporal_report(
                conn_a=conn_a,
                conn_b=conn_b,
                a_inv=a_inv,
                b_inv=b_inv,
                event_rows=event_rows,
            )
            _write(art / "unified-temporal-event-layer.json", temporal)

            print(json.dumps({"phase": "state_input"}), flush=True)
            state_input = build_state_input_layer(materialization=materialization)
            _write(art / "unified-state-input-layer.json", state_input)

            print(json.dumps({"phase": "overlap_split"}), flush=True)
            linkage = None
            link_path = root / "artifacts" / "stage-02" / "identity-linkage-assessment.json"
            if link_path.is_file():
                linkage = json.loads(link_path.read_text(encoding="utf-8"))
            split = build_overlap_and_split(
                root=root, conn_canonical=conn, linkage_assessment=linkage
            )
            _write(art / "cross-source-overlap-and-split.json", split)

        print(json.dumps({"phase": "provider"}), flush=True)
        provider = write_provider_and_lab(root=root)
        _write(
            art / "provider-input-status.json",
            {k: v for k, v in provider.items() if k != "lab"}
            | {"lab_summary": provider.get("lab")},
        )
        _write(
            art / "cross-source-semantic-status.json",
            {
                "version": VERSION,
                "CROSS_SOURCE_SEMANTIC_STATUS": "PARTIAL_NO_ACCEPTED",
                "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
                "PROVIDER_INPUT_STATUS": provider.get("PROVIDER_INPUT_STATUS"),
                "A_PROVIDER_GRAINS": provider.get("A_PROVIDER_GRAINS"),
                "B_CODE_UNIT_STRATA": provider.get("B_CODE_UNIT_STRATA"),
                "exact_synonym_universe_874": provider.get("universe_complete_874_of_874"),
                "UNRESOLVED_RETAINED_COUNT": provider.get("UNRESOLVED_RETAINED_COUNT"),
                "REJECTED_CONFLICT_COUNT": provider.get("REJECTED_CONFLICT_COUNT"),
                "ok": True,
            },
        )

        print(json.dumps({"phase": "privacy"}), flush=True)
        # build status contract first for privacy of public dir mid-flight
        ds = materialization.get("datasets") or {}

        def mat_status(name: str) -> str:
            row = ds.get(name) or {}
            if not row.get("exists"):
                return "FAIL_MISSING"
            if name == "research_diagnosis":
                return "PASS_EMPTY_STRUCTURED_ABSENT"
            if name == "research_condition_history":
                return "PASS_EMPTY_STRUCTURED_ABSENT"
            if row.get("rows", 0) > 0 or name in {
                "research_diagnosis",
                "research_condition_history",
            }:
                return "PASS"
            return "FAIL_EMPTY"

        technical_pass = bool(
            materialization.get("ok")
            and accounting.get("ok")
            and temporal.get("ok")
            and state_input.get("ok")
            and defects.get("ok")
            and clf_combined_ok
            and a_inv.get("ok")
            and b_inv.get("ok")
            and accounting.get("UNACCOUNTED_COUNT") == 0
        )
        if not materialization.get("patient_rows_written"):
            technical_merge = "FAIL_NOT_MATERIALIZED"
            technical_pass = False
        else:
            technical_merge = "PASS" if technical_pass else "FAIL"

        status = {
            "version": VERSION,
            "generated_at": _now(),
            "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
            "V03_TECHNICAL_MERGE_CLAIM_STATUS": defects.get(
                "V03_TECHNICAL_MERGE_CLAIM_STATUS"
            ),
            "V03_RESEARCH_LAYER_MATERIALIZATION_STATUS": defects.get(
                "V03_RESEARCH_LAYER_MATERIALIZATION_STATUS"
            ),
            "V03_STATE_ASSEMBLY_STATUS": defects.get("V03_STATE_ASSEMBLY_STATUS"),
            "V03_SOURCE_B_INVENTORY_SCOPE_STATUS": defects.get(
                "V03_SOURCE_B_INVENTORY_SCOPE_STATUS"
            ),
            "V03_MULTI_DOMAIN_ACCOUNTING_STATUS": defects.get(
                "V03_MULTI_DOMAIN_ACCOUNTING_STATUS"
            ),
            "V03_OVERLAP_AWARE_SPLIT_STATUS": defects.get(
                "V03_OVERLAP_AWARE_SPLIT_STATUS"
            ),
            "FULL_SOURCE_A_SCHEMA_INVENTORY_STATUS": (
                "PASS" if a_inv.get("ok") else "FAIL"
            ),
            "FULL_SOURCE_B_SCHEMA_INVENTORY_STATUS": (
                "PASS"
                if b_inv.get("ok")
                and "public" in (b_inv.get("schemas_all") or [])
                and "quest_digital" in (b_inv.get("schemas_all") or [])
                else "FAIL"
            ),
            "CURATED_DOMAIN_CLASSIFICATION_STATUS": (
                "PASS" if clf_combined_ok else "FAIL"
            ),
            "EXACT_MULTI_DOMAIN_ACCOUNTING_STATUS": accounting.get(
                "EXACT_MULTI_DOMAIN_ACCOUNTING_STATUS"
            ),
            "MATERIALIZED_RESEARCH_SUBJECT_STATUS": mat_status("research_subject"),
            "MATERIALIZED_RESEARCH_ENCOUNTER_STATUS": mat_status("research_encounter"),
            "MATERIALIZED_RESEARCH_EVENT_STATUS": mat_status("research_event"),
            "MATERIALIZED_RESEARCH_OBSERVATION_STATUS": mat_status(
                "research_observation"
            ),
            "MATERIALIZED_RESEARCH_DIAGNOSIS_STATUS": mat_status("research_diagnosis"),
            "MATERIALIZED_RESEARCH_MEDICATION_STATUS": mat_status(
                "research_medication_record"
            ),
            "MATERIALIZED_RESEARCH_RECOMMENDATION_STATUS": mat_status(
                "research_recommendation"
            ),
            "MATERIALIZED_RESEARCH_DOCUMENT_REFERENCE_STATUS": mat_status(
                "research_document_reference"
            ),
            "MATERIALIZED_PROVENANCE_STATUS": mat_status("research_provenance"),
            "UNIFIED_TEMPORAL_EVENT_LAYER_STATUS": temporal.get(
                "UNIFIED_TEMPORAL_EVENT_LAYER_STATUS"
            ),
            "UNIFIED_STATE_INPUT_LAYER_STATUS": state_input.get(
                "UNIFIED_STATE_INPUT_LAYER_STATUS"
            ),
            "INDIVIDUAL_STATE_DATASET_STATUS": "NOT_STARTED",
            "CROSS_SOURCE_SEMANTIC_STATUS": "PARTIAL_NO_ACCEPTED",
            "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
            "CROSS_SOURCE_OVERLAP_RISK_STATUS": split.get(
                "CROSS_SOURCE_OVERLAP_RISK_STATUS"
            ),
            "GLOBAL_A_B_SPLIT_STATUS": split.get("GLOBAL_A_B_SPLIT_STATUS"),
            "PROVIDER_INPUT_STATUS": provider.get("PROVIDER_INPUT_STATUS"),
            "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
            "UNACCOUNTED_COUNT": accounting.get("UNACCOUNTED_COUNT"),
            "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
            "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
            "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
            "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
            "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
            "SCIENTIFIC_PASS": False,
            "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
            "PRODUCTION_READINESS": "NOT_CLAIMED",
            "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
            "TECHNICAL_A_B_MERGE_STATUS": technical_merge,
            "TECHNICAL_PASS": technical_pass and technical_merge == "PASS",
            "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
            "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        }
        _write(art / "status-contract.json", status)

        priv = scan_private_materialized(root)
        _write(art / "private-materialized-privacy-scan.json", priv)
        pub = scan_public_artifacts(art)
        status["PUBLIC_DATA_MINIMIZATION_STATUS"] = (
            "PASS_AGGREGATE_ONLY" if pub.get("ok") else "FAIL"
        )
        status["ok"] = bool(
            status["TECHNICAL_PASS"] and pub.get("ok") and priv.get("ok")
        )
        _write(art / "status-contract.json", status)
        _write(art / "public-data-minimization-scan.json", pub)

        verification = {
            "version": VERSION,
            "ok": bool(status.get("ok")),
            "TECHNICAL_A_B_MERGE_STATUS": status["TECHNICAL_A_B_MERGE_STATUS"],
            "UNACCOUNTED_COUNT": status["UNACCOUNTED_COUNT"],
            "materialized": materialization.get("ok"),
            "privacy_public": pub.get("ok"),
            "privacy_private": priv.get("ok"),
            "duration_seconds": round(time.time() - t0, 3),
        }
        _write(art / "verification.json", verification)

        _write(
            art / "stage-report.md",
            f"""# Unified A+B Materialized Research Layer v{VERSION}

Generated: {_now()}

## Summary

- TECHNICAL_A_B_MERGE_STATUS={status['TECHNICAL_A_B_MERGE_STATUS']}
- SCIENTIFIC_PASS=false
- UNACCOUNTED_COUNT={status['UNACCOUNTED_COUNT']}
- GLOBAL_A_B_SPLIT_STATUS={status['GLOBAL_A_B_SPLIT_STATUS']}
- INDIVIDUAL_STATE_DATASET_STATUS=NOT_STARTED

## Materialized private datasets

See `private/unified-research-layer-v031/materialized/` (not in public ZIP).

## Non-actions

No model training; no identity merge; no migration 0005; no prior ZIP overwrite.
""",
        )
        _write(
            art / "stage-report.json",
            {
                "version": VERSION,
                "TECHNICAL_A_B_MERGE_STATUS": status["TECHNICAL_A_B_MERGE_STATUS"],
                "SCIENTIFIC_PASS": False,
                "ok": status.get("ok"),
            },
        )
        _write(
            art / "REPRODUCE.md",
            f"""# Reproduce v{VERSION}

```bash
uv run --frozen audit --root . unified-research-layer run-v0.3.1 --no-publish
uv run --frozen audit --root . unified-research-layer verify-v0.3.1
uv run --frozen audit --root . unified-research-layer publish-v0.3.1
```

Private row-level datasets remain under `private/unified-research-layer-v031/`.
""",
        )
        _write(
            art / "REVIEW_GUIDE.md",
            f"""# Review guide v{VERSION}

Confirm TECHNICAL_A_B_MERGE_STATUS=PASS only if private Parquet datasets exist and reconcile.
SCIENTIFIC_PASS remains false. No individual states in this stage.
""",
        )

        write_manifest(art)

        result = {
            "ok": verification["ok"],
            "status": status,
            "verification": verification,
            "artifact_dir": str(art),
        }
        if not no_publish and verification["ok"]:
            from human_simulator.unified_research_layer_v031.publish import publish

            result["publish"] = publish(root)
        return result
    finally:
        if conn_a is not None:
            try:
                conn_a.close()
            except Exception:
                pass
        if conn_b is not None:
            try:
                conn_b.close()
            except Exception:
                pass
