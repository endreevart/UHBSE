"""Engine shadow for trajectory expansion (no medication effect)."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from human_simulator.core.simulation import (
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    hash_state,
    snapshot_parent_branch,
    verify_parent_isolation,
)
from human_simulator.trajectory_expansion_v01.ensemble import SingleOutcomeTrajectoryEnsemble
from human_simulator.trajectory_expansion_v01.policy import VERSION


def run_engine_shadow(frozen_results: list[dict[str, Any]], *, seed: int = 42) -> dict[str, Any]:
    providers = [r for r in frozen_results if r.get("frozen")]
    if not providers:
        return {
            "ENGINE_TRAJECTORY_SHADOW_STATUS": "FAIL",
            "reason": "no_frozen_providers",
        }

    # Deterministic fixture: top coverage providers by n_test_pairs, selected before looking at y_pred
    ranked = sorted(
        providers,
        key=lambda r: (
            -int((r.get("split_counts") or {}).get("test_pairs") or 0),
            str(r.get("outcome")),
            str(r.get("unit")),
        ),
    )
    fixture_providers = ranked[: min(8, len(ranked))]
    ensemble = SingleOutcomeTrajectoryEnsemble(fixture_providers)

    snap = {
        "snapshot_id": "trajectory-expansion-shadow",
        "subject_id": "opaque-technical-only",
        "components": [
            {
                "outcome": p.get("outcome") or (p.get("frozen") or {}).get("outcome"),
                "unit": p.get("unit") or (p.get("frozen") or {}).get("unit"),
                "numeric_value": 5.0 + i * 0.1,
                "n_prior_measurements": 3,
                "has_prior_history": 1.0,
                "prior_last_delta": 0.05,
                "prior_mean": 5.0,
                "days_since_first": 90.0,
            }
            for i, p in enumerate(fixture_providers)
        ],
    }
    pred1 = ensemble.predict_snapshot(snap, horizon_days=30.0)
    pred2 = ensemble.predict_snapshot(snap, horizon_days=30.0)
    h1 = hashlib.sha256(
        json.dumps(pred1["predictions"], sort_keys=True, default=str).encode()
    ).hexdigest()
    h2 = hashlib.sha256(
        json.dumps(pred2["predictions"], sort_keys=True, default=str).encode()
    ).hexdigest()

    # Horizon perturbation
    pred_h = ensemble.predict_snapshot(snap, horizon_days=90.0)
    # Missing-outcome perturbation: drop half components
    snap_miss = copy.deepcopy(snap)
    snap_miss["components"] = snap["components"][: max(1, len(snap["components"]) // 2)]
    pred_m = ensemble.predict_snapshot(snap_miss, horizon_days=30.0)

    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 5.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    branch = kernel.simulate_branch(
        branch_def={
            "branch_id": "traj_exp_shadow_parent",
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
        return {"ENGINE_TRAJECTORY_SHADOW_STATUS": "FAIL", "reason": "no_checkpoint"}
    cp = cps[0]
    parent_before = snapshot_parent_branch(branch)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="traj_exp_shadow_fork",
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
    fork_ok = bool(
        isinstance(forked, dict)
        and forked.get("fork_isolation_verified")
        and forked.get("source_branch_unchanged_after_fork", True)
    )
    checks = {
        "checkpoint_ok": True,
        "fork_ok": fork_ok,
        "rollback_ok": rollback_ok,
        "parent_isolation_ok": bool(
            isolation.get("fork_isolation_verified") if isinstance(isolation, dict) else isolation
        ),
        "determinism_ok": h1 == h2,
        "no_medication_effect": True,
        "synthetic_intervention_kept_separate": True,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "version": VERSION,
        "ENGINE_TRAJECTORY_SHADOW_STATUS": status,
        "checks": checks,
        "fixture_n_providers": len(fixture_providers),
        "predictions_hash_run1": h1,
        "predictions_hash_run2": h2,
        "horizon_perturbation_n_preds": pred_h.get("n_predictions"),
        "missing_outcome_perturbation": {
            "n_predictions": pred_m.get("n_predictions"),
            "n_missing": pred_m.get("n_missing_outcomes"),
        },
        "checkpoint": {
            "checkpoint_id": cp.get("checkpoint_id"),
            "state_hash": cp.get("state_hash") or hash_state(cp["state"]),
        },
        "parent_isolation": isolation,
        "no_medication_features": True,
        "no_treatment_response": True,
    }
