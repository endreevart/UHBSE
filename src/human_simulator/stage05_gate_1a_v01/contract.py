"""Status transitions allowed by Gate 1A. Readiness and eligible cells do not move."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate_1a_v01.policy import QUESTION_BY_ID, QUESTIONS, SCIENTIFIC_CEILING


def _subset(records: list[dict[str, Any]], flag: str) -> list[dict[str, Any]]:
    return [record for record in records if record.get(flag)]


def _all_accepted(records: list[dict[str, Any]]) -> bool:
    return bool(records) and all(record["attestation"] == "accepted" and record["closes_question"] for record in records)


def derive(records: list[dict[str, Any]]) -> dict[str, Any]:
    feedback = _subset(records, "affects_feedback")
    if _all_accepted(feedback):
        feedback_status = "CONFIRMED"
    elif any(record["attestation"] == "accepted" for record in feedback):
        feedback_status = "PARTIALLY_ATTESTED"
    else:
        feedback_status = "UNKNOWN_PENDING_HUMAN_REVIEW"

    identity_rows = [record for record in records if record["question_id"] == "B_IDENTITY"]
    identity = identity_rows[0] if len(identity_rows) == 1 else None
    if identity and identity["attestation"] == "accepted" and identity["closes_question"]:
        linkage = "OWNER_ATTESTED_NOT_DATA_PROOF"
    elif identity and identity["attestation"] == "rejected":
        linkage = "OWNER_REJECTED"
    else:
        linkage = "INSUFFICIENT_ATTESTATION_NOT_DATA_PROOF"

    intake = _subset(records, "affects_intake")
    intake_status = (
        "ATTESTED_PATIENT_REPORTED_NOT_ADMINISTRATION"
        if _all_accepted(intake)
        else "NOT_ACCEPTED_INSUFFICIENT_ATTESTATION"
    )

    source_a = [record for record in records if record["source_system"] == "magerya_api"]
    if _all_accepted(source_a):
        source_a_status = "ATTESTED"
    elif any(record["attestation"] == "accepted" for record in source_a):
        source_a_status = "PARTIALLY_ATTESTED"
    else:
        source_a_status = "NOT_ATTESTED"

    gate = "ATTESTED" if records and all(record["closes_question"] for record in records) else "INCOMPLETE"
    return {
        "SOURCE_B_FEEDBACK_SEMANTICS_STATUS": feedback_status,
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS": linkage,
        "PATIENT_REPORTED_INTAKE_TIER_STATUS": intake_status,
        "SOURCE_A_RECOMMENDATION_SEMANTICS_STATUS": source_a_status,
        "GATE_1A_ATTESTATION_STATUS": gate,
        **SCIENTIFIC_CEILING,
    }


def _identity_claims_proof(value: str) -> bool:
    if value in {"ESTABLISHED", "PROVEN", "VERIFIED"}:
        return True
    return "DATA_PROOF" in value and "NOT_DATA_PROOF" not in value


def violations(status: dict[str, Any], records: list[dict[str, Any]], answers: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    expected = derive(records)
    for key, value in expected.items():
        if status.get(key) != value:
            found.append(f"status:{key}")
    by_key = {answer["answer_key"]: answer for answer in answers}
    ids = [record.get("question_id") for record in records]
    if sorted(ids) != sorted(QUESTION_BY_ID) or len(ids) != len(QUESTIONS):
        found.append("checklist")
    for record in records:
        spec = QUESTION_BY_ID.get(record.get("question_id"))
        if spec is None:
            found.append("unknown_question")
            continue
        for flag in ("affects_feedback", "affects_identity", "affects_intake"):
            if record.get(flag) != spec[flag]:
                found.append(f"flag:{record['question_id']}:{flag}")
        if record.get("evidence_applicability") != spec["applicability"]:
            found.append(f"applicability:{record['question_id']}")
        if record.get("closes_question") != (record.get("attestation") == "accepted"):
            found.append(f"closes:{record['question_id']}")
        if record.get("attestation") == "accepted" and spec["applicability"] != "ADDRESSES_QUESTION":
            found.append(f"accepted_unaddressed:{record['question_id']}")
        answer = by_key.get(spec["answer_key"])
        if answer is None:
            found.append(f"answer_missing:{record['question_id']}")
            continue
        if record.get("evidence_sha256") != answer.get("answer_sha256"):
            found.append(f"evidence:{record['question_id']}")
        if record.get("attestation") == "accepted" and answer.get("certainty") != "STATED":
            found.append(f"accepted_not_stated:{record['question_id']}")
    linkage = str(status.get("SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS", ""))
    if _identity_claims_proof(linkage) or _identity_claims_proof(str(status.get("SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS", ""))):
        found.append("identity_data_proof")
    if status.get("CONFIRMED_ADMINISTRATION_MAPPING_COUNT") not in {0}:
        found.append("administration_counted")
    if status.get("DOMAIN_ACCEPTED_MAPPING_COUNT") not in {0}:
        found.append("domain_mapping_counted")
    return found
