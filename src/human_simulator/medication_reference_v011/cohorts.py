"""Concept-specific readiness and conditional association baseline (v0.1.1)."""

from __future__ import annotations

from typing import Any

from human_simulator.medication_reference_v01 import cohorts as v01_cohorts
from human_simulator.medication_reference_v011.policy import (
    ACCEPTED_STATUSES,
    VERSION,
)


def build_concept_cohort_readiness(
    *,
    episodes_by_split: dict[str, list[dict[str, Any]]],
    mapped: list[dict[str, Any]],
    split_meta: dict[str, Any],
) -> dict[str, Any]:
    doc = v01_cohorts.build_concept_cohort_readiness(
        episodes_by_split=episodes_by_split,
        mapped=mapped,
        split_meta=split_meta,
    )
    doc["version"] = VERSION
    doc["grain"] = "accepted_drug_concept × outcome × unit"
    doc["no_broad_class_merge"] = True
    doc["engineering_readiness_only"] = True
    return doc


def coverage_summary(mapped: list[dict[str, Any]], total_episodes: int) -> dict[str, Any]:
    accepted = [m for m in mapped if m.get("drug_concept_status") in ACCEPTED_STATUSES]
    unresolved = [m for m in mapped if m.get("drug_concept_status") not in ACCEPTED_STATUSES]
    acc_eps = sum(int((m.get("episode_coverage") or {}).get("n_episodes") or 0) for m in accepted)
    # subject coverage as sum of n_subjects is an upper-bound aggregate (medicines overlap)
    acc_subj_sum = sum(
        int((m.get("episode_coverage") or {}).get("n_subjects") or 0) for m in accepted
    )
    top_unresolved = sorted(
        unresolved,
        key=lambda m: -int((m.get("episode_coverage") or {}).get("n_episodes") or 0),
    )[:20]
    return {
        "accepted_medication_records": len(accepted),
        "unresolved_medication_records": len(unresolved),
        "accepted_episode_coverage": acc_eps,
        "accepted_subject_coverage_sum_over_medicines": acc_subj_sum,
        "total_episodes": total_episodes,
        "accepted_episode_fraction": (acc_eps / total_episodes) if total_episodes else 0.0,
        "ingredient_coverage_among_accepted": sum(
            1 for m in accepted if m.get("ingredients") or m.get("inn")
        ),
        "product_coverage_among_accepted": sum(
            1 for m in accepted if m.get("product_name") or m.get("provider_concept_id")
        ),
        "strength_coverage_among_accepted": sum(1 for m in accepted if m.get("strength")),
        "form_coverage_among_accepted": sum(1 for m in accepted if m.get("form")),
        "top_unresolved_by_lost_episode_coverage": [
            {
                "source_medicine_id": m["source_medicine_id"],
                "status": m["drug_concept_status"],
                "n_episodes": (m.get("episode_coverage") or {}).get("n_episodes"),
                "n_subjects": (m.get("episode_coverage") or {}).get("n_subjects"),
            }
            for m in top_unresolved
        ],
    }


def run_conditional_association_baseline(
    *,
    readiness: dict[str, Any],
    episodes_by_split: dict[str, list[dict[str, Any]]],
    mapped: list[dict[str, Any]],
) -> dict[str, Any]:
    ready = readiness.get("READY_COHORTS") or []
    if not ready:
        blocked = readiness.get("BLOCKED_COHORTS") or []
        return {
            "FIRST_CONCEPT_SPECIFIC_ASSOCIATION_BASELINE_STATUS": (
                "NOT_RUN_DUE_TO_FAILED_READINESS_GATE"
            ),
            "name": "FIRST_CONCEPT_SPECIFIC_MEDICATION_ASSOCIATION_BASELINE",
            "not_intervention_response": True,
            "not_treatment_effect": True,
            "not_causal": True,
            "blockers_sample": [
                {
                    "outcome": b.get("outcome"),
                    "n_subjects": b.get("n_subjects"),
                    "n_episodes": b.get("n_episodes"),
                    "block_reasons": b.get("block_reasons"),
                }
                for b in blocked[:10]
            ],
        }
    # Delegate to v0.1 implementation when ready cohorts exist
    return v01_cohorts.run_conditional_association_baseline(
        readiness=readiness,
        episodes_by_split=episodes_by_split,
        mapped=mapped,
    )
