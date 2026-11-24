"""Train-only residual distributions. Empirical, no assumed normal."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.natural_history_rollout_v01.hashes import sha_obj
from human_simulator.natural_history_rollout_v01.policy import PI_HI, PI_LO, SEED, VERSION
from human_simulator.natural_history_rollout_v01.providers import predict_active


def _quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    i = min(len(ys) - 1, max(0, int(q * (len(ys) - 1))))
    return ys[i]


def fit_residuals(train: list[dict[str, Any]], cells: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in train:
        by[(r["source_system"], r["outcome_key"], int(r["requested_horizon_days"]))].append(r)
    out = []
    for cell in cells:
        if cell.get("one_step_status") != "ONE_STEP_VALIDATION_ACCEPTED":
            continue
        key = (cell["source_system"], cell["outcome_key"], int(cell["horizon_days"]))
        rows = by.get(key) or []
        resid = []
        for r in rows:
            yhat = predict_active(cell, r["features"], r.get("history_values") or [])
            if math.isfinite(yhat):
                resid.append(float(r["observed"]) - yhat)
        if not resid:
            continue
        mean = sum(resid) / len(resid)
        var = sum((x - mean) ** 2 for x in resid) / max(len(resid), 1)
        std = math.sqrt(var) if var > 0 else 0.0
        dist = {
            "n": len(resid),
            "mean": mean,
            "std": std,
            "q05": _quantile(resid, PI_LO),
            "q50": _quantile(resid, 0.5),
            "q95": _quantile(resid, PI_HI),
            "samples": resid[:4000],
            "method": "empirical_subject_block_compatible",
            "normal_not_assumed": True,
        }
        dist["residual_distribution_sha256"] = sha_obj(
            [round(x, 6) for x in sorted(dist["samples"])[:500]]
        )
        cell["residual_dist"] = {
            k: dist[k]
            for k in dist
            if k != "samples"
        }
        cell["residual_samples"] = dist["samples"]
        out.append(
            {
                "source_system": cell["source_system"],
                "outcome_key": cell["outcome_key"],
                "horizon_days": cell["horizon_days"],
                "n": dist["n"],
                "q05": dist["q05"],
                "q50": dist["q50"],
                "q95": dist["q95"],
                "residual_distribution_sha256": dist["residual_distribution_sha256"],
                "normal_not_assumed": True,
            }
        )
    return {
        "version": VERSION,
        "STOCHASTIC_RESIDUAL_DISTRIBUTION_STATUS": "FITTED_TRAIN_EMPIRICAL",
        "public": out,
        "ok": True,
    }


def sample_residual(cell: dict[str, Any], rng: random.Random) -> float:
    xs = cell.get("residual_samples") or [0.0]
    return float(xs[rng.randrange(len(xs))])


def interval(cell: dict[str, Any], point: float) -> tuple[float, float]:
    dist = cell.get("residual_dist") or {}
    return point + float(dist.get("q05") or 0.0), point + float(dist.get("q95") or 0.0)
