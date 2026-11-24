"""Per-grain train/eval with active-provider uncertainty (v0.1.1)."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from human_simulator.scientific.models import (
    FEATURE_ORDER,
    EmpiricalTrendBaseline,
    FirstLearnedBaseline,
    PersistenceBaseline,
    feature_schema_hash,
    gaussian_interval_multiplier,
)
from human_simulator.scientific.splits import assign_pairs_to_splits, build_subject_split
from human_simulator.scientific_v02.applicability import build_applicability_reference
from human_simulator.scientific_v02.evaluate import (
    _pair_metrics,
    _preds_to_dicts,
    horizon_sensitivity,
    shuffled_label_control,
    subject_cluster_bootstrap,
    _subject_improvement,
)
from human_simulator.scientific_v02.policy import L2, SEED
from human_simulator.scientific_v02.uncertainty import compute_uncertainty
from human_simulator.trajectory_expansion_v011.applicability_runtime import (
    assess_heldout_applicability,
)
from human_simulator.trajectory_expansion_v011.policy import (
    BOOTSTRAP_ITERS_EXPANSION,
    NOMINAL_COVERAGE,
    SHUFFLE_PERMS_EXPANSION,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _pair_manifest_hash(pairs: list[dict[str, Any]]) -> str:
    payload = [
        {
            "pair_id": p.get("pair_id"),
            "y0": p.get("y_t0"),
            "y1": p.get("y_t1"),
            "h": p.get("horizon_days"),
        }
        for p in pairs
    ]
    payload.sort(key=lambda x: str(x.get("pair_id") or ""))
    return _hash(payload)


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    w = pos - lo
    return float(sorted_vals[lo] * (1 - w) + sorted_vals[hi] * w)


def _attach_symmetric_interval(
    preds: list[Any], half_width: float
) -> list[dict[str, Any]]:
    out = []
    for p in preds:
        d = {
            "pair_id": p.pair_id,
            "y_true": p.y_true,
            "y_pred": p.y_pred,
            "lower": float(p.y_pred) - half_width,
            "upper": float(p.y_pred) + half_width,
            "opaque_subject_key": p.opaque_subject_key,
            "horizon_days": p.horizon_days,
        }
        out.append(d)
    return out


def build_active_uncertainty(
    *,
    active: str,
    val_pairs: list[dict[str, Any]],
    test_pairs: list[dict[str, Any]],
    ridge: FirstLearnedBaseline,
    persistence: PersistenceBaseline,
    trend: EmpiricalTrendBaseline,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Return (uncertainty_payload, active_test_preds_with_intervals, interval_spec)."""
    mult = gaussian_interval_multiplier(NOMINAL_COVERAGE)
    if active == "ridge":
        if val_pairs:
            resid = [
                float(p.y_true) - float(p.y_pred)
                for p in (ridge.predict_pair(x) for x in val_pairs)
            ]
            ridge.residual_std = math.sqrt(sum(r * r for r in resid) / len(resid)) or 1e-6
        half = mult * float(ridge.residual_std)
        test_raw = [ridge.predict_pair(p) for p in test_pairs]
        test_dicts = _preds_to_dicts(test_raw)
        interval_spec = {
            "active_provider": "ridge",
            "interval_method": "validation_gaussian_residual_std",
            "nominal_coverage": NOMINAL_COVERAGE,
            "validation_count": len(val_pairs),
            "residual_std": float(ridge.residual_std),
            "interval_multiplier": mult,
            "half_width": half,
        }
    else:
        model = persistence if active == "persistence" else trend
        val_raw = [model.predict_pair(p) for p in val_pairs]
        abs_resid = sorted(abs(float(p.y_true) - float(p.y_pred)) for p in val_raw)
        q = _quantile(abs_resid, NOMINAL_COVERAGE) if abs_resid else 1e-6
        half = max(float(q), 1e-6)
        test_raw = [model.predict_pair(p) for p in test_pairs]
        test_dicts = _attach_symmetric_interval(test_raw, half)
        interval_spec = {
            "active_provider": active,
            "interval_method": "validation_absolute_residual_quantile",
            "nominal_coverage": NOMINAL_COVERAGE,
            "validation_count": len(val_pairs),
            "residual_quantile": half,
            "interval_multiplier": None,
            "half_width": half,
        }

    interval_spec["interval_payload_hash"] = _hash(
        {k: v for k, v in interval_spec.items() if k != "interval_payload_hash"}
    )
    unc = compute_uncertainty(test_dicts, None, nominal_coverage=NOMINAL_COVERAGE)
    unc["active_provider"] = active
    unc["interval_spec"] = interval_spec
    unc["ACTIVE_PROVIDER_UNCERTAINTY_BOUND"] = True
    # Keep construction status; do not claim calibration established
    u_status = unc.get("uncertainty_interval_construction_status") or "FAIL"
    return unc, test_dicts, interval_spec | {"construction_status": u_status}


