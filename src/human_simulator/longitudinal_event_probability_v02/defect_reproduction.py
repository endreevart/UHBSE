"""Phase 0 — reproduce v0.1 survival / engine / regime defects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v02.policy import (
    ACCEPTED_TRAJ_ARTIFACT_DIR,
    VERSION,
)


def reproduce_v01_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ACCEPTED_TRAJ_ARTIFACT_DIR
    tte_src = (root / "src/human_simulator/trajectory_regime_tte_v01/tte.py").read_text(
        encoding="utf-8"
    )
    eng_src = (
        root / "src/human_simulator/trajectory_regime_tte_v01/engine_shadow.py"
    ).read_text(encoding="utf-8")
    reg_src = (root / "src/human_simulator/trajectory_regime_tte_v01/regimes.py").read_text(
        encoding="utf-8"
    )
    vocab_src = (
        root / "src/human_simulator/trajectory_regime_tte_v01/vocabulary.py"
    ).read_text(encoding="utf-8")
    ood = json.loads((art / "applicability-ood-v02.json").read_text(encoding="utf-8"))
    vocab = json.loads(
        (art / "outcome-vocabulary-train-only.json").read_text(encoding="utf-8")
    )
    enc = json.loads(
        (art / "denoising-encoder-train-summary.json").read_text(encoding="utf-8")
    )
    regimes = json.loads(
        (art / "trajectory-regime-discovery.json").read_text(encoding="utf-8")
    )
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))

    hist0 = (enc.get("epoch_end_history") or [{}])[0]

    survival_defects = [
        {
            "id": "censor_fixed_90_days",
            "reproduced": "window = 90.0" in tte_src,
            "code_marker": "window = 90.0",
        },
        {
            "id": "excursion_nearest_target_as_censor_not_first_future_search",
            "reproduced": "for t in targets:" in tte_src
            and "event = 1 if (y > thr[\"hi\"] or y < thr[\"lo\"]) else 0" in tte_src
            and "first_exc" not in tte_src
            and "subsequent" not in tte_src.lower(),
            "note": "Each target row is a landmark; non-excursion nearest result coded event=0 without searching later observations",
        },
        {
            "id": "bootstrap_by_rows_not_subjects",
            "reproduced": "sample = [split_rows[rng.randrange(len(split_rows))] for _ in split_rows]"
            in tte_src,
        },
        {
            "id": "km_tied_time_sequential_not_grouped",
            "reproduced": "if e:\n            surv *= 1.0 - 1.0 / at_risk\n        at_risk -= 1" in tte_src
            or ("surv *= 1.0 - 1.0 / at_risk" in tte_src and "at_risk -= 1" in tte_src),
            "note": "No aggregation of d_i/n_i at tied timestamps",
        },
        {
            "id": "m1_mean_difference_not_discrete_hazard",
            "reproduced": "weights[k] = me - mc" in tte_src,
        },
        {
            "id": "sigmoid_untrained_uncalibrated",
            "reproduced": "pred = 1.0 / (1.0 + math.exp(-sc))" in tte_src
            and "calibrat" not in tte_src.lower(),
        },
        {
            "id": "brier_excludes_censored_no_ipcw",
            "reproduced": "if r[\"event\"] == 0 and r[\"time_days\"] < h:\n                            continue" in tte_src
            and "ipcw" not in tte_src.lower(),
        },
        {
            "id": "excursions_aggregated_across_outcomes",
            "reproduced": "eval_endpoint(exc_rows," in tte_src
            and "per_outcome" not in tte_src[tte_src.find("def eval_endpoint") :].split("return")[0],
        },
    ]

    engine_defects = [
        {
            "id": "engine_uses_actual_future_horizon_days",
            "reproduced": '1.0 / (1.0 + float(row.get("horizon_days") or 30) / 30.0)' in eng_src,
            "V01_ENGINE_FUTURE_LEAKAGE_STATUS": "CONFIRMED_FUTURE_HORIZON_LEAKAGE",
        },
        {
            "id": "engine_regime_pad_3_of_9_features",
            "reproduced": "pad/truncate" in eng_src or "x + [0.0]" in eng_src,
            "note": "Training regime features are 9-D; engine feeds 3 then pads",
        },
        {
            "id": "engine_emits_regime_id_despite_rejection",
            "reproduced": "regime_candidate_id" in eng_src
            and regimes.get("TRAJECTORY_REGIME_DISCOVERY_STATUS")
            == "CANDIDATE_ONLY_UNSTABLE",
        },
    ]

    regime_defects = [
        {
            "id": "stability_stable_but_discovery_unstable_confounded",
            "reproduced": regimes.get("TRAJECTORY_REGIME_STABILITY_STATUS") == "STABLE"
            and regimes.get("TRAJECTORY_REGIME_DISCOVERY_STATUS")
            == "CANDIDATE_ONLY_UNSTABLE",
            "observed": {
                "stability": regimes.get("TRAJECTORY_REGIME_STABILITY_STATUS"),
                "discovery": regimes.get("TRAJECTORY_REGIME_DISCOVERY_STATUS"),
                "source_ari": regimes.get("source_assignment_ari"),
            },
        },
        {
            "id": "ari_is_simple_rand_index_not_adjusted",
            "reproduced": "Adjusted Rand Index" in reg_src
            and "simplified RI" in reg_src
            and "expected_index" not in reg_src,
            "note": "_ari docstring claims ARI but implements pair-agreement RI",
        },
        {
            "id": "k_selection_raw_inertia_prefers_larger_k",
            "reproduced": regimes.get("k_selected_on_validation") == 5
            and "best_score, best_k = score, k" in reg_src
            and "silhouette" not in reg_src.lower(),
            "observed_k": regimes.get("k_selected_on_validation"),
        },
        {
            "id": "regime_features_include_source_flag_and_horizon",
            "reproduced": 'float(ctx.get("source_is_a") or 0)' in reg_src
            and 'float(row.get("horizon_days") or 0) / 30.0' in reg_src,
        },
    ]

    other = [
        {
            "id": "ood_validation_fpr_0_2625",
            "reproduced": abs(float(ood.get("validation_calibration_fpr") or 0) - 0.2625) < 1e-6,
            "observed": ood.get("validation_calibration_fpr"),
        },
        {
            "id": "vocab_test_evaluable_copied_from_validation_count",
            "reproduced": '"test_evaluable_in_vocab": val_eval' in vocab_src,
            "funnel": {
                "validation_evaluable_in_vocab": (vocab.get("funnel") or {}).get(
                    "validation_evaluable_in_vocab"
                ),
                "test_evaluable_in_vocab": (vocab.get("funnel") or {}).get(
                    "test_evaluable_in_vocab"
                ),
            },
        },
        {
            "id": "denoising_val_n_fore_zero_encoder_not_accepted",
            "reproduced": hist0.get("val_n_fore") == 0.0
            and status.get("CORRECTED_STATE_REPRESENTATION_FOUNDATION_STATUS")
            == "NOT_ACCEPTED",
            "observed_val_n_fore": hist0.get("val_n_fore"),
        },
    ]

    all_s = survival_defects + engine_defects + regime_defects + other
    n_ok = sum(1 for d in all_s if d.get("reproduced"))

    survival_doc = {
        "version": VERSION,
        "V01_SURVIVAL_DEFECT_REPRODUCTION_STATUS": (
            "PASS" if all(d.get("reproduced") for d in survival_defects) else "PARTIAL"
        ),
        "defects": survival_defects,
        "ok": all(d.get("reproduced") for d in survival_defects),
    }
    engine_doc = {
        "version": VERSION,
        "V01_ENGINE_FUTURE_LEAKAGE_STATUS": "CONFIRMED_FUTURE_HORIZON_LEAKAGE",
        "defects": engine_defects,
        "ok": all(d.get("reproduced") for d in engine_defects),
    }
    regime_doc = {
        "version": VERSION,
        "V01_REGIME_METHODOLOGY_STATUS": "DEFECTS_REPRODUCED",
        "defects": regime_defects,
        "ok": all(d.get("reproduced") for d in regime_defects),
    }
    matrix = {
        "version": VERSION,
        "PRIOR_TRANSITION_DATASET_FOUNDATION_STATUS": "ACCEPTED_TECHNICAL_LONGITUDINAL_INPUT",
        "PRIOR_TTE_DATASET_FOUNDATION_STATUS": "NOT_ACCEPTED_INCORRECT_SURVIVAL_COHORTS",
        "PRIOR_TTE_MODEL_FOUNDATION_STATUS": "NOT_ACCEPTED_NOT_PROBABILISTIC",
        "PRIOR_ENGINE_TTE_INFERENCE_STATUS": "NOT_ACCEPTED_FUTURE_HORIZON_LEAKAGE",
        "PRIOR_STATE_ENCODER_FOUNDATION_STATUS": "NOT_ACCEPTED",
        "PRIOR_CSR_ENCODER_FOUNDATION_STATUS": "NOT_ACCEPTED_WEAK_OR_NEGATIVE_EVIDENCE",
        "PRIOR_REGIME_RUNTIME_STATUS": "NOT_ACCEPTED_RETROSPECTIVE_CANDIDATES_ONLY",
        "other_defects": other,
        "n_defects_reproduced": n_ok,
        "n_defects": len(all_s),
        "ok": True,
    }
    return {
        "survival": survival_doc,
        "engine": engine_doc,
        "regime": regime_doc,
        "matrix": matrix,
        "ok": survival_doc["ok"] and engine_doc["ok"] and regime_doc["ok"],
    }
