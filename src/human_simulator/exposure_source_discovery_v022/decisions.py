"""Build owner decisions from recorded answers and validate them against the v0.2 decision schema."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from human_simulator.exposure_source_discovery_v022.policy import (
    ANSWER_CHANNEL,
    DECIDED_AT,
    DECIDING_CERTAINTIES,
    REVIEWER_LABEL,
    REVIEWER_ROLE,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def canonical_sha256(obj: Any) -> str:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reviewer_digest(label: str = REVIEWER_LABEL) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def answer_record(answers: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**answer, "answer_sha256": canonical_sha256(answer)} for answer in answers]


def build_decisions(record: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = []
    for answer in record:
        if answer["certainty"] not in DECIDING_CERTAINTIES or not answer["decision"]:
            continue
        basis = f"{ANSWER_CHANNEL}; certainty={answer['certainty']}; answer_key={answer['answer_key']}"
        decisions.append({
            "basis": basis,
            "decided_at": DECIDED_AT,
            "decision": answer["decision"],
            "decision_schema_version": "0.2",
            "evidence_sha256": answer["answer_sha256"],
            "field_path": answer["field_path"],
            "reviewer_digest": reviewer_digest(),
            "role": REVIEWER_ROLE,
            "source_system": answer["source_system"],
        })
    return decisions


def validate(decision: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors = []
    props = schema["properties"]
    for key in schema["required"]:
        if key not in decision:
            errors.append(f"missing:{key}")
    if schema.get("additionalProperties") is False:
        errors.extend(f"extra:{key}" for key in decision if key not in props)
    for key, value in decision.items():
        rule = props.get(key)
        if rule is None:
            continue
        if "const" in rule and value != rule["const"]:
            errors.append(f"const:{key}")
        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"enum:{key}")
        if rule.get("type") == "string":
            if not isinstance(value, str):
                errors.append(f"type:{key}")
                continue
            if len(value) < rule.get("minLength", 0):
                errors.append(f"minLength:{key}")
            if "pattern" in rule and not re.search(rule["pattern"], value):
                errors.append(f"pattern:{key}")
    if isinstance(decision.get("reviewer_digest"), str) and not _HEX64.match(decision["reviewer_digest"]):
        errors.append("reviewer_digest_not_sha256")
    return errors


def evidence_hash_errors(decisions: list[dict[str, Any]], record: list[dict[str, Any]]) -> list[str]:
    by_hash = {canonical_sha256({k: v for k, v in item.items() if k != "answer_sha256"}): item for item in record}
    errors = []
    for decision in decisions:
        answer = by_hash.get(decision["evidence_sha256"])
        if answer is None:
            errors.append(f"evidence_not_found:{decision['field_path']}")
        elif answer["certainty"] not in DECIDING_CERTAINTIES:
            errors.append(f"decision_from_non_deciding_answer:{decision['field_path']}")
        elif answer["decision"] != decision["decision"]:
            errors.append(f"decision_differs_from_answer:{decision['field_path']}")
    return errors


def validate_all(decisions: list[dict[str, Any]], record: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    per = [{"field_path": d.get("field_path"), "errors": validate(d, schema)} for d in decisions]
    hash_errors = evidence_hash_errors(decisions, record)
    ok = bool(decisions) and all(not item["errors"] for item in per) and not hash_errors
    return {
        "DECISION_SCHEMA_VALIDATION_STATUS": "PASS" if ok else "FAIL",
        "ok": ok,
        "decision_count": len(decisions),
        "answer_count": len(record),
        "non_deciding_answer_count": len(record) - len(decisions),
        "per_decision": per,
        "evidence_hash_errors": hash_errors,
    }
