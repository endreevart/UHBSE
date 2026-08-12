"""Table role assignment and infrastructure separation for schema classification."""

from __future__ import annotations

import re
from typing import Any

TABLE_ROLES: tuple[str, ...] = (
    "ENTITY",
    "EVENT",
    "OBSERVATION",
    "ATTRIBUTE_CONTAINER",
    "REFERENCE",
    "LINK",
    "WORKFLOW",
    "UNCLASSIFIED",
    "TECHNICAL",
)

APPLICATION_SCHEMAS: frozenset[str] = frozenset({"public", "quest_digital"})

INFRASTRUCTURE_SCHEMAS: frozenset[str] = frozenset(
    {
        "tiger",
        "tiger_data",
        "topology",
        "pg_catalog",
        "information_schema",
        "pg_toast",
    }
)

ROLE_ALLOWED_ENTITY_TYPES: dict[str, frozenset[str]] = {
    "ENTITY": frozenset(
        {
            "patients",
            "doctors",
            "specialties",
        }
    ),
    "EVENT": frozenset({"visits", "appointments"}),
    "OBSERVATION": frozenset(
        {
            "laboratory_results",
            "diagnoses",
            "prescriptions",
            "medications",
            "procedures",
            "ultrasound_examinations",
            "operations",
            "medical_documents",
            "measurements",
        }
    ),
    "ATTRIBUTE_CONTAINER": frozenset({"measurements", "patients"}),
    "REFERENCE": frozenset(),
    "LINK": frozenset(),
    "WORKFLOW": frozenset(),
    "UNCLASSIFIED": frozenset(),
    "TECHNICAL": frozenset(),
}

ROLE_OVERRIDES: dict[tuple[str, str], str] = {
    ("public", "consultations"): "EVENT",
    ("public", "persons"): "ENTITY",
    ("public", "users"): "ENTITY",
    ("public", "profilaxys_profile"): "ATTRIBUTE_CONTAINER",
    ("public", "users_profile"): "ATTRIBUTE_CONTAINER",
    ("public", "payment_transactions"): "WORKFLOW",
    ("public", "feedback"): "ATTRIBUTE_CONTAINER",
    ("public", "questionnaire"): "ATTRIBUTE_CONTAINER",
    ("public", "users_rating"): "REFERENCE",
    ("public", "consultation_service_changes"): "WORKFLOW",
    ("public", "profilaxys_analyses"): "OBSERVATION",
    ("quest_digital", "analyses_constructor"): "OBSERVATION",
    ("quest_digital", "analyses_pool"): "WORKFLOW",
    ("quest_digital", "lab_result"): "OBSERVATION",
    ("quest_digital", "analyses_codes"): "REFERENCE",
    ("quest_digital", "catalog_labs"): "REFERENCE",
    ("quest_digital", "analyses_catalog"): "REFERENCE",
    ("quest_digital", "analyses_labs"): "REFERENCE",
    ("quest_digital", "analyses_weight"): "REFERENCE",
    ("quest_digital", "lab_addresses"): "REFERENCE",
    ("quest_digital", "lab_referral"): "REFERENCE",
    ("quest_digital", "lab_referral_codes"): "REFERENCE",
    ("quest_digital", "lab_referral_regions"): "REFERENCE",
    ("quest_digital", "link_analyses"): "LINK",
    ("public", "users_persons"): "LINK",
    ("public", "role_user"): "LINK",
    ("public", "document_types"): "REFERENCE",
    ("magerya_api", "account_patient"): "ENTITY",
    ("magerya_api", "account_doctor"): "ENTITY",
    ("magerya_api", "appointment_appointment"): "EVENT",
    ("magerya_api", "appointment_appointmentrequest"): "WORKFLOW",
    ("magerya_api", "appointment_callbackrequest"): "WORKFLOW",
    ("magerya_api", "diagnosis_diagnosis"): "REFERENCE",
    ("magerya_api", "diagnosis_medicines"): "REFERENCE",
    ("magerya_api", "diagnosis_procedures"): "REFERENCE",
    ("magerya_api", "diagnosis_manipulations"): "REFERENCE",
    ("magerya_api", "diagnosis_functionalstudies"): "REFERENCE",
    ("magerya_api", "document_analysisresult"): "OBSERVATION",
    ("magerya_api", "document_analysisresultitem"): "OBSERVATION",
    ("magerya_api", "document_medicalreport"): "OBSERVATION",
    ("magerya_api", "document_document"): "OBSERVATION",
    ("magerya_api", "document_procedurelist"): "OBSERVATION",
    ("magerya_api", "document_informationform"): "OBSERVATION",
    ("magerya_api", "document_patientquestionnaire"): "OBSERVATION",
    ("magerya_api", "diagnosis_diagnosis_appointment_recommendations"): "LINK",
    ("magerya_api", "diagnosis_diagnosis_analysis"): "LINK",
    ("magerya_api", "diagnosis_diagnosis_medicines"): "LINK",
    ("magerya_api", "diagnosis_diagnosis_procedures"): "LINK",
    ("magerya_api", "diagnosis_diagnosis_manipulations"): "LINK",
    ("magerya_api", "diagnosis_diagnosis_functional_studies"): "LINK",
    ("magerya_api", "diagnosis_diagnosis_recommendations"): "LINK",
    ("magerya_api", "diagnosis_measurementunits"): "REFERENCE",
    ("magerya_api", "diagnosis_medicinesform"): "REFERENCE",
    ("magerya_api", "diagnosis_receptionfrequency"): "REFERENCE",
    ("magerya_api", "diagnosis_recommendationcategory"): "REFERENCE",
}

