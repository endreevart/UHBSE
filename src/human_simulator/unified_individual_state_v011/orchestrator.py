"""Orchestrator — Individual State + Multi-Outcome Baseline v0.1.1 corrective."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.unified_individual_state_v011.baseline_models import (
    run_source_aware_baseline,
)
from human_simulator.unified_individual_state_v011.baseline_verify import verify_baseline
from human_simulator.unified_individual_state_v011.canonical_subject import (
    build_canonical_subject_map,
)
from human_simulator.unified_individual_state_v011.defect_reproduction import (
    reproduce_v01_methodology_defects,
)
from human_simulator.unified_individual_state_v011.engine_shadow import (
    run_engine_unified_state_shadow,
)
from human_simulator.unified_individual_state_v011.overlap_guard import (
    build_overlap_guarded_split,
)
from human_simulator.unified_individual_state_v011.policy import (
    ARTIFACT_DIR,
    CANONICAL_MAP_DIR,
    MODELS_DIR,
    OVERLAP_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_individual_state_v011.privacy_scan import (
    scan_private_plane,
    scan_public,
)
from human_simulator.unified_individual_state_v011.state_dataset import (
    build_individual_states,
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

    print(json.dumps({"phase": "baseline_v01"}), flush=True)
    baseline = verify_baseline(root)
    _write_json(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    print(json.dumps({"phase": "v01_defect_reproduction"}), flush=True)
    defects = reproduce_v01_methodology_defects(root)
    _write_json(art / "v01-methodology-defect-reproduction.json", defects)
    if not defects.get("ok"):
        return {"ok": False, "error": "DEFECT_REPRODUCTION_FAIL", "defects": defects}

    _write_json(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "canonical_subject_resolution"}), flush=True)
    canon = build_canonical_subject_map(root)
    # Drop large maps from public artifact
    public_canon = {k: v for k, v in canon.items() if k not in {"a_map", "b_map", "research_ids"}}
    _write_json(art / "canonical-subject-resolution.json", public_canon)
    if not canon.get("ok"):
        return {"ok": False, "error": "CANONICAL_SUBJECT_FAIL", "canonical": public_canon}

    print(json.dumps({"phase": "overlap_rebuild"}), flush=True)
    split = build_overlap_guarded_split(root)
    _write_json(art / "overlap-guarded-split.json", split)
    # Copy reconciliation / integrity aggregates to public artifacts
    for name in (
        "overlap-reconciliation.json",
        "overlap-group-integrity.json",
        "overlap-split-summary.json",
    ):
        src = root / OVERLAP_DIR / name
        if src.is_file():
            _write_json(art / name, json.loads(src.read_text(encoding="utf-8")))

    state_meta: dict[str, Any] = {"ok": False}
    baseline_meta: dict[str, Any] = {"ok": False}
    shadow: dict[str, Any] = {
        "ENGINE_UNIFIED_STATE_SHADOW_STATUS": "NOT_RUN",
        "ok": False,
    }

    if split.get("ok"):
        print(json.dumps({"phase": "individual_states_rebuild"}), flush=True)
        state_meta = build_individual_states(root)
        _write_json(art / "individual-state-dataset.json", state_meta)
        if (root / "private/unified-individual-state-v011/states/target-reuse-audit.json").is_file():
            _write_json(
                art / "target-reuse-audit.json",
                json.loads(
                    (
                        root
                        / "private/unified-individual-state-v011/states/target-reuse-audit.json"
                    ).read_text(encoding="utf-8")
                ),
            )
        if (root / "private/unified-individual-state-v011/states/state-dataset-funnel.json").is_file():
            _write_json(
                art / "state-dataset-funnel.json",
                json.loads(
                    (
                        root
                        / "private/unified-individual-state-v011/states/state-dataset-funnel.json"
                    ).read_text(encoding="utf-8")
                ),
            )
        if state_meta.get("ok"):
            print(json.dumps({"phase": "baseline_models"}), flush=True)
            baseline_meta = run_source_aware_baseline(
                root, state_meta, split_ok=True
            )
            _write_json(art / "source-aware-baseline.json", baseline_meta)
            gate_src = root / MODELS_DIR / "joint-model-data-gate.json"
            if gate_src.is_file():
                _write_json(
                    art / "joint-model-data-gate.json",
                    json.loads(gate_src.read_text(encoding="utf-8")),
                )
            freeze_ver = root / MODELS_DIR / "model-freeze-verification.json"
            if freeze_ver.is_file():
                _write_json(
                    art / "model-freeze-verification.json",
                    json.loads(freeze_ver.read_text(encoding="utf-8")),
                )
            print(json.dumps({"phase": "engine_shadow"}), flush=True)
            shadow = run_engine_unified_state_shadow(root, baseline_meta)
            _write_json(art / "engine-unified-state-shadow.json", shadow)
            baseline_meta["ENGINE_UNIFIED_STATE_SHADOW_STATUS"] = shadow.get(
                "ENGINE_UNIFIED_STATE_SHADOW_STATUS"
            )

    print(json.dumps({"phase": "privacy"}), flush=True)
    priv = scan_private_plane(root)
    _write_json(art / "private-research-plane-privacy.json", priv)

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V01_METHODOLOGY_DEFECT_REPRODUCTION_STATUS": defects.get(
            "V01_METHODOLOGY_DEFECT_REPRODUCTION_STATUS"
        ),
        "CANONICAL_SUBJECT_ID_RESOLUTION_STATUS": canon.get(
            "CANONICAL_SUBJECT_ID_RESOLUTION_STATUS"
        ),
        "OVERLAP_UNIVERSE_RECONCILIATION_STATUS": split.get(
            "OVERLAP_UNIVERSE_RECONCILIATION_STATUS"
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
        "PRIMARY_TARGET_IDENTITY_STATUS": state_meta.get(
            "PRIMARY_TARGET_IDENTITY_STATUS", "NOT_STARTED"
        ),
        "TARGET_REUSE_AUDIT_STATUS": state_meta.get(
            "TARGET_REUSE_AUDIT_STATUS", "NOT_STARTED"
        ),
        "STATE_DATASET_ACCOUNTING_STATUS": state_meta.get(
            "STATE_DATASET_ACCOUNTING_STATUS", "NOT_STARTED"
        ),
        "STATE_TEMPORAL_LEAKAGE_STATUS": state_meta.get(
            "STATE_TEMPORAL_LEAKAGE_STATUS", "NOT_STARTED"
        ),
        "SOURCE_A_BASELINE_STATUS": baseline_meta.get("SOURCE_A_BASELINE_STATUS", "NOT_RUN"),
        "SOURCE_B_BASELINE_STATUS": baseline_meta.get("SOURCE_B_BASELINE_STATUS", "NOT_RUN"),
        "SOURCE_A_INCREMENTAL_SIGNAL_STATUS": baseline_meta.get(
            "SOURCE_A_INCREMENTAL_SIGNAL_STATUS"
        ),
        "SOURCE_B_INCREMENTAL_SIGNAL_STATUS": baseline_meta.get(
            "SOURCE_B_INCREMENTAL_SIGNAL_STATUS"
        ),
        "CROSS_OUTCOME_AGGREGATE_STATUS": baseline_meta.get(
            "CROSS_OUTCOME_AGGREGATE_STATUS"
        ),
        "OVERALL_SOURCE_AWARE_BASELINE_STATUS": baseline_meta.get(
            "OVERALL_SOURCE_AWARE_BASELINE_STATUS"
        ),
        "JOINT_MODEL_DATA_GATE_STATUS": baseline_meta.get("JOINT_MODEL_DATA_GATE_STATUS"),
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": baseline_meta.get(
            "JOINT_MULTI_OUTCOME_MODEL_STATUS"
        ),
        "MODEL_FILE_HASH_STATUS": baseline_meta.get("MODEL_FILE_HASH_STATUS"),
        "MODEL_IDENTITY_RECOMPUTATION_STATUS": baseline_meta.get(
            "MODEL_IDENTITY_RECOMPUTATION_STATUS"
        ),
        "FROZEN_PROVIDER_RELOAD_STATUS": baseline_meta.get(
            "FROZEN_PROVIDER_RELOAD_STATUS"
        ),
        "SOURCE_AWARE_MODEL_FREEZE_STATUS": baseline_meta.get(
            "SOURCE_AWARE_MODEL_FREEZE_STATUS"
        ),
        "ENGINE_UNIFIED_STATE_SHADOW_STATUS": shadow.get(
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
    }

    required_pass = [
        status["BASELINE_VERIFICATION_STATUS"] == "PASS",
        status["V01_METHODOLOGY_DEFECT_REPRODUCTION_STATUS"] == "PASS",
        status["CANONICAL_SUBJECT_ID_RESOLUTION_STATUS"] == "PASS",
        status["OVERLAP_UNIVERSE_RECONCILIATION_STATUS"] == "PASS",
        status["PRIVATE_OVERLAP_GROUP_DATASET_STATUS"] == "BUILT",
        status["GLOBAL_A_B_SPLIT_STATUS"] == "PASS_OVERLAP_GUARDED",
        status["INDIVIDUAL_STATE_DATASET_STATUS"] == "REBUILT",
        status["PRIMARY_TARGET_IDENTITY_STATUS"] == "PASS",
        status["TARGET_REUSE_AUDIT_STATUS"] == "PASS",
        status["STATE_DATASET_ACCOUNTING_STATUS"] == "PASS",
        status["STATE_TEMPORAL_LEAKAGE_STATUS"] == "PASS",
        status["SOURCE_AWARE_MODEL_FREEZE_STATUS"] == "FROZEN",
        status["ENGINE_UNIFIED_STATE_SHADOW_STATUS"] == "TECHNICAL_SHADOW_PASS",
        priv.get("ok"),
    ]
    status["TECHNICAL_PASS"] = all(required_pass)
    status["ok"] = status["TECHNICAL_PASS"]

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
        "INDIVIDUAL_STATE_DATASET_STATUS": status.get("INDIVIDUAL_STATE_DATASET_STATUS"),
        "GLOBAL_A_B_SPLIT_STATUS": status.get("GLOBAL_A_B_SPLIT_STATUS"),
        "OVERALL_SOURCE_AWARE_BASELINE_STATUS": status.get(
            "OVERALL_SOURCE_AWARE_BASELINE_STATUS"
        ),
        "ENGINE_UNIFIED_STATE_SHADOW_STATUS": status.get(
            "ENGINE_UNIFIED_STATE_SHADOW_STATUS"
        ),
    }
    _write_json(art / "verification.json", verification)

    report = f"""# Unified A+B Individual State + Multi-Outcome Baseline v{VERSION}

