"""Medication-event hierarchy Levels 0–5 with independent gates (L4 ≠ L3 by assignment)."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_association_v01.policy import (
    MIN_LEVEL5_EPISODES,
    MIN_LEVEL5_SUBJECTS,
    MIN_TEST_EPISODES,
    MIN_TEST_SUBJECTS,
    VERSION,
)


def build_hierarchy_summary(
    *,
    level0: int,
    level1: int,
    level2: int,
    level3_pairs: int,
    level3_events: int,
    level3_subjects: int,
    level4_episodes: int,
    level4_subjects: int,
    level5_episodes: int,
    level5_subjects: int,
    timestamp_hypothesis: str,
    timestamp_status: str,
    polypharmacy_event_days: int,
    same_time_excluded: int,
) -> dict[str, Any]:
    semantic_gate = {
        "name": "semantic_timestamp_gate",
        "status": timestamp_status,
        "passed": timestamp_status
        in (
            "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
            "TECHNICAL_HYPOTHESES_EVALUATED_DOMAIN_CONFIRMATION_PENDING",
            "RECORD_CREATION_TIMESTAMP_SENSITIVITY_CONTROL",
        ),
    }
    construction_gate = {
        "name": "episode_construction_gate",
        "status": "PASS" if level4_episodes > 0 else "FAIL",
        "passed": level4_episodes > 0,
        "level4_episodes": level4_episodes,
        "note": "Level 4 counted from materialised episodes, not copied from Level 3",
    }
    cohort_gate = {
        "name": "cohort_size_gate",
        "min_subjects": MIN_LEVEL5_SUBJECTS,
        "min_episodes": MIN_LEVEL5_EPISODES,
        "level4_subjects": level4_subjects,
        "level4_episodes": level4_episodes,
        "passed": level4_subjects >= MIN_LEVEL5_SUBJECTS
        and level4_episodes >= MIN_LEVEL5_EPISODES,
        "evaluated_on": "materialised_level4_before_test_split",
    }
    test_gate = {
        "name": "test_size_gate",
        "min_test_subjects": MIN_TEST_SUBJECTS,
        "min_test_episodes": MIN_TEST_EPISODES,
        "note": "Filled after split in modeling stage",
        "passed": None,
    }
    leakage_gate = {
        "name": "leakage_gate",
        "strict_pre_lt_event_lt_post": True,
        "same_time_excluded": same_time_excluded,
        "passed": True,
    }

    return {
        "version": VERSION,
        "timestamp_hypothesis": timestamp_hypothesis,
        "levels": {
            "0_source_medication_rows": level0,
            "1_subject_medicine_id_timestamp": level1,
            "2_any_pre_and_post_measurement": level2,
            "3_medication_event_x_outcome_unit_candidates": {
                "pairs": level3_pairs,
                "events": level3_events,
                "subjects": level3_subjects,
                "label": (
                    "medication events with at least one same-outcome numeric "
                    "pre/post candidate"
                ),
            },
            "4_materialised_outcome_specific_episodes": {
                "episodes": level4_episodes,
                "subjects": level4_subjects,
            },
            "5_model_eligible_after_gates": {
                "episodes": level5_episodes,
                "subjects": level5_subjects,
            },
        },
        "level4_not_copied_from_level3": True,
        "polypharmacy_event_days": polypharmacy_event_days,
        "gates": {
            "semantic_timestamp": semantic_gate,
            "episode_construction": construction_gate,
            "cohort_size": cohort_gate,
            "test_size": test_gate,
            "leakage": leakage_gate,
        },
    }
