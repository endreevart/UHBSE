"""Reproduce Medication Residual v0.1 limitations. Do not rewrite that ZIP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.natural_history_rollout_v01.policy import (
    MEDRES_ARTIFACT_DIR,
    MEDRES_SRC,
    PRIOR_ZIPS,
    VERSION,
)


def reproduce_limitations(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    src = root / MEDRES_SRC
    art = root / MEDRES_ARTIFACT_DIR
    landmarks = (src / "landmarks.py").read_text(encoding="utf-8")
    controls = (src / "controls.py").read_text(encoding="utf-8")
    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    nc = json.loads((art / "negative-controls.json").read_text(encoding="utf-8"))
    train = json.loads((art / "residual-training.json").read_text(encoding="utf-8"))
    vocab_ids = (train.get("vocab_public") or {}).get("ids") or []
    feat_order = (train.get("vocab_public") or {}).get("feature_order") or []

    lim1 = {
        "first_target_in_open_right_closed_window": "for ts, v, eid in future" in landmarks
        and "window_end" in landmarks,
        "horizons_iterated_30_90_180_365": "for h in PREDECLARED_HORIZONS_DAYS" in landmarks,
        "global_used_targets": "used_targets: set[str] = set()" in landmarks
        and "if tid in used_targets" in landmarks,
        "not_fixed_horizon_intervention_cohort": True,
    }
    lim2 = {
        "shuffle_small_subset": "min(len(rows), 20)" in controls,
        "no_refit_in_shuffle": "fit_ridge" not in controls and "train_and_freeze" not in controls,
        "no_empirical_null_of_model_result": True,
        "pre_t0_falsification_would_fail": nc.get("pre_t0_falsification_would_fail"),
        "overall_ok_true": nc.get("ok") is True,
        "mismatch_ok_true_with_pre_t0_false": (
            nc.get("ok") is True and nc.get("pre_t0_falsification_would_fail") is False
        ),
    }
    low_entropy = bool(vocab_ids) and all(
        isinstance(x, str) and len(x) == 64 for x in vocab_ids[:5]
    )
    lim3 = {
        "vocab_hashes_in_residual_training_json": bool(vocab_ids),
        "n_vocab_ids_published": len(vocab_ids),
        "feature_order_contains_row_derived_catalog_ids": any(
            str(x).startswith("med::") and x not in {"med::OOV"} for x in feat_order
        ),
        "not_patient_level": True,
        "fails_strict_aggregate_only": bool(vocab_ids) or bool(feat_order),
    }
    ok = (
        all(lim1[k] is True for k in lim1)
        and lim2["shuffle_small_subset"]
        and lim2["mismatch_ok_true_with_pre_t0_false"]
        and lim3["vocab_hashes_in_residual_training_json"]
    )
    return {
        "version": VERSION,
        "PRIOR_MEDICATION_RESIDUAL_LIMITATION_REPRODUCTION_STATUS": (
            "PASS" if ok else "FAIL"
        ),
        "PRIOR_MEDICATION_RESIDUAL_FOUNDATION_STATUS": (
            "NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL_FOR_EVALUATED_CONSTRUCTION"
        ),
        "zip_sha256": PRIOR_ZIPS["medres_v01"][1],
        "validation_accepted_cells": st.get("VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT"),
        "heldout_confirmed_cells": st.get("HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT"),
        "engine_eligible_cells": st.get("ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT"),
        "SOURCE_B_MEDICATION_CONTEXT_STATUS": st.get("SOURCE_B_MEDICATION_CONTEXT_STATUS"),
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT": st.get(
            "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT"
        ),
        "STATE_ENCODER_STATUS": st.get("STATE_ENCODER_STATUS"),
        "UPSTREAM_PROBABILITY_CONSUMPTION_STATUS": st.get(
            "UPSTREAM_PROBABILITY_CONSUMPTION_STATUS"
        ),
        "ENGINE_MEDICATION_RESIDUAL_SHADOW_STATUS": st.get(
            "ENGINE_MEDICATION_RESIDUAL_SHADOW_STATUS"
        ),
        "limitation_1_target_assignment": lim1,
        "limitation_2_negative_controls": lim2,
        "limitation_3_public_minimization": lim3,
        "do_not_rewrite_or_republish": True,
        "do_not_consume_vocab_models_or_cells": True,
        "ok": ok,
    }


def consumption_matrix() -> dict[str, Any]:
    return {
        "version": VERSION,
        "medication_residual_v01": {
            "consume_models": False,
            "consume_vocab": False,
            "consume_cells": False,
            "status": "NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL_FOR_EVALUATED_CONSTRUCTION",
        },
        "uis_v0111_m1": {
            "consume": False,
            "reason": "MEDICATION_FEATURES_AND_NO_REQUESTED_HORIZON",
        },
        "uis_m2_encoder": {"consume": False, "reason": "REJECTED_OR_NOT_ACCEPTED"},
        "lep_v0211": {
            "consume_as_outcome": False,
            "consume_as_observation_scheduler": "OPTIONAL_WITH_UPSTREAM_LIMITATION",
        },
        "research_layer_v031": {"consume": True, "role": "observation_sequences"},
        "global_split_v011": {"consume": True, "role": "overlap_guarded_split"},
    }


def rollout_acceptance_policy() -> dict[str, Any]:
    return {
        "version": VERSION,
        "one_step_required_before_rollout": True,
        "teacher_forced_is_not_recursive_quality": True,
        "do_not_force_accepted_cell": True,
        "no_medication_features": True,
        "no_cross_source_transfer": True,
        "marginal_multi_outcome_only": True,
        "intervention_nonzero_returns_UNAVAILABLE": True,
    }
