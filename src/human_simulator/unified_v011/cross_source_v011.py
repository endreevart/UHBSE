"""Cross-source linkage correction + gated transfer exploration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_v011.policy import (
    CROSS_SOURCE_NOT_RUN_GATE,
    CROSS_SOURCE_TRANSFER_NAME,
    FIXED_OUTCOME_CANDIDATE_ID,
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    INDEPENDENCE_NOT_ESTABLISHED,
    NO_DETECTED_OVERLAP_AFTER_EXCLUSION,
    OUTCOME_NOT_COMPARABLE,
)


def load_stage02_linkage(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "artifacts" / "stage-02" / "identity-linkage-assessment.json"
    if not path.is_file():
        return {"missing": True}
    return json.loads(path.read_text(encoding="utf-8"))


def corrected_linkage_readiness(repo_root: Path) -> dict[str, Any]:
    doc = load_stage02_linkage(repo_root)
    overlap = doc.get("overlap_aggregates") or {}
    verdict_obj = doc.get("identity_verdict") or {}
    verdict = (
        verdict_obj.get("verdict") if isinstance(verdict_obj, dict) else verdict_obj
    )

    dual = int(overlap.get("consistent_subject_pairs_by_phone_and_email") or 0)
    ambiguous = int(overlap.get("ambiguous_subject_pairs") or 0)
    conflicting = int(overlap.get("cross_field_conflicts") or 0)
    # Single-identifier collisions — prefer explicit fields; fall back to aggregate sum
    single = int(overlap.get("matched_unique_email_identifiers") or 0) + int(
        overlap.get("matched_unique_phone_identifiers") or 0
    )

    uniquely_resolved = 0  # never elevate dual-consistent to confirmed without FP control
    return {
        "linkage_inputs_available": not doc.get("missing", False),
        "single_identifier_collision_count": single,
        "dual_identifier_consistent_candidate_count": dual,
        "ambiguous_candidate_count": ambiguous,
        "cross_identifier_conflict_count": conflicting,
        "uniquely_resolved_pair_count": uniquely_resolved,
        "false_positive_control": "absent",
        "identity_status": "CANDIDATE_ONLY",
        "stage02_identity_verdict": verdict,
        "identity_merge_performed": False,
        "notes": [
            "dual_identifier_consistent candidates are NOT confirmed subjects.",
            "unique pair resolution and false-positive control are required for confirmation.",
        ],
    }


def conservative_overlap_exclusion(linkage: dict[str, Any]) -> dict[str, Any]:
    excluded = (
        int(linkage.get("single_identifier_collision_count") or 0)
        + int(linkage.get("dual_identifier_consistent_candidate_count") or 0)
        + int(linkage.get("ambiguous_candidate_count") or 0)
        + int(linkage.get("cross_identifier_conflict_count") or 0)
    )
    return {
        "cross_source_overlap_control_status": NO_DETECTED_OVERLAP_AFTER_EXCLUSION,
        "excluded_candidate_count_aggregate": excluded,
        "evaluation_subset": "Source B subjects after excluding all detected overlap candidates",
        "proves_absence_of_all_overlap": False,
        "identity_merge": False,
    }


def label_only_match_rejected(
    *, label_a: str, label_b: str, unit_a: str, unit_b: str, verified_conversion: bool
) -> dict[str, Any]:
    same_label = (label_a or "").strip().lower() == (label_b or "").strip().lower()
    units_ok = (unit_a == unit_b) or verified_conversion
    if same_label and not units_ok:
        return {
            "accepted": False,
            "reason": "label_match_without_verified_unit_compatibility",
        }
    if same_label and units_ok and not verified_conversion and unit_a != unit_b:
        return {"accepted": False, "reason": "unverified_unit_conversion"}
    if same_label and unit_a == unit_b:
        return {
            "accepted": False,
            "reason": "label_only_insufficient_without_biological_equivalence_evidence",
            "note": "Identical name alone is not enough for comparability",
        }
    return {"accepted": False, "reason": "no_semantic_equivalent_established"}


def build_outcome_intersection(
    *,
    source_b_observation_accepted: bool,
    source_b_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_b_catalog = source_b_catalog or {}
    fixed = {
        "candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "label": FIXED_OUTCOME_LABEL,
        "unit": FIXED_OUTCOME_UNIT,
    }
    if not source_b_observation_accepted:
        return {
            "status": OUTCOME_NOT_COMPARABLE,
            "fixed_source_a_outcome": fixed,
            "source_b_equivalent": None,
            "reason": "Source B Observation mapping not accepted",
            "label_only_rejected": label_only_match_rejected(
                label_a=FIXED_OUTCOME_LABEL,
                label_b=FIXED_OUTCOME_LABEL,
                unit_a=FIXED_OUTCOME_UNIT,
                unit_b=FIXED_OUTCOME_UNIT,
                verified_conversion=False,
            ),
        }
    # Even with Observation accepted, require verified semantic equivalent
    return {
        "status": OUTCOME_NOT_COMPARABLE,
        "fixed_source_a_outcome": fixed,
        "source_b_equivalent": source_b_catalog.get("fixed_outcome_match"),
        "reason": "Semantic equivalent for Т3 св. / пмоль/л not proven in Source B",
        "label_only_rejected": label_only_match_rejected(
            label_a=FIXED_OUTCOME_LABEL,
            label_b=str((source_b_catalog.get("fixed_outcome_match") or {}).get("label") or ""),
            unit_a=FIXED_OUTCOME_UNIT,
            unit_b=str((source_b_catalog.get("fixed_outcome_match") or {}).get("unit") or ""),
            verified_conversion=False,
        ),
    }


def assess_comparability(
    *,
    observation_accepted: bool,
    intersection: dict[str, Any],
    overlap_control: dict[str, Any],
    sufficient_b_pairs: bool,
) -> dict[str, Any]:
    gates = {
        "source_b_observation_mapping_accepted": observation_accepted,
        "fixed_outcome_comparable": intersection.get("status") != OUTCOME_NOT_COMPARABLE,
        "units_compatible": False,  # not established without equivalent
        "timestamps_compatible": False,
        "sufficient_b_repeated_pairs": sufficient_b_pairs,
        "conservative_overlap_exclusion_completed": overlap_control.get(
            "cross_source_overlap_control_status"
        )
        == NO_DETECTED_OVERLAP_AFTER_EXCLUSION,
    }
    failed = [k for k, v in gates.items() if not v]
    if failed:
        status = OUTCOME_NOT_COMPARABLE if not gates["fixed_outcome_comparable"] else "FAIL"
    else:
        status = "PASS"
    return {
        "status": status,
        "gates": gates,
        "failed_gates": failed,
        "cross_source_outcome_comparability_status": status,
        "independence_status": INDEPENDENCE_NOT_ESTABLISHED,
        "external_clinical_validation": False,
    }


def run_transfer_or_skip(*, comparability: dict[str, Any]) -> dict[str, Any]:
    if comparability.get("status") != "PASS" or comparability.get("failed_gates"):
        return {
            "name": CROSS_SOURCE_TRANSFER_NAME,
            "executed": False,
            "status": CROSS_SOURCE_NOT_RUN_GATE,
            "failed_gates": comparability.get("failed_gates"),
            "external_clinical_validation": False,
            "clinical_validation_status": "NOT_STARTED",
            "note": "Transfer test not run; gates failed",
        }
    # Gates pass path reserved — still never claim clinical validation
    return {
        "name": CROSS_SOURCE_TRANSFER_NAME,
        "executed": True,
        "status": "EXPLORATORY",
        "external_clinical_validation": False,
        "clinical_validation_status": "NOT_STARTED",
        "b_tuning_forbidden": True,
        "note": "Frozen A model evaluated once on B; not clinical validation",
    }


def build_source_b_outcome_catalog(*, observation_accepted: bool) -> dict[str, Any]:
    if not observation_accepted:
        return {
            "status": "EMPTY",
            "outcomes": 0,
            "subjects": 0,
            "subjects_with_repeats": 0,
            "strict_consecutive_pairs": 0,
            "reason": "Outcome catalog requires accepted clinical Observations",
            "mapping_confidence": "HYPOTHESIS",
            "domain_review_status": "REQUIRED",
        }
    return {
        "status": "PASS",
        "outcomes": 0,
        "subjects": 0,
        "subjects_with_repeats": 0,
        "strict_consecutive_pairs": 0,
        "note": "Observation accepted but catalog builder not populated in this run",
        "domain_review_status": "REQUIRED",
    }
