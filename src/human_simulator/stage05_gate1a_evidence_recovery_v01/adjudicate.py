"""Decide whether a piece of evidence closes a Gate 1A question."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import (
    FORM_FIELDS,
    GATE_1B_BLOCKERS,
    SOURCE_A_OPEN,
)

_BLOCKED_APPLICABILITY = {
    "UNRELATED_FORM",
    "TEST_FIXTURE",
    "DEAD_CODE",
    "OTHER_SYSTEM",
    "NAMING_ONLY",
    "PRIOR_ARTIFACT",
    "ANALYSIS_CODE",
    "UNRELATED_REPOSITORY",
}
_SEMANTIC = set(FORM_FIELDS) | {"B_SHORT", "B_DRUGS", "B_VITAMINS", "B_CHANGE", "B_DECLINE", "B_POSITIVE"}


def closes(question_id: str, evidence: dict[str, Any]) -> bool:
    level = evidence.get("level")
    applicability = evidence.get("applicability")
    if applicability in _BLOCKED_APPLICABILITY or evidence.get("object") == "DoctorFeedback":
        return False
    if evidence.get("basis") in {"NUMERIC_KEY_AGREEMENT", "COLUMN_NAME", "TOKEN", "ROW_EXISTS", "FIXTURE"}:
        return False
    if evidence.get("auto_merged") or evidence.get("accepted_from_token"):
        return False
    if question_id == "A_RECOMMENDATION_ITEMS" and evidence.get("object") == "document_analysis.items":
        return False
    if question_id == "A_MEDICATION_CODE_SET" and evidence.get("sole_section_from_name"):
        return False
    if question_id == "A_DOCUMENT_FINAL" and evidence.get("basis") == "ROW_EXISTS":
        return False
    if question_id == "B_IDENTITY":
        return (
            level in {"E1", "E2", "E3", "E4"}
            and evidence.get("relation_contract") == "PROVEN_SINGLE_ENTITY"
            and evidence.get("basis") != "NUMERIC_KEY_AGREEMENT"
        )
    if question_id in _SEMANTIC or question_id in GATE_1B_BLOCKERS or question_id in SOURCE_A_OPEN:
        if level not in {"E2", "E3", "E4"}:
            return False
        if evidence.get("database_binding") is not True:
            return False
        if level == "E3" and evidence.get("database_binding") is not True:
            return False
        if level == "E1":
            return False
        return evidence.get("unambiguous_production") is True and applicability == "PRODUCTION"
    return False


def gate_outcome(closed: dict[str, bool]) -> dict[str, str]:
    blockers_closed = all(closed.get(question_id) is True for question_id in GATE_1B_BLOCKERS)
    if blockers_closed:
        return {
            "GATE_1A_STATUS": "SOURCE_B_ROUTE_ACCEPTED_SOURCE_A_OPEN",
            "GATE_1A_SOURCE_B_EXPOSURE_ROUTE_STATUS": "PASS",
            "GATE_1B_STATUS": "READY_FOR_EXPLICIT_OWNER_OPENING",
        }
    return {
        "GATE_1A_STATUS": "PARTIALLY_ATTESTED_OPEN",
        "GATE_1A_SOURCE_B_EXPOSURE_ROUTE_STATUS": "BLOCKED",
        "GATE_1B_STATUS": "BLOCKED",
    }
