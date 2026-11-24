"""Backtest metrics with subject-macro primary metric (v0.1.1)."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.scientific.models import PairPrediction
from human_simulator.scientific.policy import MIN_TEST_SUBJECTS_FOR_INCREMENTAL


def pair_micro_mae(preds: list[PairPrediction]) -> float:
    return sum(abs(p.y_pred - p.y_true) for p in preds) / len(preds)


def pair_micro_rmse(preds: list[PairPrediction]) -> float:
    return math.sqrt(sum((p.y_pred - p.y_true) ** 2 for p in preds) / len(preds))


def subject_macro_mae(preds: list[PairPrediction]) -> float:
    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[p.opaque_subject_key].append(abs(p.y_pred - p.y_true))
    if not by:
        return float("nan")
    per_subj = [sum(v) / len(v) for v in by.values()]
    return sum(per_subj) / len(per_subj)


def coverage(preds: list[PairPrediction]) -> float:
    if not preds:
        return 0.0
    return sum(1 for p in preds if p.lower <= p.y_true <= p.upper) / len(preds)


def mean_interval_width(preds: list[PairPrediction]) -> float:
    if not preds:
        return 0.0
    return sum(p.upper - p.lower for p in preds) / len(preds)


def metrics_block(preds: list[PairPrediction]) -> dict[str, Any]:
    if not preds:
        return {"n_pairs": 0, "n_subjects": 0}
    subjects = {p.opaque_subject_key for p in preds}
    horizons = [p.horizon_days for p in preds]
    resid = [p.y_true - p.y_pred for p in preds]
    return {
        "n_pairs": len(preds),
        "n_subjects": len(subjects),
        "subject_macro_mae": subject_macro_mae(preds),
        "pair_micro_mae": pair_micro_mae(preds),
        "pair_micro_rmse": pair_micro_rmse(preds),
        "median_absolute_error": sorted(abs(p.y_pred - p.y_true) for p in preds)[len(preds) // 2],
        "mean_bias": sum(p.y_pred - p.y_true for p in preds) / len(preds),
        "empirical_interval_coverage": coverage(preds),
        "mean_interval_width": mean_interval_width(preds),
        "horizon_days": {
            "min": min(horizons),
            "median": sorted(horizons)[len(horizons) // 2],
            "max": max(horizons),
            "mean": sum(horizons) / len(horizons),
        },
        "residual_summary": {
            "mean": sum(resid) / len(resid),
            "std": math.sqrt(
                sum((r - sum(resid) / len(resid)) ** 2 for r in resid) / len(resid)
            ),
        },
    }


def compare_models(
    *,
    persistence: list[PairPrediction],
    trend: list[PairPrediction],
    learned: list[PairPrediction],
) -> dict[str, Any]:
    p_m = metrics_block(persistence)
    t_m = metrics_block(trend)
    l_m = metrics_block(learned)
    enough = (
        l_m.get("n_subjects", 0) >= MIN_TEST_SUBJECTS_FOR_INCREMENTAL
        and p_m.get("n_subjects", 0) >= MIN_TEST_SUBJECTS_FOR_INCREMENTAL
    )
    outperforms_persistence = bool(
        enough
        and l_m.get("subject_macro_mae", 1e9) < p_m.get("subject_macro_mae", 0)
        and l_m.get("pair_micro_mae", 1e9) < p_m.get("pair_micro_mae", 0)
    )
    outperforms_trend = bool(
        enough
        and l_m.get("subject_macro_mae", 1e9) < t_m.get("subject_macro_mae", 0)
        and l_m.get("pair_micro_mae", 1e9) < t_m.get("pair_micro_mae", 0)
    )
    if p_m.get("n_pairs", 0) == 0:
        status = "BACKTEST_PIPELINE_FAIL"
        incremental = "NO_INCREMENTAL_SIGNAL_DETECTED"
    else:
        status = "FIRST_EXPLORATORY_RETROSPECTIVE_BACKTEST_PASS"
        incremental = (
            "INCREMENTAL_SIGNAL_DETECTED"
            if outperforms_persistence
            else "NO_INCREMENTAL_SIGNAL_DETECTED"
        )
    return {
        "retrospective_backtest_status": status,
        "incremental_signal_status": incremental,
        "primary_metric": "subject_macro_mae",
        "secondary_metric": "pair_micro_mae",
        "outperforms_persistence": outperforms_persistence,
        "outperforms_empirical_trend": outperforms_trend,
        "delta_subject_macro_mae_vs_persistence": (
            (l_m.get("subject_macro_mae") - p_m.get("subject_macro_mae"))
            if l_m.get("n_pairs") and p_m.get("n_pairs")
            else None
        ),
        "persistence": p_m,
        "empirical_trend": t_m,
        "first_learned": l_m,
        "forbidden_statuses_not_used": [
            "CLINICALLY_VALIDATED",
            "CLINICALLY_ACCURATE",
            "TREATMENT_EFFECT_CONFIRMED",
            "PRODUCTION_READY",
        ],
    }


def uncertainty_status(
    *,
    val_preds: list[PairPrediction],
    test_preds: list[PairPrediction],
    nominal: float = 0.90,
    interval_multiplier: float,
    residual_estimation_split: str = "validation",
    min_val_for_construction: int = 10,
    min_test_subjects: int = 10,
    min_test_pairs: int = 10,
) -> dict[str, Any]:
    """Separate interval construction from independent calibration evaluation."""
    from human_simulator.scientific.policy import gaussian_interval_multiplier

    expected_z = gaussian_interval_multiplier(nominal)
    if abs(interval_multiplier - expected_z) > 1e-9:
        # caller must pass the coverage-derived multiplier (never hard-code 1.96 for 0.90)
        pass
    n_val = len(val_preds)
    n_test = len(test_preds)
    n_test_subjects = len({p.opaque_subject_key for p in test_preds})
    width = mean_interval_width(test_preds) if test_preds else None
    val_cov = coverage(val_preds) if val_preds else None
    test_cov = coverage(test_preds) if test_preds else None

    construction_ok = n_val >= min_val_for_construction and interval_multiplier > 0
    construction_status = (
        "UNCERTAINTY_INTERVAL_CONSTRUCTION_PASS"
        if construction_ok
        else "UNCERTAINTY_INTERVAL_CONSTRUCTION_FAIL"
    )

    held_out_sufficient = (
        n_test_subjects >= min_test_subjects and n_test >= min_test_pairs
    )
    limitations = [
        "INTERVAL_SHARPNESS_NOT_ESTABLISHED",
        "validation_coverage_is_in_sample_descriptive_when_residual_scale_fit_on_validation",
        "test_coverage_is_descriptive_only_unless_held_out_sample_meets_calibration_thresholds",
    ]
    if abs(interval_multiplier - 1.96) < 1e-12 and abs(nominal - 0.90) < 1e-12:
        limitations.append("incorrect_1.96_multiplier_for_nominal_0.90_forbidden")

    if not held_out_sufficient:
        calibration_status = "INSUFFICIENT_DATA_FOR_UNCERTAINTY_CALIBRATION"
    elif test_cov is None:
        calibration_status = "INSUFFICIENT_DATA_FOR_UNCERTAINTY_CALIBRATION"
    elif abs(test_cov - nominal) <= 0.15:
        calibration_status = "UNCERTAINTY_CALIBRATION_PASS"
    else:
        calibration_status = "UNCERTAINTY_CALIBRATION_FAIL"

    return {
        # back-compat primary field = calibration (not construction)
        "status": calibration_status,
        "uncertainty_interval_construction_status": construction_status,
        "uncertainty_calibration_status": calibration_status,
        "nominal_target_coverage": nominal,
        "interval_multiplier": interval_multiplier,
        "expected_interval_multiplier_from_nominal": expected_z,
        "interval_multiplier_matches_nominal": abs(interval_multiplier - expected_z) < 1e-9,
        "uses_fixed_1_96_for_0_90": abs(interval_multiplier - 1.96) < 1e-12
        and abs(nominal - 0.90) < 1e-12,
        "residual_estimation_split": residual_estimation_split,
        "calibration_sample_size": n_val,
        "independent_evaluation_sample_size": {
            "n_pairs": n_test,
            "n_subjects": n_test_subjects,
        },
        "min_required_for_construction": min_val_for_construction,
        "min_required_for_calibration": {
            "held_out_test_subjects": min_test_subjects,
            "held_out_test_pairs": min_test_pairs,
        },
        "held_out_sample_sufficient_for_calibration": held_out_sufficient,
        "method": "gaussian_interval_from_nominal_coverage_residual_std_fit_on_validation",
        "observed_coverage_validation_in_sample_descriptive": val_cov,
        "observed_coverage_test_held_out_descriptive": test_cov,
        # legacy keys kept as descriptive aliases
        "observed_coverage_validation": val_cov,
        "observed_coverage_test": test_cov,
        "mean_interval_width_test": width,
        "interval_sharpness_status": "INTERVAL_SHARPNESS_NOT_ESTABLISHED",
        "calibration_limitations": limitations,
    }
