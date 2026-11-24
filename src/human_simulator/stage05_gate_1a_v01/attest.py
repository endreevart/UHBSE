"""Turn frozen v0.2.2 answers into Gate 1A decision records. No new answers are invented."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v022.decisions import canonical_sha256
from human_simulator.stage05_gate_1a_v01.policy import (
    ADDRESSES,
    ANSWER_RECORD,
    MISMATCH,
    NO_DECISION,
    OWNER_DECISIONS,
    PARTIAL,
    QUESTION_BY_ID,
    QUESTIONS,
    REVIEWER_LABEL,
    REVIEWER_ROLE,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_NON_DECISION = {"DEFERRED_TO_CODE", "NOT_REMEMBERED", "NOT_KNOWN"}


def load_answers(root: Path) -> list[dict[str, Any]]:
    document = json.loads((Path(root) / ANSWER_RECORD).read_text(encoding="utf-8"))
    answers = document["answers"]
    if document.get("reviewer_role") != REVIEWER_ROLE or document.get("automatic_contact") is not False:
        raise ValueError("AnswerRecordRejected")
    return answers


def load_reviewer(root: Path) -> dict[str, str]:
    document = json.loads((Path(root) / OWNER_DECISIONS).read_text(encoding="utf-8"))
    responses = document["responses"]
    if not responses:
        raise ValueError("ReviewerMissing")
    role = responses[0]["role"]
    digest = responses[0]["reviewer_digest"]
    decided_at = responses[0]["decided_at"]
    if any(item["role"] != role or item["reviewer_digest"] != digest or item["decided_at"] != decided_at for item in responses):
        raise ValueError("ReviewerInconsistent")
    if role != REVIEWER_ROLE or digest != hashlib.sha256(REVIEWER_LABEL.encode("utf-8")).hexdigest():
        raise ValueError("ReviewerRejected")
    if not _HEX64.match(digest):
        raise ValueError("ReviewerDigestRejected")
    return {"role": role, "reviewer_digest": digest, "decided_at": decided_at}


def binding(answers: list[dict[str, Any]]) -> dict[str, Any]:
    checks = []
    for answer in answers:
        body = {key: value for key, value in answer.items() if key != "answer_sha256"}
        recomputed = canonical_sha256(body)
        checks.append({
            "answer_key": answer["answer_key"],
            "stored_sha256": answer.get("answer_sha256"),
            "recomputed_sha256": recomputed,
            "ok": answer.get("answer_sha256") == recomputed,
        })
    return {
        "ok": bool(checks) and all(item["ok"] for item in checks),
        "answers": checks,
    }


def _decision_text(spec: dict[str, Any], answer: dict[str, Any]) -> tuple[str, str]:
    applicability = spec["applicability"]
    certainty = answer["certainty"]
    stated = certainty == "STATED" and bool(answer.get("decision"))
    if applicability == MISMATCH:
        return "insufficient", spec["mismatch_decision"]
    if applicability == NO_DECISION or certainty in _NON_DECISION:
        return "insufficient", "NOT_ATTESTED"
    if certainty == "STATED_WITH_RECALL_UNCERTAINTY":
        return "insufficient", f"NOT_ACCEPTED_RECALL_UNCERTAIN:{answer.get('decision') or 'NO_DECISION'}"
    if applicability == PARTIAL:
        return "insufficient", spec["partial_decision"]
    if applicability == ADDRESSES and stated:
        return "accepted", str(answer["decision"])
    return "insufficient", "NOT_ATTESTED"


def build_records(answers: list[dict[str, Any]], reviewer: dict[str, str]) -> list[dict[str, Any]]:
    by_key = {answer["answer_key"]: answer for answer in answers}
    records = []
    for spec in QUESTIONS:
        answer = by_key[spec["answer_key"]]
        attestation, decision = _decision_text(spec, answer)
        records.append({
            "affects_feedback": spec["affects_feedback"],
            "affects_identity": spec["affects_identity"],
            "affects_intake": spec["affects_intake"],
            "attestation": attestation,
            "basis": (
                f"{ANSWER_RECORD}#{answer['answer_key']}; certainty={answer['certainty']}; "
                f"applicability={spec['applicability']}"
            ),
            "closes_question": attestation == "accepted",
            "decided_at": reviewer["decided_at"],
            "decision": decision,
            "decision_schema_version": "0.1",
            "evidence_applicability": spec["applicability"],
            "evidence_sha256": answer["answer_sha256"],
            "field_path": spec["field_path"],
            "proposition": spec["proposition"],
            "question_id": spec["question_id"],
            "reviewer_digest": reviewer["reviewer_digest"],
            "role": reviewer["role"],
            "source_system": spec["source_system"],
        })
    return records


def outside_gate(answers: list[dict[str, Any]]) -> list[dict[str, str]]:
    cited = {spec["answer_key"] for spec in QUESTIONS}
    return [
        {"answer_key": answer["answer_key"], "certainty": answer["certainty"], "field_path": answer["field_path"]}
        for answer in answers
        if answer["answer_key"] not in cited
    ]


def validate_record(record: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors = []
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
            if "pattern" in rule and re.search(rule["pattern"], value) is None:
                errors.append(f"pattern:{key}")
    return errors


def validate_records(records: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    per = [{"question_id": record.get("question_id"), "errors": validate_record(record, schema)} for record in records]
    ids = [record.get("question_id") for record in records]
    completeness = sorted(ids) == sorted(QUESTION_BY_ID)
    ok = bool(records) and completeness and all(not item["errors"] for item in per)
    return {
        "DECISION_SCHEMA_VALIDATION_STATUS": "PASS" if ok else "FAIL",
        "ok": ok,
        "checklist_complete": completeness,
        "record_count": len(records),
        "per_record": per,
    }
