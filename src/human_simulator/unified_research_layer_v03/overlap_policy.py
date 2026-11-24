"""Cross-source overlap policy — no automatic identity merge."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_research_layer_v03.policy import (
    PIN_SOURCE_A_SUBJECTS,
    PIN_SOURCE_B_SUBJECTS,
    VERSION,
)


def build_overlap_policy(canonical: dict[str, Any]) -> dict[str, Any]:
    n_a = int(canonical.get("source_a_subjects") or 0)
    n_b = int(canonical.get("source_b_subjects") or 0)
    collisions = int(canonical.get("cross_source_subject_key_collisions") or 0)
    return {
        "version": VERSION,
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "CROSS_SOURCE_OVERLAP_POLICY_STATUS": "PASS",
        "automatic_identity_merge": False,
        "source_scoped_population_count": {
            "source_a": n_a,
            "source_b": n_b,
            "sum_source_scoped": n_a + n_b,
        },
        "confirmed_unique_people_count": None,
        "confirmed_unique_people_provable": False,
        "unresolved_overlap_count": "UNKNOWN_NO_LINKAGE_EVIDENCE",
        "confirmed_overlap_groups": 0,
        "ambiguous_overlap_groups": 0,
        "conflicting_overlap_groups": collisions,
        "unresolved_overlap_groups": "ALL_UNLINKED",
        "conservative_usable_population_count": {
            "note": (
                "Until overlap is resolved, conservative evaluation must treat "
                "A and B as potentially overlapping populations and avoid "
                "claiming A+B unique patients."
            ),
            "source_a_only_usable": n_a,
            "source_b_only_usable": n_b,
            "cross_source_pooled_unique_not_claimed": True,
        },
        "split_policy": {
            "possible_a_b_duplicates_must_not_span_train_and_heldout": True,
            "ambiguous_overlap_may_be_excluded_from_cross_source_eval": True,
            "must_not_claim_unique_patients": True,
        },
        "linkage_keys_published": False,
        "row_derived_fingerprints_published": False,
        "pins_match_live": n_a == PIN_SOURCE_A_SUBJECTS and n_b == PIN_SOURCE_B_SUBJECTS,
        "ok": True,
    }
