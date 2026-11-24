"""Orchestrator — Unified A+B Clinical Research Layer v0.3."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v03.baseline_verify import verify_baseline
from human_simulator.unified_research_layer_v03.connections import (
    connect_source_a,
    connect_source_b,
)
from human_simulator.unified_research_layer_v03.domain_inventory import (
    inventory_canonical,
    inventory_source,
)
from human_simulator.unified_research_layer_v03.overlap_policy import build_overlap_policy
from human_simulator.unified_research_layer_v03.policy import (
    ARTIFACT_DIR,
    PIN_SOURCE_A_SUBJECTS,
    PIN_SOURCE_B_SUBJECTS,
    PROVIDER_INPUT_DIR,
    RESEARCH_LAYER_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_research_layer_v03.privacy_scan import scan_public_artifacts
from human_simulator.unified_research_layer_v03.provider_pack import write_provider_pack
from human_simulator.unified_research_layer_v03.research_schema import (
    materialize_research_layer,
)
from human_simulator.unified_research_layer_v03.semantic_registry import (
    build_semantic_layers,
)
from human_simulator.unified_research_layer_v03.split_foundation import (
    build_split_foundation,
)
from human_simulator.unified_research_layer_v03.state_assembly import assemble_states
from human_simulator.unified_research_layer_v03.temporal_layer import build_temporal_layer


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
        print(json.dumps({"phase": "canonical_inventory"}), flush=True)
        with canonical_connection(settings) as conn:
            canonical = inventory_canonical(conn)
            _write(art / "canonical-subject-inventory.json", canonical)

            print(json.dumps({"phase": "source_a_inventory"}), flush=True)
            a_inv = inventory_source(
                conn=conn_a,
                source_system="magerya_api",
                schema="magerya_api",
                subject_table="account_patient",
                pin_subjects=PIN_SOURCE_A_SUBJECTS,
            )
            # strip heavy relations list from public? keep table names only — already aggregate
            _write(
                art / "full-source-a-domain-inventory.json",
                {k: v for k, v in a_inv.items() if k != "relations"}
                | {"n_relations_listed": len(a_inv.get("relations") or [])},
            )

            print(json.dumps({"phase": "source_b_inventory"}), flush=True)
            b_inv = inventory_source(
                conn=conn_b,
                source_system="kgz_raw",
                schema="quest_digital",
                subject_table=None,
                pin_subjects=PIN_SOURCE_B_SUBJECTS,
            )
            # Attach B subject count from canonical (raw subject table not a single patients table)
            b_inv["subject_count_exact"] = canonical.get("source_b_subjects")
            b_inv["subject_count_source"] = "canonical_evidence.subject[kgz_raw]"
            b_inv["subject_count_matches_pin"] = (
                b_inv["subject_count_exact"] == PIN_SOURCE_B_SUBJECTS
            )
            if b_inv.get("connection") == "OK":
                b_inv["FULL_SOURCE_B_DOMAIN_INVENTORY_STATUS"] = (
                    "PASS" if b_inv.get("UNACCOUNTED_COUNT") == 0 else "FAIL"
                )
                b_inv["ok"] = b_inv["FULL_SOURCE_B_DOMAIN_INVENTORY_STATUS"] == "PASS"
            _write(
                art / "full-source-b-domain-inventory.json",
                {k: v for k, v in b_inv.items() if k != "relations"}
                | {"n_relations_listed": len(b_inv.get("relations") or [])},
            )

            accounting = {
                "version": VERSION,
                "MULTI_DOMAIN_ACCOUNTING_STATUS": (
                    "PASS"
                    if a_inv.get("ok")
                    and b_inv.get("ok")
                    and a_inv.get("UNACCOUNTED_COUNT") == 0
                    and b_inv.get("UNACCOUNTED_COUNT") == 0
                    else "FAIL"
                ),
                "source_a_subjects_live": a_inv.get("subject_count_exact"),
                "source_b_subjects_live": b_inv.get("subject_count_exact"),
                "sum_not_unique_people": True,
                "UNACCOUNTED_COUNT": (a_inv.get("UNACCOUNTED_COUNT") or 0)
                + (b_inv.get("UNACCOUNTED_COUNT") or 0),
                "accepted_lab_a_b_mappings": 0,
                "cross_source_identity_merge": "NOT_RUN",
                "ok": True,
            }
            accounting["ok"] = (
                accounting["MULTI_DOMAIN_ACCOUNTING_STATUS"] == "PASS"
                and accounting["UNACCOUNTED_COUNT"] == 0
            )
            _write(art / "multi-domain-accounting.json", accounting)

            print(json.dumps({"phase": "semantic_layers"}), flush=True)
            semantic = build_semantic_layers(root=root, a_inv=a_inv, b_inv=b_inv)
            # public semantic without huge candidate list? include full exact list in provider pack only
            sem_public = {
                k: v
                for k, v in semantic.items()
                if k != "lab"
            }
            lab_pub = {
                k: v
                for k, v in (semantic.get("lab") or {}).items()
                if k != "exact_synonym_candidates"
            }
            lab_pub["n_exact_synonym_candidates_in_provider_pack"] = len(
                (semantic.get("lab") or {}).get("exact_synonym_candidates") or []
            )
            sem_public["lab"] = lab_pub
            _write(art / "cross-source-semantic-layers.json", sem_public)

            print(json.dumps({"phase": "research_layer"}), flush=True)
            research = materialize_research_layer(
                root=root,
                a_inv=a_inv,
                b_inv=b_inv,
                canonical=canonical,
                semantic=semantic,
            )
            _write(art / "unified-research-layer-status.json", research)

            print(json.dumps({"phase": "overlap_policy"}), flush=True)
            overlap = build_overlap_policy(canonical)
            _write(art / "cross-source-overlap-policy.json", overlap)

            print(json.dumps({"phase": "temporal_layer"}), flush=True)
            temporal = build_temporal_layer(
                conn_a=conn_a,
                conn_b=conn_b,
                a_inv=a_inv,
                b_inv=b_inv,
                canonical=canonical,
            )
            _write(art / "unified-temporal-layer.json", temporal)

            print(json.dumps({"phase": "state_assembly"}), flush=True)
            states = assemble_states(conn_canonical=conn, canonical=canonical)
            _write(art / "unified-source-aware-state-assembly.json", states)

            print(json.dumps({"phase": "split_foundation"}), flush=True)
            split = build_split_foundation(conn_canonical=conn, overlap=overlap)
            _write(art / "global-a-b-split-foundation.json", split)

        print(json.dumps({"phase": "provider_pack"}), flush=True)
        provider = write_provider_pack(root=root, lab_semantic=semantic.get("lab") or {})
        _write(art / "provider-input-status.json", provider)

        aux = {
            "version": VERSION,
            "adapters_prepared": [
                "laboratory_dictionaries",
                "medication_references",
                "diagnosis_ontologies",
                "procedure_catalogs",
                "local_document_extraction",
                "llm_assisted_candidate_generation",
            ],
            "llm_may": [
                "structure_local_documents",
                "propose_mappings",
                "explain_conflicts",
                "form_review_queues",
            ],
            "llm_must_not": [
                "accept_clinical_mapping",
                "create_HUMAN_ACCEPTED",
                "unit_conversion_without_contract",
                "receive_raw_patient_data_via_external_api",
                "invent_diagnosis_or_intervention",
            ],
            "ok": True,
        }
        _write(art / "auxiliary-sources-llm-boundary.json", aux)

    finally:
        for c in (conn_a, conn_b):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

    print(json.dumps({"phase": "privacy_scan"}), flush=True)
    privacy = scan_public_artifacts(art)
    _write(art / "public-data-minimization-scan.json", privacy)

    statuses = {
        "BASELINE_VERIFICATION_STATUS": baseline["BASELINE_VERIFICATION_STATUS"],
        "INTEGRATION_FIRST_CONTRACT_STATUS": "PASS",
        "FULL_SOURCE_A_DOMAIN_INVENTORY_STATUS": a_inv.get(
            "FULL_SOURCE_A_DOMAIN_INVENTORY_STATUS", "FAIL"
        ),
        "FULL_SOURCE_B_DOMAIN_INVENTORY_STATUS": b_inv.get(
            "FULL_SOURCE_B_DOMAIN_INVENTORY_STATUS", "FAIL"
        ),
        "MULTI_DOMAIN_ACCOUNTING_STATUS": accounting["MULTI_DOMAIN_ACCOUNTING_STATUS"],
        "UNIFIED_RESEARCH_SCHEMA_STATUS": research["UNIFIED_RESEARCH_SCHEMA_STATUS"],
        "SOURCE_A_RESEARCH_LAYER_STATUS": research["SOURCE_A_RESEARCH_LAYER_STATUS"],
        "SOURCE_B_RESEARCH_LAYER_STATUS": research["SOURCE_B_RESEARCH_LAYER_STATUS"],
        "TECHNICAL_A_B_MERGE_STATUS": research["TECHNICAL_A_B_MERGE_STATUS"],
        "CROSS_SOURCE_SEMANTIC_STATUS": semantic["CROSS_SOURCE_SEMANTIC_STATUS"],
        "CROSS_SOURCE_LAB_MAPPING_STATUS": semantic["CROSS_SOURCE_LAB_MAPPING_STATUS"],
        "CROSS_SOURCE_DIAGNOSIS_MAPPING_STATUS": semantic[
            "CROSS_SOURCE_DIAGNOSIS_MAPPING_STATUS"
        ],
        "CROSS_SOURCE_MEDICATION_MAPPING_STATUS": semantic[
            "CROSS_SOURCE_MEDICATION_MAPPING_STATUS"
        ],
        "CROSS_SOURCE_PROCEDURE_MAPPING_STATUS": semantic[
            "CROSS_SOURCE_PROCEDURE_MAPPING_STATUS"
        ],
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": overlap[
            "CROSS_SOURCE_IDENTITY_MERGE_STATUS"
        ],
        "CROSS_SOURCE_OVERLAP_POLICY_STATUS": overlap[
            "CROSS_SOURCE_OVERLAP_POLICY_STATUS"
        ],
        "UNIFIED_TEMPORAL_LAYER_STATUS": temporal["UNIFIED_TEMPORAL_LAYER_STATUS"],
        "UNIFIED_SOURCE_AWARE_STATE_STATUS": states[
            "UNIFIED_SOURCE_AWARE_STATE_STATUS"
        ],
        "GLOBAL_A_B_SPLIT_FOUNDATION_STATUS": split[
            "GLOBAL_A_B_SPLIT_FOUNDATION_STATUS"
        ],
        "PROVENANCE_STATUS": canonical.get("PROVENANCE_STATUS", "FAIL"),
        "PUBLIC_DATA_MINIMIZATION_STATUS": privacy["PUBLIC_DATA_MINIMIZATION_STATUS"],
        "PRIVACY_BOUNDARY_STATUS": privacy["PRIVACY_BOUNDARY_STATUS"],
        "PROVIDER_INPUT_STATUS": provider["PROVIDER_INPUT_STATUS"],
        "DOMAIN_ACCEPTED_MAPPING_COUNT": semantic["DOMAIN_ACCEPTED_MAPPING_COUNT"],
        "SOURCE_SPECIFIC_SUPPORTED_COUNT": semantic["SOURCE_SPECIFIC_SUPPORTED_COUNT"],
        "UNRESOLVED_RETAINED_COUNT": semantic["UNRESOLVED_RETAINED_COUNT"],
        "REJECTED_CONFLICT_COUNT": semantic["REJECTED_CONFLICT_COUNT"],
        "UNACCOUNTED_COUNT": accounting["UNACCOUNTED_COUNT"],
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
        "REVIEW_PACKET_PUBLICATION_STATUS": "PENDING_PUBLISH",
        "SCIENTIFIC_MAPPING_STATUS": "PARTIAL_PROVIDER_INPUT_REQUIRED",
        "SCIENTIFIC_PASS": False,
        "TECHNICAL_PASS": False,  # set below
    }

    technical_ok = all(
        [
            baseline.get("ok"),
            a_inv.get("ok"),
            b_inv.get("ok"),
            accounting.get("ok"),
            research.get("ok"),
            semantic.get("ok"),
            overlap.get("ok"),
            temporal.get("ok"),
            states.get("ok"),
            split.get("ok"),
            privacy.get("ok"),
            canonical.get("ok"),
            accounting.get("UNACCOUNTED_COUNT") == 0,
            provider.get("universe_complete_874_of_874"),
        ]
    )
    statuses["TECHNICAL_PASS"] = technical_ok

    _write(art / "status-contract.json", statuses)

    plain = {
        "source_scoped_subjects_a": a_inv.get("subject_count_exact"),
        "source_scoped_subjects_b": b_inv.get("subject_count_exact"),
        "domains_unified_source_aware": research.get("entities_declared"),
        "domains_source_specific": [
            "diagnoses",
            "medications",
            "procedures",
            "recommendations",
            "most_lab_outcomes_pending_comparability",
        ],
        "preserved_supported_estimated_rows": semantic.get(
            "SOURCE_SPECIFIC_SUPPORTED_COUNT"
        ),
        "unresolved_lab_candidates": semantic.get("UNRESOLVED_RETAINED_COUNT"),
        "rejected_conflicts": semantic.get("REJECTED_CONFLICT_COUNT"),
        "available_for_first_common_modeling": [
            "source-scoped states from canonical observations A and B",
            "source-specific features with masks",
            "overlap-aware split foundation",
            "NOT cross-source accepted lab mappings (0)",
        ],
        "blockers_for_unified_a_b_models": [
            "PROVIDER_INPUT_REQUIRED for specimen/assay scientific comparability",
            "0 CROSS_SOURCE_ACCEPTED lab mappings",
            "identity overlap unresolved — cannot claim unique pooled patients",
            "CURRENT_STATE_CLASSIFIER and joint models intentionally NOT_STARTED",
        ],
    }
    _write(art / "plain-language-completion.json", plain)

    report = {
        "version": VERSION,
        "generated_at": _now(),
        "elapsed_s": round(time.time() - t0, 2),
        "statuses": statuses,
        "plain_language": plain,
        "private_paths": {
            "research_layer": RESEARCH_LAYER_DIR,
            "provider_input": PROVIDER_INPUT_DIR,
        },
        "non_actions": [
            "No model training",
            "No Current State Classifier",
            "No joint ML",
            "No zero-shot performance evaluation",
            "No intervention-response",
            "No causal/treatment-effect claims",
            "No QSP/PKPD",
            "No identity merge without evidence",
            "No raw A/B writes",
            "No migration 0005",
            "No external patient-data transmission",
            "No security remediation",
            "No prior ZIP overwrite",
        ],
        "stop_reason": "UNIFIED_A_B_CLINICAL_RESEARCH_LAYER",
    }
    _write(art / "stage-report.json", report)
    (art / "stage-report.md").write_text(
        f"""# Unified A+B Clinical Research Layer v{VERSION}

