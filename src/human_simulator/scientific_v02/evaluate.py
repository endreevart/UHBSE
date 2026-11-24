"""A-only evaluation: persistence / trend / Ridge + bootstrap + shuffle."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.scientific.models import (
    EmpiricalTrendBaseline,
    FirstLearnedBaseline,
    PersistenceBaseline,
)
from human_simulator.scientific_v02.policy import BOOTSTRAP_ITERS, SEED, SHUFFLE_PERMS, VERSION


def _preds_to_dicts(preds: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "y_true": p.y_true,
            "y_pred": p.y_pred,
            "lower": p.lower,
            "upper": p.upper,
            "opaque_subject_key": p.opaque_subject_key,
            "horizon_days": p.horizon_days,
        }
        for p in preds
    ]


def _subject_macro_mae(preds: list[dict[str, Any]]) -> float:
    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[str(p["opaque_subject_key"])].append(abs(p["y_pred"] - p["y_true"]))
    if not by:
        return float("nan")
    return sum(sum(v) / len(v) for v in by.values()) / len(by)


def _pair_metrics(preds: list[dict[str, Any]]) -> dict[str, Any]:
    if not preds:
        return {
            "n_pairs": 0,
            "n_subjects": 0,
            "pair_micro_mae": None,
            "pair_micro_rmse": None,
            "median_absolute_error": None,
            "mean_bias": None,
            "subject_macro_mae": None,
        }
    abs_err = [abs(p["y_pred"] - p["y_true"]) for p in preds]
    sq = [(p["y_pred"] - p["y_true"]) ** 2 for p in preds]
    bias = [p["y_pred"] - p["y_true"] for p in preds]
    srt = sorted(abs_err)
    return {
        "n_pairs": len(preds),
        "n_subjects": len({p["opaque_subject_key"] for p in preds}),
        "pair_micro_mae": sum(abs_err) / len(abs_err),
        "pair_micro_rmse": math.sqrt(sum(sq) / len(sq)),
        "median_absolute_error": srt[len(srt) // 2],
        "mean_bias": sum(bias) / len(bias),
        "subject_macro_mae": _subject_macro_mae(preds),
    }


def _subject_improvement(ridge: list[dict[str, Any]], pers: list[dict[str, Any]]) -> dict[str, Any]:
    by_r: dict[str, list[float]] = defaultdict(list)
    by_p: dict[str, list[float]] = defaultdict(list)
    for p in ridge:
        by_r[str(p["opaque_subject_key"])].append(abs(p["y_pred"] - p["y_true"]))
    for p in pers:
        by_p[str(p["opaque_subject_key"])].append(abs(p["y_pred"] - p["y_true"]))
    common = sorted(set(by_r) & set(by_p))
    if not common:
        return {"n_subjects": 0}
    diffs = [sum(by_r[s]) / len(by_r[s]) - sum(by_p[s]) / len(by_p[s]) for s in common]
    srt = sorted(diffs)
    better = sum(1 for d in diffs if d < 0)
    return {
        "n_subjects": len(common),
        "mean_subject_error_diff_ridge_minus_persistence": sum(diffs) / len(diffs),
        "median_subject_improvement_ridge_minus_persistence": srt[len(srt) // 2],
        "fraction_subjects_ridge_better": better / len(common),
        "negative_diff_means_ridge_better": True,
    }


def subject_cluster_bootstrap(
    ridge: list[dict[str, Any]],
    pers: list[dict[str, Any]],
    *,
    n_iter: int = BOOTSTRAP_ITERS,
    seed: int = SEED,
) -> dict[str, Any]:
    by_r: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_p: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in ridge:
        by_r[str(p["opaque_subject_key"])].append(p)
    for p in pers:
        by_p[str(p["opaque_subject_key"])].append(p)
    subjects = sorted(set(by_r) & set(by_p))
    if len(subjects) < 2:
        return {"status": "INSUFFICIENT_DATA", "n_iterations": 0, "seed": seed}
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(n_iter):
        sample = [subjects[rng.randrange(len(subjects))] for _ in subjects]
        r_rows = [r for s in sample for r in by_r[s]]
        p_rows = [r for s in sample for r in by_p[s]]
        diffs.append(_subject_macro_mae(r_rows) - _subject_macro_mae(p_rows))
    diffs_sorted = sorted(diffs)
    return {
        "status": "COMPUTED",
        "n_iterations": n_iter,
        "seed": seed,
        "resampling_unit": "subject",
        "mean_diff_ridge_minus_persistence": sum(diffs) / n_iter,
        "ci_95_lower": diffs_sorted[int(0.025 * n_iter)],
        "ci_95_upper": diffs_sorted[min(n_iter - 1, int(0.975 * n_iter))],
        "fraction_negative": sum(1 for d in diffs if d < 0) / n_iter,
    }


def shuffled_label_control(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    *,
    l2: float,
    seed: int,
    n_perm: int = SHUFFLE_PERMS,
) -> dict[str, Any]:
    """Shuffle train labels only; retrain; evaluate on fixed test. Count fixed before results."""
    persistence = PersistenceBaseline()
    p_test = _preds_to_dicts([persistence.predict_pair(p) for p in test])
    real = FirstLearnedBaseline(seed=seed, l2=l2)
    real.fit(train)
    real_preds = _preds_to_dicts([real.predict_pair(p) for p in test])
    real_mae = _subject_macro_mae(real_preds)
    pers_mae = _subject_macro_mae(p_test)
    real_delta = real_mae - pers_mae

    rng = random.Random(seed)
    le_real = 0
    for i in range(n_perm):
        ys = [float(p["y_t1"]) for p in train]
        rng.shuffle(ys)
        m = FirstLearnedBaseline(seed=seed + i + 1, l2=l2)
        m.fit(train, y_override=ys)
        preds = _preds_to_dicts([m.predict_pair(p) for p in test])
        delta = _subject_macro_mae(preds) - pers_mae
        if delta <= real_delta:
            le_real += 1
    # Finite-sample corrected permutation p-value; never serialize as literal 0.0.
    permutation_p_value = (le_real + 1) / (n_perm + 1)
    return {
        "n_permutations": n_perm,
        "seed": seed,
        "shuffle_train_labels_only": True,
        "evaluate_on_fixed_a_only_test": True,
        "real_ridge_minus_persistence_macro_mae": real_delta,
        "count_shuffles_le_real": le_real,
        "fraction_shuffles_le_real": le_real / n_perm if n_perm else None,
        "permutation_p_value": permutation_p_value,
        "permutation_p_value_formula": "(count_shuffles_le_real + 1) / (n_permutations + 1)",
        "permutation_count_fixed_before_results": True,
    }


def horizon_sensitivity(ridge: list[dict[str, Any]], pers: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = (
        ("lt_1d", 0.0, 1.0),
        ("1_7d", 1.0, 7.0),
        ("7_30d", 7.0, 30.0),
        ("30_90d", 30.0, 90.0),
        ("90_365d", 90.0, 365.0),
        ("gt_365d", 365.0, float("inf")),
    )
    out = {}
    for name, lo, hi in buckets:
        r = [p for p in ridge if lo <= float(p["horizon_days"]) < hi]
        p = [p for p in pers if lo <= float(p["horizon_days"]) < hi]
        out[name] = {
            "n_pairs": len(r),
            "ridge": _pair_metrics(r),
            "persistence": _pair_metrics(p),
        }
    return out


def evaluate_a_only(
    model: FirstLearnedBaseline,
    *,
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
    seed: int = SEED,
) -> dict[str, Any]:
    persistence = PersistenceBaseline()
    trend = EmpiricalTrendBaseline()
    r_test = _preds_to_dicts([model.predict_pair(p) for p in test])
    p_test = _preds_to_dicts([persistence.predict_pair(p) for p in test])
    t_test = _preds_to_dicts([trend.predict_pair(p) for p in test])
    r_val = _preds_to_dicts([model.predict_pair(p) for p in val]) if val else []
    p_val = _preds_to_dicts([persistence.predict_pair(p) for p in val]) if val else []

    ridge_m = _pair_metrics(r_test)
    pers_m = _pair_metrics(p_test)
    trend_m = _pair_metrics(t_test)
    abs_delta = None
    rel = None
    if ridge_m["subject_macro_mae"] is not None and pers_m["subject_macro_mae"] is not None:
        abs_delta = ridge_m["subject_macro_mae"] - pers_m["subject_macro_mae"]
        if pers_m["subject_macro_mae"]:
            rel = abs_delta / pers_m["subject_macro_mae"]

    boot = subject_cluster_bootstrap(r_test, p_test, seed=seed)
    shuffle = shuffled_label_control(train, test, l2=model.l2, seed=seed)
    improve = _subject_improvement(r_test, p_test)
    horizon = horizon_sensitivity(r_test, p_test)

    # Signal status (exploratory only)
    gates = {
        "ridge_macro_lt_persistence": (
            ridge_m["subject_macro_mae"] is not None
            and pers_m["subject_macro_mae"] is not None
            and ridge_m["subject_macro_mae"] < pers_m["subject_macro_mae"]
        ),
        "ridge_micro_lt_persistence": (
            ridge_m["pair_micro_mae"] is not None
            and pers_m["pair_micro_mae"] is not None
            and ridge_m["pair_micro_mae"] < pers_m["pair_micro_mae"]
        ),
        "bootstrap_ci_upper_lt_0": (
            boot.get("status") == "COMPUTED" and float(boot.get("ci_95_upper") or 1) < 0
        ),
        "permutation_p_le_0_05": (
            shuffle.get("permutation_p_value") is not None
            and float(shuffle["permutation_p_value"]) <= 0.05
        ),
    }
    if not test:
        signal = "INSUFFICIENT_DATA"
    elif all(gates.values()):
        signal = "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED"
    elif gates["ridge_macro_lt_persistence"] is False and gates["ridge_micro_lt_persistence"] is False:
        if (
            ridge_m["subject_macro_mae"] is not None
            and pers_m["subject_macro_mae"] is not None
            and ridge_m["subject_macro_mae"] > pers_m["subject_macro_mae"]
        ):
            signal = "MODEL_DEGRADATION_DETECTED"
        else:
            signal = "NO_INCREMENTAL_SIGNAL_DETECTED"
    else:
        signal = "NO_INCREMENTAL_SIGNAL_DETECTED"

    return {
        "version": VERSION,
        "source_a_retrospective_backtest_status": "PASS" if test else "INSUFFICIENT_DATA",
        "source_a_incremental_signal_status": signal,
        "clinical_validation": "NOT_CLAIMED",
        "n_train": len(train),
        "n_validation": len(val),
        "n_test": len(test),
        "test_metrics": {
            "ridge": ridge_m,
            "persistence": pers_m,
            "empirical_trend": trend_m,
            "ridge_minus_persistence_macro_mae": abs_delta,
            "relative_improvement_vs_persistence": rel,
        },
        "validation_metrics": {
            "ridge": _pair_metrics(r_val),
            "persistence": _pair_metrics(p_val),
        },
        "subject_improvement": improve,
        "bootstrap": boot,
        "shuffle_control": shuffle,
        "horizon_sensitivity": horizon,
        "signal_gates": gates,
        "_runtime_test_preds_ridge": r_test,  # stripped before write
        "_runtime_test_preds_persistence": p_test,
    }
