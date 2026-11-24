"""Data-readiness scenarios and threshold options (proposal only)."""

from __future__ import annotations

from typing import Any

from human_simulator.post_pilot_audit_v01.policy import VERSION


def build_scenarios(
    *,
    inventory: dict[str, Any],
    funnel: dict[str, Any],
) -> dict[str, Any]:
    cov = inventory.get("outcome_coverage_distribution") or {}
    overlap = inventory.get("multi_outcome_overlap_profile") or {}
    pair_hist = cov.get("pair_count_histogram_thresholds") or {}
    top = cov.get("top_20_by_pairs") or []

    med_cohorts = funnel.get("cohorts") or []
    med_primary_eps = [c.get("n_primary_episodes") for c in med_cohorts]

    scenarios = [
        {
            "id": "A",
            "name": "Single-outcome trajectory expansion",
            "description": (
                "Expand natural-history / persistence baselines across many outcome×unit "
                "grains independently; no multi-outcome state vector."
            ),
            "available_subjects_signal": cov.get("subjects_ge2_thresholds"),
            "available_pairs_signal": pair_hist,
            "outcome_coverage": {
                "grains_with_ge100_pairs": pair_hist.get("ge_100"),
                "grains_with_ge1000_pairs": pair_hist.get("ge_1000"),
                "top_examples": top[:5],
            },
            "missingness_policy_needed": (
                "Per-outcome dominant unit; drop non-numeric; require timestamps; "
                "no cross-outcome imputation."
            ),
            "risks": [
                "Outcome label semantics still DOMAIN_REVIEW_PENDING",
                "Multiple units per label",
                "Scientific gates still unmet for medication intervention cohorts",
            ],
            "new_assumptions": [
                "Strict consecutive pairs are the trajectory grain",
                "No causal/medication interpretation in this stage",
            ],
            "without_new_data": True,
            "requires_new_data_or_human_review": False,
            "evidence_support": "HIGH" if (pair_hist.get("ge_1000") or 0) >= 10 else "MODERATE",
        },
        {
            "id": "B",
            "name": "Multi-outcome state baseline",
            "description": (
                "Joint state from co-observed outcomes on panels / timestamps."
            ),
            "available_subjects_signal": {
                "subjects_multi_outcome": overlap.get(
                    "n_subjects_with_ge2_distinct_outcome_units"
                ),
                "median_outcomes_per_subject": overlap.get("median_outcomes_per_subject"),
                "panels_ge10": overlap.get("n_panels_with_ge10_outcomes"),
                "panels_ge20": overlap.get("n_panels_with_ge20_outcomes"),
            },
            "available_pairs_signal": "depends_on_completeness_policy_not_yet_chosen",
            "outcome_coverage": overlap.get("potential_multi_outcome_snapshots"),
            "missingness_policy_needed": (
                "Must define required core outcome set and allowed missingness; "
                "not chosen in this audit."
            ),
            "risks": [
                "Missingness-induced selection bias",
                "Panel completeness arbitrary without owner thresholds",
                "Much harder evaluation leakage control",
            ],
            "new_assumptions": [
                "A stable core outcome set exists",
                "Same-timestamp components form a valid state snapshot",
            ],
            "without_new_data": True,
            "requires_new_data_or_human_review": True,
            "evidence_support": (
                "CONDITIONAL"
                if (overlap.get("n_panels_with_ge10_outcomes") or 0) > 1000
                else "LOW"
            ),
            "gate": "Do not start until completeness policy chosen (THRESHOLD_DECISION_REQUIRED)",
        },
        {
            "id": "C",
            "name": "Medication cohort enrichment",
            "description": (
                "Continue provider enrichment / typed review to grow strict concept cohorts "
                "toward scientific gates 100/300/30."
            ),
            "available_subjects_signal": {
                "current_primary_subjects": [c.get("n_primary_subjects") for c in med_cohorts],
                "current_primary_episodes": med_primary_eps,
            },
            "available_pairs_signal": med_primary_eps,
            "outcome_coverage": "limited_by_medication_x_outcome_intersection",
            "missingness_policy_needed": "Same as pilot; concept acceptance still HUMAN",
            "risks": [
                "HUMAN_ACCEPTED still 0",
                "Primary grains remain ~29–50 episodes until enrichment or broader outcomes",
            ],
            "new_assumptions": ["Typed acceptance semantics remain required for READY"],
            "without_new_data": False,
            "requires_new_data_or_human_review": True,
            "evidence_support": "NECESSARY_FOR_SCIENTIFIC_MEDICATION_READY_BUT_NOT_NEXT_TECHNICAL",
        },
        {
            "id": "D",
            "name": "Source-ID technical experiments",
            "description": (
                "Continue technical association experiments on medicine IDs / provisional "
                "concepts without scientific acceptance."
            ),
            "available_subjects_signal": {
                "pilot_showed_unstable_cv": True,
                "primary_n": med_primary_eps,
            },
            "available_pairs_signal": med_primary_eps,
            "outcome_coverage": "five_v01_grains_or_expanded_list",
            "missingness_policy_needed": "Existing pilot filters",
            "risks": [
                "Small-N instability will persist",
                "Risk of over-interpreting NC p-values (documented)",
            ],
            "new_assumptions": ["Remain CLINICAL_USE_PROHIBITED / non-causal"],
            "without_new_data": True,
            "requires_new_data_or_human_review": False,
            "evidence_support": "LOW_FOR_NEXT_STAGE_GIVEN_UNSTABLE_SMALL_N",
        },
    ]

    # Recommendation from measured coverage — not developer preference
    # Prefer A when many grains have large consecutive-pair counts.
    if (pair_hist.get("ge_1000") or 0) >= 10:
        recommended = "A"
        readiness_nh = "TECHNICALLY_SUPPORTED_FOR_AUDIT_BACKED_EXPANSION"
        reason = (
            "Source A shows many outcome×unit grains with ≥1000 strict consecutive pairs; "
            "medication primary grains remain 29–50. Next model stage supported by data is "
            "single-outcome trajectory expansion, not multi-outcome natural history yet "
            "(thresholds for B not accepted) and not another medication association train."
        )
    else:
        recommended = "A"
        readiness_nh = "PARTIAL"
        reason = "Default to single-outcome expansion; re-check pair histogram."

    return {
        "version": VERSION,
        "scenarios": scenarios,
        "RECOMMENDED_NEXT_STAGE": recommended,
        "recommendation_reason": reason,
        "NATURAL_HISTORY_DATA_READINESS_STATUS": readiness_nh,
        "MEDICATION_COHORT_DATA_READINESS_STATUS": "NOT_READY_SMALL_PRIMARY_GRAINS_ZERO_HUMAN_ACCEPTED",
        "no_automatic_scenario_acceptance": True,
    }


