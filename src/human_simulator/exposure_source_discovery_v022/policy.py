"""Recorded answers and status policy for v0.2.2. Answers are paraphrased; they contain no patient data."""

from __future__ import annotations

from typing import Any

VERSION = "0.2.2"
ARTIFACT_DIR = "artifacts/exposure-source-discovery-v0.2.2"
V02_DIR = "artifacts/exposure-source-discovery-v0.2"
V021_DIR = "artifacts/exposure-source-discovery-v0.2.1"
V021_SOURCE = "src/human_simulator/exposure_source_discovery_v021"
DECISION_SCHEMA = f"{V02_DIR}/semantic-decision.schema.json"
V021_STATUS = f"{V021_DIR}/status-contract.json"

REVIEWER_LABEL = "system-architect"
REVIEWER_ROLE = "system_architect"
DECIDED_AT = "2026-11-06T17:47:00Z"
ANSWER_CHANNEL = "verbal_answer_relayed_in_chat"

MAGERYA_CODE_ROOT_ENV = "UHBSE_MAGERYA_CODE_ROOT"
MAGERYA_CODE_ROOT_DEFAULT = "~/Library/Mobile Documents/com~apple~CloudDocs/DEV/django-develop"
MAGERYA_CODE_FILES = (
    "apps/document/models/recommendation/models.py",
    "apps/document/models/recommendation/v1_0.py",
    "apps/document/lk_doctor/views.py",
    "apps/document/lk_doctor/serializers.py",
    "apps/document/models/analysis.py",
    "apps/diagnosis/models.py",
    "apps/diagnosis/enums.py",
    "apps/mixin/models/results.py",
    "apps/mixin/enums.py",
    "apps/appointment/services.py",
    "apps/document/baker_recipes.py",
)

STATED = "STATED"
STATED_WITH_RECALL_UNCERTAINTY = "STATED_WITH_RECALL_UNCERTAINTY"
DEFERRED_TO_CODE = "DEFERRED_TO_CODE"
NOT_REMEMBERED = "NOT_REMEMBERED"
NOT_KNOWN = "NOT_KNOWN"
DECIDING_CERTAINTIES = (STATED, STATED_WITH_RECALL_UNCERTAINTY)

