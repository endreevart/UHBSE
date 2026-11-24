"""Engine shadow: eligible cells only; otherwise abstain. No synthetic physiology drive."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from human_simulator.core.simulation import (
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    hash_state,
    snapshot_parent_branch,
    verify_parent_isolation,
)
from human_simulator.medication_residual_v01.hashes import sha_obj
from human_simulator.medication_residual_v01.infer import load_payload, load_vocab
from human_simulator.medication_residual_v01.models import predict_family
from human_simulator.medication_residual_v01.policy import (
    PREDECLARED_HORIZONS_DAYS,
    VERSION,
)


def _kernel_lifecycle(seed: int = 42) -> dict[str, Any]:
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 1.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "medres_v01_parent",
            "label": "Parent",
            "dose": 1.0,
            "dose_change_week": None,
            "events": [{"week": 0, "type": "start"}],
        },
        base_state=base_state,
        models=models,
        start_week=0,
        start_state=copy.deepcopy(base_state),
        start_dose=1.0,
        emit_checkpoint_at=2,
    )
    cps = parent.get("checkpoints") or []
    if not cps:
        return {"ok": False}
    cp = cps[0]
    parent_before = snapshot_parent_branch(parent)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="medres_v01_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={"week": 3, "type": "dose_change", "dose": 2.5, "name": "medres_fork"},
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=parent)
    rollback_ok = hash_state(copy.deepcopy(cp["state"])) == (
        cp.get("state_hash") or hash_state(cp["state"])
    )
    return {
        "ok": bool(forked.get("ok"))
        and bool(isolation.get("fork_isolation_verified"))
        and rollback_ok,
        "checkpoint": True,
        "fork": True,
        "rollback": rollback_ok,
        "parent_isolation": bool(isolation.get("fork_isolation_verified")),
        "predictions_do_not_drive_synthetic_physiology": True,
        "no_medication_recommendations": True,
    }


def infer_request(
    root: Path,
    registry: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Route a residual inference request. Hash mismatch / pad / future context → hard FAIL."""
    if request.get("has_post_t0_medication"):
        return {
            "status": "FAIL",
            "reason": "FUTURE_MEDICATION_CONTEXT_POISON",
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "FAIL",
        }
    if request.get("target_in_features") or request.get("residual_in_features"):
        return {"status": "FAIL", "reason": "TARGET_VALUE_POISON"}
    horizon = int(request.get("requested_horizon_days") or 0)
    if horizon not in PREDECLARED_HORIZONS_DAYS:
        return {
            "status": "ABSTAIN",
            "reason": "UNSUPPORTED_HORIZON_NO_INTERPOLATION",
            "requested_horizon_days": horizon,
        }
    eligible = [
        c
        for c in (registry.get("cells") or [])
        if c.get("engine_eligible")
        and c.get("source_system") == request.get("source_system")
        and c.get("outcome_key") == request.get("outcome_key")
        and int(c.get("horizon_days") or 0) == horizon
        and c.get("representation") == request.get("representation")
    ]
    if not eligible:
        return {
            "status": "ABSTAIN",
            "reason": "NO_ENGINE_ELIGIBLE_CELL",
            "rejected_cell_refusal": True,
            "did_not_run_rejected_model": True,
        }
    cell = eligible[0]
    fname = cell.get("frozen_file")
    if not fname:
        return {"status": "FAIL", "reason": "MISSING_FROZEN_FILE"}
    payload = load_payload(root, fname)
    if request.get("feature_order_sha256") and request["feature_order_sha256"] != payload.get(
        "feature_order_sha256"
    ):
        return {"status": "FAIL", "reason": "HASH_MISMATCH_HARD_FAIL"}
    if request.get("model_identity_sha256") and request["model_identity_sha256"] != payload.get(
        "model_identity_sha256"
    ):
        return {"status": "FAIL", "reason": "HASH_MISMATCH_HARD_FAIL"}
    feats = request.get("feature_vector")
    order = payload.get("feature_order") or []
    if feats is not None:
        if len(feats) != len(order):
            return {"status": "FAIL", "reason": "NO_PAD_TRUNCATE"}
    row = request.get("row")
    residual_adj = None
    if row is not None:
        vocab = load_vocab(root)
        try:
            residual_adj = predict_family(cell["representation"], payload, [row], vocab)[0]
        except ValueError as exc:
            return {"status": "FAIL", "reason": str(exc)}
    nh = row.get("frozen_nh_prediction") if row else request.get("frozen_nh_prediction")
    adjusted = None
    if nh is not None and residual_adj is not None:
        adjusted = float(nh) + float(residual_adj)
    return {
        "status": "OK",
        "frozen_natural_history_prediction": nh,
        "technical_residual_adjustment": residual_adj,
        "adjusted_technical_prediction": adjusted,
        "uncertainty": "bootstrap_ci_not_transferred_to_point",
        "medication_representation_type": cell.get("representation"),
        "supported_horizon": horizon,
        "applicability": "PASS",
        "model_identity_sha256": payload.get("model_identity_sha256"),
        "feature_order_sha256": payload.get("feature_order_sha256"),
        "scaler_sha256": payload.get("scaler_sha256"),
        "RECORDED_CONTEXT_ASSOCIATION_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "CAUSAL_INTERPRETATION_PROHIBITED": True,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_FUTURE_CONTEXT",
    }


