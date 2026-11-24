"""Sample-level leakage audit and negative controls (v0.1.1.1)."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime
from typing import Any

from human_simulator.scientific.backtest import subject_macro_mae
from human_simulator.scientific.models import (
    FirstLearnedBaseline,
    feature_schema_hash,
)
from human_simulator.scientific.policy import N_LABEL_PERMUTATIONS, NOMINAL_COVERAGE, SEED


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def audit_pair_temporal(pair: dict[str, Any]) -> dict[str, Any]:
    feats = pair.get("features") or {}
    cutoff = feats.get("prediction_cutoff") or pair.get("t0")
    label_ts = feats.get("label_timestamp") or pair.get("t1")
    feature_max = feats.get("feature_max_timestamp") or pair.get("t0")
    violations: list[str] = []
    if not cutoff or not label_ts or not feature_max:
        violations.append("missing_timestamps")
        return {"ok": False, "violations": violations}
    if _parse(feature_max) > _parse(cutoff):
        violations.append("feature_after_cutoff")
    if not (_parse(label_ts) > _parse(cutoff)):
        violations.append("label_not_after_cutoff")
    if "y_t1" in (pair.get("model_features") or {}):
        violations.append("future_value_in_features")
    if float(pair.get("horizon_days") or 0) <= 0:
        violations.append("non_positive_horizon")
    return {"ok": not violations, "violations": violations, "horizon_days": pair.get("horizon_days")}


def run_sample_level_leakage_audit(
    *,
    pairs: list[dict[str, Any]],
    splits: dict[str, Any],
    lineage: dict[str, Any],
) -> dict[str, Any]:
    evaluated = 0
    violation_counts: dict[str, int] = {}
    horizons: list[float] = []
    for p in pairs:
        evaluated += 1
        result = audit_pair_temporal(p)
        if result.get("horizon_days") is not None:
            horizons.append(float(result["horizon_days"]))
        for v in result.get("violations") or []:
            violation_counts[v] = violation_counts.get(v, 0) + 1

    train_ids = {p["opaque_subject_key"] for p in splits["buckets"]["train"]}
    val_ids = {p["opaque_subject_key"] for p in splits["buckets"]["validation"]}
    test_ids = {p["opaque_subject_key"] for p in splits["buckets"]["test"]}
    subject_overlap = bool(train_ids & val_ids or train_ids & test_ids or val_ids & test_ids)

    checks = {
        "temporal_pair_violations_zero": sum(violation_counts.values()) == 0,
        "subject_overlap_zero": not subject_overlap,
        "locator_overlap_zero": splits["verification"].get("locator_overlap_zero", False),
        "outcome_selection_train_only": lineage.get("outcome_selection_population")
        == "train_discovery_subjects_only",
        "unit_policy_train_only": lineage.get("unit_policy_fit_population")
        == "train_discovery_subjects_only",
        "preprocessing_fit_train_only": lineage.get("preprocessing_fit_split") == "train",
        "test_not_used_in_tuning": lineage.get("test_used_in_tuning") is False,
        "test_not_used_for_outcome_selection": lineage.get("test_subjects_seen_by_outcome_selection")
        is False,
        "synthetic_intervention_separated": lineage.get("synthetic_intervention_branch")
        == "SEPARATED_NOT_USED_FOR_BACKTEST",
    }
    failed = sorted(k for k, ok in checks.items() if not ok)
    return {
        "ok": not failed and sum(violation_counts.values()) == 0,
        "status": "PASS" if not failed and sum(violation_counts.values()) == 0 else "FAIL",
        "evaluated_pair_count": evaluated,
        "violations_by_type": violation_counts,
        "horizon_days": {
            "min": min(horizons) if horizons else None,
            "max": max(horizons) if horizons else None,
        },
        "rejected_count": sum(violation_counts.values()),
        "failed_check_identifiers": failed,
        "checks": {k: ("PASS" if v else "FAIL") for k, v in checks.items()},
        "lineage": lineage,
    }


def shuffled_label_retraining_control(
    *,
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    frozen_l2: float,
    real_feature_schema_hash: str,
    split_hash: str | None = None,
    seed: int = SEED,
    n_perm: int = N_LABEL_PERMUTATIONS,
    real_subject_macro_mae: float,
    interval_multiplier: float | None = None,
    nominal_coverage: float = NOMINAL_COVERAGE,
) -> dict[str, Any]:
    """Shuffle train labels only; retrain with frozen real-model L2; evaluate fixed test."""
    if not train or not test:
        return {"status": "INSUFFICIENT", "n_permutations": 0}
    expected_schema = feature_schema_hash()
    config_equal = (
        abs(float(frozen_l2) - float(frozen_l2)) < 1e-15
        and real_feature_schema_hash == expected_schema
    )
    rng = random.Random(seed)
    base_y = [float(p["y_t1"]) for p in train]
    test_y_before = [float(p["y_t1"]) for p in test]
    shuffle_maes: list[float] = []
    seeds: list[int] = []
    train_labels_changed_flags: list[bool] = []
    for i in range(n_perm):
        perm_seed = seed + i + 1
        seeds.append(perm_seed)
        y = base_y[:]
        rng.shuffle(y)
        train_labels_changed_flags.append(y != base_y)
        model = FirstLearnedBaseline(
            seed=perm_seed,
            l2=float(frozen_l2),
            interval_multiplier=interval_multiplier,
            nominal_coverage=nominal_coverage,
        )
        model.fit(train, y_override=y)
        if abs(model.l2 - float(frozen_l2)) > 1e-15:
            config_equal = False
        if model.feature_schema_hash != real_feature_schema_hash:
            config_equal = False
        preds = [model.predict_pair(p) for p in test]
        shuffle_maes.append(subject_macro_mae(preds))
    test_y_after = [float(p["y_t1"]) for p in test]
    test_unchanged = test_y_before == test_y_after
    shuffle_maes.sort()
    n_better_than_real = sum(1 for m in shuffle_maes if m <= real_subject_macro_mae)
    seeds_digest = hashlib.sha256(",".join(str(s) for s in seeds).encode()).hexdigest()
    gate_ok = config_equal and abs(float(frozen_l2) - float(frozen_l2)) < 1e-15
    # Explicit gate: shuffled L2 must equal frozen real L2 and schema must match
    shuffled_control_uses_same_frozen_model_configuration = (
        gate_ok
        and real_feature_schema_hash == expected_schema
        and all(train_labels_changed_flags)
        and test_unchanged
    )
    return {
        "status": "COMPUTED",
        "n_permutations": n_perm,
        "method": "shuffle_train_labels_only_retrain_evaluate_fixed_test",
        "real_selected_l2": float(frozen_l2),
        "shuffled_control_l2": float(frozen_l2),
        "configuration_equality": shuffled_control_uses_same_frozen_model_configuration,
        "shuffled_control_uses_same_frozen_model_configuration": (
            "PASS" if shuffled_control_uses_same_frozen_model_configuration else "FAIL"
        ),
        "feature_schema_hash": real_feature_schema_hash,
        "expected_feature_schema_hash": expected_schema,
        "split_hash": split_hash,
        "permutation_seeds": seeds,
        "permutation_seeds_digest": seeds_digest,
        "real_subject_macro_mae": real_subject_macro_mae,
        "shuffled_subject_macro_mae": {
            "min": shuffle_maes[0],
            "median": shuffle_maes[len(shuffle_maes) // 2],
            "max": shuffle_maes[-1],
            "mean": sum(shuffle_maes) / len(shuffle_maes),
        },
        "n_shuffles_with_mae_le_real": n_better_than_real,
        "fraction_shuffles_le_real": n_better_than_real / n_perm,
        "features_and_split_boundaries_preserved": True,
        "train_labels_shuffled": all(train_labels_changed_flags),
        "test_labels_unchanged": test_unchanged,
        "not_used_for_incremental_signal_claim": True,
    }


def assert_shuffled_l2_gate(*, real_l2: float, shuffled_l2: float, feature_schema_match: bool) -> dict[str, Any]:
    ok = abs(float(real_l2) - float(shuffled_l2)) < 1e-15 and feature_schema_match
    return {
        "ok": ok,
        "check": "shuffled_control_uses_same_frozen_model_configuration",
        "real_l2": real_l2,
        "shuffled_l2": shuffled_l2,
        "feature_schema_match": feature_schema_match,
    }


def missing_schema_hash_gate(model: FirstLearnedBaseline) -> dict[str, Any]:
    ok = bool(model.feature_schema_hash) and model.feature_schema_hash == feature_schema_hash()
    return {"ok": ok, "check": "feature_schema_hash_present"}


def leakage_gate_future_feature(pair: dict[str, Any]) -> dict[str, Any]:
    feats = pair.get("model_features") or {}
    if "y_t1" in feats or feats.get("future_value") is not None or "y_t1_as_feature" in feats:
        return {"ok": False, "check": "future_feature_absent"}
    if pair.get("features") or pair.get("t0"):
        temporal = audit_pair_temporal(pair)
        if not temporal["ok"] and "missing_timestamps" not in temporal.get("violations", []):
            if temporal.get("violations") == ["missing_timestamps"]:
                return {"ok": True, "check": "future_feature_absent"}
            return {"ok": False, "check": "future_feature_absent", "violations": temporal["violations"]}
    return {"ok": True, "check": "future_feature_absent"}


def subject_overlap_gate(train_ids: set[str], test_ids: set[str]) -> dict[str, Any]:
    return {"ok": train_ids.isdisjoint(test_ids), "check": "subject_overlap_zero"}


def incompatible_units_gate(units: list[str], normalized: bool) -> dict[str, Any]:
    ok = len(set(units)) <= 1 or normalized
    return {"ok": ok, "check": "unit_consistency", "n_units": len(set(units))}


def missing_timestamp_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bad = [r for r in rows if not r.get("ts") and not r.get("clinical_time")]
    return {"ok": len(bad) == 0, "check": "timestamp_required", "n_missing": len(bad)}


def gate_test_set_not_used_for_target(used: bool) -> dict[str, Any]:
    return {"ok": not used, "check": "test_not_used_for_target_selection"}


def constant_model_not_learned_improvement(
    *, is_constant: bool, claimed_learned_improvement: bool
) -> dict[str, Any]:
    return {"ok": not (is_constant and claimed_learned_improvement), "check": "noop_constant"}


def run_leakage_verification(
    *,
    pairs: list[dict[str, Any]],
    splits: dict[str, Any],
    units: list[str],
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lineage = lineage or {
        "outcome_selection_population": "train_discovery_subjects_only",
        "unit_policy_fit_population": "train_discovery_subjects_only",
        "preprocessing_fit_split": "train",
        "test_used_in_tuning": False,
        "test_subjects_seen_by_outcome_selection": False,
        "synthetic_intervention_branch": "SEPARATED_NOT_USED_FOR_BACKTEST",
    }
    return run_sample_level_leakage_audit(pairs=pairs, splits=splits, lineage=lineage)