Generated: {_now()}

## Summary

Corrective release over published v0.1 — overlap identity, target reuse, metrics, Ridge,
M2 gate, freeze identity recomputation, and real engine shadow.

- TECHNICAL_PASS={status.get('TECHNICAL_PASS')}
- V01_METHODOLOGY_DEFECT_REPRODUCTION_STATUS={status.get('V01_METHODOLOGY_DEFECT_REPRODUCTION_STATUS')}
- CANONICAL_SUBJECT_ID_RESOLUTION_STATUS={status.get('CANONICAL_SUBJECT_ID_RESOLUTION_STATUS')}
- GLOBAL_A_B_SPLIT_STATUS={status.get('GLOBAL_A_B_SPLIT_STATUS')}
- INDIVIDUAL_STATE_DATASET_STATUS={status.get('INDIVIDUAL_STATE_DATASET_STATUS')}
- TARGET_REUSE_AUDIT_STATUS={status.get('TARGET_REUSE_AUDIT_STATUS')}
- SOURCE_A_INCREMENTAL_SIGNAL_STATUS={status.get('SOURCE_A_INCREMENTAL_SIGNAL_STATUS')}
- SOURCE_B_INCREMENTAL_SIGNAL_STATUS={status.get('SOURCE_B_INCREMENTAL_SIGNAL_STATUS')}
- OVERALL_SOURCE_AWARE_BASELINE_STATUS={status.get('OVERALL_SOURCE_AWARE_BASELINE_STATUS')}
- JOINT_MULTI_OUTCOME_MODEL_STATUS={status.get('JOINT_MULTI_OUTCOME_MODEL_STATUS')}
- ENGINE_UNIFIED_STATE_SHADOW_STATUS={status.get('ENGINE_UNIFIED_STATE_SHADOW_STATUS')}
- DOMAIN_ACCEPTED_MAPPING_COUNT=0
- SCIENTIFIC_CROSS_SOURCE_PASS=false
- SECURITY_STAGE_STATUS=PAUSED_NOT_ACCEPTED_BY_OWNER