ANSWERS: tuple[dict[str, Any], ...] = (
    {
        "answer_key": "A1",
        "v02_question": 1,
        "source_system": "magerya_api",
        "field_path": "document_recommendation.document.recommendations[].code=medicines",
        "answer_ru": "В разделе medicines встречаются БАДы и медикаменты",
        "certainty": STATED,
        "decision": "MEDICINES_SECTION_HOLDS_DRUGS_AND_SUPPLEMENTS",
    },
    {
        "answer_key": "A2",
        "v02_question": 2,
        "source_system": "magerya_api",
        "field_path": "document_analysis.items->document_analysisitem",
        "answer_ru": "Анализ или группа (например, ОАК) состоит из поданализов; у ТТГ поданализ тоже ТТГ",
        "certainty": STATED,
        "decision": "ANALYSIS_ITEMS_ARE_COMPONENT_SUBANALYSES",
    },
    {
        "answer_key": "A3",
        "v02_question": 3,
        "source_system": "magerya_api",
        "field_path": "document_recommendation",
        "answer_ru": "Смотреть в коде",
        "certainty": DEFERRED_TO_CODE,
        "decision": None,
    },
    {
        "answer_key": "A4",
        "v02_question": None,
        "source_system": "magerya_api",
        "field_path": "diagnosis_medicineappointments->appointment",
        "answer_ru": "Смотреть в коде",
        "certainty": DEFERRED_TO_CODE,
        "decision": None,
    },
    {
        "answer_key": "B1",
        "v02_question": 4,
        "source_system": "kgz_raw",
        "field_path": "public.feedback",
        "answer_ru": "Когда как: сам пациент или со слов пациента",
        "certainty": STATED,
        "decision": "FILLED_BY_PATIENT_OR_STAFF_FROM_PATIENT_WORDS",
    },
    {
        "answer_key": "B2",
        "v02_question": 5,
        "source_system": "kgz_raw",
        "field_path": "public.feedback.created_at",
        "answer_ru": "Перед консультацией",
        "certainty": STATED,
        "decision": "FILLED_BEFORE_CONSULTATION",
    },
    {
        "answer_key": "B3",
        "v02_question": 6,
        "source_system": "kgz_raw",
        "field_path": "public.feedback",
        "answer_ru": "Первый приём: в целом; повторный: с момента прошлого приёма",
        "certainty": STATED,
        "decision": "FIRST_VISIT_GENERAL_HISTORY_REPEAT_VISIT_SINCE_PREVIOUS_VISIT",
    },
    {
        "answer_key": "B4",
        "v02_question": 7,
        "source_system": "kgz_raw",
        "field_path": "public.feedback.user_id",
        "answer_ru": "Да, не помню",
        "certainty": STATED_WITH_RECALL_UNCERTAINTY,
        "decision": "SAME_SUBJECT_AS_CONSULTATIONS_PATIENT_ID",
    },
    {
        "answer_key": "B5",
        "v02_question": 8,
        "source_system": "kgz_raw",
        "field_path": "public.feedback.drugs,public.feedback.vitamins",
        "answer_ru": "Медикаменты / БАДы, тоже не помню",
        "certainty": STATED_WITH_RECALL_UNCERTAINTY,
        "decision": "DRUGS_MEDICATIONS_VITAMINS_SUPPLEMENTS",
    },
    {
        "answer_key": "B6",
        "v02_question": 8,
        "source_system": "kgz_raw",
        "field_path": "public.feedback.drugs_first",
        "answer_ru": "Не помню",
        "certainty": NOT_REMEMBERED,
        "decision": None,
    },
    {
        "answer_key": "B7",
        "v02_question": 10,
        "source_system": "kgz_raw",
        "field_path": "public.feedback.change_drugs,public.feedback.decline_drugs",
        "answer_ru": "Да: относятся к рекомендациям врача",
        "certainty": STATED,
        "decision": "CHANGE_OR_DECLINE_RELATIVE_TO_DOCTOR_RECOMMENDATIONS",
    },
    {
        "answer_key": "B8",
        "v02_question": 11,
        "source_system": "kgz_raw",
        "field_path": "public.feedback.positive_changes",
        "answer_ru": "Не помню",
        "certainty": NOT_REMEMBERED,
        "decision": None,
    },
    {
        "answer_key": "B9",
        "v02_question": 12,
        "source_system": "kgz_raw",
        "field_path": "public.feedback",
        "answer_ru": "Не помню",
        "certainty": NOT_REMEMBERED,
        "decision": None,
    },
    {
        "answer_key": "B10",
        "v02_question": None,
        "source_system": "kgz_raw",
        "field_path": "public.consultations.date",
        "answer_ru": "Не знаю, почему дата пуста",
        "certainty": NOT_KNOWN,
        "decision": None,
    },
    {
        "answer_key": "B11",
        "v02_question": None,
        "source_system": "kgz_raw",
        "field_path": "public.feedback.created_at,public.consultations.date",
        "answer_ru": "По МСК",
        "certainty": STATED,
        "decision": "SOURCE_TIMEZONE_EUROPE_MOSCOW",
    },
)

SCIENTIFIC_CEILING = {
    "SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS": "NOT_ESTABLISHED",
    "CROSS_SOURCE_IDENTITY_LINKAGE_STATUS": "NOT_PERFORMED",
    "PATIENT_REPORTED_INTAKE_TIER_STATUS": "NOT_ACCEPTED_PENDING_SEMANTIC_REVIEW",
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
    "owner-answer-record.json",
    "owner-decisions.json",
    "decision-validation.json",
    "source-a-code-and-catalog-evidence.json",
    "field-semantic-status.json",
    "negative-control-results.json",
    "query-log.json",
    "baseline-verification.json",
    "privacy-scan.json",
    "status-contract.json",
    "verification.json",
    "discovery-report.md",
    "MANIFEST.json",
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage_05_gate": False,
        "model_training": False,
        "cohort_construction": False,
        "medication_extractor": False,
        "external_review_zip": False,
        "automatic_contact": False,
        "scientific_ceiling": SCIENTIFIC_CEILING,
    }
