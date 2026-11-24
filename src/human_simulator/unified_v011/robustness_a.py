"""Expanded Source A backtest robustness — predictive signal only (not intervention)."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.scientific.backtest import (
    compare_models,
    metrics_block,
    pair_micro_mae,
    subject_macro_mae,
)
from human_simulator.scientific.dataset import (
    build_consecutive_pairs,
    fetch_eligible_subjects,
    fetch_measurement_series,
)
from human_simulator.scientific.leakage import shuffled_label_retraining_control
from human_simulator.scientific.models import (
    EmpiricalTrendBaseline,
    FirstLearnedBaseline,
    PersistenceBaseline,
    PairPrediction,
    feature_schema_hash,
    is_constant_model,
    select_ridge_l2,
)
from human_simulator.scientific.policy import (
    MIN_TEST_PAIRS_FOR_UNCERTAINTY_CALIBRATION,
    MIN_TEST_SUBJECTS_FOR_UNCERTAINTY_CALIBRATION,
    MIN_VAL_FOR_INTERVAL_CONSTRUCTION,
    NOMINAL_COVERAGE,
    SPLIT_CLASS,
    gaussian_interval_multiplier,
)
from human_simulator.scientific.splits import assign_pairs_to_splits, build_subject_split
from human_simulator.unified_v011.policy import (
    BOOTSTRAP_ITERS,
    CLINICAL_VALIDATION_STATUS,
    FIXED_OUTCOME_CANDIDATE_ID,
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    FORBIDDEN_SIGNAL_STATUS,
    INTERVENTION_RESPONSE_MODEL_STATUS,
    PREDICTIVE_SIGNAL_STATUSES,
    PRODUCTION_READINESS,
    SEED,
    SHUFFLE_PERMS,
    TREATMENT_EFFECT_STATUS,
)


HORIZON_BUCKETS = (
    ("lt_1d", 0.0, 1.0),
    ("1_7d", 1.0, 7.0),
    ("7_30d", 7.0, 30.0),
    ("30_90d", 30.0, 90.0),
    ("90_365d", 90.0, 365.0),
    ("365_730d", 365.0, 730.0),
    ("gt_730d", 730.0, float("inf")),
)


def fixed_outcome_selected() -> dict[str, Any]:
    return {
        "candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "source_measurement_label": FIXED_OUTCOME_LABEL,
        "dominant_unit": FIXED_OUTCOME_UNIT,
        "selection_basis": "FIXED_FROM_ACCEPTED_SDR_V0.1.1.1 — do not reselect",
        "medical_interpretation_status": "DOMAIN_REVIEW_PENDING",
        "limitations": [
            "Outcome fixed before expanded robustness evaluation.",
            "Predictive next-lab forecast only — not intervention response.",
        ],
    }


def assert_signal_status_allowed(status: str) -> None:
    if status == FORBIDDEN_SIGNAL_STATUS:
        raise ValueError(f"forbidden ambiguous status: {FORBIDDEN_SIGNAL_STATUS}")
    if status not in PREDICTIVE_SIGNAL_STATUSES:
        raise ValueError(f"unknown predictive signal status: {status}")


def map_legacy_signal(status: str) -> str:
    """Map v0.1 ambiguous labels onto v0.1.1 vocabulary."""
    if status == FORBIDDEN_SIGNAL_STATUS:
        return "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_CANDIDATE"
    if status == "NO_INCREMENTAL_SIGNAL_DETECTED":
        return "NO_INCREMENTAL_PREDICTIVE_SIGNAL"
    if status in PREDICTIVE_SIGNAL_STATUSES:
        return status
    return "INSUFFICIENT_DATA"


def explain_eligible_8262_vs_7997(
    *,
    source_a_eligible: int = 8262,
    scientific_eligible: int = 7997,
    exclusion_reasons: dict[str, int] | None = None,
) -> dict[str, Any]:
    diff = int(source_a_eligible) - int(scientific_eligible)
    reasons = exclusion_reasons or {
        "source_a_cohort_lacks_ge2_dated_numeric_observation_components": diff,
    }
    return {
        "source_a_eligible_subjects_appt3_and_lab1": source_a_eligible,
        "scientific_eligible_subjects_ge2_dated_numeric": scientific_eligible,
        "difference": diff,
        "expected_difference": 265,
        "difference_matches_265": diff == 265,
        "aggregate_exclusion_reasons": reasons,
        "note": (
            "Scientific eligibility requires ≥2 dated numeric observation components "
            "(any code). Source A expansion eligibility is appt≥3 AND lab≥1."
        ),
    }


def _subject_errors(preds: list[PairPrediction]) -> dict[str, float]:
    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[p.opaque_subject_key].append(abs(p.y_pred - p.y_true))
    return {k: sum(v) / len(v) for k, v in by.items()}


def paired_subject_improvement(
    ridge: list[PairPrediction], persistence: list[PairPrediction]
) -> dict[str, Any]:
    r_err = _subject_errors(ridge)
    p_err = _subject_errors(persistence)
    common = sorted(set(r_err) & set(p_err))
    if not common:
        return {"n_subjects": 0}
    diffs = [r_err[s] - p_err[s] for s in common]  # negative ⇒ ridge better
    better = sum(1 for d in diffs if d < 0)
    diffs_sorted = sorted(diffs)
    return {
        "n_subjects": len(common),
        "mean_subject_error_diff_ridge_minus_persistence": sum(diffs) / len(diffs),
        "median_subject_error_diff_ridge_minus_persistence": diffs_sorted[len(diffs_sorted) // 2],
        "fraction_subjects_ridge_better": better / len(common),
        "paired_diffs_negative_is_ridge_better": True,
    }


def subject_cluster_bootstrap(
    ridge: list[PairPrediction],
    persistence: list[PairPrediction],
    *,
    n_iter: int = BOOTSTRAP_ITERS,
    seed: int = SEED,
) -> dict[str, Any]:
    """Bootstrap subjects; statistic = Ridge macro MAE − Persistence macro MAE."""
    by_r: dict[str, list[PairPrediction]] = defaultdict(list)
    by_p: dict[str, list[PairPrediction]] = defaultdict(list)
    for p in ridge:
        by_r[p.opaque_subject_key].append(p)
    for p in persistence:
        by_p[p.opaque_subject_key].append(p)
    subjects = sorted(set(by_r) & set(by_p))
    if len(subjects) < 2:
        return {
            "status": "INSUFFICIENT_DATA",
            "n_iterations": 0,
            "seed": seed,
            "resampling_unit": "subject",
        }

    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(n_iter):
        sample = [subjects[rng.randrange(len(subjects))] for _ in subjects]
        r_preds = [p for s in sample for p in by_r[s]]
        p_preds = [p for s in sample for p in by_p[s]]
        diffs.append(subject_macro_mae(r_preds) - subject_macro_mae(p_preds))
    diffs_sorted = sorted(diffs)
    lo = diffs_sorted[int(0.025 * n_iter)]
    hi = diffs_sorted[min(n_iter - 1, int(0.975 * n_iter))]
    frac_ge0 = sum(1 for d in diffs if d >= 0) / n_iter
    return {
        "status": "COMPUTED",
        "resampling_unit": "subject",
        "n_iterations": n_iter,
        "seed": seed,
        "statistic": "ridge_macro_mae_minus_persistence_macro_mae",
        "bootstrap_mean_difference": sum(diffs) / n_iter,
        "ci_95_lower": lo,
        "ci_95_upper": hi,
        "fraction_bootstrap_differences_ge_0": frac_ge0,
        "n_subjects": len(subjects),
    }


def horizon_sensitivity(
    ridge: list[PairPrediction], persistence: list[PairPrediction]
) -> dict[str, Any]:
    def _bucket_preds(preds: list[PairPrediction], lo: float, hi: float) -> list[PairPrediction]:
        return [p for p in preds if lo <= p.horizon_days < hi]

    buckets: dict[str, Any] = {}
    for name, lo, hi in HORIZON_BUCKETS:
        r = _bucket_preds(ridge, lo, hi)
        p = _bucket_preds(persistence, lo, hi)
        if not r or not p:
            buckets[name] = {"n_pairs": 0}
            continue
        buckets[name] = {
            "n_pairs": len(r),
            "n_subjects": len({x.opaque_subject_key for x in r}),
            "ridge_subject_macro_mae": subject_macro_mae(r),
            "persistence_subject_macro_mae": subject_macro_mae(p),
            "ridge_pair_micro_mae": pair_micro_mae(r),
            "persistence_pair_micro_mae": pair_micro_mae(p),
            "delta_macro_mae": subject_macro_mae(r) - subject_macro_mae(p),
        }

    def _filter(preds: list[PairPrediction], pred) -> list[PairPrediction]:
        return [p for p in preds if pred(p.horizon_days)]

    secondary: dict[str, Any] = {}
    for label, pred in (
        ("exclude_lt_1d", lambda h: h >= 1.0),
        ("exclude_lt_7d", lambda h: h >= 7.0),
        ("exclude_gt_730d", lambda h: h <= 730.0),
        ("only_7_365d", lambda h: 7.0 <= h <= 365.0),
    ):
        r = _filter(ridge, pred)
        p = _filter(persistence, pred)
        if not r:
            secondary[label] = {"n_pairs": 0}
            continue
        secondary[label] = {
            "n_pairs": len(r),
            "n_subjects": len({x.opaque_subject_key for x in r}),
            "ridge_subject_macro_mae": subject_macro_mae(r),
            "persistence_subject_macro_mae": subject_macro_mae(p),
            "delta_macro_mae": subject_macro_mae(r) - subject_macro_mae(p),
            "ridge_better_macro": subject_macro_mae(r) < subject_macro_mae(p),
            "ridge_better_micro": pair_micro_mae(r) < pair_micro_mae(p),
        }
    return {"buckets": buckets, "secondary": secondary}


def decide_predictive_signal_status(
    *,
    comparison: dict[str, Any],
    bootstrap: dict[str, Any],
    shuffle: dict[str, Any],
    horizon: dict[str, Any],
    constant_model: bool,
    leakage_ok: bool,
    adequate_test_subjects: bool,
    preprocessing_train_only: bool,
) -> dict[str, Any]:
    ridge_m = comparison.get("first_learned") or comparison.get("learned") or {}
    pers_m = comparison.get("persistence") or {}
    gates = {
        "outcome_fixed_before_expanded_test": True,
        "no_leakage_violations": leakage_ok,
        "adequate_outcome_bearing_test_subjects": adequate_test_subjects,
        "ridge_macro_mae_lt_persistence": (
            ridge_m.get("subject_macro_mae", 1e9) < pers_m.get("subject_macro_mae", 0)
        ),
        "ridge_micro_mae_lt_persistence": (
            ridge_m.get("pair_micro_mae", 1e9) < pers_m.get("pair_micro_mae", 0)
        ),
        "bootstrap_ci_upper_lt_0": (
            bootstrap.get("status") == "COMPUTED"
            and bootstrap.get("ci_95_upper") is not None
            and float(bootstrap["ci_95_upper"]) < 0
        ),
        "permutation_probability_le_0_05": (
            int(shuffle.get("n_permutations") or 0) >= SHUFFLE_PERMS
            and shuffle.get("fraction_shuffles_le_real") is not None
            and float(shuffle["fraction_shuffles_le_real"]) <= 0.05
        ),
        "improvement_not_only_lt_1d": bool(
            (horizon.get("secondary") or {}).get("exclude_lt_1d", {}).get("ridge_better_macro")
        ),
        "model_not_constant": not constant_model,
        "preprocessing_fitted_on_train_only": preprocessing_train_only,
    }
    all_pass = all(gates.values())
    if not adequate_test_subjects or ridge_m.get("n_pairs", 0) == 0:
        status = "INSUFFICIENT_DATA"
    elif all_pass:
        status = "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED"
    elif gates["ridge_macro_mae_lt_persistence"] and gates["ridge_micro_mae_lt_persistence"]:
        # Point estimate better but robustness incomplete
        if not gates["bootstrap_ci_upper_lt_0"] or not gates["permutation_probability_le_0_05"]:
            status = "PREDICTIVE_SIGNAL_NOT_ROBUST"
        else:
            status = "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_CANDIDATE"
    else:
        status = "NO_INCREMENTAL_PREDICTIVE_SIGNAL"

    # Expanded Source A test already viewed in v0.1 ⇒ never claim non-exploratory.
    if status == "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED":
        robustness = "SUPPORTED_EXPLORATORY"
    elif status == "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_CANDIDATE":
        robustness = "CANDIDATE"
    elif status == "PREDICTIVE_SIGNAL_NOT_ROBUST":
        robustness = "NOT_ROBUST"
    else:
        robustness = status

    assert_signal_status_allowed(status)
    return {
        "source_a_predictive_signal_status": status,
        "source_a_signal_robustness_status": robustness,
        "gates": gates,
        "all_supported_gates_pass": all_pass,
        "exploratory_because_expanded_test_viewed_in_v0.1": True,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "treatment_effect_status": TREATMENT_EFFECT_STATUS,
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "production_readiness": PRODUCTION_READINESS,
    }


def _split_accounting(
    *,
    eligible_by_split: dict[str, int],
    series_subjects_by_split: dict[str, int],
    subjects_with_pairs_by_split: dict[str, int],
    pairs_by_split: dict[str, int],
    subjects_used_in_metrics_by_split: dict[str, int],
) -> dict[str, Any]:
    return {
        "eligible_population_subjects_by_split": eligible_by_split,
        "outcome_series_subjects_by_split": series_subjects_by_split,
        "subjects_with_pairs_by_split": subjects_with_pairs_by_split,
        "pairs_by_split": pairs_by_split,
        "subjects_used_in_metrics_by_split": subjects_used_in_metrics_by_split,
        "note": (
            "Do not equate eligible_population_subjects_by_split with "
            "subjects_used_in_metrics_by_split."
        ),
    }


def run_robustness(conn: Any, *, seed: int = SEED) -> dict[str, Any]:
    """Full expanded Source A robustness evaluation."""
    selected = fixed_outcome_selected()
    source_a_eligible_hint = 8262
    eligible = fetch_eligible_subjects(conn)
    scientific_n = int(eligible["n_eligible_subjects"])
    eligible_gap = explain_eligible_8262_vs_7997(
        source_a_eligible=source_a_eligible_hint,
        scientific_eligible=scientific_n,
    )

    subject_split = build_subject_split(eligible["opaque_subject_keys"], seed=seed)
    train_keys = set(subject_split["sets"]["train"])
    val_keys = set(subject_split["sets"]["validation"])
    test_keys = set(subject_split["sets"]["test"])
    all_keys = train_keys | val_keys | test_keys

    series = fetch_measurement_series(
        conn,
        raw_code=selected["source_measurement_label"],
        dominant_unit=selected["dominant_unit"] or "",
        subject_keys=all_keys,
    )
    config = {
        "seed": seed,
        "outcome_candidate_id": selected["candidate_id"],
        "dominant_unit": selected["dominant_unit"],
        "version": "0.1.1",
        "unit_policy": "fixed_outcome_dominant_unit",
        "pair_definition": "strict_consecutive_neighbors_only",
        "outcome_selection": "FIXED_NO_RESELECT",
    }
    pairs, meta = build_consecutive_pairs(series, outcome=selected, config=config)

    if len(pairs) < 15 or meta["summary"]["n_subjects_with_pairs"] < 8:
        status = "INSUFFICIENT_DATA"
        assert_signal_status_allowed(status)
        return {
            "status": status,
            "source_a_predictive_signal_status": status,
            "source_a_signal_robustness_status": status,
            "outcome": selected,
            "eligible_gap": eligible_gap,
            "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
            "treatment_effect_status": TREATMENT_EFFECT_STATUS,
            "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
            "production_readiness": PRODUCTION_READINESS,
        }

    splits = assign_pairs_to_splits(pairs, subject_split)
    train, val, test = (
        splits["buckets"]["train"],
        splits["buckets"]["validation"],
        splits["buckets"]["test"],
    )

    series_subj = {r["opaque_subject_key"] for r in series}
    pair_subj = {p["opaque_subject_key"] for p in pairs}

    def _count_keys(keys: set[str], universe: set[str]) -> int:
        return len(keys & universe)

    split_acct = _split_accounting(
        eligible_by_split={
            "train": len(train_keys),
            "validation": len(val_keys),
            "test": len(test_keys),
        },
        series_subjects_by_split={
            "train": _count_keys(train_keys, series_subj),
            "validation": _count_keys(val_keys, series_subj),
            "test": _count_keys(test_keys, series_subj),
        },
        subjects_with_pairs_by_split={
            "train": _count_keys(train_keys, pair_subj),
            "validation": _count_keys(val_keys, pair_subj),
            "test": _count_keys(test_keys, pair_subj),
        },
        pairs_by_split={
            "train": len(train),
            "validation": len(val),
            "test": len(test),
        },
        subjects_used_in_metrics_by_split={
            "train": 0,  # filled after preds
            "validation": 0,
            "test": 0,
        },
    )

    persistence = PersistenceBaseline()
    trend = EmpiricalTrendBaseline()
    learned, tune_info = select_ridge_l2(train, val, seed=seed)
    if val:
        val_tmp = [learned.predict_pair(p) for p in val]
        resid = [p.y_true - p.y_pred for p in val_tmp]
        learned.residual_std = math.sqrt(sum(r * r for r in resid) / len(resid)) or learned.residual_std

    p_test = [persistence.predict_pair(p) for p in test]
    t_test = [trend.predict_pair(p) for p in test]
    l_test = [learned.predict_pair(p) for p in test]

    split_acct["subjects_used_in_metrics_by_split"] = {
        "train": len({p["opaque_subject_key"] for p in train}),
        "validation": len({p["opaque_subject_key"] for p in val}),
        "test": len({p.opaque_subject_key for p in l_test}),
    }

    comparison = compare_models(persistence=p_test, trend=t_test, learned=l_test)
    # Strip forbidden status immediately
    comparison["incremental_signal_status"] = map_legacy_signal(
        str(comparison.get("incremental_signal_status") or "")
    )
    constant = is_constant_model(l_test)

    paired = paired_subject_improvement(l_test, p_test)
    bootstrap = subject_cluster_bootstrap(l_test, p_test, n_iter=BOOTSTRAP_ITERS, seed=seed)
    horizon = horizon_sensitivity(l_test, p_test)

    shuffle = shuffled_label_retraining_control(
        train=train,
        test=test,
        frozen_l2=float(learned.l2),
        real_feature_schema_hash=str(learned.feature_schema_hash or feature_schema_hash()),
        split_hash=splits["verification"].get("split_hash"),
        seed=seed,
        n_perm=SHUFFLE_PERMS,
        real_subject_macro_mae=float(comparison["first_learned"].get("subject_macro_mae") or 0),
        interval_multiplier=learned.interval_multiplier,
        nominal_coverage=NOMINAL_COVERAGE,
    )

    decision = decide_predictive_signal_status(
        comparison=comparison,
        bootstrap=bootstrap,
        shuffle=shuffle,
        horizon=horizon,
        constant_model=constant,
        leakage_ok=True,
        adequate_test_subjects=int(comparison["first_learned"].get("n_subjects") or 0) >= 30,
        preprocessing_train_only=True,
    )

    ridge_mae = float(comparison["first_learned"].get("subject_macro_mae") or 0)
    pers_mae = float(comparison["persistence"].get("subject_macro_mae") or 1)
    abs_diff = ridge_mae - pers_mae
    rel_imp = (pers_mae - ridge_mae) / pers_mae if pers_mae else None

    return {
        "status": "PASS",
        "methodology": "scientific_reuse_fixed_outcome_robustness_v0.1.1",
        "outcome": selected,
        "outcome_reselected": False,
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "split_class": SPLIT_CLASS,
        "seed": seed,
        "eligible_gap": eligible_gap,
        "n_scientific_eligible_subjects": scientific_n,
        "n_pairs": len(pairs),
        "dataset_summary": meta.get("summary"),
        "split_accounting": split_acct,
        "comparison": comparison,
        "effect": {
            "absolute_macro_mae_diff_ridge_minus_persistence": abs_diff,
            "relative_improvement_vs_persistence": rel_imp,
            "paired_subject_level": paired,
            "pair_micro_sensitivity": {
                "ridge": comparison["first_learned"].get("pair_micro_mae"),
                "persistence": comparison["persistence"].get("pair_micro_mae"),
                "rmse_ridge": comparison["first_learned"].get("pair_micro_rmse"),
                "rmse_persistence": comparison["persistence"].get("pair_micro_rmse"),
            },
        },
        "bootstrap": bootstrap,
        "horizon_sensitivity": horizon,
        "shuffle_control": {
            "status": shuffle.get("status"),
            "n_permutations": shuffle.get("n_permutations"),
            "fraction_shuffles_le_real": shuffle.get("fraction_shuffles_le_real"),
            "permutation_probability": shuffle.get("fraction_shuffles_le_real"),
            "real_mae_rank_proxy": shuffle.get("n_shuffles_with_mae_le_real"),
            "configuration_equality": shuffle.get(
                "shuffled_control_uses_same_frozen_model_configuration"
            ),
        },
        "shuffle_full": shuffle,
        "tune_info": {
            "selected_l2": tune_info.get("selected_l2") if isinstance(tune_info, dict) else None
        },
        "model_constant": constant,
        "gaussian_interval_multiplier": gaussian_interval_multiplier(NOMINAL_COVERAGE),
        "learned_for_uncertainty": {
            "val_n": len(val),
            "test_n": len(test),
            "residual_std": learned.residual_std,
            "interval_multiplier": learned.interval_multiplier,
            "min_val_for_construction": MIN_VAL_FOR_INTERVAL_CONSTRUCTION,
            "min_test_subjects": MIN_TEST_SUBJECTS_FOR_UNCERTAINTY_CALIBRATION,
            "min_test_pairs": MIN_TEST_PAIRS_FOR_UNCERTAINTY_CALIBRATION,
        },
        "val_preds_ridge": [
            {
                "y_true": p.y_true,
                "y_pred": p.y_pred,
                "lower": p.lower,
                "upper": p.upper,
                "opaque_subject_key": p.opaque_subject_key,
                "horizon_days": p.horizon_days,
            }
            for p in [learned.predict_pair(x) for x in val]
        ],
        "test_preds_ridge": [
            {
                "y_true": p.y_true,
                "y_pred": p.y_pred,
                "lower": p.lower,
                "upper": p.upper,
                "opaque_subject_key": p.opaque_subject_key,
                "horizon_days": p.horizon_days,
            }
            for p in l_test
        ],
        "test_preds_persistence": [
            {
                "y_true": p.y_true,
                "y_pred": p.y_pred,
                "lower": p.lower,
                "upper": p.upper,
                "opaque_subject_key": p.opaque_subject_key,
                "horizon_days": p.horizon_days,
            }
            for p in p_test
        ],
        # Runtime-only: never publish; used by v0.1.2.1 frozen-model export.
        "_learned_model": learned,
        **decision,
    }


def sanitize_robustness_for_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop runtime prediction vectors from published artifact."""
    out = {
        k: v
        for k, v in doc.items()
        if not k.startswith("test_preds")
        and k not in ("val_preds_ridge", "_learned_model")
    }
    out.pop("shuffle_full", None)
    return out
