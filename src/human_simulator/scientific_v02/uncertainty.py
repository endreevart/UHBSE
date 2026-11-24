"""Uncertainty on A-only held-out test for model v0.2."""

from __future__ import annotations

import math
from typing import Any

from human_simulator.unified_v012.quantile_fix import assign_exclusive_quantiles
from human_simulator.scientific_v02.policy import VERSION


def _iqr(vals: list[float]) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    q1 = s[int(0.25 * (len(s) - 1))]
    q3 = s[int(0.75 * (len(s) - 1))]
    return q3 - q1


def compute_uncertainty(
    test_preds_ridge: list[dict[str, Any]],
    test_preds_persistence: list[dict[str, Any]] | None = None,
    *,
    nominal_coverage: float = 0.90,
) -> dict[str, Any]:
    n = len(test_preds_ridge)
    if n == 0:
        return {
            "version": VERSION,
            "source_a_uncertainty_status": "INSUFFICIENT_DATA",
            "n_test_pairs": 0,
        }

    covered = [
        bool(p["lower"] <= p["y_true"] <= p["upper"]) for p in test_preds_ridge
    ]
    widths = [float(p["upper"]) - float(p["lower"]) for p in test_preds_ridge]
    y_true = [float(p["y_true"]) for p in test_preds_ridge]
    starts = [
        float(p["y_pred"])
        for p in (test_preds_persistence or test_preds_ridge)
    ]
    # Prefer persistence y_pred as y_t0 proxy when available
    if test_preds_persistence and len(test_preds_persistence) == n:
        starts = [float(p["y_pred"]) for p in test_preds_persistence]

    obs_cov = sum(covered) / n
    mean_w = sum(widths) / n
    med_w = sorted(widths)[n // 2]
    iqr = _iqr(y_true)
    exclusive = assign_exclusive_quantiles(starts)
    bins = {}
    for q, idxs in exclusive.items():
        if not idxs:
            bins[q] = {"n_pairs": 0, "coverage": None, "mean_width": None}
            continue
        cov = sum(1 for i in idxs if covered[i]) / len(idxs)
        bins[q] = {
            "n_pairs": len(idxs),
            "coverage": cov,
            "mean_width": sum(widths[i] for i in idxs) / len(idxs),
        }
    sum_n = sum(int(v["n_pairs"]) for v in bins.values())
    # pairwise empty + union full checked via exclusive assigner
    pairwise_empty = True
    keys = list(exclusive)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if set(exclusive[a]) & set(exclusive[b]):
                pairwise_empty = False

    # horizon coverage
    horizon_bins = {}
    for name, lo, hi in (
        ("lt_7d", 0.0, 7.0),
        ("7_30d", 7.0, 30.0),
        ("30_90d", 30.0, 90.0),
        ("90_365d", 90.0, 365.0),
        ("gt_365d", 365.0, float("inf")),
    ):
        idxs = [i for i, p in enumerate(test_preds_ridge) if lo <= float(p["horizon_days"]) < hi]
        if not idxs:
            horizon_bins[name] = {"n_pairs": 0, "coverage": None}
        else:
            horizon_bins[name] = {
                "n_pairs": len(idxs),
                "coverage": sum(1 for i in idxs if covered[i]) / len(idxs),
            }

    # Status honesty: high coverage alone ≠ calibration PASS
    if abs(obs_cov - nominal_coverage) <= 0.05 and mean_w / max(iqr, 1e-9) < 2.0:
        status = "UNCERTAINTY_CALIBRATION_AND_SHARPNESS_NOT_ESTABLISHED"
        # We still constructed intervals
        construction = "UNCERTAINTY_INTERVAL_CONSTRUCTION_PASS"
    elif obs_cov > nominal_coverage + 0.1:
        status = "UNCERTAINTY_OVERCONSERVATIVE"
        construction = "UNCERTAINTY_INTERVAL_CONSTRUCTION_PASS"
    elif obs_cov < nominal_coverage - 0.1:
        status = "UNCERTAINTY_UNDERCOVERAGE"
        construction = "UNCERTAINTY_INTERVAL_CONSTRUCTION_PASS"
    else:
        status = "UNCERTAINTY_CALIBRATION_AND_SHARPNESS_NOT_ESTABLISHED"
        construction = "UNCERTAINTY_INTERVAL_CONSTRUCTION_PASS"

    return {
        "version": VERSION,
        "source_a_uncertainty_status": status,
        "uncertainty_interval_construction_status": construction,
        "n_test_pairs": n,
        "legacy_956_pair_metrics_not_reused": True,
        "nominal_coverage": nominal_coverage,
        "observed_coverage": obs_cov,
        "mean_interval_width": mean_w,
        "median_interval_width": med_w,
        "interval_width_relative_to_outcome_iqr": mean_w / iqr if iqr else None,
        "outcome_iqr": iqr,
        "exclusive_starting_value_quartiles": {
            "bins": bins,
            "sum_bucket_counts": sum_n,
            "sum_equals_n": sum_n == n,
            "pairwise_intersection_empty": pairwise_empty,
            "union_equals_full": sum_n == n and pairwise_empty,
        },
        "coverage_by_horizon": horizon_bins,
        "note": (
            "High coverage alone does not imply calibration PASS. "
            "Not clinical validation."
        ),
    }
