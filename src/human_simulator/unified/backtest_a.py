"""Expanded Source A backtest with FIXED outcome (no reselection)."""

from __future__ import annotations

import math
from typing import Any

from human_simulator.scientific.backtest import compare_models, uncertainty_status
from human_simulator.scientific.dataset import (
    build_consecutive_pairs,
    fetch_eligible_subjects,
    fetch_measurement_series,
)
from human_simulator.scientific.leakage import shuffled_label_retraining_control
from human_simulator.scientific.models import (
    EmpiricalTrendBaseline,
    PersistenceBaseline,
    feature_schema_hash,
    is_constant_model,
    select_ridge_l2,
)
from human_simulator.scientific.policy import (
    MIN_TEST_PAIRS_FOR_UNCERTAINTY_CALIBRATION,
    MIN_TEST_SUBJECTS_FOR_UNCERTAINTY_CALIBRATION,
    MIN_VAL_FOR_INTERVAL_CONSTRUCTION,
    NOMINAL_COVERAGE,
    SEED,
    SPLIT_CLASS,
    gaussian_interval_multiplier,
)
from human_simulator.scientific.splits import assign_pairs_to_splits, build_subject_split
from human_simulator.unified.policy import (
    FIXED_OUTCOME_CANDIDATE_ID,
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
)


def fixed_outcome_selected() -> dict[str, Any]:
    return {
        "candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "source_measurement_label": FIXED_OUTCOME_LABEL,
        "dominant_unit": FIXED_OUTCOME_UNIT,
        "selection_basis": "FIXED_FROM_ACCEPTED_SDR_V0.1.1.1 — do not reselect",
        "medical_interpretation_status": "DOMAIN_REVIEW_PENDING",
        "limitations": [
            "Outcome fixed from accepted Scientific Data Readiness v0.1.1.1.",
            "Held-out results must not trigger reselection.",
        ],
    }


def run_expanded_source_a_backtest(
    conn: Any,
    *,
    seed: int = SEED,
) -> dict[str, Any]:
    """Reuse v0.1.1.1 methodology with fixed outcome candidate."""
    selected = fixed_outcome_selected()
    eligible = fetch_eligible_subjects(conn)
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
        "version": "0.1.1.1",
        "unit_policy": "fixed_outcome_dominant_unit",
        "pair_definition": "strict_consecutive_neighbors_only",
        "outcome_selection": "FIXED_NO_RESELECT",
    }
    pairs, meta = build_consecutive_pairs(series, outcome=selected, config=config)

    if len(pairs) < 15 or meta["summary"]["n_subjects_with_pairs"] < 8:
        return {
            "status": "INSUFFICIENT_DATA",
            "outcome": selected,
            "dataset_summary": meta.get("summary"),
            "n_pairs": len(pairs),
            "split_class": SPLIT_CLASS,
            "gaussian_interval_multiplier": gaussian_interval_multiplier(NOMINAL_COVERAGE),
            "outcome_reselected": False,
            "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        }

    splits = assign_pairs_to_splits(pairs, subject_split)
    train, val, test = (
        splits["buckets"]["train"],
        splits["buckets"]["validation"],
        splits["buckets"]["test"],
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
    p_val = [persistence.predict_pair(p) for p in val]
    l_val = [learned.predict_pair(p) for p in val]

    comparison = compare_models(persistence=p_test, trend=t_test, learned=l_test)
    if is_constant_model(l_test) and comparison["outperforms_persistence"]:
        comparison["outperforms_persistence"] = False
        comparison["incremental_signal_status"] = "NO_INCREMENTAL_SIGNAL_DETECTED"

    unc = uncertainty_status(
        val_preds=l_val,
        test_preds=l_test,
        nominal=NOMINAL_COVERAGE,
        interval_multiplier=learned.interval_multiplier,
        residual_estimation_split="validation",
        min_val_for_construction=MIN_VAL_FOR_INTERVAL_CONSTRUCTION,
        min_test_subjects=MIN_TEST_SUBJECTS_FOR_UNCERTAINTY_CALIBRATION,
        min_test_pairs=MIN_TEST_PAIRS_FOR_UNCERTAINTY_CALIBRATION,
    )

    shuffle = shuffled_label_retraining_control(
        train=train,
        test=test,
        frozen_l2=float(learned.l2),
        real_feature_schema_hash=str(learned.feature_schema_hash or feature_schema_hash()),
        split_hash=splits["verification"].get("split_hash"),
        seed=seed,
        real_subject_macro_mae=float(comparison["first_learned"].get("subject_macro_mae") or 0),
        interval_multiplier=learned.interval_multiplier,
        nominal_coverage=NOMINAL_COVERAGE,
    )

    # Sanitize split sets for publication
    split_counts = {
        "train_pairs": len(train),
        "validation_pairs": len(val),
        "test_pairs": len(test),
        "train_subjects": len(train_keys),
        "validation_subjects": len(val_keys),
        "test_subjects": len(test_keys),
    }

    status = "PASS"
    if comparison.get("incremental_signal_status") == "NO_INCREMENTAL_SIGNAL_DETECTED":
        status = "PASS"  # technical backtest completed

    return {
        "status": status,
        "retrospective_backtest_status": "FIRST_EXPLORATORY_RETROSPECTIVE_BACKTEST_PASS",
        "incremental_signal_status": comparison.get("incremental_signal_status"),
        "uncertainty_interval_construction_status": unc.get(
            "uncertainty_interval_construction_status"
        )
        or unc.get("interval_construction_status"),
        "uncertainty_calibration_status": unc.get("uncertainty_calibration_status")
        or unc.get("calibration_status"),
        "outcome": selected,
        "outcome_reselected": False,
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "n_eligible_subjects": eligible["n_eligible_subjects"],
        "n_series_rows": len(series),
        "dataset_summary": meta.get("summary"),
        "n_pairs": len(pairs),
        "split_class": SPLIT_CLASS,
        "split_counts": split_counts,
        "comparison": comparison,
        "uncertainty": unc,
        "shuffle_control": {
            "status": shuffle.get("status"),
            "n_permutations": shuffle.get("n_permutations"),
            "real_mae_rank": shuffle.get("real_mae_rank"),
        },
        "tune_info": {
            "selected_l2": tune_info.get("selected_l2") if isinstance(tune_info, dict) else None
        },
        "gaussian_interval_multiplier": gaussian_interval_multiplier(NOMINAL_COVERAGE),
        "methodology": "scientific_v0.1.1.1_fixed_outcome",
        "opaque_subject_keys_redacted": True,
        "persistence_val_n": len(p_val),
    }
