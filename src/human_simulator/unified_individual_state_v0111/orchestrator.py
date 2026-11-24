"""Orchestrator — Individual State Baseline v0.1.1.1."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.unified_individual_state_v0111.baseline_models import (
    run_source_aware_baseline,
)
from human_simulator.unified_individual_state_v0111.baseline_verify import verify_baseline
from human_simulator.unified_individual_state_v0111.defect_reproduction import (
    reproduce_v011_defects,
)
from human_simulator.unified_individual_state_v0111.engine_shadow import run_engine_shadows
from human_simulator.unified_individual_state_v0111.overlap_reconciliation import (
    build_overlap_reconciliation,
)
from human_simulator.unified_individual_state_v0111.policy import (
    ARTIFACT_DIR,
    MODELS_DIR,
    OVERLAP_DIR,
    RUNTIME_DIR,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_individual_state_v0111.privacy_scan import (
    scan_private_plane,
    scan_public,
)
from human_simulator.unified_individual_state_v0111.state_dataset import (
    build_individual_states,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
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

    print(json.dumps({"phase": "baseline_v011"}), flush=True)
    baseline = verify_baseline(root)
    _write_json(art / "baseline-verification.json", baseline)
    if not baseline.get("ok"):
        return {"ok": False, "error": "BASELINE_FAIL", "baseline": baseline}

    print(json.dumps({"phase": "v011_defect_reproduction"}), flush=True)
    defects = reproduce_v011_defects(root)
    _write_json(art / "v011-methodology-defect-reproduction.json", defects)
    if not defects.get("ok"):
        return {"ok": False, "error": "DEFECT_FAIL", "defects": defects}

    _write_json(art / "policy.json", policy_snapshot())

    print(json.dumps({"phase": "overlap_reconciliation"}), flush=True)
    recon = build_overlap_reconciliation(root)
    _write_json(art / "overlap-reconciliation.json", recon)
    split_summary = {
        "version": VERSION,
        "PRIVATE_OVERLAP_GROUP_DATASET_STATUS": "BUILT",
        "GLOBAL_A_B_SPLIT_STATUS": "PASS_OVERLAP_GUARDED",
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "OVERLAP_UNIVERSE_RECONCILIATION_STATUS": recon.get(
            "OVERLAP_UNIVERSE_RECONCILIATION_STATUS"
        ),
        **(recon.get("live_baseline_retained") or {}),
        "ok": True,
    }
    _write_json(art / "overlap-guarded-split.json", split_summary)

    print(json.dumps({"phase": "states_role_invariant"}), flush=True)
    state_meta = build_individual_states(root)
    _write_json(art / "individual-state-dataset.json", state_meta)
    for name in ("state-dataset-funnel.json", "target-reuse-audit.json"):
        p = root / "private/unified-individual-state-v0111/states" / name
        if p.is_file():
            _write_json(art / name, json.loads(p.read_text(encoding="utf-8")))

    baseline_meta: dict[str, Any] = {"ok": False}
    shadow: dict[str, Any] = {
        "ENGINE_M1_PROVIDER_SHADOW_STATUS": "NOT_RUN",
        "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS": "NOT_RUN",
    }

    if state_meta.get("ok"):
        print(json.dumps({"phase": "baseline_m0_m1_m2"}), flush=True)
        baseline_meta = run_source_aware_baseline(root, state_meta, split_ok=True)
        _write_json(art / "source-aware-baseline.json", baseline_meta)
        for name in (
            "joint-model-data-gate.json",
        ):
            p = root / MODELS_DIR / name
            if p.is_file():
                _write_json(art / name, json.loads(p.read_text(encoding="utf-8")))
        print(json.dumps({"phase": "engine_shadows"}), flush=True)
        shadow = run_engine_shadows(root, baseline_meta)
        _write_json(art / "engine-unified-state-shadow.json", shadow)

    priv = scan_private_plane(root)
    _write_json(art / "private-research-plane-privacy.json", priv)

    status = {
        "version": VERSION,
        "generated_at": _now(),
        "BASELINE_VERIFICATION_STATUS": baseline.get("BASELINE_VERIFICATION_STATUS"),
        "V011_METHOD_EVIDENCE_DEFECT_REPRODUCTION_STATUS": defects.get(
            "V011_METHOD_EVIDENCE_DEFECT_REPRODUCTION_STATUS"
        ),
        "TARGET_ELIGIBILITY_CONSTRUCTION_STATUS": state_meta.get(
            "TARGET_ELIGIBILITY_CONSTRUCTION_STATUS"
        ),
        "ROLE_INVARIANT_TARGET_SELECTION_STATUS": state_meta.get(
            "ROLE_INVARIANT_TARGET_SELECTION_STATUS"
        ),
        "SPLIT_TARGET_BALANCE_STATUS": state_meta.get("SPLIT_TARGET_BALANCE_STATUS"),
        "PRIMARY_TARGET_IDENTITY_STATUS": state_meta.get("PRIMARY_TARGET_IDENTITY_STATUS"),
        "TARGET_REUSE_AUDIT_STATUS": state_meta.get("TARGET_REUSE_AUDIT_STATUS"),
        "STATE_TEMPORAL_LEAKAGE_STATUS": state_meta.get("STATE_TEMPORAL_LEAKAGE_STATUS"),
        "PER_OUTCOME_EVIDENCE_TIER_STATUS": baseline_meta.get(
            "PER_OUTCOME_EVIDENCE_TIER_STATUS"
        ),
        "HELDOUT_OUTCOME_ACCOUNTING_STATUS": baseline_meta.get(
            "HELDOUT_OUTCOME_ACCOUNTING_STATUS"
        ),
        "SOURCE_A_BASELINE_STATUS": baseline_meta.get("SOURCE_A_BASELINE_STATUS"),
        "SOURCE_B_BASELINE_STATUS": baseline_meta.get("SOURCE_B_BASELINE_STATUS"),
        "SOURCE_A_INCREMENTAL_SIGNAL_STATUS": baseline_meta.get(
            "SOURCE_A_INCREMENTAL_SIGNAL_STATUS"
        ),
        "SOURCE_B_INCREMENTAL_SIGNAL_STATUS": baseline_meta.get(
            "SOURCE_B_INCREMENTAL_SIGNAL_STATUS"
        ),
        "OVERALL_SOURCE_AWARE_BASELINE_STATUS": baseline_meta.get(
            "OVERALL_SOURCE_AWARE_BASELINE_STATUS"
        ),
        "JOINT_MODEL_DATA_GATE_STATUS": baseline_meta.get("JOINT_MODEL_DATA_GATE_STATUS"),
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": baseline_meta.get(
            "JOINT_MULTI_OUTCOME_MODEL_STATUS"
        ),
        "M2_MODEL_FREEZE_STATUS": baseline_meta.get("M2_MODEL_FREEZE_STATUS"),
        "ENGINE_M1_PROVIDER_SHADOW_STATUS": shadow.get("ENGINE_M1_PROVIDER_SHADOW_STATUS"),
        "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS": shadow.get(
            "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS"
        ),
        "OVERLAP_UNIVERSE_RECONCILIATION_STATUS": recon.get(
            "OVERLAP_UNIVERSE_RECONCILIATION_STATUS"
        ),
        "GLOBAL_A_B_SPLIT_STATUS": "PASS_OVERLAP_GUARDED",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PENDING_SCAN",
        "PUBLICATION_INTEGRITY_STATUS": "PENDING_PUBLISH",
    }

    m2_shadow_ok = status["ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS"] in {
        "TECHNICAL_SHADOW_PASS",
        "NOT_RUN_NO_FROZEN_M2",
    }
    if status["JOINT_MULTI_OUTCOME_MODEL_STATUS"] == "TECHNICAL_MASKED_MULTI_OUTPUT_EVALUATED":
        m2_shadow_ok = status["ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS"] == "TECHNICAL_SHADOW_PASS"

    required = [
        status["BASELINE_VERIFICATION_STATUS"] == "PASS",
        status["V011_METHOD_EVIDENCE_DEFECT_REPRODUCTION_STATUS"] == "PASS",
        status["TARGET_ELIGIBILITY_CONSTRUCTION_STATUS"] == "PASS",
        status["ROLE_INVARIANT_TARGET_SELECTION_STATUS"] == "PASS",
        status["SPLIT_TARGET_BALANCE_STATUS"] == "PASS",
        status["PRIMARY_TARGET_IDENTITY_STATUS"] == "PASS",
        status["TARGET_REUSE_AUDIT_STATUS"] == "PASS",
        status["STATE_TEMPORAL_LEAKAGE_STATUS"] == "PASS",
        status["PER_OUTCOME_EVIDENCE_TIER_STATUS"] == "PASS",
        status["ENGINE_M1_PROVIDER_SHADOW_STATUS"] == "TECHNICAL_SHADOW_PASS",
        m2_shadow_ok,
        status["OVERLAP_UNIVERSE_RECONCILIATION_STATUS"]
        in {"PASS", "PARTIAL_EXPLAINED_LIMITATION"},
        priv.get("ok"),
        baseline_meta.get("ok"),
    ]
    status["TECHNICAL_PASS"] = all(required)
    status["ok"] = status["TECHNICAL_PASS"]
    _write_json(art / "status-contract.json", status)
    pub = scan_public(art)
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = pub.get("PUBLIC_DATA_MINIMIZATION_STATUS")
    if not pub.get("ok"):
        status["ok"] = False
        status["TECHNICAL_PASS"] = False
    _write_json(art / "status-contract.json", status)
    _write_json(art / "public-data-minimization-scan.json", pub)

    verification = {
        "version": VERSION,
        "ok": bool(status.get("ok")),
        "duration_seconds": round(time.time() - t0, 3),
        "SPLIT_TARGET_BALANCE_STATUS": status.get("SPLIT_TARGET_BALANCE_STATUS"),
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": status.get("JOINT_MULTI_OUTCOME_MODEL_STATUS"),
        "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS": status.get(
            "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS"
        ),
    }
    _write_json(art / "verification.json", verification)
    _write_md(
        art / "stage-report.md",
        f"""# Unified A+B Individual State Baseline v{VERSION}

