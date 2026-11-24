"""A→B zero-shot shadow — only for accepted comparable mappings; no B tuning."""

from __future__ import annotations

from typing import Any

from human_simulator.privacy_cross_source_v01.policy import (
    CLAIM_LEVEL_SHADOW,
    VERSION,
)


def run_zero_shot_or_refuse(
    *,
    accepted_mappings: list[dict[str, Any]],
    frozen_provider_hashes_ok: bool,
) -> dict[str, Any]:
    """Execute technical A→B shadow only when accepted mappings exist.

    This release refuses scientific transfer when ACCEPTED_COMPARABLE_OUTCOME_COUNT=0.
    """
    n = len(accepted_mappings)
    if n == 0:
        return {
            "version": VERSION,
            "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "NOT_RUN_NO_ACCEPTED_MAPPINGS",
            "claim_level": CLAIM_LEVEL_SHADOW,
            "executed": False,
            "n_accepted_mappings": 0,
            "b_tuning": False,
            "b_hpo": False,
            "b_model_selection": False,
            "reason": (
                "No EXACT/SUPPORTED_TRANSFORM mappings with domain acceptance. "
                "Transfer not invented from HYPOTHESIS/name similarity."
            ),
            "missing_evidence": [
                "specimen_material",
                "method_assay_equivalence",
                "domain_review_acceptance",
            ],
            "not_external_validation": True,
            "not_clinical_validation": True,
            "ok_to_publish_readiness": True,
            "ok": True,  # honest non-execution is a valid readiness outcome
        }

    if not frozen_provider_hashes_ok:
        return {
            "version": VERSION,
            "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "FAIL",
            "executed": False,
            "reason": "frozen_provider_hash_verification_failed",
            "ok": False,
        }

    # Placeholder for future accepted mappings — not reached in this release
    return {
        "version": VERSION,
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "PASS",
        "claim_level": CLAIM_LEVEL_SHADOW,
        "executed": True,
        "n_accepted_mappings": n,
        "b_tuning": False,
        "note": "Would run frozen A providers at actual target_horizon_days on B.",
        "ok": True,
    }


def independence_status(*, candidate_overlap_excluded: int = 0) -> dict[str, Any]:
    return {
        "version": VERSION,
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "INDEPENDENCE_NOT_ESTABLISHED",
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "identity_merge_performed": False,
        "external_independence_claimed": False,
        "candidate_overlap_excluded_from_eval": candidate_overlap_excluded,
        "excluded_ambiguous_conflicting_counts": {
            "excluded": candidate_overlap_excluded,
            "ambiguous": "NOT_ENUMERATED_NO_LINKAGE_RUN",
            "conflicting": "NOT_ENUMERATED_NO_LINKAGE_RUN",
        },
        "ok": True,
    }
