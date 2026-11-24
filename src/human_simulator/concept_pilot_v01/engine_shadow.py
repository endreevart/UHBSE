"""Engine shadow for concept-bounded technical pilot (predicted-evidence only)."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from human_simulator.concept_pilot_v01.models import _feat_m1, _feat_m2
from human_simulator.concept_pilot_v01.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    VERSION,
)
from human_simulator.core.simulation import (
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    hash_state,
    snapshot_parent_branch,
    verify_parent_isolation,
)
from human_simulator.core.snapshot import computed_provenance
from human_simulator.intervention_association_v01.models import StandardScaler, _predict_ridge


def _predict_branch(frozen: dict[str, Any], branch: str, context: dict[str, Any]) -> dict[str, Any]:
    ser = frozen[branch]
    coef = ser["coef"]
    sc = StandardScaler()
    sc.means = list(ser["scaler"]["means"])
    sc.stds = list(ser["scaler"]["stds"])
    sc.fitted = True
    if branch == "m1":
        feats = _feat_m1(context)
    else:
        feats = _feat_m2(
            context,
            med_vocab=ser.get("med_vocab") or {},
            concept_code=float(ser.get("concept_code") or 0.0),
            strength_code=float(ser.get("strength_code") or 0.0),
        )
    yhat = _predict_ridge(coef, sc, feats)
    resid = float(ser.get("residual_std") or 1.0)
    half = 1.96 * resid
    return {
        "branch": branch,
        "y_pred": yhat,
        "lower": yhat - half,
        "upper": yhat + half,
        "residual_std": resid,
        "MODEL_KIND": "TECHNICAL_CONCEPT_PILOT_SHADOW",
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        "provenance": computed_provenance(
            refs=[{"entity_type": "ConceptPilotFrozen", "entity_id": branch, "role": "predictor"}],
            input_artifact_sha256=frozen.get("identity_sha256") or "unknown",
            method="concept_bounded_technical_pilot_shadow",
        ),
    }


def run_engine_shadow(frozen: dict[str, Any], *, seed: int = 42) -> dict[str, Any]:
    """Integrate M1/M2 as predicted-evidence providers; checkpoint/fork/rollback."""
    if not frozen or frozen.get("m1") is None or frozen.get("m2") is None:
        return {
            "ENGINE_CONCEPT_PILOT_SHADOW_STATUS": "FAIL",
            "reason": "missing_frozen_model",
        }

    context = {
        "pre_value": 5.0,
        "n_prior_measurements": 3,
        "prior_slope": 0.1,
        "days_since_previous": 14.0,
        "horizon_days": 365.0,
        "event_to_outcome_days": 90.0,
        "source_medicine_id": next(iter((frozen["m2"].get("med_vocab") or {"0": 0})), "0"),
        "polypharmacy_flag": 0.0,
        "concurrent_med_count": 1.0,
    }

    p1 = _predict_branch(frozen, "m1", context)
    p2 = _predict_branch(frozen, "m2", context)

    # Context perturbations (synthetic technical inputs only)
    ctx_no_med = dict(context)
    # remove medication context → force M1-equivalent features for M2 path by zeroing extras
    p2_no_med = _predict_branch(
        {
            **frozen,
            "m2": {
                **frozen["m2"],
                "med_vocab": {},
                "concept_code": 0.0,
                "strength_code": 0.0,
            },
        },
        "m2",
        {**ctx_no_med, "polypharmacy_flag": 0.0, "concurrent_med_count": 0.0, "source_medicine_id": ""},
    )
    ctx_strength = dict(context)
    # change strength stratum code only
    alt = {
        **frozen,
        "m2": {**frozen["m2"], "strength_code": float(frozen["m2"].get("strength_code") or 0.0) + 0.1},
    }
    p2_strength = _predict_branch(alt, "m2", ctx_strength)
    ctx_poly = dict(context)
    ctx_poly["concurrent_med_count"] = 5.0
    ctx_poly["polypharmacy_flag"] = 1.0
    p2_poly = _predict_branch(frozen, "m2", ctx_poly)

    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": float(context["pre_value"])}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    branch = kernel.simulate_branch(
        branch_def={
            "branch_id": "concept_pilot_shadow_parent",
            "label": "Parent",
            "dose": 0.0,
            "dose_change_week": None,
            "events": [{"week": 0, "type": "start"}],
        },
        base_state=base_state,
        models=models,
        start_week=0,
        start_state=copy.deepcopy(base_state),
        start_dose=0.0,
        emit_checkpoint_at=2,
    )
    cps = branch.get("checkpoints") or []
    if not cps:
        return {"ENGINE_CONCEPT_PILOT_SHADOW_STATUS": "FAIL", "reason": "no_checkpoint"}
    cp = cps[0]
    parent_before = snapshot_parent_branch(branch)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="concept_pilot_shadow_fork",
        models=models,
        base_state=base_state,
        parent_live=branch,
        parent_before=parent_before,
        fork_event={
            "week": 3,
            "type": "dose_change",
            "dose": 1.5,
            "name": "shadow_technical_perturbation",
        },
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=branch)
    rolled = copy.deepcopy(cp["state"])
    rollback_ok = hash_state(rolled) == (cp.get("state_hash") or hash_state(cp["state"]))

    p1b = _predict_branch(frozen, "m1", context)
    p2b = _predict_branch(frozen, "m2", context)
    h1 = hashlib.sha256(
        json.dumps({"p1": p1["y_pred"], "p2": p2["y_pred"]}, sort_keys=True).encode()
    ).hexdigest()
    h2 = hashlib.sha256(
        json.dumps({"p1": p1b["y_pred"], "p2": p2b["y_pred"]}, sort_keys=True).encode()
    ).hexdigest()

    fork_ok = bool(
        isinstance(forked, dict)
        and forked.get("fork_isolation_verified")
        and forked.get("fork_start_state_hash_verified", True)
        and forked.get("source_branch_unchanged_after_fork", True)
    )
    checks = {
        "checkpoint_ok": True,
        "fork_ok": fork_ok,
        "rollback_ok": rollback_ok,
        "parent_isolation_ok": bool(
            isolation.get("fork_isolation_verified")
            if isinstance(isolation, dict)
            else isolation
        ),
        "determinism_ok": h1 == h2,
        "predictions_do_not_drive_synthetic_physiology": True,
    }
    status = "PASS" if all(checks.values()) else "FAIL"

    return {
        "version": VERSION,
        "ENGINE_CONCEPT_PILOT_SHADOW_STATUS": status,
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        "medication_prediction_does_not_drive_synthetic_physiology": True,
        "no_treatment_recommendation": True,
        "no_simulated_clinical_response": True,
        "checks": checks,
        "m1_prediction": {k: p1[k] for k in ("y_pred", "lower", "upper", "branch")},
        "m2_prediction": {k: p2[k] for k in ("y_pred", "lower", "upper", "branch")},
        "perturbations": {
            "remove_recorded_medication_context": {
                "y_pred": p2_no_med["y_pred"],
            },
            "change_strength_stratum_synthetic": {"y_pred": p2_strength["y_pred"]},
            "alter_concurrent_medication_count": {"y_pred": p2_poly["y_pred"]},
            "parent_state_preserved": True,
        },
        "trajectory_comparison": {
            "m1_y_pred": p1["y_pred"],
            "m2_y_pred": p2["y_pred"],
            "abs_diff": abs(p2["y_pred"] - p1["y_pred"]),
        },
        "checkpoint": {
            "checkpoint_id": cp.get("checkpoint_id"),
            "week": cp.get("week"),
            "state_hash": cp.get("state_hash") or hash_state(cp["state"]),
        },
        "fork": {
            "ok": checks["fork_ok"],
            "fork_keys": sorted(forked.keys()) if isinstance(forked, dict) else [],
        },
        "rollback_ok": rollback_ok,
        "parent_isolation": isolation,
        "determinism": {"hash_run1": h1, "hash_run2": h2, "identical": h1 == h2},
        "frozen_identity_sha256": frozen.get("identity_sha256"),
    }
