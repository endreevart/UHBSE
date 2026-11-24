"""Corrected bootstrap, upper-tail permutation, validation conformal uncertainty."""

from __future__ import annotations

import math
import random
from typing import Any

from human_simulator.intervention_association_v011.policy import (
    MIN_VAL_FOR_CALIBRATION_CLAIM,
    MIN_VAL_FOR_UNCERTAINTY,
    N_BOOTSTRAP,
    N_PERMUTATION,
    NOMINAL_COVERAGE,
    SEED,
    VERSION,
)


def finite_sample_permutation_p(*, count_ge_real: int, n_permutations: int) -> float:
    """(count + 1) / (n + 1); never literal 0.0."""
    return (int(count_ge_real) + 1) / (int(n_permutations) + 1)


def assert_permutation_p_not_literal_zero(p: float) -> None:
    if p == 0.0:
        raise ValueError("finite permutation p-value must not be serialized as literal 0.0")


def subject_mae(preds: list[dict[str, Any]]) -> dict[str, float]:
    from collections import defaultdict

    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[p["opaque_subject_key"]].append(abs(float(p["y_pred"]) - float(p["y_true"])))
    return {s: sum(v) / len(v) for s, v in by.items()}


def bootstrap_m1_vs_m2c(
    m1_preds: list[dict[str, Any]],
    m2c_preds: list[dict[str, Any]],
    *,
    n_bootstrap: int = N_BOOTSTRAP,
    seed: int = SEED,
) -> dict[str, Any]:
    s1 = subject_mae(m1_preds)
    s2 = subject_mae(m2c_preds)
    subjects = sorted(set(s1) & set(s2))
    if not subjects:
        return {"status": "INSUFFICIENT_DATA", "n_subjects": 0}
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_bootstrap):
        sample = [subjects[rng.randrange(len(subjects))] for _ in subjects]
        diffs.append(sum(s1[s] - s2[s] for s in sample) / len(sample))
    diffs.sort()
    real = sum(s1[s] - s2[s] for s in subjects) / len(subjects)
    return {
        "status": "COMPUTED",
        "n_bootstrap": n_bootstrap,
        "seed": seed,
        "n_subjects": len(subjects),
        "mean_subject_mae_improvement_m1_minus_m2c": real,
        "ci95": [diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs))]],
        "improvement_definition": "positive means M2C lower subject-MAE than M1",
    }


def permutation_m1_vs_m2c_upper_tail(
    m1_preds: list[dict[str, Any]],
    m2c_preds: list[dict[str, Any]],
    *,
    n_perm: int = N_PERMUTATION,
    seed: int = SEED,
) -> dict[str, Any]:
    """One-sided test: H0 no improvement; reject for large positive M1_MAE - M2C_MAE.

    Null: randomly flip subject-level model labels. Count permutations where
    permuted_improvement >= observed_improvement (upper tail).
    """
    s1 = subject_mae(m1_preds)
    s2 = subject_mae(m2c_preds)
    subjects = sorted(set(s1) & set(s2))
    if len(subjects) < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "PERMUTATION_DIRECTION_STATUS": "NOT_RUN",
            "permutation_p_value": None,
        }
    observed = sum(s1[s] - s2[s] for s in subjects) / len(subjects)
    rng = random.Random(seed + 1)
    count_ge = 0
    for _ in range(n_perm):
        flipped = 0.0
        for s in subjects:
            if rng.random() < 0.5:
                flipped += s2[s] - s1[s]
            else:
                flipped += s1[s] - s2[s]
        flipped /= len(subjects)
        if flipped >= observed:
            count_ge += 1
    p = finite_sample_permutation_p(count_ge_real=count_ge, n_permutations=n_perm)
    assert_permutation_p_not_literal_zero(p)
    return {
        "status": "COMPUTED",
        "PERMUTATION_DIRECTION_STATUS": "CORRECTED_UPPER_TAIL",
        "null_hypothesis": (
            "No systematic subject-MAE improvement of M2C over M1; "
            "label flips are exchangeable under H0"
        ),
        "alternative": "M2C improves subject-MAE vs M1 (positive improvement)",
        "tail": "upper",
        "count_rule": "permuted_improvement >= observed_improvement",
        "n_permutations": n_perm,
        "count_ge_observed": count_ge,
        "permutation_p_value": p,
        "permutation_p_value_formula": "(count_ge_observed + 1) / (n_permutations + 1)",
        "observed_mean_improvement": observed,
        "v01_defect": "v0.1 used lower-tail count (permuted <= observed); corrected here",
    }


