"""First intervention-cohort readiness map (engineering gates only)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from human_simulator.medication_concept_v01.policy import (
    ACCEPTED_CONCEPT_STATUSES,
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    V01_COHORTS,
    VERSION,
)


def build_cohort_readiness(
    *,
    episodes_by_split: dict[str, list[dict[str, Any]]],
    concept_records: list[dict[str, Any]],
    split_meta: dict[str, Any],
) -> dict[str, Any]:
    """Predeclared technical gates — not clinical sufficiency; no model performance."""
    concept_by_id = {
        str(r["source_medicine_id"]): r for r in concept_records if "source_medicine_id" in r
    }
    accepted_ids = {
        mid
        for mid, r in concept_by_id.items()
        if r.get("drug_concept_status") in ACCEPTED_CONCEPT_STATUSES
    }

    ready, partial, blocked = [], [], []

    all_eps = (
        list(episodes_by_split.get("train") or [])
        + list(episodes_by_split.get("validation") or [])
        + list(episodes_by_split.get("test") or [])
    )

    # Aggregate by accepted concept × outcome × unit; if no accepted concepts,
    # still report blocked rows for the five outcome cohorts at source-medicine level
    # is not used for READY — only accepted concepts qualify for readiness inventory.
    if not accepted_ids:
        for outcome, unit in V01_COHORTS:
            cohort_eps = [e for e in all_eps if e["outcome"] == outcome and e["unit"] == unit]
            subjects = {e["opaque_subject_key"] for e in cohort_eps}
            test_eps = [
                e
                for e in (episodes_by_split.get("test") or [])
                if e["outcome"] == outcome and e["unit"] == unit
            ]
            test_subj = {e["opaque_subject_key"] for e in test_eps}
            row = {
                "outcome": outcome,
                "unit": unit,
                "accepted_drug_concept": None,
                "n_subjects": len(subjects),
                "n_episodes": len(cohort_eps),
                "n_test_subjects": len(test_subj),
                "gates": {
                    "accepted_drug_concept_mapping": False,
                    "min_subjects": len(subjects) >= GATE_MIN_SUBJECTS,
                    "min_episodes": len(cohort_eps) >= GATE_MIN_EPISODES,
                    "subject_disjoint_split": bool(split_meta.get("zero_subject_overlap")),
                    "min_test_subjects": len(test_subj) >= GATE_MIN_TEST_SUBJECTS,
                    "no_unit_conflict": True,
                    "no_unresolved_temporal_inversion": True,  # not promoted; candidate ts only
                    "no_identity_or_locator_overlap": bool(
                        split_meta.get("zero_subject_overlap")
                        and split_meta.get("zero_episode_overlap")
                        and split_meta.get("zero_locator_overlap")
                    ),
                },
                "block_reasons": ["no_accepted_drug_concept_mapping"],
                "timestamp_confidence": "LOW_TECHNICAL_ASSOCIATION_ONLY",
                "ingredient_coverage": 0.0,
                "strength_coverage": 0.0,
                "dose_form_route_availability": False,
            }
            blocked.append(row)

        status = "ZERO_READY"
        return {
            "version": VERSION,
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS": status,
            "READY_COHORTS": ready,
            "PARTIAL_COHORTS": partial,
            "BLOCKED_COHORTS": blocked,
            "gates_predeclared_before_model_performance": True,
            "clinical_sufficiency_not_claimed": True,
            "n_accepted_concepts": 0,
            "note": (
                "Zero-ready is acceptable when no accepted drug-concept mappings exist. "
                "Engineering gates only; intervention-response training not started."
            ),
        }

    # With accepted concepts: inventory concept × outcome × unit
    for mid in sorted(accepted_ids):
        rec = concept_by_id[mid]
        for outcome, unit in V01_COHORTS:
            cohort_eps = [
                e
                for e in all_eps
                if e["outcome"] == outcome
                and e["unit"] == unit
                and str(e["medicine_id"]) == mid
            ]
            if not cohort_eps:
                continue
            subjects = {e["opaque_subject_key"] for e in cohort_eps}
            test_eps = [
                e
                for e in (episodes_by_split.get("test") or [])
                if e["outcome"] == outcome
                and e["unit"] == unit
                and str(e["medicine_id"]) == mid
            ]
            test_subj = {e["opaque_subject_key"] for e in test_eps}
            gates = {
                "accepted_drug_concept_mapping": True,
                "min_subjects": len(subjects) >= GATE_MIN_SUBJECTS,
                "min_episodes": len(cohort_eps) >= GATE_MIN_EPISODES,
                "subject_disjoint_split": bool(split_meta.get("zero_subject_overlap")),
                "min_test_subjects": len(test_subj) >= GATE_MIN_TEST_SUBJECTS,
                "no_unit_conflict": True,
                "no_unresolved_temporal_inversion": True,
                "no_identity_or_locator_overlap": bool(
                    split_meta.get("zero_subject_overlap")
                    and split_meta.get("zero_episode_overlap")
                    and split_meta.get("zero_locator_overlap")
                ),
            }
            failed = [k for k, v in gates.items() if not v]
            row = {
                "outcome": outcome,
                "unit": unit,
                "source_medicine_id": mid,
                "drug_concept_status": rec.get("drug_concept_status"),
                "n_subjects": len(subjects),
                "n_episodes": len(cohort_eps),
                "n_test_subjects": len(test_subj),
                "gates": gates,
                "block_reasons": failed,
                "timestamp_confidence": "LOW_TECHNICAL_ASSOCIATION_ONLY",
            }
            if not failed:
                ready.append(row)
            elif "accepted_drug_concept_mapping" not in failed and len(failed) <= 2:
                partial.append(row)
            else:
                blocked.append(row)

    if ready:
        status = "READY_COHORTS_PRESENT"
    elif partial:
        status = "PARTIAL_ONLY"
    else:
        status = "ZERO_READY"

    return {
        "version": VERSION,
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": status,
        "READY_COHORTS": ready,
        "PARTIAL_COHORTS": partial,
        "BLOCKED_COHORTS": blocked,
        "gates_predeclared_before_model_performance": True,
        "clinical_sufficiency_not_claimed": True,
        "n_accepted_concepts": len(accepted_ids),
    }


def episode_coverage_by_medicine(
    episodes: list[dict[str, Any]],
    episodes_by_split: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for e in episodes:
        mid = str(e["medicine_id"])
        slot = by.setdefault(
            mid,
            {
                "n_episodes": 0,
                "subjects": set(),
                "outcomes": set(),
                "splits": set(),
            },
        )
        slot["n_episodes"] += 1
        slot["subjects"].add(e["opaque_subject_key"])
        slot["outcomes"].add((e["outcome"], e["unit"]))
    for split, rows in episodes_by_split.items():
        for e in rows:
            mid = str(e["medicine_id"])
            if mid in by:
                by[mid]["splits"].add(split)
    out = {}
    for mid, slot in by.items():
        out[mid] = {
            "n_episodes": slot["n_episodes"],
            "n_subjects": len(slot["subjects"]),
            "n_outcomes": len(slot["outcomes"]),
            "splits": sorted(slot["splits"]),
        }
    return out
