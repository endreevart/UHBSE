"""Bootstrap / permutation / uncertainty controls for M2 vs M1."""

from __future__ import annotations

import random
from typing import Any

from human_simulator.intervention_association_v01.policy import (
    N_BOOTSTRAP,
    N_PERMUTATION,
    SEED,
    VERSION,
)


def finite_sample_permutation_p(*, count_le_real: int, n_permutations: int) -> float:
    return (int(count_le_real) + 1) / (int(n_permutations) + 1)


def assert_permutation_p_not_literal_zero(p: float) -> None:
    if p == 0.0:
        raise ValueError("finite permutation p-value must not be serialized as literal 0.0")


def subject_mae(preds: list[dict[str, Any]]) -> dict[str, float]:
    from collections import defaultdict

    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[p["opaque_subject_key"]].append(abs(float(p["y_pred"]) - float(p["y_true"])))
    return {s: sum(v) / len(v) for s, v in by.items()}


def bootstrap_m2_vs_m1(
    m1_preds: list[dict[str, Any]],
    m2_preds: list[dict[str, Any]],
    *,
    n_bootstrap: int = N_BOOTSTRAP,
    seed: int = SEED,
) -> dict[str, Any]:
    s1 = subject_mae(m1_preds)
    s2 = subject_mae(m2_preds)
    subjects = sorted(set(s1) & set(s2))
    if not subjects:
        return {"status": "INSUFFICIENT_DATA", "n_subjects": 0}
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_bootstrap):
        sample = [subjects[rng.randrange(len(subjects))] for _ in subjects]
        d = sum(s1[s] - s2[s] for s in sample) / len(sample)
        diffs.append(d)
    diffs.sort()
    real = sum(s1[s] - s2[s] for s in subjects) / len(subjects)
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs))]
    return {
        "status": "COMPUTED",
        "n_bootstrap": n_bootstrap,
        "seed": seed,
        "n_subjects": len(subjects),
        "mean_subject_mae_improvement_m1_minus_m2": real,
        "ci95": [lo, hi],
    }


def permutation_m2_vs_m1(
    m1_preds: list[dict[str, Any]],
    m2_preds: list[dict[str, Any]],
    *,
    n_perm: int = N_PERMUTATION,
    seed: int = SEED,
) -> dict[str, Any]:
    s1 = subject_mae(m1_preds)
    s2 = subject_mae(m2_preds)
    subjects = sorted(set(s1) & set(s2))
    if len(subjects) < 2:
        return {"status": "INSUFFICIENT_DATA", "permutation_p_value": None}
    real = sum(s1[s] - s2[s] for s in subjects) / len(subjects)
    rng = random.Random(seed + 1)
    count_le = 0
    for _ in range(n_perm):
        # permute which model label is M2 at subject level
        flipped = 0.0
        for s in subjects:
            if rng.random() < 0.5:
                flipped += s2[s] - s1[s]
            else:
                flipped += s1[s] - s2[s]
        flipped /= len(subjects)
        if flipped <= real:
            count_le += 1
    p = finite_sample_permutation_p(count_le_real=count_le, n_permutations=n_perm)
    assert_permutation_p_not_literal_zero(p)
    return {
        "status": "COMPUTED",
        "n_permutations": n_perm,
        "count_le_real": count_le,
        "permutation_p_value": p,
        "permutation_p_value_formula": "(count_le_real + 1) / (n_permutations + 1)",
        "real_mean_improvement": real,
    }


def uncertainty_from_validation(
    val_preds: list[dict[str, Any]],
    test_preds: list[dict[str, Any]],
    *,
    residual_std: float,
    min_val: int = 30,
) -> dict[str, Any]:
    if len(val_preds) < min_val:
        return {
            "predictive_uncertainty_status": "INSUFFICIENT_DATA",
            "calibration_status": "INSUFFICIENT_DATA",
            "n_validation": len(val_preds),
        }
    # simple gaussian interval from residual_std (validation-calibrated upstream)
    z = 1.96
    covered = 0
    widths = []
    for p in test_preds:
        lo = p["y_pred"] - z * residual_std
        hi = p["y_pred"] + z * residual_std
        widths.append(hi - lo)
        if lo <= p["y_true"] <= hi:
            covered += 1
    cov = covered / len(test_preds) if test_preds else None
    return {
        "predictive_uncertainty_status": "COMPUTED",
        "calibration_status": "REPORTED_NOT_CLAIMED_SHARP",
        "nominal_coverage": 0.95,
        "empirical_coverage": cov,
        "mean_width": sum(widths) / len(widths) if widths else None,
        "residual_std": residual_std,
        "n_validation": len(val_preds),
        "n_test": len(test_preds),
    }


def summarize_incremental_signal(cohort_results: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [c for c in cohort_results if c.get("status") == "EVALUATED"]
    if not evaluated:
        return {
            "version": VERSION,
            "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": "INSUFFICIENT_DATA",
        }
    improved = 0
    for c in evaluated:
        diff = (c.get("m2_vs_m1") or {}).get("abs_mae_diff_micro")
        p = (c.get("permutation") or {}).get("permutation_p_value")
        if diff is not None and diff > 0 and p is not None and p < 0.05:
            improved += 1
    if improved:
        status = "EXPLORATORY_TECHNICAL_SIGNAL_SUPPORTED"
    else:
        status = "NO_INCREMENTAL_SIGNAL_DETECTED"
    return {
        "version": VERSION,
        "INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS": status,
        "n_cohorts_evaluated": len(evaluated),
        "n_cohorts_with_exploratory_signal": improved,
        "note": "Not a causal or treatment-effect claim.",
    }
