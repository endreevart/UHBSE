"""Derive field and stage statuses from decisions and evidence, and check the scientific ceiling."""

from __future__ import annotations

from typing import Any

from human_simulator.exposure_source_discovery_v022.policy import (
    DEFERRED_TO_CODE,
    NOT_KNOWN,
    NOT_REMEMBERED,
    SCIENTIFIC_CEILING,
    STATED,
    STATED_WITH_RECALL_UNCERTAINTY,
)

_CERTAINTY_STATUS = {
    STATED: "OWNER_CONFIRMED",
    STATED_WITH_RECALL_UNCERTAINTY: "OWNER_STATED_RECALL_UNCERTAIN",
    NOT_REMEMBERED: "UNKNOWN",
    NOT_KNOWN: "UNKNOWN",
}
_SCHEMA_ITEM_KEYS = {"name", "description", "id"}


def _answer(record: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(item for item in record if item["answer_key"] == key)


def _label(evidence: dict[str, Any], code: str) -> str | None:
    return next((c["label"] for c in evidence["template_categories"] if c["code"] == code), None)


def field_statuses(record: list[dict[str, Any]], evidence: dict[str, Any], code: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for answer in record:
        if answer["certainty"] == DEFERRED_TO_CODE:
            continue
        fields.append({
            "answer_key": answer["answer_key"],
            "source_system": answer["source_system"],
            "field_path": answer["field_path"],
            "status": _CERTAINTY_STATUS[answer["certainty"]],
            "decision": answer["decision"],
            "evidence": [f"owner-answer-record.json#{answer['answer_key']}"],
        })
    activity = _label(evidence, "activity")
    fields.append({
        "source_system": "magerya_api",
        "field_path": "document_recommendation.document.recommendations[].code=activity",
        "status": "LIKELY",
        "decision": "LIFESTYLE_SECTION_NOT_MEDICATION_SECTION" if activity == "Образ жизни" else None,
        "catalog_label": activity,
        "evidence": ["query:a_template_categories", "owner-answer-record.json#A1"],
    })
    keys = set(evidence["item_key_counts"])
    fields.append({
        "source_system": "magerya_api",
        "field_path": "document_recommendation.document.recommendations[].items",
        "status": "CONFIRMED_SCHEMA" if keys and keys <= _SCHEMA_ITEM_KEYS else "UNKNOWN",
        "decision": "ONE_RECOMMENDATION_PER_ITEM_NAME_AND_DOCTOR_TEXT",
        "semantic_status": "LIKELY",
        "observed_item_keys": sorted(keys),
        "evidence": ["query:a_item_keys", "code:apps/document/models/recommendation/v1_0.py"],
    })
    shape = evidence["recommendation_shape"]
    fields.append({
        "source_system": "magerya_api",
        "field_path": "document_recommendation",
        "status": "LIKELY" if shape["one_document_per_appointment"] else "UNKNOWN",
        "decision": "ONE_MUTABLE_DOCUMENT_PER_APPOINTMENT_READ_ONLY_AFTER_APPOINTMENT_CLOSES_NO_VERSION_HISTORY",
        "delivery_to_patient_status": "UNKNOWN",
        "evidence": [
            "query:a_recommendation_shape",
            "code:apps/document/models/recommendation/models.py",
            "code:apps/document/lk_doctor/views.py",
            "code:apps/document/lk_doctor/serializers.py",
        ],
    })
    link = evidence["medicine_appointment_link"]
    resolves = link["link_rows"] > 0 and link["link_rows_resolving_to_assignment"] == link["link_rows"]
    fields.append({
        "source_system": "magerya_api",
        "field_path": "diagnosis_medicineappointments->appointment",
        "status": "CONFIRMED_SCHEMA" if resolves else "LIKELY",
        "decision": "ASSIGNMENT_LINKED_TO_APPOINTMENT_VIA_DOCUMENT_APPOINTMENTANALYSISRESULT",
        "semantic_status": "ASSIGNMENT_NOT_ADMINISTRATION",
        "evidence": ["query:a_medicine_link", "query:a_medicine_status", "code:apps/mixin/models/results.py"],
    })
    fields.append({
        "source_system": "magerya_api",
        "field_path": "diagnosis_medicines.category",
        "status": "CONFIRMED_SCHEMA",
        "decision": "DRUG_OR_SUPPLEMENTS",
        "evidence": ["query:a_medicine_catalog", "code:apps/diagnosis/enums.py"],
    })
    if code["SOURCE_A_CODE_EVIDENCE_STATUS"] != "AVAILABLE":
        for item in fields:
            if any(ref.startswith("code:") for ref in item["evidence"]) and item["status"] == "CONFIRMED_SCHEMA":
                item["status"] = "LIKELY"
    return fields


def stage_statuses(record: list[dict[str, Any]], evidence: dict[str, Any], v021: dict[str, Any]) -> dict[str, Any]:
    identity = _answer(record, "B4")["certainty"]
    window = _answer(record, "B3")["certainty"]
    timing = _answer(record, "B2")["certainty"]
    timezone = _answer(record, "B11")
    activity = _label(evidence, "activity")
    identity_status = {
        STATED: "OWNER_CONFIRMED_NOT_DATA_PROOF",
        STATED_WITH_RECALL_UNCERTAINTY: "OWNER_STATED_RECALL_UNCERTAIN_NOT_DATA_PROOF",
    }.get(identity, "NOT_ESTABLISHED")
    sequence_ok = window == STATED and timing == STATED
    return {
        "OWNER_SEMANTIC_REVIEW_STATUS": "PARTIAL_OWNER_DECISIONS_RECORDED",
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS": identity_status,
        "SOURCE_B_TIMEZONE_SEMANTICS_STATUS": "OWNER_STATED_EUROPE_MOSCOW"
        if timezone["certainty"] == STATED and timezone["decision"] == "SOURCE_TIMEZONE_EUROPE_MOSCOW"
        else "UNKNOWN_SOURCE_TIMEZONE",
        "FEEDBACK_REPORTING_WINDOW_STATUS": _CERTAINTY_STATUS.get(window, "UNKNOWN"),
        "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": "CANDIDATE_COUNTED_SEQUENCE_SEMANTICS_OWNER_CONFIRMED"
        if sequence_ok
        else v021["SOURCE_B_TEMPORAL_SEQUENCE_STATUS"],
        "SOURCE_B_CANDIDATE_CHAIN_COUNT": v021["counts"]["candidate_count"],
        "SOURCE_B_CANDIDATE_CHAIN_DENOMINATOR": v021["counts"]["candidate_denominator"],
        "SOURCE_A_MEDICATION_SECTION_STATUS": "OWNER_CONFIRMED_MEDICINES"
        if _answer(record, "A1")["certainty"] == STATED
        else "UNKNOWN",
        "SOURCE_A_ACTIVITY_SECTION_STATUS": "LIKELY_LIFESTYLE_NOT_MEDICATION" if activity == "Образ жизни" else "UNKNOWN",
        "SOURCE_A_V02_DOSE_SIGNAL_INTERPRETATION_STATUS": "CORRECTION_REQUIRED_ACTIVITY_SIGNAL_NOT_MEDICATION_EVIDENCE"
        if activity == "Образ жизни"
        else "UNCHANGED",
        "SOURCE_A_MEDICINE_ASSIGNMENT_SEMANTICS": "ASSIGNMENT_NOT_ADMINISTRATION",
        **SCIENTIFIC_CEILING,
    }


def violations(
    status: dict[str, Any],
    decisions: list[dict[str, Any]],
    record: list[dict[str, Any]],
    fields: list[dict[str, Any]],
) -> list[str]:
    found = []
    for key, value in SCIENTIFIC_CEILING.items():
        if status.get(key) != value:
            found.append(f"ceiling:{key}")
    if "PROOF" in status.get("SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS", "") and not status[
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"
    ].endswith("NOT_DATA_PROOF"):
        found.append("identity_claimed_as_data_proof")
    if status.get("SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS") in {"ESTABLISHED", "PROVEN", "VERIFIED"}:
        found.append("identity_claimed_as_data_proof")
    uncertain = {a["field_path"] for a in record if a["certainty"] == STATED_WITH_RECALL_UNCERTAINTY}
    for item in fields:
        if item["field_path"] in uncertain and item["status"] == "OWNER_CONFIRMED":
            found.append(f"recall_uncertain_promoted:{item['field_path']}")
        if item["field_path"].endswith("code=activity") and "MEDICATION_SECTION" in str(item.get("decision")) and not str(
            item.get("decision")
        ).endswith("NOT_MEDICATION_SECTION"):
            found.append("activity_labelled_medication")
    deciding = {a["answer_sha256"] for a in record if a["certainty"] in {STATED, STATED_WITH_RECALL_UNCERTAINTY}}
    for decision in decisions:
        if decision["evidence_sha256"] not in deciding:
            found.append(f"decision_without_deciding_answer:{decision['field_path']}")
    if status.get("SOURCE_A_MEDICINE_ASSIGNMENT_SEMANTICS") != "ASSIGNMENT_NOT_ADMINISTRATION":
        found.append("assignment_treated_as_administration")
    return found
