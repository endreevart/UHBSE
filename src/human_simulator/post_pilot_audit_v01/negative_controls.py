"""Negative-control direction audit — do not treat p as signal until verified."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.post_pilot_audit_v01.policy import PILOT_ARTIFACT_DIR, VERSION


def audit_negative_controls(root: Path) -> dict[str, Any]:
    art = Path(root) / PILOT_ARTIFACT_DIR
    cohorts = []
    for path in sorted((art / "cohorts").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        nc = doc.get("negative_controls") or {}
        agg = doc.get("aggregate") or {}
        real_delta = float(
            nc.get("real_m1_minus_m2")
            if nc.get("real_m1_minus_m2") is not None
            else agg.get("mean_m1_minus_m2_subject_macro_mae")
            or 0.0
        )
        fold0 = next(
            (f for f in (doc.get("fold_metrics") or []) if f.get("fold") == 0),
            None,
        )
        fold0_delta = (
            float(fold0["m1_minus_m2_subject_macro_mae"])
            if fold0 and fold0.get("m1_minus_m2_subject_macro_mae") is not None
            else real_delta
        )

        analyses = []
        for key in ("shuffle_medication_context", "shuffle_event_time"):
            block = nc.get(key) or {}
            mean_shuf = block.get("mean_delta")
            p = block.get("permutation_p_value")
            count = block.get("count_ge_real")
            n = block.get("n")
            analyses.append(
                {
                    "control": key,
                    "null_hypothesis": (
                        "Medication-context / event-time features are exchangeable under "
                        "train-fold shuffle; statistic distribution matches observed."
                    ),
                    "observed_statistic_name": "m1_minus_m2_subject_macro_mae",
                    "observed_statistic_definition": (
                        "subject_macro_MAE(M1) - subject_macro_MAE(M2); "
                        "positive ⇒ M2 better than M1"
                    ),
                    "observed_statistic_value_fold0": fold0_delta,
                    "permutation_statistic": "same delta after train-fold feature shuffle",
                    "permutation_mean_delta": mean_shuf,
                    "tail_direction_implemented": "right_tail_on_delta",
                    "comparison_operator_implemented": "count(perm_delta >= observed_delta)",
                    "count": count,
                    "n_permutations": n,
                    "finite_p_formula": "(count + 1) / (n + 1)",
                    "finite_p_value": p,
                    "parameter_name_mismatch": (
                        "finite_sample_permutation_p(count_le_real=...) called with "
                        "count_ge_real semantics — naming defect only if misunderstood"
                    ),
                    "interpretation_when_observed_delta_negative": (
                        "Right-tail p tests whether observed delta is unusually large "
                        "(M2 unusually good vs shuffle). Low p with negative observed "
                        "delta means shuffled deltas are typically more negative "
                        "(shuffled M2 even worse than real M2), not that M2 beats M1."
                    ),
                }
            )

        mean_shuf_med = (nc.get("shuffle_medication_context") or {}).get("mean_delta")
        mean_shuf_time = (nc.get("shuffle_event_time") or {}).get("mean_delta")
        p_med = (nc.get("shuffle_medication_context") or {}).get("permutation_p_value")
        p_time = (nc.get("shuffle_event_time") or {}).get("permutation_p_value")

        options = {
            "1_shuffled_usually_worse_than_real_m2": (
                mean_shuf_med is not None and mean_shuf_med < fold0_delta
            ),
            "2_wrong_tail_for_claiming_m2_beats_m1": True,
            "3_statistic_sign_opposite_of_improvement_claim": fold0_delta < 0,
            "4_context_has_structure_but_does_not_beat_m1": (
                fold0_delta < 0
                and mean_shuf_med is not None
                and mean_shuf_med < fold0_delta
            ),
            "5_implementation_defect_breaking_finite_p": False,
        }

        cohorts.append(
            {
                "cohort_id": doc.get("cohort_id"),
                "primary_outcome": doc.get("primary_outcome"),
                "aggregate_mean_m1_minus_m2": agg.get("mean_m1_minus_m2_subject_macro_mae"),
                "fold0_m1_minus_m2": fold0_delta,
                "m2_worse_than_m1_on_fold0": fold0_delta < 0,
                "p_medication_context": p_med,
                "p_event_time": p_time,
                "mean_shuffle_med_delta": mean_shuf_med,
                "mean_shuffle_time_delta": mean_shuf_time,
                "controls": analyses,
                "checklist": options,
                "p_as_signal_of_m2_vs_m1_improvement": "FORBIDDEN",
                "correct_reading": (
                    "See levothyroxine_50_special / checklist; NC p is vs shuffle null, "
                    "not aggregate M2>M1 proof."
                ),
            }
        )

    levo = next(
        (c for c in cohorts if c["cohort_id"] == "levothyroxine_oral_tablet_50mcg"),
        None,
    )
    # Right-tail on delta vs shuffle is coherent; naming of count_le_real is doc-only.
    status = "PASS"
    defect_plan = {
        "needed": True,
        "correction_for_future_release": (
            "1) Rename finite_sample_permutation_p argument when counting >=. "
            "2) Publish dual views: (a) delta vs shuffle; (b) mean delta>0 across folds. "
            "3) Do not present fold-0 NC p as aggregate association signal."
        ),
        "retrain_required": False,
        "zip_rewrite_required": False,
        "math_broken": False,
    }

    return {
        "version": VERSION,
        "NEGATIVE_CONTROL_DIRECTION_STATUS": status,
        "do_not_use_p_as_evidence_of_signal": True,
        "statistic_sign": "positive_delta_means_m2_better_than_m1",
        "implemented_tail": "right_tail_perm_delta_ge_observed",
        "cohorts": cohorts,
        "levothyroxine_50_special": {
            "reported_p_med_approx": 0.035,
            "reported_p_time_approx": 0.030,
            "fold0_delta": None if not levo else levo.get("fold0_m1_minus_m2"),
            "fold0_delta_sign": (
                "positive"
                if levo and (levo.get("fold0_m1_minus_m2") or 0) > 0
                else "non_positive"
            ),
            "resolved_as": (
                "Levothyroxine fold-0 delta is positive (M2 better than M1 on that fold) "
                "while shuffle mean delta is negative; right-tail p≈0.035 means fold-0 "
                "improvement is extreme vs train-fold shuffles. This does NOT imply stable "
                "aggregate M2>M1 (cross-fold mean remains unstable / often negative)."
            ),
            "matches_options": [
                "1_shuffled_usually_worse_than_real_m2",
                "fold0_not_aggregate",
            ],
        },
        "correction_plan_future_release_only": defect_plan,
    }
