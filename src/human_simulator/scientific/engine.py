"""Integrate scientific baselines with the existing simulation kernel."""

from __future__ import annotations

from typing import Any

from human_simulator.core.simulation import SimulationKernel, hash_state
from human_simulator.scientific.models import (
    EmpiricalTrendBaseline,
    FirstLearnedBaseline,
    PersistenceBaseline,
)


def integrate_heldout_subject(
    *,
    pair: dict[str, Any],
    learned: FirstLearnedBaseline,
    seed: int = 42,
) -> dict[str, Any]:
    """One held-out pair: starting state at t0 → three models → compare to observed t1."""
    outcome_key = "selected_outcome"
    y0 = float(pair["y_t0"])
    y1 = float(pair["y_t1"])
    state = {outcome_key: y0}
    persistence = PersistenceBaseline()
    trend = EmpiricalTrendBaseline()

    p_pair = persistence.predict_pair(pair)
    t_pair = trend.predict_pair(pair)
    l_pair = learned.predict_pair(pair)

    # Kernel smoke: weekly steps for horizon weeks proxy
    horizon_weeks = max(1, int(round(float(pair["horizon_days"]) / 7.0)))
    kernel = SimulationKernel(seed=seed, horizon_weeks=min(horizon_weeks, 12), step_weeks=1)
    models = {
        "persistence": persistence,
        "empirical_trend": trend,
        "first_learned": learned,
    }
    # Use simulate_branch control-like path via kernel helpers
    branch = kernel.simulate_branch(
        branch_def={
            "branch_id": "retrospective_control",
            "label": "retrospective",
            "dose": 0.0,
            "dose_change_week": None,
            "events": [{"week": 0, "type": "start"}],
        },
        base_state=state,
        models=models,
        start_week=0,
        start_state=state,
        start_dose=0.0,
        emit_checkpoint_at=None,
    )
    return {
        "ok": True,
        "opaque_subject_key": pair["opaque_subject_key"],
        "pair_id": pair["pair_id"],
        "starting_state_hash": hash_state(state),
        "observed": {"y_t0": y0, "y_t1": y1, "horizon_days": pair["horizon_days"]},
        "predictions": {
            "persistence": {"y_pred": p_pair.y_pred, "abs_err": abs(p_pair.y_pred - y1)},
            "empirical_trend": {"y_pred": t_pair.y_pred, "abs_err": abs(t_pair.y_pred - y1)},
            "first_learned": {"y_pred": l_pair.y_pred, "abs_err": abs(l_pair.y_pred - y1)},
        },
        "uncertainty": {
            "persistence": {"lower": p_pair.lower, "upper": p_pair.upper},
            "empirical_trend": {"lower": t_pair.lower, "upper": t_pair.upper},
            "first_learned": {"lower": l_pair.lower, "upper": l_pair.upper},
        },
        "layers": {
            "observed": True,
            "computed": True,
            "synthetic_intervention_branch": "SEPARATED_NOT_USED_FOR_BACKTEST",
        },
        "kernel_final_state_hash": branch["final_state_hash"],
        "claim": "RETROSPECTIVE_COMPARISON_ONLY",
    }
