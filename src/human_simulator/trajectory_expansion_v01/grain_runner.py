"""Per-grain train / validation selection / evaluate (methodology reuse)."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from human_simulator.scientific.models import (
    EmpiricalTrendBaseline,
    FirstLearnedBaseline,
    PersistenceBaseline,
    feature_schema_hash,
)
from human_simulator.scientific.splits import assign_pairs_to_splits, build_subject_split
from human_simulator.scientific_v02.applicability import (
    assess_b_applicability,
    build_applicability_reference,
)
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
from human_simulator.trajectory_expansion_v01.policy import (
    BOOTSTRAP_ITERS_EXPANSION,
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
            "split": {k: split.get(k) for k in ("ok", "subject_overlap_zero", "n_subjects")},
        }
    assigned = assign_pairs_to_splits(pairs, split)
    train = assigned["buckets"]["train"]
    val = assigned["buckets"]["validation"]
    test = assigned["buckets"]["test"]
    n_test_subj = len({p["opaque_subject_key"] for p in test})
    leakage_ok = bool((assigned.get("verification") or {}).get("ok"))
    # locator overlap
    def locs(rows: list[dict[str, Any]]) -> set[str]:
        out = set()
        for p in rows:
            for k in ("pre_locator", "post_locator", "pair_id"):
                if p.get(k):
                    out.add(str(p[k]))
            loc = p.get("locators") or {}
            for v in loc.values() if isinstance(loc, dict) else []:
                out.add(str(v))
            prov = p.get("provenance") or {}
            for key in ("t0_component_id", "t1_component_id"):
                if prov.get(key):
                    out.add(str(prov[key]))
        return out

    # scientific pairs may use different locator fields — check pair_id disjointness
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

    # Train Ridge with fixed L2=0.1; calibrate residual on validation
    ridge = FirstLearnedBaseline(seed=SEED, l2=L2)
    ridge.fit(train)
    if val:
        val_preds_fit = [ridge.predict_pair(p) for p in val]
        resid = [p.y_true - p.y_pred for p in val_preds_fit]
        ridge.residual_std = math.sqrt(sum(r * r for r in resid) / len(resid)) or ridge.residual_std

    persistence = PersistenceBaseline()
    trend = EmpiricalTrendBaseline()

    # Validation selection (test not used)
    p_val = _preds_to_dicts([persistence.predict_pair(p) for p in val])
    t_val = _preds_to_dicts([trend.predict_pair(p) for p in val])
    r_val = _preds_to_dicts([ridge.predict_pair(p) for p in val])
    val_metrics = {
        "persistence": _pair_metrics(p_val),
        "empirical_trend": _pair_metrics(t_val),
        "ridge": _pair_metrics(r_val),
    }
    # Active = lowest validation subject-macro MAE; ties prefer Persistence
    candidates = [
        ("persistence", val_metrics["persistence"].get("subject_macro_mae")),
        ("empirical_trend", val_metrics["empirical_trend"].get("subject_macro_mae")),
        ("ridge", val_metrics["ridge"].get("subject_macro_mae")),
    ]
    scored = [(name, mae) for name, mae in candidates if mae is not None]
    scored.sort(key=lambda x: (x[1], 0 if x[0] == "persistence" else 1 if x[0] == "empirical_trend" else 2))
    active = scored[0][0] if scored else "persistence"
    reason = (
        f"Lowest validation subject-macro MAE among P0/P1/P2 "
        f"(persistence={val_metrics['persistence'].get('subject_macro_mae')}, "
        f"trend={val_metrics['empirical_trend'].get('subject_macro_mae')}, "
        f"ridge={val_metrics['ridge'].get('subject_macro_mae')}); "
        "test unused for selection."
    )

    # Full test evaluation (active selection already frozen from validation)
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
    elif gates["ridge_macro_lt_persistence"] is False and gates["ridge_micro_lt_persistence"] is False:
        outcome_probe = (
            ridge_m["subject_macro_mae"] is not None
            and pers_m["subject_macro_mae"] is not None
            and ridge_m["subject_macro_mae"] > pers_m["subject_macro_mae"]
        )
        signal = "RESULT_UNSTABLE" if outcome_probe and (boot.get("status") != "COMPUTED") else (
            "NO_INCREMENTAL_SIGNAL_DETECTED"
        )
        if outcome_probe and abs_delta is not None and abs_delta > 0:
            # degradation vs persistence without exploratory support
            if not gates["bootstrap_ci_upper_lt_0"]:
                signal = "NO_INCREMENTAL_SIGNAL_DETECTED"
    else:
        signal = "NO_INCREMENTAL_SIGNAL_DETECTED"

    eval_doc = {
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
    }

    # Active provider test metrics
    active_test = {
        "persistence": pers_m,
        "empirical_trend": trend_m,
        "ridge": ridge_m,
    }

    if signal == "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED":
        outcome_status = "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED"
    elif signal == "INSUFFICIENT_DATA":
        outcome_status = "INSUFFICIENT_TEST_DATA"
    elif signal == "RESULT_UNSTABLE":
        outcome_status = "RESULT_UNSTABLE"
    else:
        outcome_status = "NO_INCREMENTAL_SIGNAL_DETECTED"

    unc = compute_uncertainty(r_test, p_test)
    u_status = unc.get("uncertainty_interval_construction_status") or unc.get(
        "source_a_uncertainty_status"
    )

    train_hash = _pair_manifest_hash(train)
    appl_ref = build_applicability_reference(
        train,
        training_pair_manifest_hash=train_hash,
        feature_schema_hash=feature_schema_hash(),
        scaler_fit_n_rows=ridge.scaler.fit_n_rows,
    )
    appl_score = (
        assess_b_applicability(test[: min(50, len(test))], appl_ref)
        if test
        else {}
    )

    # Freeze payload for active provider
    frozen = {
        "grain_id": grain["grain_id"],
        "outcome": grain.get("normalized_label") or grain.get("outcome"),
        "unit": grain.get("unit"),
        "active_provider": active,
        "seed": SEED,
        "l2": L2,
        "feature_schema_hash": feature_schema_hash(),
        "feature_order_hash": feature_schema_hash(),
        "split_hash": split["split_hash"],
        "train_manifest_hash": train_hash,
        "ridge": {
            "coef": ridge.coef,
            "intercept": ridge.intercept,
            "residual_std": ridge.residual_std,
            "scaler": {"means": ridge.scaler.means, "stds": ridge.scaler.stds},
            "interval_multiplier": ridge.interval_multiplier,
        },
        "applicability_reference_hash": _hash(
            {k: v for k, v in appl_ref.items() if k != "feature_distributions"}
        ),
    }
    model_file_hash = _hash(frozen)
    identity_hash = _hash(
        {
            "grain_id": frozen["grain_id"],
            "active": active,
            "feature_schema_hash": frozen["feature_schema_hash"],
            "split_hash": frozen["split_hash"],
            "train_manifest_hash": frozen["train_manifest_hash"],
        }
    )
    frozen["model_file_hash"] = model_file_hash
    frozen["model_identity_hash"] = identity_hash

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
        "test_metrics": active_test,
        "evaluation": {
            k: v
            for k, v in eval_doc.items()
            if not str(k).startswith("_")
        },
        "uncertainty": unc,
        "uncertainty_status": u_status,
        "applicability_reference": {
            k: v for k, v in appl_ref.items() if k != "feature_distributions"
        },
        "applicability_sample": appl_score,
        "frozen": frozen,
        "medication_features_present": False,
    }