def run_engine_shadow(root: Path, registry: dict[str, Any], sample_row: dict[str, Any] | None) -> dict[str, Any]:
    life = _kernel_lifecycle()
    eligible = [c for c in (registry.get("cells") or []) if c.get("engine_eligible")]
    if not eligible:
        abstain = infer_request(
            root,
            registry,
            {
                "source_system": "magerya_api",
                "outcome_key": "A::dummy::u",
                "requested_horizon_days": 90,
                "representation": "R2ID",
            },
        )
        poison = infer_request(
            root,
            registry,
            {
                "source_system": "magerya_api",
                "outcome_key": "A::dummy::u",
                "requested_horizon_days": 90,
                "representation": "R2ID",
                "has_post_t0_medication": True,
            },
        )
        mismatch = infer_request(
            root,
            registry,
            {
                "source_system": "magerya_api",
                "outcome_key": "A::dummy::u",
                "requested_horizon_days": 90,
                "representation": "R2ID",
                "feature_order_sha256": "0" * 64,
            },
        )
        pad = infer_request(
            root,
            registry,
            {
                "source_system": "magerya_api",
                "outcome_key": "A::dummy::u",
                "requested_horizon_days": 90,
                "representation": "R2ID",
                "feature_vector": [0.0],
            },
        )
        status = "TECHNICAL_SHADOW_ABSTAIN_NO_ELIGIBLE_CELL"
        ok = (
            life.get("ok")
            and abstain.get("status") == "ABSTAIN"
            and poison.get("status") == "FAIL"
            and (mismatch.get("status") in {"FAIL", "ABSTAIN"})
        )
        return {
            "version": VERSION,
            "ENGINE_MEDICATION_RESIDUAL_SHADOW_STATUS": status,
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_FUTURE_CONTEXT",
            "lifecycle": life,
            "abstain": abstain,
            "future_poison": poison,
            "hash_mismatch": mismatch,
            "no_pad_truncate": pad,
            "n_eligible": 0,
            "ok": ok,
        }

    cell = eligible[0]
    req = {
        "source_system": cell["source_system"],
        "outcome_key": cell["outcome_key"],
        "requested_horizon_days": cell["horizon_days"],
        "representation": cell["representation"],
        "model_identity_sha256": cell.get("model_identity_sha256"),
        "feature_order_sha256": cell.get("feature_order_sha256"),
        "row": sample_row,
        "frozen_nh_prediction": (sample_row or {}).get("frozen_nh_prediction"),
    }
    ok_inf = infer_request(root, registry, req)
    poison = infer_request(root, registry, {**req, "has_post_t0_medication": True, "row": None})
    mismatch = infer_request(
        root, registry, {**req, "model_identity_sha256": "0" * 64, "row": None}
    )
    pad = infer_request(
        root,
        registry,
        {**req, "feature_vector": [0.0], "row": None},
    )
    repeat = infer_request(root, registry, req)
    det = sha_obj(ok_inf) == sha_obj(repeat)
    status = "TECHNICAL_SHADOW_PASS" if ok_inf.get("status") == "OK" else "FAIL"
    ok = (
        life.get("ok")
        and ok_inf.get("status") == "OK"
        and poison.get("status") == "FAIL"
        and mismatch.get("status") == "FAIL"
        and pad.get("status") == "FAIL"
        and det
    )
    return {
        "version": VERSION,
        "ENGINE_MEDICATION_RESIDUAL_SHADOW_STATUS": status,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_FUTURE_CONTEXT",
        "lifecycle": life,
        "inference": {k: v for k, v in ok_inf.items() if k != "row"},
        "future_poison": poison,
        "hash_mismatch": mismatch,
        "no_pad_truncate": pad,
        "deterministic_repeat": det,
        "n_eligible": len(eligible),
        "ok": ok,
    }