MAGERYA_EVENT_EXCLUDED_NAMES: frozenset[str] = frozenset(
    {
        "appointment_appointmentrequest",
        "appointment_callbackrequest",
    }
)

CURATED_ENTITY_CANDIDATES: dict[tuple[str, str], tuple[str, ...]] = {
    ("quest_digital", "analyses_constructor"): ("laboratory_results",),
    ("public", "profilaxys_profile"): ("measurements",),
    ("public", "consultations"): ("visits", "appointments"),
    ("public", "persons"): ("patients",),
    ("public", "profilaxys_analyses"): ("measurements",),
    ("quest_digital", "lab_result"): ("laboratory_results",),
    ("magerya_api", "account_patient"): ("patients",),
    ("magerya_api", "account_doctor"): ("doctors",),
    ("magerya_api", "appointment_appointment"): ("visits", "appointments"),
    ("magerya_api", "document_analysisresult"): ("laboratory_results",),
    ("magerya_api", "document_analysisresultitem"): ("laboratory_results",),
    ("magerya_api", "document_medicalreport"): ("medical_documents",),
    ("magerya_api", "document_document"): ("medical_documents",),
    ("magerya_api", "document_procedurelist"): ("medical_documents",),
    ("magerya_api", "document_informationform"): ("medical_documents",),
    ("magerya_api", "document_patientquestionnaire"): ("medical_documents",),
}

POSTGIS_INFRASTRUCTURE_RELATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("public", "spatial_ref_sys"),
        ("public", "geometry_columns"),
        ("public", "geography_columns"),
    }
)


def _patterns(*terms: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rf"(^|_){re.escape(term)}($|_)", re.IGNORECASE) for term in terms)


EVENT_NAME_PATTERNS: tuple[re.Pattern[str], ...] = _patterns(
    "visit",
    "visits",
    "encounter",
    "appointment",
)

OBSERVATION_NAME_PATTERNS: tuple[re.Pattern[str], ...] = _patterns(
    "lab_result",
    "lab_results",
    "analyses_constructor",
    "analyses_pool",
)

EVENT_SIGNATURE_COLUMNS: frozenset[str] = frozenset(
    {"patient_id", "doctor_id", "visit_id", "encounter_id"}
)

CONSULTATION_LINK_COLUMNS: frozenset[str] = frozenset({"consultation_id", "consultations_id"})

OBSERVATION_SIGNATURE_COLUMNS: frozenset[str] = frozenset({"value", "result", "catalog_id"})

ATTRIBUTE_CONTAINER_SIGNATURE_COLUMNS: frozenset[str] = frozenset(
    {"sex", "birthdate", "weight", "height", "gender", "age"}
)

