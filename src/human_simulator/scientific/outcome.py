"""Deterministic outcome selection — never uses model performance."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.policy import (
    MIN_CONSECUTIVE_PAIRS,
    MIN_INDEPENDENT_SUBJECTS_FOR_SPLIT,
    MIN_NUMERIC_PARSE_RATE,
    MIN_SUBJECTS_WITH_REPEAT,
    MIN_UNIT_DOMINANCE,
)


SCORING_RULE = {
    "version": "0.1",
    "description": (
        "Select the candidate maximizing a weighted coverage score among those "
        "passing hard gates. Model performance is forbidden as an input."
    ),
    "hard_gates": {
        "min_subjects_with_repeats": MIN_SUBJECTS_WITH_REPEAT,
        "min_consecutive_pairs": MIN_CONSECUTIVE_PAIRS,
        "min_numeric_parse_rate": MIN_NUMERIC_PARSE_RATE,
        "min_unit_dominance": MIN_UNIT_DOMINANCE,
        "min_subjects_with_pairs": MIN_INDEPENDENT_SUBJECTS_FOR_SPLIT,
    },
    "weights": {
        "n_subjects_with_pairs": 3.0,
        "n_consecutive_pairs": 2.0,
        "unit_dominance": 2.0,
        "numeric_parse_rate_dominant": 1.0,
        "n_subjects_with_repeats": 1.5,
        "median_measurements_per_subject": 0.5,
    },
    "tie_breakers": ["n_consecutive_pairs", "n_subjects_with_pairs", "candidate_id"],
    "forbidden_inputs": [
        "model_mae",
        "model_rmse",
        "test_set_performance",
        "developer_biomarker_preference",
    ],
}


def _passes_gates(c: dict[str, Any]) -> tuple[bool, list[str]]:
    fails: list[str] = []
    if c["n_subjects_with_repeats"] < MIN_SUBJECTS_WITH_REPEAT:
        fails.append("n_subjects_with_repeats")
    if c["n_consecutive_pairs"] < MIN_CONSECUTIVE_PAIRS:
        fails.append("n_consecutive_pairs")
    if c.get("numeric_parse_rate_dominant", 0) < MIN_NUMERIC_PARSE_RATE:
        fails.append("numeric_parse_rate")
    if c.get("unit_dominance", 0) < MIN_UNIT_DOMINANCE:
        fails.append("unit_dominance")
    if c.get("n_subjects_with_pairs", 0) < MIN_INDEPENDENT_SUBJECTS_FOR_SPLIT:
        fails.append("n_subjects_with_pairs")
    return (not fails), fails


def score_candidate(c: dict[str, Any]) -> float:
    w = SCORING_RULE["weights"]
    return (
        w["n_subjects_with_pairs"] * float(c.get("n_subjects_with_pairs") or 0)
        + w["n_consecutive_pairs"] * float(c.get("n_consecutive_pairs") or 0)
        + w["unit_dominance"] * 100.0 * float(c.get("unit_dominance") or 0)
        + w["numeric_parse_rate_dominant"] * 100.0 * float(c.get("numeric_parse_rate_dominant") or 0)
        + w["n_subjects_with_repeats"] * float(c.get("n_subjects_with_repeats") or 0)
        + w["median_measurements_per_subject"] * float(c.get("median_measurements_per_subject") or 0)
    )


def select_outcome(profile: dict[str, Any]) -> dict[str, Any]:
    candidates = list(profile.get("candidates") or [])
    scored: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for c in candidates:
        ok, fails = _passes_gates(c)
        entry = {
            **{k: c[k] for k in c if k != "source_measurement_label" or True},
            "passes_hard_gates": ok,
            "failed_gates": fails,
            "coverage_score": round(score_candidate(c), 4),
        }
        # keep label for report (it's a lab code name, not a patient identifier)
        scored.append(entry)
        if ok:
            eligible.append(entry)

    if not eligible:
        return {
            "status": "INSUFFICIENT_DATA_FOR_FIRST_BACKTEST",
            "scoring_rule": SCORING_RULE,
            "n_candidates_scored": len(scored),
            "n_eligible": 0,
            "selected": None,
            "scored_candidates": scored,
            "insufficiency_reasons": [
                "No candidate passed hard gates for longitudinal coverage, "
                "repeat density, numeric validity, and unit dominance on train/discovery subjects."
            ],
            "medical_interpretation_status": "DOMAIN_REVIEW_PENDING",
            "selection_population": "train_discovery_subjects_only",
        }

    eligible.sort(
        key=lambda e: (
            -e["coverage_score"],
            -e["n_consecutive_pairs"],
            -e["n_subjects_with_pairs"],
            e["candidate_id"],
        )
    )
    selected = eligible[0]
    return {
        "status": "OUTCOME_SELECTED",
        "scoring_rule": SCORING_RULE,
        "n_candidates_scored": len(scored),
        "n_eligible": len(eligible),
        "selected": {
            "candidate_id": selected["candidate_id"],
            "source_measurement_label": selected["source_measurement_label"],
            "dominant_unit": selected["dominant_unit"],
            "coverage_score": selected["coverage_score"],
            "n_subjects_with_pairs": selected["n_subjects_with_pairs"],
            "n_consecutive_pairs": selected["n_consecutive_pairs"],
            "unit_dominance": selected["unit_dominance"],
            "selection_basis": (
                "Highest coverage_score among gate-passers; no model performance used."
            ),
            "limitations": [
                "Medical semantics of source_measurement_label are DOMAIN_REVIEW_PENDING.",
                "Only dominant unit retained; other units excluded without unverified conversion.",
                "Pilot cohort is TECHNICAL_COVERAGE_BIASED_SAMPLE from core vertical slice.",
            ],
            "medical_interpretation_status": "DOMAIN_REVIEW_PENDING",
        },
        "scored_candidates": [
            {
                "candidate_id": e["candidate_id"],
                "source_measurement_label": e["source_measurement_label"],
                "coverage_score": e["coverage_score"],
                "passes_hard_gates": e["passes_hard_gates"],
                "failed_gates": e["failed_gates"],
                "n_consecutive_pairs": e["n_consecutive_pairs"],
                "n_subjects_with_pairs": e["n_subjects_with_pairs"],
                "unit_dominance": e["unit_dominance"],
            }
            for e in scored
        ],
        "selection_population": "train_discovery_subjects_only",
        "medical_interpretation_status": "DOMAIN_REVIEW_PENDING",
    }
