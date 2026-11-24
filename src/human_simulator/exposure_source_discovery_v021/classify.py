"""Exclusive labels for one feedback row. Used by tests and negative controls."""

from __future__ import annotations

from typing import Any

from human_simulator.exposure_source_discovery_v021.policy import SUBJECT_CATEGORIES, TEMPORAL_CATEGORIES


def classify_temporal(row: dict[str, Any]) -> str:
    if row.get("consultation_id") is None:
        return "CONSULTATION_ID_NULL"
    if not row.get("target_found"):
        return "CONSULTATION_ID_PRESENT_TARGET_NOT_FOUND"
    if row.get("created_at_is_null") or row.get("consultation_date_is_null") or row.get("targets_disagree"):
        return "CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE"
    order = row.get("order")
    if order == "before":
        return "CONSULTATION_TARGET_FOUND_TIME_BEFORE"
    if order == "same":
        return "CONSULTATION_TARGET_FOUND_TIME_SAME_DAY"
    if order == "after":
        return "CONSULTATION_TARGET_FOUND_TIME_AFTER"
    return "CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE"


def classify_subject(row: dict[str, Any]) -> str:
    if row.get("consultation_id") is None or not row.get("target_found"):
        return "SUBJECT_COMPARISON_NOT_RUN_TARGET_MISSING"
    user_null = bool(row.get("user_id_is_null"))
    patient_null = bool(row.get("patient_id_is_null"))
    if user_null and patient_null:
        return "BOTH_SUBJECT_KEYS_NULL"
    if user_null:
        return "FEEDBACK_USER_ID_NULL"
    if patient_null or row.get("targets_disagree"):
        return "CONSULTATION_PATIENT_ID_NULL" if patient_null else "SUBJECT_KEYS_BOTH_PRESENT_UNEQUAL"
    if row.get("keys_equal"):
        return "SUBJECT_KEYS_BOTH_PRESENT_EQUAL"
    return "SUBJECT_KEYS_BOTH_PRESENT_UNEQUAL"


def tally(rows: list[dict[str, Any]], classifier) -> dict[str, Any]:
    labels = TEMPORAL_CATEGORIES if classifier is classify_temporal else SUBJECT_CATEGORIES
    counts = {label: 0 for label in labels}
    overlap = 0
    for row in rows:
        label = classifier(row)
        if label not in counts:
            overlap += 1
            continue
        counts[label] += 1
    total = len(rows)
    covered = sum(counts.values())
    return {
        "counts": counts,
        "total": total,
        "overlap_count": overlap,
        "unclassified_count": total - covered,
        "sum_categories": covered,
    }


def completed_chain(row: dict[str, Any]) -> bool:
    """A completed candidate chain needs a found target, comparable dates, and a prior other consultation."""
    temporal = classify_temporal(row)
    return (
        temporal in {
            "CONSULTATION_TARGET_FOUND_TIME_BEFORE",
            "CONSULTATION_TARGET_FOUND_TIME_SAME_DAY",
        }
        and bool(row.get("prior_other_consultation"))
        and not bool(row.get("same_consultation_only"))
    )


def subject_equality_denominator(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if classify_subject(row) in {
            "SUBJECT_KEYS_BOTH_PRESENT_EQUAL",
            "SUBJECT_KEYS_BOTH_PRESENT_UNEQUAL",
        }
    )


def ledger_closes(counts: dict[str, int], total: int, labels: tuple[str, ...]) -> bool:
    return sum(counts[label] for label in labels) == total and set(counts) >= set(labels)