def build_threshold_options(inventory: dict[str, Any]) -> dict[str, Any]:
    grains = inventory.get("grains") or []

    def count_pass(min_subj: int, min_pairs: int) -> dict[str, Any]:
        ok = [
            g
            for g in grains
            if int(g.get("n_subjects_with_ge2") or 0) >= min_subj
            and int(g.get("n_strict_consecutive_pairs") or 0) >= min_pairs
        ]
        return {
            "n_outcomes_passing": len(ok),
            "example_top": [
                {
                    "outcome": g["outcome"],
                    "unit": g["unit"],
                    "n_pairs": g["n_strict_consecutive_pairs"],
                    "n_subjects_ge2": g["n_subjects_with_ge2"],
                }
                for g in ok[:10]
            ],
        }

    options = {
        "conservative": {
            "min_subjects_with_ge2": 100,
            "min_strict_consecutive_pairs": 300,
            "min_test_subjects_if_split": 30,
            "pass": count_pass(100, 300),
        },
        "moderate_technical": {
            "min_subjects_with_ge2": 50,
            "min_strict_consecutive_pairs": 100,
            "min_test_subjects_if_split": 15,
            "pass": count_pass(50, 100),
        },
        "minimal_engineering": {
            "min_subjects_with_ge2": 30,
            "min_strict_consecutive_pairs": 50,
            "min_test_subjects_if_split": 10,
            "pass": count_pass(30, 50),
        },
    }
    return {
        "version": VERSION,
        "THRESHOLD_DECISION_STATUS": "THRESHOLD_DECISION_REQUIRED",
        "written_into_policy": False,
        "used_for_training": False,
        "options": options,
        "note": "Proposals only — require next owner prompt before acceptance.",
    }


def write_recommended_next_stage_md(
    *,
    scenarios: dict[str, Any],
    thresholds: dict[str, Any],
    funnel: dict[str, Any],
    nc: dict[str, Any],
) -> str:
    rec = scenarios.get("RECOMMENDED_NEXT_STAGE")
    lines = [
        f"# Recommended next stage (audit v{VERSION})",
        "",
        f"**RECOMMENDED_NEXT_STAGE:** Scenario {rec} — Single-outcome trajectory expansion",
        "",
        "## Why (evidence)",
        "",
        scenarios.get("recommendation_reason") or "",
        "",
        "## What this is not",
        "",
        "- Not Multi-Outcome Natural History Baseline (Scenario B) — thresholds not accepted",
        "- Not medication intervention-response / treatment-effect",
        "- Not scientific READY medication cohorts (primary grains 29–50; HUMAN_ACCEPTED=0)",
        "",
        "## Episode accounting headline",
        "",
    ]
    for c in funnel.get("cohorts") or []:
        lines.append(
            f"- {c['cohort_id']}: {c['n_total_concept_episodes']} → "
            f"{c['n_primary_episodes']} primary "
            f"({c['n_unique_medication_events']} unique medication events; "
            f"~{c['mean_outcomes_per_medication_event']} outcomes/event)"
        )
    lines += [
        "",
        "## Negative controls",
        "",
        f"Status: `{nc.get('NEGATIVE_CONTROL_DIRECTION_STATUS')}`. "
        "Do not treat low p as M2>M1 signal.",
        "",
        "## Thresholds",
        "",
        "`THRESHOLD_DECISION_REQUIRED` — options in `threshold-options.json`; "
        "not written to policy.",
        "",
        "## Non-actions",
        "",
        "- No model training in this audit",
        "- No ZIP publication",
        "- No HUMAN_ACCEPTED",
        "- Security remains PAUSED_NOT_ACCEPTED_BY_OWNER",
        "",
    ]
    return "\n".join(lines) + "\n"
