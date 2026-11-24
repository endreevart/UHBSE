"""Negative controls, association status, and technical residual intervals."""

from __future__ import annotations

import statistics
from typing import Any

from human_simulator.concept_pilot_v01.models import run_fold_baselines
from human_simulator.concept_pilot_v01.policy import N_PERMUTATION, SEED, VERSION
from human_simulator.intervention_association_v01.evaluate import (
    assert_permutation_p_not_literal_zero,
    finite_sample_permutation_p,
)


def fold_stability(deltas: list[float]) -> dict[str, Any]:
    if len(deltas) < 2:
        return {"status": "INSUFFICIENT_FOLDS", "n": len(deltas)}
    mean = sum(deltas) / len(deltas)
    stdev = statistics.pstdev(deltas)
    sign_flip = any(d > 0 for d in deltas) and any(d < 0 for d in deltas)
    unstable = sign_flip or (abs(mean) > 1e-12 and stdev > abs(mean))
    return {
        "status": "UNSTABLE" if unstable else "STABLE",
        "mean_m1_minus_m2": mean,
        "stdev": stdev,
        "sign_flip_across_folds": sign_flip,
        "n_folds": len(deltas),
    }


def association_status(*, mean_delta: float, stability: dict[str, Any]) -> str:
    if stability.get("status") == "UNSTABLE":
        return "TECHNICAL_RESULT_UNSTABLE_ACROSS_FOLDS"
    if mean_delta > 1e-6:
        return "TECHNICAL_ASSOCIATION_DIFFERENCE_OBSERVED"
    return "NO_TECHNICAL_ASSOCIATION_DIFFERENCE_DETECTED"


def run_negative_controls(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    *,
    outcome: str,
    unit: str,
    concept_hash: str,
    strength_stratum: str,
    real_delta: float,
    n_perm: int = N_PERMUTATION,
) -> dict[str, Any]:
    """Train-fold-only shuffles / ablations; finite permutation p."""
    real = run_fold_baselines(
        train,
        test,
        outcome=outcome,
        unit=unit,
        concept_hash=concept_hash,
        strength_stratum=strength_stratum,
    )
    if real.get("status") != "EVALUATED":
        return {"status": "INSUFFICIENT_FOLD_DATA", "real": real}

    shuffle_med_deltas = []
    shuffle_time_deltas = []
    for i in range(n_perm):
        sm = run_fold_baselines(
            train,
            test,
            outcome=outcome,
            unit=unit,
            concept_hash=concept_hash,
            strength_stratum=strength_stratum,
            shuffle_med_context=True,
            rng_seed=SEED + 1000 + i,
        )
        st = run_fold_baselines(
            train,
            test,
            outcome=outcome,
            unit=unit,
            concept_hash=concept_hash,
            strength_stratum=strength_stratum,
            shuffle_event_time=True,
            rng_seed=SEED + 2000 + i,
        )
        if sm.get("status") == "EVALUATED":
            shuffle_med_deltas.append(float(sm["m1_minus_m2_subject_macro_mae"]))
        if st.get("status") == "EVALUATED":
            shuffle_time_deltas.append(float(st["m1_minus_m2_subject_macro_mae"]))

    drop_s = run_fold_baselines(
        train,
        test,
        outcome=outcome,
        unit=unit,
        concept_hash=concept_hash,
        strength_stratum=strength_stratum,
        drop_strength=True,
    )
    drop_p = run_fold_baselines(
        train,
        test,
        outcome=outcome,
        unit=unit,
        concept_hash=concept_hash,
        strength_stratum=strength_stratum,
        drop_poly=True,
    )

    count_med = sum(1 for d in shuffle_med_deltas if d >= real_delta)
    count_time = sum(1 for d in shuffle_time_deltas if d >= real_delta)
    p_med = finite_sample_permutation_p(
        count_le_real=count_med, n_permutations=max(len(shuffle_med_deltas), 1)
    )
    p_time = finite_sample_permutation_p(
        count_le_real=count_time, n_permutations=max(len(shuffle_time_deltas), 1)
    )
    assert_permutation_p_not_literal_zero(p_med)
    assert_permutation_p_not_literal_zero(p_time)

    return {
        "version": VERSION,
        "status": "COMPUTED",
        "DIAGNOSTIC_PIPELINE_ONLY_NOT_CAUSAL": True,
        "real_m1_minus_m2": real_delta,
        "shuffle_medication_context": {
            "n": len(shuffle_med_deltas),
            "mean_delta": (
                sum(shuffle_med_deltas) / len(shuffle_med_deltas) if shuffle_med_deltas else None
            ),
            "count_ge_real": count_med,
            "permutation_p_value": p_med,
            "formula": "(count + 1) / (n + 1)",
        },
        "shuffle_event_time": {
            "n": len(shuffle_time_deltas),
            "mean_delta": (
                sum(shuffle_time_deltas) / len(shuffle_time_deltas)
                if shuffle_time_deltas
                else None
            ),
            "count_ge_real": count_time,
            "permutation_p_value": p_time,
            "formula": "(count + 1) / (n + 1)",
        },
        "ablate_strength": {
            "status": drop_s.get("status"),
            "m1_minus_m2": drop_s.get("m1_minus_m2_subject_macro_mae"),
        },
        "ablate_polypharmacy": {
            "status": drop_p.get("status"),
            "m1_minus_m2": drop_p.get("m1_minus_m2_subject_macro_mae"),
        },
    }


def uncertainty_from_fold_residuals(
    fold_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Technical residual interval from validation-fold residuals (CV folds as val)."""
    coverages = []
    widths = []
    for fr in fold_results:
        if fr.get("status") != "EVALUATED":
            continue
        resid = float(fr.get("train_residual_std_m2") or 0.0)
        if resid <= 0:
            continue
        preds = fr.get("m2_preds") or []
        if len(preds) < 5:
            continue
        z = 1.96
        covered = 0
        for p in preds:
            lo = p["y_pred"] - z * resid
            hi = p["y_pred"] + z * resid
            widths.append(hi - lo)
            if lo <= p["y_true"] <= hi:
                covered += 1
        coverages.append(covered / len(preds))

    if not coverages:
        return {
            "TECHNICAL_INTERVAL_STATUS": "INSUFFICIENT_DATA_FOR_INTERVAL",
            "nominal_coverage": 0.95,
            "note": "Not clinical calibration.",
        }

    mean_cov = sum(coverages) / len(coverages)
    mean_w = sum(widths) / len(widths) if widths else None
    cov_stdev = statistics.pstdev(coverages) if len(coverages) > 1 else 0.0
    unstable = cov_stdev > 0.15
    return {
        "TECHNICAL_INTERVAL_STATUS": (
            "TECHNICAL_INTERVAL_UNSTABLE" if unstable else "TECHNICAL_INTERVAL_CONSTRUCTED"
        ),
        "nominal_coverage": 0.95,
        "observed_cv_coverage_mean": mean_cov,
        "observed_cv_coverage_stdev": cov_stdev,
        "mean_width": mean_w,
        "n_folds_used": len(coverages),
        "CLINICAL_CALIBRATION_CLAIMED": False,
        "SHARPNESS_CLAIMED": False,
    }