def run_grain(
    grain: dict[str, Any],
    pairs: list[dict[str, Any]],
    *,
    min_test_subjects: int,
) -> dict[str, Any]:
    if grain.get("unexplained", 0) not in (0, None) and grain.get("unexplained"):
        return {
            "grain_id": grain["grain_id"],
            "status": "METHODOLOGY_INCOMPATIBLE",
            "reason": "unexplained_rows_nonzero",
        }
    if len(pairs) < 50:
        return {
            "grain_id": grain["grain_id"],
            "outcome": grain.get("normalized_label") or grain.get("outcome"),
            "unit": grain.get("unit"),
            "status": "INSUFFICIENT_TEST_DATA",
            "reason": "too_few_pairs",
            "n_pairs": len(pairs),
        }

    subjects = sorted({p["opaque_subject_key"] for p in pairs})
    split = build_subject_split(subjects, seed=SEED)
    if not split.get("ok"):
        return {
            "grain_id": grain["grain_id"],
            "status": "METHODOLOGY_INCOMPATIBLE",
            "reason": "subject_split_failed",
        }
    assigned = assign_pairs_to_splits(pairs, split)
    train = assigned["buckets"]["train"]
    val = assigned["buckets"]["validation"]
    test = assigned["buckets"]["test"]
    n_test_subj = len({p["opaque_subject_key"] for p in test})
    leakage_ok = bool((assigned.get("verification") or {}).get("ok"))

    tr_ids = {p["pair_id"] for p in train}
    te_ids = {p["pair_id"] for p in test}
    va_ids = {p["pair_id"] for p in val}
    pair_overlap = bool(tr_ids & te_ids or tr_ids & va_ids or va_ids & te_ids)

    if n_test_subj < min_test_subjects:
        return {
            "grain_id": grain["grain_id"],
            "outcome": grain.get("normalized_label") or grain.get("outcome"),
            "unit": grain.get("unit"),
            "status": "INSUFFICIENT_TEST_DATA",
            "reason": "test_subjects_below_conservative_min",
            "n_test_subjects": n_test_subj,
            "min_test_subjects": min_test_subjects,
            "split_counts": {
                "train_pairs": len(train),
                "val_pairs": len(val),
                "test_pairs": len(test),
                "train_subjects": len({p["opaque_subject_key"] for p in train}),
                "val_subjects": len({p["opaque_subject_key"] for p in val}),
                "test_subjects": n_test_subj,
            },
            "n_pairs": len(pairs),
        }

    if pair_overlap or not leakage_ok:
        return {
            "grain_id": grain["grain_id"],
            "status": "METHODOLOGY_INCOMPATIBLE",
            "reason": "leakage_or_overlap",
            "pair_overlap": pair_overlap,
        }

    if len(train) < 20 or len(val) < 5 or len(test) < 5:
        return {
            "grain_id": grain["grain_id"],
            "status": "INSUFFICIENT_TEST_DATA",
            "reason": "split_pair_counts_too_small",
            "split_counts": {
                "train_pairs": len(train),
                "val_pairs": len(val),
                "test_pairs": len(test),
            },
        }

    ridge = FirstLearnedBaseline(seed=SEED, l2=L2)
    ridge.fit(train)
    if val:
        val_preds_fit = [ridge.predict_pair(p) for p in val]
        resid = [p.y_true - p.y_pred for p in val_preds_fit]
        ridge.residual_std = math.sqrt(sum(r * r for r in resid) / len(resid)) or ridge.residual_std

    persistence = PersistenceBaseline()
    trend = EmpiricalTrendBaseline()

    p_val = _preds_to_dicts([persistence.predict_pair(p) for p in val])
    t_val = _preds_to_dicts([trend.predict_pair(p) for p in val])
    r_val = _preds_to_dicts([ridge.predict_pair(p) for p in val])
    val_metrics = {
        "persistence": _pair_metrics(p_val),
        "empirical_trend": _pair_metrics(t_val),
        "ridge": _pair_metrics(r_val),
    }
    candidates = [
        ("persistence", val_metrics["persistence"].get("subject_macro_mae")),
        ("empirical_trend", val_metrics["empirical_trend"].get("subject_macro_mae")),
        ("ridge", val_metrics["ridge"].get("subject_macro_mae")),
    ]
    scored = [(name, mae) for name, mae in candidates if mae is not None]
    scored.sort(
        key=lambda x: (
            x[1],
            0 if x[0] == "persistence" else 1 if x[0] == "empirical_trend" else 2,
        )
    )
    active = scored[0][0] if scored else "persistence"
    reason = (
        f"Lowest validation subject-macro MAE among P0/P1/P2 "
        f"(persistence={val_metrics['persistence'].get('subject_macro_mae')}, "
        f"trend={val_metrics['empirical_trend'].get('subject_macro_mae')}, "
        f"ridge={val_metrics['ridge'].get('subject_macro_mae')}); "
        "test unused for selection."
    )

    r_test = _preds_to_dicts([ridge.predict_pair(p) for p in test])
    p_test = _preds_to_dicts([persistence.predict_pair(p) for p in test])
    t_test = _preds_to_dicts([trend.predict_pair(p) for p in test])
    ridge_m = _pair_metrics(r_test)
    pers_m = _pair_metrics(p_test)
    trend_m = _pair_metrics(t_test)
    abs_delta = None
    rel = None
    if ridge_m["subject_macro_mae"] is not None and pers_m["subject_macro_mae"] is not None:
        abs_delta = ridge_m["subject_macro_mae"] - pers_m["subject_macro_mae"]
        if pers_m["subject_macro_mae"]:
            rel = abs_delta / pers_m["subject_macro_mae"]

    boot = subject_cluster_bootstrap(
        r_test, p_test, n_iter=BOOTSTRAP_ITERS_EXPANSION, seed=SEED
    )
    shuffle = shuffled_label_control(
        train, test, l2=L2, seed=SEED, n_perm=SHUFFLE_PERMS_EXPANSION
    )
    improve = _subject_improvement(r_test, p_test)
    horizon = horizon_sensitivity(r_test, p_test)

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
    elif (
        gates["ridge_macro_lt_persistence"] is False
        and gates["ridge_micro_lt_persistence"] is False
    ):
        signal = "NO_INCREMENTAL_SIGNAL_DETECTED"
    else:
        signal = "NO_INCREMENTAL_SIGNAL_DETECTED"

    outcome_status = (
        "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED"
        if signal == "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED"
        else "INSUFFICIENT_TEST_DATA"
        if signal == "INSUFFICIENT_DATA"
        else "NO_INCREMENTAL_SIGNAL_DETECTED"
    )

    unc, active_test_preds, interval_spec = build_active_uncertainty(
        active=active,
        val_pairs=val,
        test_pairs=test,
        ridge=ridge,
        persistence=persistence,
        trend=trend,
    )
    # Re-apply ridge residual_std from active path when ridge
    if active == "ridge":
        ridge.residual_std = float(interval_spec["residual_std"])

    train_hash = _pair_manifest_hash(train)
    appl_ref = build_applicability_reference(
        train,
        training_pair_manifest_hash=train_hash,
        feature_schema_hash=feature_schema_hash(),
        scaler_fit_n_rows=ridge.scaler.fit_n_rows,
    )
    # Embed full applicability reference (not hash-only) for runtime
    appl_ref_full = dict(appl_ref)
    appl_ref_full["ood_fraction_threshold"] = 0.10
    appl_ref_full["scaler_means"] = list(ridge.scaler.means)
    appl_ref_full["scaler_stds"] = list(ridge.scaler.stds)
    appl_ref_pub = {
        k: v for k, v in appl_ref_full.items() if k != "feature_distributions"
    }
    # Keep compact feature support summaries for runtime without row vectors
    if "feature_distributions" in appl_ref:
        dist = appl_ref["feature_distributions"]
        appl_ref_pub["feature_support"] = {
            name: {
                "p01": (dist.get(name) or {}).get("p01"),
                "p05": (dist.get(name) or {}).get("p05"),
                "p95": (dist.get(name) or {}).get("p95"),
                "p99": (dist.get(name) or {}).get("p99"),
                "min": (dist.get(name) or {}).get("min"),
                "max": (dist.get(name) or {}).get("max"),
            }
            for name in (dist or {})
        }

    appl_score = (
        assess_heldout_applicability(test[: min(50, len(test))], appl_ref_full)
        if test
        else {}
    )

    frozen = {
        "grain_id": grain["grain_id"],
        "outcome": grain.get("normalized_label") or grain.get("outcome"),
        "unit": grain.get("unit"),
        "active_provider": active,
        "seed": SEED,
        "l2": L2,
        "feature_schema_hash": feature_schema_hash(),
        "feature_order_hash": feature_schema_hash(),
        "feature_order": list(FEATURE_ORDER),
        "split_hash": split["split_hash"],
        "train_manifest_hash": train_hash,
        "dataset_pair_count": len(pairs),
        "ridge": {
            "coef": ridge.coef,
            "intercept": ridge.intercept,
            "residual_std": ridge.residual_std,
            "scaler": {"means": ridge.scaler.means, "stds": ridge.scaler.stds},
            "interval_multiplier": ridge.interval_multiplier,
        },
        "active_uncertainty": interval_spec,
        "applicability_reference": appl_ref_pub,
        "applicability_reference_hash": _hash(appl_ref_pub),
    }
    model_file_hash = _hash(frozen)
    identity_hash = _hash(
        {
            "grain_id": frozen["grain_id"],
            "active": active,
            "feature_schema_hash": frozen["feature_schema_hash"],
            "split_hash": frozen["split_hash"],
            "train_manifest_hash": frozen["train_manifest_hash"],
            "interval_payload_hash": interval_spec["interval_payload_hash"],
        }
    )
    frozen["model_file_hash"] = model_file_hash
    frozen["model_identity_hash"] = identity_hash

    active_mismatch = False
    if active != "ridge" and interval_spec.get("interval_method", "").startswith(
        "validation_gaussian"
    ):
        active_mismatch = True
    if active == "ridge" and interval_spec.get("active_provider") != "ridge":
        active_mismatch = True

    return {
        "grain_id": grain["grain_id"],
        "outcome": grain.get("normalized_label") or grain.get("outcome"),
        "unit": grain.get("unit"),
        "status": outcome_status,
        "active_provider": active,
        "active_provider_decision_reason": reason,
        "split_counts": {
            "train_pairs": len(train),
            "val_pairs": len(val),
            "test_pairs": len(test),
            "train_subjects": len({p["opaque_subject_key"] for p in train}),
            "val_subjects": len({p["opaque_subject_key"] for p in val}),
            "test_subjects": n_test_subj,
        },
        "subject_overlap_zero": split.get("subject_overlap_zero"),
        "pair_overlap_zero": not pair_overlap,
        "validation_metrics": val_metrics,
        "test_metrics": {
            "persistence": pers_m,
            "empirical_trend": trend_m,
            "ridge": ridge_m,
        },
        "evaluation": {
            "version": VERSION,
            "source_a_incremental_signal_status": signal,
            "test_metrics": {
                "ridge": ridge_m,
                "persistence": pers_m,
                "empirical_trend": trend_m,
                "ridge_minus_persistence_macro_mae": abs_delta,
                "relative_improvement_vs_persistence": rel,
            },
            "subject_improvement": improve,
            "bootstrap": boot,
            "shuffle_control": shuffle,
            "horizon_sensitivity": horizon,
            "signal_gates": gates,
        },
        "uncertainty": unc,
        "uncertainty_status": unc.get("uncertainty_interval_construction_status"),
        "active_provider_uncertainty_ok": not active_mismatch,
        "n_active_test_preds": len(active_test_preds),
        "applicability_reference": appl_ref_pub,
        "applicability_sample": appl_score,
        "frozen": frozen,
        "medication_features_present": False,
        "n_pairs": len(pairs),
    }
