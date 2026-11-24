"""Cross-source T3 comparability, overlap exclusion, gated transfer exploration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_v012.policy import (
    CROSS_SOURCE_NOT_RUN_GATE,
    CROSS_SOURCE_TRANSFER_NAME,
    DOMAIN_REVIEW_REQUIRED,
    FIXED_OUTCOME_CANDIDATE_ID,
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    INDEPENDENCE_NOT_ESTABLISHED,
    NO_DETECTED_OVERLAP_AFTER_EXCLUSION,
    OUTCOME_COMPARABLE,
    OUTCOME_COMPARABLE_WITH_LIMITATIONS,
    OUTCOME_NOT_COMPARABLE,
)


def label_only_match_rejected(
    *,
    label_a: str,
    label_b: str,
    unit_a: str,
    unit_b: str,
    verified_conversion: bool,
    biological_equivalence_evidence: bool = False,
) -> dict[str, Any]:
    same_label = (label_a or "").strip().lower() == (label_b or "").strip().lower()
    if same_label and not biological_equivalence_evidence:
        return {
            "accepted": False,
            "reason": "label_only_insufficient_without_biological_equivalence_evidence",
            "note": "Identical name alone is not enough for T3 comparability",
        }
    if same_label and unit_a != unit_b and not verified_conversion:
        return {"accepted": False, "reason": "unverified_unit_conversion"}
    return {"accepted": False, "reason": "no_semantic_equivalent_established"}


def assess_t3_comparability(
    *,
    observation_accepted: bool,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = catalog or {}
    fixed = {
        "candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "label": FIXED_OUTCOME_LABEL,
        "unit": FIXED_OUTCOME_UNIT,
    }
    candidates = list(catalog.get("fixed_t3_label_candidates") or [])
    # Prefer Source B analyses_catalog aggregate search when present
    source_catalog = list(catalog.get("source_b_catalog_t3_candidates") or [])
    if source_catalog:
        candidates = source_catalog

    label_check = label_only_match_rejected(
        label_a=FIXED_OUTCOME_LABEL,
        label_b=(candidates[0].get("sanitised_label") or "") if candidates else "",
        unit_a=FIXED_OUTCOME_UNIT,
        unit_b=(candidates[0].get("unit") or "") if candidates else "",
        verified_conversion=False,
        biological_equivalence_evidence=False,
    )
    if not observation_accepted:
        return {
            "status": OUTCOME_NOT_COMPARABLE,
            "cross_source_outcome_comparability_status": OUTCOME_NOT_COMPARABLE,
            "fixed_source_a_outcome": fixed,
            "source_b_candidates": candidates,
            "selection_rule": "deterministic_label_unit_biology — no predictive performance selection",
            "label_only_rejected": label_check,
            "reason": "Source B Observation mapping not accepted",
        }
    if not candidates:
        return {
            "status": OUTCOME_NOT_COMPARABLE,
            "cross_source_outcome_comparability_status": OUTCOME_NOT_COMPARABLE,
            "fixed_source_a_outcome": fixed,
            "source_b_candidates": [],
            "label_only_rejected": label_check,
            "reason": "No Source B catalog candidates for free T3 / Т3 св.",
        }

    # Deterministic selection: free-T3 analyte preference; reject unverified unit conversion
    free_t3 = [
        c
        for c in candidates
        if "свободн" in (c.get("sanitised_label") or "").lower()
        or "ft3" in (c.get("sanitised_label") or "").lower()
        or "free" in (c.get("sanitised_label") or "").lower()
    ]
    selected = free_t3[0] if free_t3 else candidates[0]
    unit_b = (selected.get("unit") or "").strip()
    unit_compatible = unit_b == FIXED_OUTCOME_UNIT
    if not unit_compatible:
        return {
            "status": OUTCOME_NOT_COMPARABLE,
            "cross_source_outcome_comparability_status": OUTCOME_NOT_COMPARABLE,
            "fixed_source_a_outcome": fixed,
            "source_b_candidates": candidates,
            "selected_candidate": selected,
            "selection_rule": (
                "prefer free-T3 label; require identical unit string; "
                "no unverified conversion; no predictive-performance selection"
            ),
            "label_only_rejected": label_check,
            "unit_compatible": False,
            "reason": (
                f"Source A unit {FIXED_OUTCOME_UNIT!r} incompatible with Source B unit "
                f"{unit_b!r}; unverified conversion forbidden"
            ),
        }

    return {
        "status": DOMAIN_REVIEW_REQUIRED,
        "cross_source_outcome_comparability_status": DOMAIN_REVIEW_REQUIRED,
        "fixed_source_a_outcome": fixed,
        "source_b_candidates": candidates,
        "selected_candidate": selected,
        "selection_rule": "list all candidates; prefer free-T3; unit match only",
        "label_only_rejected": label_check,
        "unit_compatible": True,
        "reason": (
            "Unit matches but biological equivalence / specimen context still require "
            "domain review before transfer"
        ),
        "would_be_comparable_statuses": [
            OUTCOME_COMPARABLE,
            OUTCOME_COMPARABLE_WITH_LIMITATIONS,
        ],
    }


def load_stage02_linkage(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "artifacts" / "stage-02" / "identity-linkage-assessment.json"
    if not path.is_file():
        return {"missing": True}
    return json.loads(path.read_text(encoding="utf-8"))


def conservative_overlap_exclusion(repo_root: Path) -> dict[str, Any]:
    doc = load_stage02_linkage(repo_root)
    overlap = doc.get("overlap_aggregates") or {}
    single = int(overlap.get("matched_unique_email_identifiers") or 0) + int(
        overlap.get("matched_unique_phone_identifiers") or 0
    )
    dual = int(overlap.get("consistent_subject_pairs_by_phone_and_email") or 0)
    ambiguous = int(overlap.get("ambiguous_subject_pairs") or 0)
    conflicting = int(overlap.get("cross_field_conflicts") or 0)
    excluded = single + dual + ambiguous + conflicting
    return {
        "cross_source_overlap_control_status": NO_DETECTED_OVERLAP_AFTER_EXCLUSION,
        "identity_linkage_status": "CANDIDATE_ONLY",
        "uniquely_resolved_pair_count": 0,
        "identity_merge": False,
        "excluded_candidate_count_aggregate": excluded,
        "single_identifier_collision_count": single,
        "dual_identifier_consistent_candidate_count": dual,
        "ambiguous_candidate_count": ambiguous,
        "cross_identifier_conflict_count": conflicting,
        "proves_absence_of_all_overlap": False,
        "independence_status": INDEPENDENCE_NOT_ESTABLISHED,
        "evaluation_subset": (
            "Source B subjects after excluding all detected overlap candidates"
        ),
    }


def run_transfer_or_skip(
    *,
    observation_accepted: bool,
    comparability: dict[str, Any],
    overlap: dict[str, Any],
    sufficient_b_pairs: bool = False,
) -> dict[str, Any]:
    gates = {
        "source_b_observation_mapping_accepted": observation_accepted,
        "t3_outcome_comparable": comparability.get("status")
        in (OUTCOME_COMPARABLE, OUTCOME_COMPARABLE_WITH_LIMITATIONS),
        "overlap_exclusion_complete": overlap.get("cross_source_overlap_control_status")
        == NO_DETECTED_OVERLAP_AFTER_EXCLUSION,
        "sufficient_b_pairs": sufficient_b_pairs,
    }
    if not all(gates.values()):
        return {
            "name": CROSS_SOURCE_TRANSFER_NAME,
            "executed": False,
            "status": CROSS_SOURCE_NOT_RUN_GATE,
            "cross_source_transfer_status": CROSS_SOURCE_NOT_RUN_GATE,
            "gates": gates,
            "failed_gates": [k for k, v in gates.items() if not v],
            "external_clinical_validation": False,
            "clinical_validation": False,
            "treatment_effect_validation": False,
            "intervention_response_validation": False,
            "production_validation": False,
            "b_cannot_tune_a": True,
        }
    # Gates passed — transfer not implemented as clinical claim in v0.1.2 without
    # proven T3 equivalence; still skip with explicit note if we somehow get here.
    return {
        "name": CROSS_SOURCE_TRANSFER_NAME,
        "executed": False,
        "status": CROSS_SOURCE_NOT_RUN_GATE,
        "cross_source_transfer_status": CROSS_SOURCE_NOT_RUN_GATE,
        "gates": gates,
        "reason": "T3 biological equivalence still not proven despite gate scaffolding",
        "external_clinical_validation": False,
        "b_cannot_tune_a": True,
    }