## Non-claims

No clinical validation, treatment effect, causal effect, QSP/PKPD, or production readiness.
No identity merge A↔B. No pooled raw MAE across outcome units.

## Private datasets

Row-level Parquet remains under `private/unified-individual-state-v011/` (not in ZIP).
"""
    _write_md(art / "stage-report.md", report)
    _write_json(
        art / "stage-report.json",
        {
            "version": VERSION,
            "TECHNICAL_PASS": status.get("TECHNICAL_PASS"),
            "overall": status.get("OVERALL_SOURCE_AWARE_BASELINE_STATUS"),
            "ok": status.get("ok"),
        },
    )
    _write_md(
        art / "REPRODUCE.md",
        f"""# Reproduce v{VERSION}

```bash
uv run --frozen audit --root . unified-individual-state run-v0.1.1 --no-publish
uv run --frozen audit --root . unified-individual-state verify-v0.1.1
uv run --frozen audit --root . unified-individual-state publish-v0.1.1
```

Private row-level data stays under `private/unified-individual-state-v011/`.
Do not overwrite v0.1 ZIP.
""",
    )
    _write_md(
        art / "REVIEW_GUIDE.md",
        f"""# Review guide v{VERSION}

Confirm defect reproduction, canonical subject resolution, non-zero overlap reconciliation,
primary target reuse=0, per-outcome metrics (no pooled raw MAE), computed M2 gate,
freeze identity recomputation, and real engine checkpoint/fork/rollback shadow.
""",
    )

    # Ensure private map dir noted but not copied
    _ = CANONICAL_MAP_DIR

    write_manifest(art)
    result = {
        "ok": verification["ok"],
        "status": status,
        "verification": verification,
        "artifact_dir": str(art),
    }
    if not no_publish and verification["ok"]:
        from human_simulator.unified_individual_state_v011.publish import publish

        result["publish"] = publish(root)
    return result