Source-scoped subjects: A={plain['source_scoped_subjects_a']} B={plain['source_scoped_subjects_b']}  
TECHNICAL_PASS={technical_ok} SCIENTIFIC_PASS=false  
CROSS_SOURCE_ACCEPTED lab mappings: 0  
UNACCOUNTED_COUNT={statuses['UNACCOUNTED_COUNT']}
""",
        encoding="utf-8",
    )
    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_unified_research_layer_v03*.py -q
uv run --frozen audit --root . unified-research-layer run-v0.3 --no-publish
uv run --frozen audit --root . unified-research-layer publish-v0.3
```
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide v{VERSION}

Technical merge = source-aware retention + unified research schema.
Scientific cross-source PASS remains blocked on provider documentation.
Do not overwrite v0.2.1.1 or earlier ZIPs.
""",
        encoding="utf-8",
    )

    verification = {
        "version": VERSION,
        "ok": technical_ok,
        "statuses": statuses,
        "generated_at": _now(),
    }
    _write(art / "verification.json", verification)
    write_manifest(art)

    # re-privacy after all writes
    privacy2 = scan_public_artifacts(art)
    _write(art / "public-data-minimization-scan.json", privacy2)
    for k in (
        "PUBLIC_DATA_MINIMIZATION_STATUS",
        "PRIVACY_BOUNDARY_STATUS",
    ):
        statuses[k] = privacy2[k]
    verification["ok"] = technical_ok and privacy2.get("ok")
    statuses["TECHNICAL_PASS"] = verification["ok"]
    verification["statuses"] = statuses
    _write(art / "status-contract.json", statuses)
    _write(art / "verification.json", verification)
    write_manifest(art)

    result = {
        "ok": verification["ok"],
        "version": VERSION,
        "statuses": statuses,
        "plain_language": plain,
        "artifacts_dir": ARTIFACT_DIR,
        "no_publish": no_publish,
        "elapsed_s": report["elapsed_s"],
    }
    if not no_publish:
        from human_simulator.unified_research_layer_v03.publish import publish

        result["publish"] = publish(root)
    return result