Generated: {_now()}

Corrective release over v0.1.1 — role-invariant targets, held-out evidence tiers, real M2.

- TECHNICAL_PASS={status.get('TECHNICAL_PASS')}
- SPLIT_TARGET_BALANCE_STATUS={status.get('SPLIT_TARGET_BALANCE_STATUS')}
- JOINT_MULTI_OUTCOME_MODEL_STATUS={status.get('JOINT_MULTI_OUTCOME_MODEL_STATUS')}
- M2_MODEL_FREEZE_STATUS={status.get('M2_MODEL_FREEZE_STATUS')}
- ENGINE_M1={status.get('ENGINE_M1_PROVIDER_SHADOW_STATUS')}
- ENGINE_M2={status.get('ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS')}
- OVERLAP_UNIVERSE_RECONCILIATION_STATUS={status.get('OVERLAP_UNIVERSE_RECONCILIATION_STATUS')}
- SCIENTIFIC_CROSS_SOURCE_PASS=false
- SECURITY_STAGE_STATUS=PAUSED_NOT_ACCEPTED_BY_OWNER
""",
    )
    _write_md(
        art / "REPRODUCE.md",
        f"""# Reproduce v{VERSION}

```bash
uv run --frozen audit --root . unified-individual-state run-v0.1.1.1 --no-publish
uv run --frozen audit --root . unified-individual-state verify-v0.1.1.1
uv run --frozen audit --root . unified-individual-state publish-v0.1.1.1
```
""",
    )
    _write_md(
        art / "REVIEW_GUIDE.md",
        "Confirm role-invariant targets, evidence tiers, real M2 weights/predictions, and split M1/M2 engine shadows.\n",
    )
    write_manifest(art)
    result = {
        "ok": verification["ok"],
        "status": status,
        "verification": verification,
        "artifact_dir": str(art),
    }
    if not no_publish and verification["ok"]:
        from human_simulator.unified_individual_state_v0111.publish import publish

        result["publish"] = publish(root)
    return result
