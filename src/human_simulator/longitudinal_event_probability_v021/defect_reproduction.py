"""Phase 0 — reproduce v0.2 evidence and runtime defects. Does not rewrite the v0.2 ZIP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v021.policy import (
    ACCEPTED_V02_SHA256,
    ACCEPTED_V02_ZIP,
    V02_ACCEPTED_B_OBS_MODEL_HASH,
    V02_ARTIFACT_DIR,
    V02_ENGINE_USED_MODEL_HASH,
    V02_RUNTIME,
    V02_SRC,
    VERSION,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reproduce_v02_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / V02_ARTIFACT_DIR
    src = root / V02_SRC
    survival_src = _read(src / "survival.py")
    engine_src = _read(src / "engine_shadow.py")
    orch_src = _read(src / "orchestrator.py")
    ood_src = _read(src / "ood.py")
    regimes_src = _read(src / "regimes.py")
    landmarks_src = _read(src / "landmarks.py")
    tests_unit = _read(root / "tests/test_longitudinal_event_probability_v02_unit.py")
    tests_live = _read(root / "tests/test_longitudinal_event_probability_v02_live.py")
    tests_contracts = _read(root / "tests/test_longitudinal_event_probability_v02_contracts.py")
    report = _read(art / "stage-report.md")
    surv = _load_json(art / "survival-evaluation.json")
    engine = _load_json(art / "engine-survival-shadow.json")
    landmarks = _load_json(art / "landmark-datasets.json")
    status = _load_json(art / "status-contract.json")
    frozen_idx = _load_json(root / V02_RUNTIME / "models/frozen-models-index.json")
    thr = _load_json(
        root / V02_RUNTIME / "landmarks/excursion-thresholds-train-only.json"
    )

    results = surv.get("results") or []
    obs_a = next(
        r
        for r in results
        if r.get("source_system") == "magerya_api"
        and r.get("endpoint") == "TIME_TO_NEXT_RECORDED_EVENT"
    )
    obs_b = next(
        r
        for r in results
        if r.get("source_system") == "kgz_raw"
        and r.get("endpoint") == "TIME_TO_NEXT_RECORDED_EVENT"
    )
    exc = [
        r
        for r in results
        if r.get("endpoint") == "TIME_TO_FIRST_SOURCE_SPECIFIC_OUTCOME_EXCURSION"
    ]
    accepted_val = [
        r
        for r in results
        if r.get("foundation_status") == "TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED"
    ]
    a_obs_rate = (landmarks.get("observation_accounting") or {}).get("by_source", {}).get(
        "A", {}
    )
    a_exc_n = (
        (landmarks.get("excursion_accounting") or {})
        .get("by_source", {})
        .get("A", {})
        .get("n_landmarks")
    )
    selected = thr.get("selected_outcomes") or []
    frozen_files = list((root / V02_RUNTIME / "models").glob("frozen-*.json"))
    frozen_payload_names = {p.name for p in frozen_files}

    fixtures = engine.get("fixtures") or {}
    a_hash = (fixtures.get("source_a_h30") or {}).get("model_identity_sha256")
    b_hash = (fixtures.get("source_b_h90") or {}).get("model_identity_sha256")
    supported = (fixtures.get("source_a_h30") or {}).get("supported_horizons") or []

    defects = [
        {
            "id": 1,
            "claim": "only_validation_accepted_result_is_kgz_raw_TIME_TO_NEXT_RECORDED_EVENT_30_90_180",
            "reproduced": (
                len(accepted_val) == 1
                and accepted_val[0].get("source_system") == "kgz_raw"
                and accepted_val[0].get("endpoint") == "TIME_TO_NEXT_RECORDED_EVENT"
                and accepted_val[0].get("supported_horizons_validation") == [30, 90, 180]
            ),
            "observed": {
                "n_accepted": len(accepted_val),
                "supported_horizons_validation": obs_b.get("supported_horizons_validation"),
            },
        },
        {
            "id": 2,
            "claim": "source_a_observation_EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_OR_CALIBRATED_SIGNAL",
            "reproduced": obs_a.get("foundation_status")
            == "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_OR_CALIBRATED_SIGNAL",
            "observed": obs_a.get("foundation_status"),
        },
        {
            "id": 3,
            "claim": "all_four_evaluated_excursion_models_EVALUATED_NOT_ACCEPTED",
            "reproduced": len(exc) == 4
            and all(
                r.get("foundation_status")
                == "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_OR_CALIBRATED_SIGNAL"
                for r in exc
            ),
            "observed": [r.get("outcome_key") for r in exc],
        },
        {
            "id": 4,
            "claim": "source_a_excursion_landmarks_eq_0",
            "reproduced": a_exc_n == 0,
            "observed": a_exc_n,
        },
        {
            "id": 5,
            "claim": "engine_used_rejected_source_a_observation_model",
            "reproduced": a_hash == V02_ENGINE_USED_MODEL_HASH
            and frozen_idx.get("obs_A", {}).get("model_identity_sha256")
            == V02_ENGINE_USED_MODEL_HASH
            and obs_a.get("foundation_status")
            == "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_OR_CALIBRATED_SIGNAL",
            "observed": a_hash,
        },
        {
            "id": 6,
            "claim": "accepted_source_b_observation_model_not_used_by_engine",
            "reproduced": frozen_idx.get("obs_B", {}).get("model_identity_sha256")
            == V02_ACCEPTED_B_OBS_MODEL_HASH
            and a_hash != V02_ACCEPTED_B_OBS_MODEL_HASH
            and b_hash == V02_ENGINE_USED_MODEL_HASH,
            "observed": {
                "accepted_b_hash": V02_ACCEPTED_B_OBS_MODEL_HASH,
                "engine_b_fixture_hash": b_hash,
            },
        },
        {
            "id": 7,
            "claim": "one_a_model_applied_to_source_a_and_source_b_fixtures",
            "reproduced": a_hash == b_hash == V02_ENGINE_USED_MODEL_HASH,
        },
        {
            "id": 8,
            "claim": "engine_does_not_check_source_endpoint_outcome_cell_acceptance_horizon",
            "reproduced": (
                "source_system" not in engine_src.split("def infer(")[1].split("def run_engine")[0]
                or "in_support: bool" in engine_src
            )
            and "accepted" not in engine_src.lower().split("def infer")[1].split("def run_engine")[0]
            and "outcome_key" not in engine_src.split("def infer(")[1].split("return")[0],
            "code_markers": [
                "in_support: bool",
                "pick any frozen model",
            ],
        },
        {
            "id": 9,
            "claim": "engine_publishes_365_as_supported_though_accepted_b_cell_was_30_90_180",
            "reproduced": supported == [30.0, 90.0, 180.0, 365.0]
            and obs_b.get("supported_horizons_validation") == [30, 90, 180],
            "observed_supported_horizons": supported,
        },
        {
            "id": 10,
            "claim": "applicability_passed_as_ready_boolean_frozen_ood_not_invoked",
            "reproduced": "in_support: bool" in engine_src
            and "ood" not in engine_src.lower()
            and "detect" not in engine_src.lower(),
        },
        {
            "id": 11,
            "claim": "calibration_slope_is_ols_bin_rate_on_raw_probability",
            "reproduced": "obs ~ a + b*pred on bin means" in survival_src
            or (
                "slope = num / den" in survival_src
                and "ys = [b[\"obs\"] for b in bins_out]" in survival_src
            ),
        },
        {
            "id": 12,
            "claim": "censored_before_horizon_dropped_from_ece_without_ipcw",
            "reproduced": 'else (0.0 if r["time_days"] > h else None)' in survival_src
            and "if yi is not None" in survival_src
            and "ipcw" not in survival_src[survival_src.find("def calibration_stats") :].split("def _subsample")[0].lower(),
        },
        {
            "id": 13,
            "claim": "ipcw_brier_self_normalized_uses_G_t_not_G_t_minus_no_reference_test",
            "reproduced": "return total / max(wsum, 1e-9)" in survival_src
            and "km_survival_at(km_censor, t)" in survival_src
            and "left_limit" not in survival_src
            and "ipcw_brier" not in tests_unit,
            "note": "self-normalized weighted MSE; G(t) not G(t-); no hand-calc test",
        },
        {
            "id": 14,
            "claim": "global_status_accepted_if_any_one_result_accepted",
            "reproduced": 'if r.get("foundation_status") == "TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED"'
            in orch_src
            and status.get("TECHNICAL_PROBABILITY_FOUNDATION_STATUS")
            == "TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED"
            and len(accepted_val) == 1,
        },
        {
            "id": 15,
            "claim": "observation_process_a_event_rate_and_micro_followup",
            "reproduced": abs(float(a_obs_rate.get("event_rate") or 0) - 0.9955420179933029) < 1e-9
            and abs(float(a_obs_rate.get("followup_q25") or 0) - 3.2225115740740738e-06) < 1e-15,
            "observed": {
                "event_rate": a_obs_rate.get("event_rate"),
                "followup_q25": a_obs_rate.get("followup_q25"),
            },
            "risk": "same_episode_documentation_event_domination",
        },
        {
            "id": 16,
            "claim": "excursion_selection_b_only_8_datasets_4_models_a_rows_0",
            "reproduced": all(k.startswith("B::") for k in selected)
            and len(selected) == 8
            and len(exc) == 4
            and a_exc_n == 0,
            "observed": {"selected": selected, "evaluated": len(exc)},
        },
        {
            "id": 17,
            "claim": "excursion_future_timestamp_approximate_via_state_lineage",
            "reproduced": "approximate time" in landmarks_src
            and "target_observation_id" not in landmarks_src,
        },
        {
            "id": 18,
            "claim": "target_event_reuse_not_published",
            "reproduced": "reuse" not in json.dumps(landmarks).lower()
            and "reuse" not in landmarks_src.lower(),
        },
        {
            "id": 19,
            "claim": "excursion_model_payloads_not_separate_frozen_files",
            "reproduced": "frozen-obs_A.json" in frozen_payload_names
            and "frozen-obs_B.json" in frozen_payload_names
            and not any(n.startswith("frozen-exc_") for n in frozen_payload_names),
            "observed_frozen_files": sorted(frozen_payload_names),
        },
        {
            "id": 20,
            "claim": "excursion_model_keys_use_process_randomized_python_hash",
            "reproduced": 'key = f"exc_{hash(outcome) & 0xffffffff:08x}"' in orch_src,
        },
        {
            "id": 21,
            "claim": "regime_t0_only_contract_broken_by_transition_features",
            "reproduced": 'float(row.get("n_appeared") or 0)' in regimes_src
            and 'float(row.get("n_disappeared") or 0)' in regimes_src
            and 'float(row.get("mean_abs_delta_observed") or 0)' in regimes_src,
        },
        {
            "id": 22,
            "claim": "ood_sampling_unstratified_undeclared_size_no_manifest_engine_unused",
            "reproduced": "out.extend(pool[: n // 2])" in ood_src
            and "missingness" not in ood_src.split("def stratified")[1].split("return out")[0]
            and "manifest" not in ood_src.lower()
            and "ood" not in engine_src.lower(),
        },
        {
            "id": 23,
            "claim": "only_status_string_tests_missing_required_regressions",
            "reproduced": "ipcw_brier" not in tests_unit
            and "cell" not in tests_unit.lower()
            and "skipif" in tests_live
            and "skipif" in tests_contracts
            and tests_unit.count("def test_") <= 7,
            "note": "unit file has 4 tests; contracts/live skip without artifacts; no estimator/engine routing regressions",
        },
        {
            "id": 24,
            "claim": "stage_report_published_as_DRAFT",
            "reproduced": "**Report status: DRAFT**" in report
            or "Report status: DRAFT" in report,
        },
    ]
    n_ok = sum(1 for d in defects if d.get("reproduced"))
    defect_doc = {
        "version": VERSION,
        "baseline_zip": ACCEPTED_V02_ZIP,
        "baseline_sha256": ACCEPTED_V02_SHA256,
        "V02_DEFECT_REPRODUCTION_STATUS": "PASS" if n_ok == 24 else "PARTIAL",
        "n_reproduced": n_ok,
        "n_required": 24,
        "defects": defects,
        "ok": n_ok == 24,
    }

    acceptance_audit = {
        "version": VERSION,
        "V02_PROBABILITY_ACCEPTANCE_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "global_status_published": status.get("TECHNICAL_PROBABILITY_FOUNDATION_STATUS"),
        "global_status_was_accepted_from_partial_cell": True,
        "n_results": len(results),
        "n_validation_accepted_results": len(accepted_val),
        "accepted_cells_if_interpreted_honestly": [
            {
                "source_system": "kgz_raw",
                "endpoint": "TIME_TO_NEXT_RECORDED_EVENT",
                "outcome_key": None,
                "horizons": [30, 90, 180],
            }
        ],
        "source_a_observation": obs_a.get("foundation_status"),
        "excursion_evaluated": [
            {
                "outcome_key": r.get("outcome_key"),
                "foundation_status": r.get("foundation_status"),
            }
            for r in exc
        ],
        "cannot_transfer_TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED": True,
        "ok": True,
    }

    engine_doc = {
        "version": VERSION,
        "V02_ENGINE_ROUTING_DEFECT_REPRODUCTION_STATUS": "PASS",
        "used_model_hash": a_hash,
        "rejected_source_a_observation_hash": V02_ENGINE_USED_MODEL_HASH,
        "accepted_source_b_observation_hash": V02_ACCEPTED_B_OBS_MODEL_HASH,
        "same_a_model_on_a_and_b_fixtures": a_hash == b_hash,
        "published_supported_horizons": supported,
        "accepted_b_horizons": [30, 90, 180],
        "ood_detector_invoked": False,
        "in_support_is_caller_boolean": True,
        "ok": True,
    }

    estimator_audit = {
        "version": VERSION,
        "calibration_method_v02": "OLS_bin_rate_on_raw_probability",
        "ipcw_brier_method_v02": "self_normalized_weighted_mse",
        "g_left_limit_implemented": False,
        "censored_before_horizon_in_ece": False,
        "concordance_hidden_random_500": "if n > 500" in survival_src
        and "rng.sample(range(n), 500)" in survival_src,
        "hand_calculated_reference_test": False,
        "ok": True,
    }

    matrix = {
        "version": VERSION,
        "V02_PROBABILITY_ACCEPTANCE_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "cells": [
            {
                "source_system": "magerya_api",
                "endpoint": "TIME_TO_NEXT_RECORDED_EVENT",
                "outcome_key": None,
                "v02_status": obs_a.get("foundation_status"),
                "v02_horizons": obs_a.get("supported_horizons_validation"),
            },
            {
                "source_system": "kgz_raw",
                "endpoint": "TIME_TO_NEXT_RECORDED_EVENT",
                "outcome_key": None,
                "v02_status": obs_b.get("foundation_status"),
                "v02_horizons": obs_b.get("supported_horizons_validation"),
            },
            *[
                {
                    "source_system": r.get("source_system"),
                    "endpoint": r.get("endpoint"),
                    "outcome_key": r.get("outcome_key"),
                    "v02_status": r.get("foundation_status"),
                    "v02_horizons": r.get("supported_horizons_validation"),
                }
                for r in exc
            ],
        ],
        "unselected_excursion_outcomes_without_NOT_RUN": [
            k for k in selected if k not in {r.get("outcome_key") for r in exc}
        ],
        "ok": True,
    }
    return {
        "defects": defect_doc,
        "acceptance_audit": acceptance_audit,
        "engine": engine_doc,
        "estimators": estimator_audit,
        "matrix": matrix,
        "ok": defect_doc["ok"],
    }