def uncertainty_from_validation_residuals(
    val_preds: list[dict[str, Any]],
    test_preds: list[dict[str, Any]],
    *,
    nominal: float = NOMINAL_COVERAGE,
) -> dict[str, Any]:
    if not val_preds:
        return {
            "UNCERTAINTY_INTERVAL_CONSTRUCTION_STATUS": "REFUSED_EMPTY_VALIDATION",
            "UNCERTAINTY_CALIBRATION_STATUS": "NOT_COMPUTED",
            "sharpness_status": "NOT_COMPUTED",
            "n_validation": 0,
            "reason": "validation predictions absent",
        }
    if len(val_preds) < MIN_VAL_FOR_UNCERTAINTY:
        return {
            "UNCERTAINTY_INTERVAL_CONSTRUCTION_STATUS": "INSUFFICIENT_DATA",
            "UNCERTAINTY_CALIBRATION_STATUS": "INSUFFICIENT_DATA",
            "sharpness_status": "INSUFFICIENT_DATA",
            "n_validation": len(val_preds),
            "min_required": MIN_VAL_FOR_UNCERTAINTY,
        }

    abs_resid = sorted(abs(float(p["y_true"]) - float(p["y_pred"])) for p in val_preds)
    # finite-sample empirical/conformal residual quantile
    q_idx = min(len(abs_resid) - 1, max(0, int(math.ceil(nominal * (len(abs_resid) + 1)) - 1)))
    q = abs_resid[q_idx]

    widths = []
    covered = 0
    for p in test_preds:
        lo = float(p["y_pred"]) - q
        hi = float(p["y_pred"]) + q
        widths.append(hi - lo)
        if lo <= float(p["y_true"]) <= hi:
            covered += 1
    emp = covered / len(test_preds) if test_preds else None
    calib_ok = (
        len(val_preds) >= MIN_VAL_FOR_CALIBRATION_CLAIM
        and emp is not None
        and abs(emp - nominal) <= 0.10
    )
    return {
        "UNCERTAINTY_INTERVAL_CONSTRUCTION_STATUS": "COMPUTED",
        "method": "validation_empirical_residual_quantile_conformal",
        "n_validation": len(val_preds),
        "n_test": len(test_preds),
        "nominal_coverage": nominal,
        "quantile_index": q_idx,
        "residual_quantile": q,
        "empirical_coverage_test": emp,
        "mean_interval_width": sum(widths) / len(widths) if widths else None,
        "median_interval_width": sorted(widths)[len(widths) // 2] if widths else None,
        "UNCERTAINTY_CALIBRATION_STATUS": (
            "PASS_WITHIN_TOLERANCE" if calib_ok else "REPORTED_NOT_CLAIMED"
        ),
        "sharpness_status": "REPORTED_NOT_CLAIMED",
        "calibration_claim_gate_min_val": MIN_VAL_FOR_CALIBRATION_CLAIM,
    }


def summarize_signal(cohort_results: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [c for c in cohort_results if c.get("status") == "EVALUATED"]
    if not evaluated:
        return {
            "version": VERSION,
            "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": "INSUFFICIENT_DATA",
            "authoritative_comparison": "M1_vs_M2C",
        }
    improved = 0
    for c in evaluated:
        diff = (c.get("m2c_vs_m1") or {}).get("abs_mae_diff_micro")
        p = (c.get("permutation") or {}).get("permutation_p_value")
        if diff is not None and diff > 0 and p is not None and p < 0.05:
            improved += 1
    if improved:
        status = "EXPLORATORY_INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_SUPPORTED"
    else:
        status = "NO_INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_DETECTED"
    return {
        "version": VERSION,
        "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": status,
        "authoritative_comparison": "M1_vs_M2C",
        "legacy_ordinal_m2_excluded_from_decision": True,
        "n_cohorts_evaluated": len(evaluated),
        "n_cohorts_with_exploratory_signal": improved,
        "note": "Not causal or treatment-effect.",
    }