REFERENCE_NAME_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^catalog",
        r"_catalog$",
        r"_codes$",
        r"_types$",
        r"_lookup$",
        r"document_types$",
    )
)

LINK_NAME_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^link_",
        r"_link$",
        r"role_user$",
        r"users_persons$",
        r"users_address$",
        r"users_company$",
    )
)

WORKFLOW_NAME_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"payment",
        r"transaction",
        r"schedule_event",
        r"queue",
        r"^job_",
    )
)


def is_infrastructure_schema(schema: str) -> bool:
    if schema in INFRASTRUCTURE_SCHEMAS:
        return True
    return schema.startswith("pg_")


def is_infrastructure_relation(schema: str, name: str) -> bool:
    if (schema, name) in POSTGIS_INFRASTRUCTURE_RELATIONS:
        return True
    if is_infrastructure_schema(schema):
        return True
    normalized = name.lower()
    return "pg_toast" in normalized


def assign_table_role(
    schema: str,
    relation_name: str,
    column_names: list[str],
    *,
    is_technical_name: bool,
) -> str:
    key = (schema, relation_name)
    if is_infrastructure_relation(schema, relation_name):
        return "TECHNICAL"
    if is_technical_name:
        return "TECHNICAL"
    if key in ROLE_OVERRIDES:
        return ROLE_OVERRIDES[key]

    column_set = {name.lower() for name in column_names}
    normalized = relation_name.replace("-", "_")

    if normalized.lower() in MAGERYA_EVENT_EXCLUDED_NAMES:
        return "WORKFLOW"
    if "appointment_id" in column_set and normalized.lower() != "appointment_appointment":
        if normalized.lower().endswith("_appointment_recommendations") or _matches_any(
            normalized, LINK_NAME_PATTERNS
        ):
            return "LINK"
        if not normalized.lower().startswith("appointment_"):
            return "LINK"
    if _matches_any(normalized, WORKFLOW_NAME_PATTERNS):
        return "WORKFLOW"
    if _matches_any(normalized, LINK_NAME_PATTERNS):
        return "LINK"
    if _matches_any(normalized, EVENT_NAME_PATTERNS):
        if normalized.lower() in MAGERYA_EVENT_EXCLUDED_NAMES:
            return "WORKFLOW"
        return "EVENT"
    if _matches_any(normalized, OBSERVATION_NAME_PATTERNS):
        return "OBSERVATION"
    if _matches_any(normalized, REFERENCE_NAME_PATTERNS):
        return "REFERENCE"
    if column_set & EVENT_SIGNATURE_COLUMNS and column_set & {"date", "time", "created_at"}:
        return "EVENT"
    if column_set & CONSULTATION_LINK_COLUMNS and not column_set & EVENT_SIGNATURE_COLUMNS:
        if normalized in {"feedback", "questionnaire"}:
            return "ATTRIBUTE_CONTAINER"
        if normalized == "users_rating":
            return "REFERENCE"
        if normalized.startswith("consultation_") and normalized != "consultations":
            return "WORKFLOW"
    if "value" in column_set and ("catalog_id" in column_set or "pool_id" in column_set):
        return "OBSERVATION"
    if column_set & ATTRIBUTE_CONTAINER_SIGNATURE_COLUMNS:
        return "ATTRIBUTE_CONTAINER"
    if normalized in {"persons", "users", "patients", "doctors"}:
        return "ENTITY"

    return "UNCLASSIFIED"


def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(value) for pattern in patterns)


def partition_relations(
    relations: list[dict[str, Any]],
    *,
    technical_names: set[tuple[str, str]],
    application_schemas: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    schemas = application_schemas or APPLICATION_SCHEMAS
    application: list[dict[str, Any]] = []
    infrastructure: list[dict[str, Any]] = []
    for relation in relations:
        schema = relation["schema"]
        name = relation["name"]
        key = (schema, name)
        if is_infrastructure_relation(schema, name) or key in technical_names:
            infrastructure.append(relation)
        elif schema in schemas:
            application.append(relation)
        else:
            infrastructure.append(relation)
    return application, infrastructure
