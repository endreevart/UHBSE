"""Corrected uncertainty evaluation — policy hash before recomputation."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.unified_v011.policy import (
    SEED,
    UNCERTAINTY_SHARPNESS_POLICY,
    uncertainty_policy_hash,
)


def _coverage(preds: list[dict[str, Any]]) -> float:
    if not preds:
        return 0.0
    return sum(1 for p in preds if p["lower"] <= p["y_true"] <= p["upper"]) / len(preds)


def _mean_width(preds: list[dict[str, Any]]) -> float:
    if not preds:
        return 0.0
    return sum(p["upper"] - p["lower"] for p in preds) / len(preds)


def _median(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[len(s) // 2]


def _iqr(xs: list[float]) -> float:
    if len(xs) < 4:
        return float("nan")
    s = sorted(xs)
    q1 = s[len(s) // 4]
    q3 = s[(3 * len(s)) // 4]
    return q3 - q1


def interval_score(preds: list[dict[str, Any]], *, alpha: float = 0.10) -> float:
    """Winkler interval score at nominal (1-alpha) coverage."""
    if not preds:
        return float("nan")
    scores = []
    for p in preds:
        lo, hi, y = float(p["lower"]), float(p["upper"]), float(p["y_true"])
        width = hi - lo
        score = width
        if y < lo:
            score += (2.0 / alpha) * (lo - y)
        elif y > hi:
            score += (2.0 / alpha) * (y - hi)
        scores.append(score)
    return sum(scores) / len(scores)


def subject_cluster_coverage_ci(
    preds: list[dict[str, Any]],
    *,
    n_iter: int = 1000,
    seed: int = SEED,
) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in preds:
        by[str(p["opaque_subject_key"])].append(p)
    subjects = sorted(by)
    if len(subjects) < 2:
        return {"status": "INSUFFICIENT", "n_iterations": 0}
    rng = random.Random(seed)
    covs: list[float] = []
    for _ in range(n_iter):
        sample = [subjects[rng.randrange(len(subjects))] for _ in subjects]
        rows = [r for s in sample for r in by[s]]
        covs.append(_coverage(rows))
    covs_sorted = sorted(covs)
    return {
        "status": "COMPUTED",
        "n_iterations": n_iter,
        "seed": seed,
        "mean": sum(covs) / n_iter,
        "ci_95_lower": covs_sorted[int(0.025 * n_iter)],
        "ci_95_upper": covs_sorted[min(n_iter - 1, int(0.975 * n_iter))],
    }


def coverage_by_horizon(preds: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = (
        ("lt_1d", 0.0, 1.0),
        ("1_7d", 1.0, 7.0),
        ("7_30d", 7.0, 30.0),
        ("30_90d", 30.0, 90.0),
        ("90_365d", 90.0, 365.0),
        ("365_730d", 365.0, 730.0),
        ("gt_730d", 730.0, float("inf")),
    )
    out: dict[str, Any] = {}
    for name, lo, hi in buckets:
        rows = [p for p in preds if lo <= float(p.get("horizon_days") or 0) < hi]
        out[name] = {"n_pairs": len(rows), "coverage": _coverage(rows) if rows else None}
    return out


def coverage_by_starting_value_quantile(preds: list[dict[str, Any]]) -> dict[str, Any]:
    """Quantile bins on y_pred proxy for starting value (persistence ≈ y_t0 via y_pred)."""
    if len(preds) < 20:
        return {"status": "INSUFFICIENT"}
    # Use midpoint of interval as starting-value proxy when y_t0 not present
    starts = []
    for p in preds:
        starts.append(float(p["y_pred"]))  # persistence pred == y_t0; ridge ≈ near y_t0
    qs = [0.0, 0.25, 0.5, 0.75, 1.0]
    srt = sorted(starts)
    cuts = [srt[min(len(srt) - 1, int(q * (len(srt) - 1)))] for q in qs]
    out: dict[str, Any] = {}
    for i in range(4):
        lo, hi = cuts[i], cuts[i + 1]
        rows = [
            p
            for p in preds
            if (lo <= float(p["y_pred"]) < hi) or (i == 3 and float(p["y_pred"]) <= hi)
        ]
        out[f"q{i + 1}"] = {"n_pairs": len(rows), "coverage": _coverage(rows) if rows else None}
    return out


def evaluate_uncertainty(
    *,
    test_preds_ridge: list[dict[str, Any]],
    test_preds_persistence: list[dict[str, Any]] | None = None,
    val_n: int = 0,
    interval_construction_ok: bool = True,
    policy_hash_before: str | None = None,
) -> dict[str, Any]:
    """Evaluate uncertainty with pre-declared policy; overcoverage ≠ full PASS."""
    # Policy hash MUST be recorded before looking at coverage numbers.
    pre_hash = policy_hash_before or uncertainty_policy_hash()
    policy = dict(UNCERTAINTY_SHARPNESS_POLICY)
    assert pre_hash == uncertainty_policy_hash(), "policy mutated after hashing"

    nominal = float(policy["nominal_coverage"])
    observed = _coverage(test_preds_ridge)
    mean_w = _mean_width(test_preds_ridge)
    widths = [p["upper"] - p["lower"] for p in test_preds_ridge]
    ys = [float(p["y_true"]) for p in test_preds_ridge]
    coverage_error = observed - nominal
    over_thr = float(policy["overcoverage_threshold"])
    under_thr = float(policy["undercoverage_threshold"])

    if interval_construction_ok and val_n > 0:
        construction = "UNCERTAINTY_INTERVAL_CONSTRUCTION_PASS"
    else:
        construction = "UNCERTAINTY_INTERVAL_CONSTRUCTION_FAIL"

    coverage_status = "UNCERTAINTY_COVERAGE_ESTIMATED"
    if coverage_error > over_thr:
        coverage_detail = "UNCERTAINTY_OVERCONSERVATIVE"
    elif coverage_error < -under_thr:
        coverage_detail = "UNCERTAINTY_UNDERCOVERING"
    else:
        coverage_detail = "UNCERTAINTY_COVERAGE_NEAR_NOMINAL"

    outcome_iqr = _iqr(ys)
    width_vs_iqr = (mean_w / outcome_iqr) if outcome_iqr and not math.isnan(outcome_iqr) else None

    pers_cov = _coverage(test_preds_persistence or [])
    pers_width = _mean_width(test_preds_persistence or [])

    # Sharpness PASS only if pre-declared policy met AND not overconservative
    sharpness_pass = (
        coverage_detail != "UNCERTAINTY_OVERCONSERVATIVE"
        and coverage_detail != "UNCERTAINTY_UNDERCOVERING"
        and width_vs_iqr is not None
        and width_vs_iqr <= float(policy["max_mean_width_vs_outcome_iqr"])
        and abs(coverage_error) <= over_thr
    )
    if sharpness_pass:
        cal_sharp = "UNCERTAINTY_CALIBRATION_AND_SHARPNESS_PASS"
        sharpness_status = "ESTABLISHED"
    else:
        cal_sharp = "UNCERTAINTY_CALIBRATION_AND_SHARPNESS_NOT_ESTABLISHED"
        sharpness_status = "NOT_ESTABLISHED"

    # Explicit rule from brief: overcoverage cannot be full uncertainty PASS
    if coverage_detail == "UNCERTAINTY_OVERCONSERVATIVE":
        cal_sharp = "UNCERTAINTY_CALIBRATION_AND_SHARPNESS_NOT_ESTABLISHED"
        sharpness_status = "NOT_ESTABLISHED"

    return {
        "uncertainty_policy_hash_before_recomputation": pre_hash,
        "uncertainty_policy": policy,
        "nominal_coverage": nominal,
        "observed_coverage": observed,
        "coverage_error": coverage_error,
        "mean_interval_width": mean_w,
        "median_interval_width": _median(widths),
        "width_relative_to_outcome_iqr": width_vs_iqr,
        "outcome_iqr": outcome_iqr,
        "interval_score": interval_score(test_preds_ridge),
        "subject_cluster_coverage_ci": subject_cluster_coverage_ci(test_preds_ridge),
        "coverage_by_horizon": coverage_by_horizon(test_preds_ridge),
        "coverage_by_starting_value_quantile": coverage_by_starting_value_quantile(
            test_preds_ridge
        ),
        "persistence_interval_comparison": {
            "persistence_coverage": pers_cov,
            "persistence_mean_width": pers_width,
            "ridge_mean_width": mean_w,
            "ridge_narrower_than_persistence": (
                mean_w < pers_width if test_preds_persistence else None
            ),
        },
        "uncertainty_interval_construction_status": construction,
        "uncertainty_coverage_status": coverage_status,
        "uncertainty_coverage_detail": coverage_detail,
        "uncertainty_sharpness_status": sharpness_status,
        "uncertainty_calibration_and_sharpness_status": cal_sharp,
        "overcoverage_blocks_full_pass": coverage_detail == "UNCERTAINTY_OVERCONSERVATIVE",
        "n_test_pairs": len(test_preds_ridge),
    }
