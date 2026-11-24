"""Orchestrator — Unified A+B Individual State + Multi-Outcome Baseline v0.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.unified_individual_state_v01.baseline_models import (
    run_source_aware_baseline,
)
from human_simulator.unified_individual_state_v01.baseline_verify import verify_baseline
from human_simulator.unified_individual_state_v01.defect_reproduction import (
    reproduce_v031_defects,
)
from human_simulator.unified_individual_state_v01.exact_accounting import (
    build_exact_accounting,
)
from human_simulator.unified_individual_state_v01.overlap_guard import (
    build_overlap_guarded_split,
)
from human_simulator.unified_individual_state_v01.parquet_integrity import (
    audit_parquet_integrity,
)
from human_simulator.unified_individual_state_v01.policy import (
    ARTIFACT_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_individual_state_v01.privacy_scan import (
    scan_private_plane,
    scan_public,
)
from human_simulator.unified_individual_state_v01.provenance_index import (
    build_provenance_index,
)
from human_simulator.unified_individual_state_v01.state_dataset import (
    build_individual_states,
)
from human_simulator.unified_individual_state_v01.temporal_accounting import (
    build_temporal_accounting,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _write_md(path: Path, text: str) -> None:
    """Write Markdown as plain text — never json.dumps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


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
    _write_json(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    print(json.dumps({"phase": "v031_defect_reproduction"}), flush=True)
    defects = reproduce_v031_defects(root)
    _write_json(art / "v031-evidence-defect-reproduction.json", defects)
    if not defects.get("ok"):
        return {"ok": False, "error": "DEFECT_REPRODUCTION_FAIL", "defects": defects}

    _write_json(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "exact_accounting"}), flush=True)
    acc_pack = build_exact_accounting(root)
    accounting = acc_pack["accounting"]
    _write_json(art / "exact-domain-accounting-v011.json", accounting)
    for name, doc in (acc_pack.get("artifacts") or {}).items():
        _write_json(art / f"{name}.json", doc)

    print(json.dumps({"phase": "parquet_integrity"}), flush=True)
    integrity = audit_parquet_integrity(root)
    _write_json(art / "private-parquet-integrity.json", integrity)
    _write_json(art / "foreign-key-integrity.json", integrity.get("foreign_key_integrity"))
    _write_json(
        art / "duplicate-and-orphan-audit.json", integrity.get("duplicate_and_orphan_audit")
    )
    _write_json(
        art / "source-row-to-research-row-cardinality.json",
        integrity.get("source_row_to_research_row_cardinality"),
    )

    print(json.dumps({"phase": "temporal"}), flush=True)
    temporal = build_temporal_accounting(root)
    _write_json(art / "temporal-event-accounting.json", temporal)

    print(json.dumps({"phase": "provenance_index"}), flush=True)
    prov = build_provenance_index(root)
    _write_json(art / "patient-linked-provenance-index.json", prov)

    print(json.dumps({"phase": "overlap_guard"}), flush=True)
    split = build_overlap_guarded_split(root)
    _write_json(art / "overlap-guarded-split.json", split)

    state_gates_ok = (
        accounting.get("ok")
        and integrity.get("ok")
        and temporal.get("ok")
        and prov.get("ok")
        and split.get("ok")
    )

    state_meta: dict[str, Any] = {"ok": False}
    baseline_meta: dict[str, Any] = {
        "FIRST_SOURCE_AWARE_MULTI_OUTCOME_BASELINE_STATUS": "NOT_RUN",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
        "SOURCE_AWARE_MODEL_FREEZE_STATUS": "NOT_RUN",
        "ENGINE_UNIFIED_STATE_SHADOW_STATUS": "NOT_RUN",
        "ok": False,
    }

    if state_gates_ok:
        print(json.dumps({"phase": "individual_states"}), flush=True)
        state_meta = build_individual_states(root)
        _write_json(art / "individual-state-dataset.json", state_meta)
        _write_json(
            art / "post-cutoff-leakage-audit.json",
            {
                "version": VERSION,
                "POST_CUTOFF_LEAKAGE_AUDIT_STATUS": state_meta.get(
                    "STATE_TEMPORAL_LEAKAGE_STATUS"
                ),
                "same_time_targets": state_meta.get("same_time_targets"),
                "ok": state_meta.get("STATE_TEMPORAL_LEAKAGE_STATUS") == "PASS",
            },
        )
        if state_meta.get("ok"):
            print(json.dumps({"phase": "baseline_models"}), flush=True)
            baseline_meta = run_source_aware_baseline(root, state_meta)
            _write_json(art / "source-aware-baseline.json", baseline_meta)
        else:
            _write_json(
                art / "source-aware-baseline.json",
                {**baseline_meta, "reason": "state_dataset_gate_failed"},
            )
    else:
        _write_json(
            art / "blocker-report.json",
            {
                "version": VERSION,
                "blockers": {
                    "accounting": accounting.get("ok"),
                    "integrity": integrity.get("ok"),
                    "temporal": temporal.get("ok"),
                    "provenance": prov.get("ok"),
                    "split": split.get("ok"),
                    "accounting_problems": accounting.get("problems"),
                    "integrity_problems": integrity.get("problems"),
                },
                "model_not_run": True,
            },
        )

    print(json.dumps({"phase": "privacy"}), flush=True)
    priv = scan_private_plane(root)
    _write_json(art / "private-research-plane-privacy.json", priv)

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V031_EVIDENCE_DEFECT_REPRODUCTION_STATUS": defects.get(
            "V031_EVIDENCE_DEFECT_REPRODUCTION_STATUS"
        ),
        "EXACT_MULTI_DOMAIN_ACCOUNTING_STATUS": accounting.get(
            "EXACT_MULTI_DOMAIN_ACCOUNTING_STATUS"
        ),
        "PRIVATE_PARQUET_INTEGRITY_STATUS": integrity.get(
            "PRIVATE_PARQUET_INTEGRITY_STATUS"
        ),
        "RESEARCH_ENTITY_LINKAGE_STATUS": integrity.get("RESEARCH_ENTITY_LINKAGE_STATUS"),
        "DUPLICATE_ORPHAN_AUDIT_STATUS": integrity.get("DUPLICATE_ORPHAN_AUDIT_STATUS"),
        "TEMPORAL_EVENT_ACCOUNTING_STATUS": temporal.get(
            "TEMPORAL_EVENT_ACCOUNTING_STATUS"
        ),
        "PATIENT_LINKED_PROVENANCE_INDEX_STATUS": prov.get(
            "PATIENT_LINKED_PROVENANCE_INDEX_STATUS"
        ),
        "PROVENANCE_STATE_FEATURE_ELIGIBILITY_STATUS": prov.get(
            "PROVENANCE_STATE_FEATURE_ELIGIBILITY_STATUS"
        ),
        "PRIVATE_OVERLAP_GROUP_DATASET_STATUS": split.get(
            "PRIVATE_OVERLAP_GROUP_DATASET_STATUS"
        ),
        "GLOBAL_A_B_SPLIT_STATUS": split.get("GLOBAL_A_B_SPLIT_STATUS"),
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "INDIVIDUAL_STATE_DATASET_STATUS": state_meta.get(
            "INDIVIDUAL_STATE_DATASET_STATUS", "NOT_STARTED"
        ),
        "STATE_TARGET_DATASET_STATUS": state_meta.get(
            "STATE_TARGET_DATASET_STATUS", "NOT_STARTED"
        ),
        "STATE_DATASET_ACCOUNTING_STATUS": state_meta.get(
            "STATE_DATASET_ACCOUNTING_STATUS", "NOT_STARTED"
        ),
        "STATE_TEMPORAL_LEAKAGE_STATUS": state_meta.get(
            "STATE_TEMPORAL_LEAKAGE_STATUS", "NOT_STARTED"
        ),
        "STATE_PRIVACY_STATUS": state_meta.get("STATE_PRIVACY_STATUS", priv.get("STATE_PRIVACY_STATUS")),
        "FIRST_SOURCE_AWARE_MULTI_OUTCOME_BASELINE_STATUS": baseline_meta.get(
            "FIRST_SOURCE_AWARE_MULTI_OUTCOME_BASELINE_STATUS"
        ),
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": baseline_meta.get(
            "JOINT_MULTI_OUTCOME_MODEL_STATUS"
        ),
        "SOURCE_AWARE_MODEL_FREEZE_STATUS": baseline_meta.get(
            "SOURCE_AWARE_MODEL_FREEZE_STATUS"
        ),
        "ENGINE_UNIFIED_STATE_SHADOW_STATUS": baseline_meta.get(
            "ENGINE_UNIFIED_STATE_SHADOW_STATUS"
        ),
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PRIVATE_RESEARCH_PLANE_STATUS": priv.get("PRIVATE_RESEARCH_PLANE_STATUS"),
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
        "baseline_claim": baseline_meta.get("claim"),
        "UNACCOUNTED_COUNT": accounting.get("UNACCOUNTED_COUNT"),
    }

    publishable = (
        status["EXACT_MULTI_DOMAIN_ACCOUNTING_STATUS"] == "PASS"
        and status["PRIVATE_PARQUET_INTEGRITY_STATUS"] == "PASS"
        and status["GLOBAL_A_B_SPLIT_STATUS"] == "PASS_OVERLAP_GUARDED"
        and status["INDIVIDUAL_STATE_DATASET_STATUS"] == "BUILT"
        and status["STATE_TEMPORAL_LEAKAGE_STATUS"] == "PASS"
        and priv.get("ok")
    )
    status["TECHNICAL_PASS"] = bool(publishable)
    status["ok"] = bool(publishable)

    _write_json(art / "status-contract.json", status)
    pub = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = pub.get("PUBLIC_DATA_MINIMIZATION_STATUS")
    status["PRIVACY_BOUNDARY_STATUS"] = pub.get("PRIVACY_BOUNDARY_STATUS")
    if not pub.get("ok"):
        status["ok"] = False
        status["TECHNICAL_PASS"] = False
    _write_json(art / "status-contract.json", status)
    _write_json(art / "public-data-minimization-scan.json", pub)

    verification = {
        "version": VERSION,
        "ok": bool(status.get("ok")),
        "duration_seconds": round(time.time() - t0, 3),
        "UNACCOUNTED_COUNT": status.get("UNACCOUNTED_COUNT"),
        "INDIVIDUAL_STATE_DATASET_STATUS": status.get("INDIVIDUAL_STATE_DATASET_STATUS"),
        "FIRST_SOURCE_AWARE_MULTI_OUTCOME_BASELINE_STATUS": status.get(
            "FIRST_SOURCE_AWARE_MULTI_OUTCOME_BASELINE_STATUS"
        ),
    }
    _write_json(art / "verification.json", verification)

    report = f"""# Unified A+B Individual State + Source-Aware Multi-Outcome Baseline v{VERSION}

Generated: {_now()}

## Summary

- TECHNICAL_PASS={status.get('TECHNICAL_PASS')}
- EXACT_MULTI_DOMAIN_ACCOUNTING_STATUS={status.get('EXACT_MULTI_DOMAIN_ACCOUNTING_STATUS')}
- GLOBAL_A_B_SPLIT_STATUS={status.get('GLOBAL_A_B_SPLIT_STATUS')}
- INDIVIDUAL_STATE_DATASET_STATUS={status.get('INDIVIDUAL_STATE_DATASET_STATUS')}
- FIRST_SOURCE_AWARE_MULTI_OUTCOME_BASELINE_STATUS={status.get('FIRST_SOURCE_AWARE_MULTI_OUTCOME_BASELINE_STATUS')}
- baseline_claim={status.get('baseline_claim')}
- DOMAIN_ACCEPTED_MAPPING_COUNT=0
- SCIENTIFIC_CROSS_SOURCE_PASS=false
- SECURITY_STAGE_STATUS=PAUSED_NOT_ACCEPTED_BY_OWNER

## Non-claims

No clinical validation, treatment effect, causal effect, QSP/PKPD, or production readiness.

## Private datasets

Row-level Parquet remains under `private/unified-individual-state-v01/` (not in ZIP).
"""
    _write_md(art / "stage-report.md", report)
    _write_json(
        art / "stage-report.json",
        {
            "version": VERSION,
            "TECHNICAL_PASS": status.get("TECHNICAL_PASS"),
            "claim": status.get("baseline_claim"),
            "ok": status.get("ok"),
        },
    )
    _write_md(
        art / "REPRODUCE.md",
        f"""# Reproduce v{VERSION}

```bash
uv run --frozen audit --root . unified-individual-state run-v0.1 --no-publish
uv run --frozen audit --root . unified-individual-state verify-v0.1
uv run --frozen audit --root . unified-individual-state publish-v0.1
```

Private row-level data stays under `private/unified-individual-state-v01/`.
""",
    )
    _write_md(
        art / "REVIEW_GUIDE.md",
        f"""# Review guide v{VERSION}

Confirm state gates and overlap-guarded split before interpreting baseline metrics.
SCIENTIFIC_CROSS_SOURCE_PASS remains false. DOMAIN_ACCEPTED_MAPPING_COUNT=0 is expected.
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
        from human_simulator.unified_individual_state_v01.publish import publish

        result["publish"] = publish(root)
    return result
