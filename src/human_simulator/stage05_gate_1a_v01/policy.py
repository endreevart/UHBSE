"""Gate 1A checklist. A question closes only when a stated answer addresses that question."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-05-gate-1a-v0.1"
V022_DIR = "artifacts/exposure-source-discovery-v0.2.2"
V022_SOURCE = "src/human_simulator/exposure_source_discovery_v022"
ANSWER_RECORD = f"{V022_DIR}/owner-answer-record.json"
OWNER_DECISIONS = f"{V022_DIR}/owner-decisions.json"

ADDRESSES = "ADDRESSES_QUESTION"
PARTIAL = "PARTIAL"
MISMATCH = "DOES_NOT_ADDRESS_QUESTION"
NO_DECISION = "NO_DECISION"
APPLICABILITY = (ADDRESSES, PARTIAL, MISMATCH, NO_DECISION)
ATTESTATION = ("accepted", "rejected", "insufficient")

REVIEWER_LABEL = "system-architect"
REVIEWER_ROLE = "system_architect"

# Flags select which statuses a question may move. Identity is not feedback semantics.
QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "question_id": "A_MEDICATION_CODE_MEDICINES",
        "group": "A_MEDICATION_CODES",
        "source_system": "magerya_api",
        "field_path": "document_recommendation.document.recommendations[].code=medicines",
        "proposition": "MEDICINES_CODE_CONTAINS_DRUGS_AND_SUPPLEMENTS",
        "answer_key": "A1",
        "applicability": ADDRESSES,
        "affects_feedback": False,
        "affects_identity": False,
        "affects_intake": False,
    },
    {
        "question_id": "A_MEDICATION_CODE_SET",
        "group": "A_MEDICATION_CODES",
        "source_system": "magerya_api",
        "field_path": "document_recommendation.document.recommendations[].code",
        "proposition": "COMPLETE_SET_OF_DRUG_AND_SUPPLEMENT_SECTION_CODES",
        "answer_key": "A1",
        "applicability": PARTIAL,
        "partial_decision": "COMPLETE_SET_NOT_ATTESTED_MEDICINES_ONLY",
        "affects_feedback": False,
        "affects_identity": False,
        "affects_intake": False,
    },
    {
        "question_id": "A_RECOMMENDATION_ITEMS",
        "group": "A_ITEMS",
        "source_system": "magerya_api",
        "field_path": "document_recommendation.document.recommendations[].items",
        "proposition": "CONTENTS_OF_RECOMMENDATION_ITEMS",
        "answer_key": "A2",
        "applicability": MISMATCH,
        "mismatch_decision": "ANSWER_ADDRESSES_ANALYSIS_ITEMS_NOT_RECOMMENDATION_ITEMS",
        "affects_feedback": False,
        "affects_identity": False,
        "affects_intake": False,
    },
    {
        "question_id": "A_DOCUMENT_FINAL",
        "group": "A_DOCUMENT_FINAL",
        "source_system": "magerya_api",
        "field_path": "document_recommendation",
        "proposition": "DOCUMENT_IS_FINAL_RECOMMENDATION_GIVEN_TO_PATIENT",
        "answer_key": "A3",
        "applicability": NO_DECISION,
        "affects_feedback": False,
        "affects_identity": False,
        "affects_intake": False,
    },
    {
        "question_id": "B_AUTHOR",
        "group": "B_AUTHOR",
        "source_system": "kgz_raw",
        "field_path": "public.feedback",
        "proposition": "WHO_FILLS_FEEDBACK",
        "answer_key": "B1",
        "applicability": ADDRESSES,
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": True,
    },
    {
        "question_id": "B_TIMING",
        "group": "B_TIMING",
        "source_system": "kgz_raw",
        "field_path": "public.feedback.created_at",
        "proposition": "FILLED_BEFORE_THE_NEXT_CONSULTATION",
        "answer_key": "B2",
        "applicability": ADDRESSES,
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": True,
    },
    {
        "question_id": "B_PERIOD",
        "group": "B_PERIOD",
        "source_system": "kgz_raw",
        "field_path": "public.feedback",
        "proposition": "PERIOD_DESCRIBED_BY_FEEDBACK",
        "answer_key": "B3",
        "applicability": ADDRESSES,
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": True,
    },
    {
        "question_id": "B_IDENTITY",
        "group": "B_IDENTITY",
        "source_system": "kgz_raw",
        "field_path": "public.feedback.user_id",
        "proposition": "SAME_SUBJECT_AS_CONSULTATIONS_PATIENT_ID",
        "answer_key": "B4",
        "applicability": ADDRESSES,
        "affects_feedback": False,
        "affects_identity": True,
        "affects_intake": True,
    },
    {
        "question_id": "B_DRUGS",
        "group": "B_DRUGS",
        "source_system": "kgz_raw",
        "field_path": "public.feedback.drugs",
        "proposition": "MEANING_OF_DRUGS",
        "answer_key": "B5",
        "applicability": ADDRESSES,
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": True,
    },
    {
        "question_id": "B_VITAMINS",
        "group": "B_VITAMINS",
        "source_system": "kgz_raw",
        "field_path": "public.feedback.vitamins",
        "proposition": "MEANING_OF_VITAMINS",
        "answer_key": "B5",
        "applicability": ADDRESSES,
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": True,
    },
    {
        "question_id": "B_CHANGE",
        "group": "B_CHANGE",
        "source_system": "kgz_raw",
        "field_path": "public.feedback.change_drugs",
        "proposition": "MEANING_OF_CHANGE_DRUGS",
        "answer_key": "B7",
        "applicability": PARTIAL,
        "partial_decision": "ATTRIBUTION_TO_DOCTOR_RECOMMENDATION_STATED_FIELD_MEANING_NOT_STATED",
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": True,
    },
    {
        "question_id": "B_DECLINE",
        "group": "B_DECLINE",
        "source_system": "kgz_raw",
        "field_path": "public.feedback.decline_drugs",
        "proposition": "MEANING_OF_DECLINE_DRUGS",
        "answer_key": "B7",
        "applicability": PARTIAL,
        "partial_decision": "ATTRIBUTION_TO_DOCTOR_RECOMMENDATION_STATED_FIELD_MEANING_NOT_STATED",
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": True,
    },
    {
        "question_id": "B_POSITIVE",
        "group": "B_POSITIVE",
        "source_system": "kgz_raw",
        "field_path": "public.feedback.positive_changes",
        "proposition": "MEANING_OF_POSITIVE_CHANGES",
        "answer_key": "B8",
        "applicability": NO_DECISION,
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": False,
    },
    {
        "question_id": "B_SHORT",
        "group": "B_SHORT",
        "source_system": "kgz_raw",
        "field_path": "public.feedback",
        "proposition": "SHORT_YES_NO_ARE_STANDARD_FORM_ANSWERS",
        "answer_key": "B9",
        "applicability": NO_DECISION,
        "affects_feedback": True,
        "affects_identity": False,
        "affects_intake": False,
    },
)

QUESTION_BY_ID = {item["question_id"]: item for item in QUESTIONS}

SCIENTIFIC_CEILING = {
    "SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS": "NOT_ESTABLISHED",
    "CROSS_SOURCE_IDENTITY_LINKAGE_STATUS": "NOT_PERFORMED",
    "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": 0,
    "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
    "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
    "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
    "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
    "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
    "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
    "PRODUCTION_READINESS": "NOT_CLAIMED",
}

REQUIRED_ARTIFACTS = (
    "decision-record.schema.json",
    "decision-records.json",
    "evidence-binding.json",
    "attestation-summary.json",
    "negative-control-results.json",
    "baseline-verification.json",
    "privacy-scan.json",
    "status-contract.json",
    "verification.json",
    "gate-1a-report.md",
    "MANIFEST.json",
)

DECISION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "uhbse/stage-05/gate-1a/decision-record/0.1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "question_id",
        "source_system",
        "field_path",
        "proposition",
        "decision",
        "role",
        "reviewer_digest",
        "decided_at",
        "basis",
        "evidence_sha256",
        "evidence_applicability",
        "attestation",
        "closes_question",
        "affects_feedback",
        "affects_identity",
        "affects_intake",
        "decision_schema_version",
    ],
    "properties": {
        "question_id": {"type": "string", "minLength": 3},
        "source_system": {"enum": ["magerya_api", "kgz_raw"]},
        "field_path": {"type": "string", "minLength": 3},
        "proposition": {"type": "string", "minLength": 3},
        "decision": {"type": "string", "minLength": 1},
        "role": {"type": "string", "minLength": 2},
        "reviewer_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "decided_at": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T.*Z$"},
        "basis": {"type": "string", "minLength": 1},
        "evidence_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "evidence_applicability": {"enum": list(APPLICABILITY)},
        "attestation": {"enum": list(ATTESTATION)},
        "closes_question": {"type": "boolean"},
        "affects_feedback": {"type": "boolean"},
        "affects_identity": {"type": "boolean"},
        "affects_intake": {"type": "boolean"},
        "decision_schema_version": {"const": "0.1"},
    },
}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "gate": "stage-05-gate-1a",
        "database_access": False,
        "model_training": False,
        "cohort_construction": False,
        "medication_extractor": False,
        "external_review_zip": False,
        "automatic_contact": False,
        "scientific_ceiling": SCIENTIFIC_CEILING,
    }
