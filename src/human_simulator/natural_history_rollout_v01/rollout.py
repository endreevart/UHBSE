"""Teacher-forced vs recursive free-running rollout. No future reads in recursive mode."""

from __future__ import annotations

import random
from typing import Any

from human_simulator.natural_history_rollout_v01.policy import MAX_STEPS, OOS_Z
from human_simulator.natural_history_rollout_v01.providers import predict_active
from human_simulator.natural_history_rollout_v01.residuals import interval, sample_residual
from human_simulator.natural_history_rollout_v01.times import bin_horizon


def _feat_from_history(history: list[float], horizons: list[float], req_h: float) -> dict[str, Any]:
    i = len(history) - 1
    prev = history[i - 1] if i >= 1 else None
    last_h = horizons[i - 1] if i >= 1 and horizons else 0.0
    return {
        "persistence_value": float(history[-1]),
        "n_prior_outcome_measurements": float(len(history)),
        "days_since_previous": float(last_h),
        "days_since_previous_missing": 0.0 if i >= 1 else 1.0,
        "prior_delta": float(history[-1] - prev) if prev is not None else 0.0,
        "prior_delta_missing": 0.0 if prev is not None else 1.0,
        "requested_horizon_days": float(req_h),
        "history_depth": float(len(history)),
        "missingness": 0.0,
    }


def evaluate_sequence(
    seq: dict[str, Any],
    cell: dict[str, Any],
    *,
    recursive: bool,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    vals = seq["values_json"]
    hs = seq["step_horizons_json"]
    n_steps = min(MAX_STEPS, len(hs))
    if n_steps < 1:
        return None
    preds = []
    history = [float(vals[0])]
    used_future = False
    oos = False
    ymin = cell.get("train_ymin")
    ymax = cell.get("train_ymax")
    ystd = float(cell.get("train_ystd") or 0.0)
    t0 = float(vals[0])
    dir_hit = 0
    for s in range(n_steps):
        req = bin_horizon(float(hs[s])) or cell["horizon_days"]
        feat = _feat_from_history(history, hs[:s], float(req))
        yhat = predict_active(cell, feat, history)
        if rng is not None:
            yhat = yhat + sample_residual(cell, rng)
        if ymin is not None and ymax is not None:
            pad = OOS_Z * ystd
            if yhat < float(ymin) - pad or yhat > float(ymax) + pad:
                oos = True
                break
        preds.append(yhat)
        obs_s = float(vals[s + 1])
        if (yhat - t0) * (obs_s - t0) > 0 or (abs(yhat - t0) < 1e-12 and abs(obs_s - t0) < 1e-12):
            dir_hit += 1
        if recursive:
            history.append(float(yhat))
        else:
            history.append(obs_s)
            used_future = True
    obs = [float(vals[s + 1]) for s in range(len(preds))]
    return {
        "n_steps": len(preds),
        "preds": preds,
        "obs": obs,
        "recursive": recursive,
        "read_future_values": used_future,
        "out_of_support": oos,
        "direction_hits": dir_hit,
        "subject": seq["source_scoped_subject_id"],
        "overlap_group_id": seq["overlap_group_id"],
    }


def persistence_sequence(seq: dict[str, Any], n_steps: int) -> list[float]:
    v0 = float(seq["values_json"][0])
    return [v0] * n_steps


def coverage_at(cell: dict[str, Any], preds: list[float], obs: list[float]) -> float:
    if not preds:
        return float("nan")
    hit = 0
    for p, o in zip(preds, obs, strict=True):
        lo, hi = interval(cell, p)
        if lo <= o <= hi:
            hit += 1
    return hit / len(preds)
