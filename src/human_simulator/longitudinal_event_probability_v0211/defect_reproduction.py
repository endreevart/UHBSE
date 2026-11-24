"""Phase 0 — reproduce v0.2.1 defects. Does not rewrite the v0.2.1 ZIP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v0211.policy import (
    ACCEPTED_V021_ARTIFACT_DIR,
    ACCEPTED_V021_INDEXED,
    ACCEPTED_V021_MEMBERS,
    ACCEPTED_V021_SHA256,
    ACCEPTED_V021_ZIP,
    V021_SRC,
    VERSION,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reproduce_v021_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ACCEPTED_V021_ARTIFACT_DIR
    src = root / V021_SRC
    landmarks_src = _read(src / "landmarks.py")
    estimators_src = _read(src / "estimators.py")
    survival_src = _read(src / "survival.py")
    engine_src = _read(src / "engine.py")
    baseline_src = _read(src / "baseline.py")
    ood_src = _read(src / "ood.py")
    landmarks = _load_json(art / "landmark-datasets.json")
    surv = _load_json(art / "survival-evaluation.json")
    engine = _load_json(art / "engine-survival-shadow.json")
    baseline = _load_json(art / "baseline-verification.json")
    registry = _load_json(art / "accepted-probability-registry-public.json")
    feat_order = json.dumps(landmarks.get("feature_order") or [])

    a_states = (
        (landmarks.get("observation_endpoints") or {})
        .get("TIME_TO_NEXT_LAB_PANEL", {})
        .get("accounting", {})
        .get("by_source", {})
        .get("A", {})
        .get("n_landmarks")
    )
    b_states = (
        (landmarks.get("observation_endpoints") or {})
        .get("TIME_TO_NEXT_LAB_PANEL", {})
        .get("accounting", {})
        .get("by_source", {})
        .get("B", {})
        .get("n_landmarks")
    )
    a_exc = (landmarks.get("excursion_accounting") or {}).get("by_source", {}).get("A", {}).get(
        "n_landmarks"
    )
    b_exc = (landmarks.get("excursion_accounting") or {}).get("by_source", {}).get("B", {}).get(
        "n_landmarks"
    )

    results = surv.get("results") or []

    def _horizon(src_sys: str, endpoint: str, split: str, h: str) -> dict[str, Any]:
        rec = next(
            r
            for r in results
            if r.get("source_system") == src_sys and r.get("endpoint") == endpoint
        )
        return ((rec.get(split) or {}).get("horizons") or {}).get(h) or {}

    b_lab_val_365 = _horizon("kgz_raw", "TIME_TO_NEXT_LAB_PANEL", "validation", "365")
    b_lab_test_365 = _horizon("kgz_raw", "TIME_TO_NEXT_LAB_PANEL", "test", "365")
    b_enc_val_365 = _horizon("kgz_raw", "TIME_TO_NEXT_ENCOUNTER", "validation", "365")
    b_enc_test_365 = _horizon("kgz_raw", "TIME_TO_NEXT_ENCOUNTER", "test", "365")

    b_lab_val_slope = ((b_lab_val_365.get("calibration") or {}).get("slope"))
    b_lab_test_slope = ((b_lab_test_365.get("calibration") or {}).get("slope"))

    fixtures = engine.get("fixtures") or {}
    unsupported_365 = fixtures.get("unsupported_365") or {}
    ood_mut = fixtures.get("ood_mutation") or {}

    accepted_cells = [
        c
        for c in (registry.get("cells") or {}).values()
        if c.get("acceptance_status") == "ACCEPTED"
    ]

    defects = [
        {
            "id": 1,
            "claim": "excursion_landmarks_are_full_state_times_selected_outcome_product",
            "reproduced": a_exc == 198296
            and b_exc == 96872
            and a_states == 49574
            and b_states == 24218
            and a_exc == a_states * 4
            and b_exc == b_states * 4,
            "observed": {
                "A_states": a_states,
                "A_excursion": a_exc,
                "B_states": b_states,
                "B_excursion": b_exc,
            },
        },
        {
            "id": 2,
            "claim": "inclusion_does_not_require_pre_t0_history_of_specific_outcome",
            "reproduced": "no_pre_t0" not in landmarks_src
            and "for outcome in selected_by_source[ss]" in landmarks_src
            and "exact_obs.get((sid, outcome)" in landmarks_src,
        },
        {
            "id": 3,
            "claim": "no_subsequent_measurement_censored_at_administrative_max_followup",
            "reproduced": "time_days = max_days" in landmarks_src
            and "event = 0" in landmarks_src,
        },
        {
            "id": 4,
            "claim": "excursion_features_lack_outcome_specific_last_value_recency_count_delta_mask",
            "reproduced": (
                "outcome_last_value" not in feat_order
                and "days_since_last_outcome" not in feat_order
                and "n_prior_outcome" not in feat_order
                and "json.dumps(feats" in landmarks_src
            ),
        },
        {
            "id": 5,
            "claim": "ipcw_calibration_report_returns_fitted_calibrator_slope_not_independent_eval",
            "reproduced": '"slope": fitted.get("slope")' in estimators_src
            and "fitted = cal if cal is not None" in estimators_src,
        },
        {
            "id": 6,
            "claim": "validation_and_test_slopes_identical_by_construction",
            "reproduced": b_lab_val_slope is not None
            and b_lab_val_slope == b_lab_test_slope,
            "observed": {
                "validation_slope": b_lab_val_slope,
                "test_slope": b_lab_test_slope,
            },
        },
        {
            "id": 7,
            "claim": "test_evaluation_runs_before_frozen_payload_and_pretest_registry",
            "reproduced": "test_m = eval_split(" in survival_src
            and survival_src.find("test_m = eval_split")
            < survival_src.find("payload_path.write"),
        },
        {
            "id": 8,
            "claim": "365_day_accepted_cells_sit_on_censoring_boundary",
            "reproduced": (
                b_lab_val_365.get("n_at_risk") == 93
                and b_lab_val_365.get("n_censored_before_horizon") == 93
                and b_lab_test_365.get("n_at_risk") == 281
                and b_lab_test_365.get("n_censored_before_horizon") == 281
                and b_enc_val_365.get("n_at_risk") == 28
                and b_enc_val_365.get("n_censored_before_horizon") == 28
                and b_enc_test_365.get("n_at_risk") == 66
                and b_enc_test_365.get("n_censored_before_horizon") == 66
            ),
            "observed": {
                "B_lab_val": {
                    "n_at_risk": b_lab_val_365.get("n_at_risk"),
                    "n_censored_before_horizon": b_lab_val_365.get(
                        "n_censored_before_horizon"
                    ),
                },
                "B_lab_test": {
                    "n_at_risk": b_lab_test_365.get("n_at_risk"),
                    "n_censored_before_horizon": b_lab_test_365.get(
                        "n_censored_before_horizon"
                    ),
                },
                "B_enc_val": {
                    "n_at_risk": b_enc_val_365.get("n_at_risk"),
                    "n_censored_before_horizon": b_enc_val_365.get(
                        "n_censored_before_horizon"
                    ),
                },
                "B_enc_test": {
                    "n_at_risk": b_enc_test_365.get("n_at_risk"),
                    "n_censored_before_horizon": b_enc_test_365.get(
                        "n_censored_before_horizon"
                    ),
                },
            },
        },
        {
            "id": 9,
            "claim": "payload_identity_hashes_singular_calibrator_while_payload_stores_calibrators",
            "reproduced": '"calibrator": model.get("calibrator")' in estimators_src
            and "calibrators" in survival_src,
        },
        {
            "id": 10,
            "claim": "mutated_or_missing_ood_returns_ok_true_plus_abstain",
            "reproduced": (
                ood_mut.get("ok") is True and ood_mut.get("abstain") is True
            )
            or (
                'return {"in_support": False, "reasons": ["missing_source_reference"]' in engine_src
                and '"ok": True' in engine_src.split("if not ood.get")[1][:400]
            ),
            "observed": {
                "ood_mutation_ok": ood_mut.get("ok"),
                "ood_mutation_abstain": ood_mut.get("abstain"),
            },
        },
        {
            "id": 11,
            "claim": "unsupported_365_fixture_actually_requested_14_days",
            "reproduced": unsupported_365.get("requested_horizon") == 14.0,
            "observed": unsupported_365.get("requested_horizon"),
        },
        {
            "id": 12,
            "claim": "baseline_verification_publishes_traj_v01_member_counts_not_v021_zip",
            "reproduced": baseline.get("members") == 703
            and baseline.get("indexed") == 702
            and "traj_members" in baseline_src
            and "ACCEPTED_TRAJ_MEMBERS" in baseline_src,
            "observed": {
                "published_members": baseline.get("members"),
                "published_indexed": baseline.get("indexed"),
                "v021_zip_members": ACCEPTED_V021_MEMBERS,
                "v021_zip_indexed": ACCEPTED_V021_INDEXED,
            },
        },
    ]
    n_ok = sum(1 for d in defects if d.get("reproduced"))
    defect_doc = {
        "version": VERSION,
        "baseline_zip": ACCEPTED_V021_ZIP,
        "baseline_sha256": ACCEPTED_V021_SHA256,
        "V021_DEFECT_REPRODUCTION_STATUS": "PASS" if n_ok == 12 else "PARTIAL",
        "n_reproduced": n_ok,
        "n_required": 12,
        "defects": defects,
        "ok": n_ok == 12,
    }

    correction = {
        "version": VERSION,
        "v021_accepted_cell_count_not_transferred": True,
        "v021_accepted_count_was": len(accepted_cells),
        "audit_expectations_not_hard_coded_final": [
            {
                "cell": "B lab 90",
                "expectation": "validation accepted, held-out not confirmed",
            },
            {
                "cell": "B lab 180",
                "expectation": "validation accepted, held-out candidate for confirmation",
            },
            {"cell": "B lab 365", "expectation": "boundary review required"},
            {
                "cell": "B encounter 30/90/180",
                "expectation": "held-out candidate for confirmation",
            },
            {"cell": "B encounter 365", "expectation": "boundary review required"},
            {
                "cell": "A Lymphocytes 90/180",
                "expectation": "outcome-risk-set correction required",
            },
        ],
        "recalculate_on_corrected_data": True,
        "ok": True,
    }

    matrix = {
        "version": VERSION,
        "v021_global_status": "PARTIAL_ACCEPTED",
        "v021_accepted_cells": len(accepted_cells),
        "do_not_copy_count_of_nine": True,
        "cells": [
            {
                "source_system": c.get("source_system"),
                "endpoint": c.get("endpoint"),
                "outcome_key": c.get("outcome_key"),
                "horizon_days": c.get("horizon_days"),
                "v021_acceptance_status": c.get("acceptance_status"),
            }
            for c in accepted_cells
        ],
        "ok": True,
    }
    return {
        "defects": defect_doc,
        "cell_acceptance_correction": correction,
        "matrix": matrix,
        "ok": defect_doc["ok"],
    }
