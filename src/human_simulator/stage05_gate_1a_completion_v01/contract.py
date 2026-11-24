"""Statuses after the scope records. Gate 1B stays blocked while the critical questions are open."""

from __future__ import annotations

import re
from typing import Any

from human_simulator.stage05_gate_1a_completion_v01.policy import (
    DECIDED_AT,
    EXPOSURE_DEFERRED,
    GATE_1B_BLOCKERS,
    PRIOR_RECORDS,
    SCIENTIFIC_CEILING,
    SCOPE,
    SCOPED_QUESTIONS,
    SOURCE_A_OPEN,
    SUPERSEDING_SCHEMA,
)
from human_simulator.stage05_gate_1a_completion_v01.prior import record_sha256

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def validate_record(record: dict[str, Any]) -> list[str]:
    schema = SUPERSEDING_SCHEMA
    errors: list[str] = []
    props = schema["properties"]
    for key in schema["required"]:
        if key not in record:
            errors.append(f"missing:{key}")
    if schema.get("additionalProperties") is False:
        errors.extend(f"extra:{key}" for key in record if key not in props)
    for key, value in record.items():
        rule = props.get(key)
        if rule is None:
            continue
        if "const" in rule and value != rule["const"]:
            errors.append(f"const:{key}")
        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"enum:{key}")
        if rule.get("type") == "boolean" and not isinstance(value, bool):
            errors.append(f"type:{key}")
        if rule.get("type") == "string":
            if not isinstance(value, str):
                errors.append(f"type:{key}")
                continue
            if len(value) < rule.get("minLength", 0):
                errors.append(f"minLength:{key}")
            if "pattern" in rule and _HEX64.match(value) is None and key.endswith("sha256"):
                errors.append(f"pattern:{key}")
            elif "pattern" in rule and re.search(rule["pattern"], value) is None:
                errors.append(f"pattern:{key}")
    if record.get("question_id") == "B_PERIOD" and record.get("requires_first_vs_repeat_visit_classification") is not True:
        errors.append("period_classification_required")
    if record.get("question_id") == "B_TIMING" and record.get("requires_first_vs_repeat_visit_classification") is not False:
        errors.append("timing_classification_not_applicable")
    return errors


def derive(prior: dict[str, Any], superseding: list[dict[str, Any]], recovery: dict[str, Any]) -> dict[str, Any]:
    blocked = [
        question_id
        for question_id in GATE_1B_BLOCKERS
        if prior["by_id"][question_id]["attestation"] != "accepted"
    ]
    return {
        "GATE_1A_STATUS": "PARTIALLY_ATTESTED_OPEN",
        "GATE_1B_STATUS": "BLOCKED" if blocked else "NOT_BLOCKED_BY_THESE_QUESTIONS",
        "GATE_1B_BLOCKERS": list(GATE_1B_BLOCKERS),
        "GATE_1B_BLOCKERS_STILL_OPEN": blocked,
        "EXPOSURE_EXTRACTOR_DEFERRED_QUESTIONS": list(EXPOSURE_DEFERRED),
        "SOURCE_A_OPEN_QUESTIONS": list(SOURCE_A_OPEN),
        "B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT": 0,
        "VISIT_CLASSIFICATION_STATUS": "NOT_PERFORMED",
        "SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS": recovery["SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS"],
        "SUPERSEDING_RECORD_COUNT": len(superseding),
        "PRIOR_DECISION_RECORDS_REWRITTEN": False,
        **SCIENTIFIC_CEILING,
    }


def violations(
    status: dict[str, Any],
    prior: dict[str, Any],
    superseding: list[dict[str, Any]],
    answers_ok: bool,
    recovery: dict[str, Any],
) -> list[str]:
    found: list[str] = []
    expected = derive(prior, superseding, recovery)
    for key, value in expected.items():
        if status.get(key) != value:
            found.append(f"status:{key}")
    if recovery.get("superseding_records_created_from_code") not in {0}:
        found.append("code_recovery_created_a_decision")
    if not answers_ok:
        found.append("answer_binding")
    if prior["duplicate_question_ids"] or prior["reviewer_digest_count"] != 1 or prior["role_count"] != 1:
        found.append("prior_review_check")
    if prior["closed_insufficient"]:
        found.append("prior_insufficient_closed")
    ids = [record.get("question_id") for record in superseding]
    if ids != list(SCOPED_QUESTIONS):
        found.append("superseding_questions")
    for record in superseding:
        previous = prior["scoped"].get(record.get("question_id"))
        if previous is None:
            found.append("missing_prior")
            continue
        if validate_record(record):
            found.append(f"schema:{record.get('question_id')}")
        if record.get("decision") != previous["decision"]:
            found.append(f"decision_changed:{record.get('question_id')}")
        if record.get("evidence_sha256") != previous["evidence_sha256"]:
            found.append(f"evidence_changed:{record.get('question_id')}")
        if record.get("prior_record_sha256") != record_sha256(previous):
            found.append(f"prior_hash:{record.get('question_id')}")
        if record.get("attestation_scope") == SCOPE and record.get("closes_question") is not False:
            found.append(f"workflow_closed_as_row_proof:{record.get('question_id')}")
        if record.get("row_level_proof") is not False:
            found.append(f"row_level_proof:{record.get('question_id')}")
        if record.get("supersedes_artifact") != PRIOR_RECORDS:
            found.append("supersedes_path")
        if record.get("decided_at") != DECIDED_AT:
            found.append("decided_at")
    if status.get("GATE_1B_STATUS") != "BLOCKED":
        found.append("gate_1b_opened")
    if status.get("B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT") not in {0}:
        found.append("period_rows_assigned_without_visit_class")
    for key, value in SCIENTIFIC_CEILING.items():
        if status.get(key) != value:
            found.append(f"ceiling:{key}")
    return found
