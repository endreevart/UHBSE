"""Strict source-medication accounting with linkage vs drug-concept separation."""

from __future__ import annotations

from collections import Counter
from typing import Any

from human_simulator.medication_concept_v01.policy import (
    EXPECTED_MEDICINE_IDS,
    SOURCE_A,
    VERSION,
)


def compute_source_accounting(
    medicine_ids: list[Any],
    *,
    joined_ids: set[Any] | None = None,
    expected: int = EXPECTED_MEDICINE_IDS,
) -> dict[str, Any]:
    """Recompute accounting — never hard-code PASS.

    SOURCE_RECORD_LINKAGE_STATUS is independent of DRUG_CONCEPT_MAPPING_STATUS.
    Exact join ≠ accepted drug-concept harmonization.
    """
    # Preserve order for reporting; detect duplicates via Counter
    counts = Counter(str(m) for m in medicine_ids)
    unique_ids = sorted(counts.keys(), key=lambda x: (len(x), x))
    duplicate_source_ids = sum(1 for _id, n in counts.items() if n > 1)
    total = len(unique_ids)

    joined = joined_ids if joined_ids is not None else set(unique_ids)
    joined_s = {str(x) for x in joined}
    exact_join = sum(1 for mid in unique_ids if mid in joined_s)
    missing_join = total - exact_join

    # Without provider-accepted concepts, all remain candidate/unknown at concept layer
    # (concept registry fills real statuses separately; this baseline split is structural)
    drug_concept_exact = 0
    drug_concept_supported = 0
    drug_concept_candidate_or_unknown = total  # until concept registry updates

    accounted = exact_join + missing_join  # every unique id classified for linkage
    unaccounted = total - accounted

    linkage_pass = (
        exact_join == total
        and missing_join == 0
        and total == expected
        and duplicate_source_ids == 0
        and unaccounted == 0
        and accounted == total
    )

    accounting_pass = (
        total == expected
        and accounted == total
        and unaccounted == 0
        and duplicate_source_ids == 0
    )

    return {
        "version": VERSION,
        "source_system": SOURCE_A,
        "expected_source_medicines": expected,
        "total_source_medicines": total,
        "duplicate_source_ids": duplicate_source_ids,
        "accounted": accounted,
        "unaccounted": unaccounted,
        "SOURCE_RECORD_LINKAGE_STATUS": "PASS" if linkage_pass else "FAIL",
        "SOURCE_RECORD_EXACT_JOIN": exact_join,
        "SOURCE_RECORD_MISSING_JOIN": missing_join,
        "DRUG_CONCEPT_MAPPING_STATUS": "UNRESOLVED_PENDING_PROVIDER",
        "DRUG_CONCEPT_EXACT": drug_concept_exact,
        "DRUG_CONCEPT_SUPPORTED_TRANSFORM": drug_concept_supported,
        "DRUG_CONCEPT_CANDIDATE_OR_UNKNOWN": drug_concept_candidate_or_unknown,
        "MEDICATION_SOURCE_ACCOUNTING_STATUS": "PASS" if accounting_pass else "FAIL",
        "matches_expected": total == expected,
        "note": (
            "SOURCE_RECORD_EXACT_JOIN is source-table join only; "
            "it is not accepted drug-concept harmonization"
        ),
    }


def apply_concept_counts_to_accounting(
    accounting: dict[str, Any],
    *,
    by_concept_status: dict[str, int],
) -> dict[str, Any]:
    """Update drug-concept fields from concept registry counts."""
    exact = int(by_concept_status.get("EXACT", 0))
    supported = int(by_concept_status.get("SUPPORTED_TRANSFORM", 0))
    candidate = int(by_concept_status.get("CANDIDATE", 0))
    ambiguous = int(by_concept_status.get("AMBIGUOUS", 0))
    no_match = int(by_concept_status.get("NO_MATCH", 0))
    conflict = int(by_concept_status.get("CONFLICT", 0))
    unresolved = candidate + ambiguous + no_match + conflict
    accepted = exact + supported
    total = int(accounting["total_source_medicines"])
    out = dict(accounting)
    out["DRUG_CONCEPT_EXACT"] = exact
    out["DRUG_CONCEPT_SUPPORTED_TRANSFORM"] = supported
    out["DRUG_CONCEPT_CANDIDATE_OR_UNKNOWN"] = unresolved
    out["DRUG_CONCEPT_ACCEPTED_COUNT"] = accepted
    out["DRUG_CONCEPT_UNRESOLVED_COUNT"] = unresolved
    out["by_drug_concept_status"] = {
        "EXACT": exact,
        "SUPPORTED_TRANSFORM": supported,
        "CANDIDATE": candidate,
        "AMBIGUOUS": ambiguous,
        "NO_MATCH": no_match,
        "CONFLICT": conflict,
    }
    concept_accounted = exact + supported + unresolved
    out["drug_concept_unaccounted"] = total - concept_accounted
    if accepted > 0 and out["drug_concept_unaccounted"] == 0:
        out["DRUG_CONCEPT_MAPPING_STATUS"] = "PARTIAL" if unresolved else "COMPLETE"
    elif out["drug_concept_unaccounted"] == 0 and accepted == 0:
        out["DRUG_CONCEPT_MAPPING_STATUS"] = "NO_ACCEPTED_MAPPINGS"
    else:
        out["DRUG_CONCEPT_MAPPING_STATUS"] = "INCOMPLETE"
    return out
