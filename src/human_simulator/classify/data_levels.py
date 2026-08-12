"""Clinical data-level assignment and crosswalk compatibility rules."""

from __future__ import annotations

DATA_LEVELS: tuple[str, ...] = (
    "PATIENT_EVENT",
    "OBSERVATION_HEADER",
    "OBSERVATION_VALUE",
    "ATTRIBUTE_CONTAINER",
    "REFERENCE_CATALOG",
    "WORKFLOW",
    "PAYLOAD",
    "UNKNOWN",
)

ROLE_DEFAULT_DATA_LEVEL: dict[str, str] = {
    "ENTITY": "ATTRIBUTE_CONTAINER",
    "EVENT": "PATIENT_EVENT",
    "OBSERVATION": "OBSERVATION_VALUE",
    "ATTRIBUTE_CONTAINER": "ATTRIBUTE_CONTAINER",
    "REFERENCE": "REFERENCE_CATALOG",
    "LINK": "UNKNOWN",
    "WORKFLOW": "WORKFLOW",
    "UNCLASSIFIED": "UNKNOWN",
    "TECHNICAL": "UNKNOWN",
}

DATA_LEVEL_OVERRIDES: dict[tuple[str, str], str] = {
    ("magerya_api", "appointment_appointment"): "PATIENT_EVENT",
    ("magerya_api", "document_analysisresult"): "OBSERVATION_HEADER",
    ("magerya_api", "document_analysisresultitem"): "OBSERVATION_VALUE",
    ("magerya_api", "diagnosis_diagnosis"): "REFERENCE_CATALOG",
    ("magerya_api", "diagnosis_medicines"): "REFERENCE_CATALOG",
    ("magerya_api", "diagnosis_functionalstudies"): "REFERENCE_CATALOG",
    ("magerya_api", "diagnosis_manipulations"): "REFERENCE_CATALOG",
    ("magerya_api", "diagnosis_procedures"): "REFERENCE_CATALOG",
    ("public", "consultations"): "PATIENT_EVENT",
    ("public", "profilaxys_profile"): "ATTRIBUTE_CONTAINER",
    ("public", "profilaxys_analyses"): "OBSERVATION_VALUE",
    ("quest_digital", "analyses_constructor"): "OBSERVATION_VALUE",
    ("quest_digital", "analyses_pool"): "WORKFLOW",
    ("quest_digital", "lab_result"): "PAYLOAD",
}

CLINICAL_DOMAIN_OVERRIDES: dict[tuple[str, str], str] = {
    ("magerya_api", "diagnosis_medicines"): "medications",
    ("magerya_api", "diagnosis_diagnosis"): "diagnoses",
    ("magerya_api", "diagnosis_functionalstudies"): "procedures",
    ("magerya_api", "diagnosis_manipulations"): "procedures",
    ("magerya_api", "diagnosis_procedures"): "procedures",
}

# Explicit cross-level pairs allowed for cross-source mapping (still CANDIDATE/HYPOTHESIS only).
CROSSWALK_COMPATIBLE_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"PATIENT_EVENT", "PATIENT_EVENT"}),
        frozenset({"OBSERVATION_HEADER", "OBSERVATION_HEADER"}),
        frozenset({"OBSERVATION_VALUE", "OBSERVATION_VALUE"}),
        frozenset({"OBSERVATION_HEADER", "OBSERVATION_VALUE"}),
        frozenset({"ATTRIBUTE_CONTAINER", "ATTRIBUTE_CONTAINER"}),
        frozenset({"REFERENCE_CATALOG", "REFERENCE_CATALOG"}),
        frozenset({"PAYLOAD", "PAYLOAD"}),
        frozenset({"PAYLOAD", "OBSERVATION_VALUE"}),
    }
)

INCOMPATIBLE_WITH_REFERENCE: frozenset[str] = frozenset(
    {"PATIENT_EVENT", "OBSERVATION_HEADER", "OBSERVATION_VALUE", "PAYLOAD"}
)


def assign_data_level(
    schema: str,
    relation: str,
    role: str,
    *,
    column_names: list[str] | None = None,
) -> str:
    key = (schema, relation)
    if key in DATA_LEVEL_OVERRIDES:
        return DATA_LEVEL_OVERRIDES[key]
    if role == "OBSERVATION" and column_names:
        normalized = relation.replace("-", "_").lower()
        if normalized.endswith("resultitem") or normalized.endswith("_item"):
            return "OBSERVATION_VALUE"
        if any(col.lower().endswith("_id") for col in column_names) and normalized.endswith("result"):
            return "OBSERVATION_HEADER"
    return ROLE_DEFAULT_DATA_LEVEL.get(role, "UNKNOWN")


def clinical_domain(schema: str, relation: str) -> str | None:
    return CLINICAL_DOMAIN_OVERRIDES.get((schema, relation))


def data_levels_compatible(level_a: str, level_b: str) -> bool:
    if level_a == "UNKNOWN" or level_b == "UNKNOWN":
        return False
    if level_a == "WORKFLOW" or level_b == "WORKFLOW":
        return level_a == level_b == "WORKFLOW"
    if "REFERENCE_CATALOG" in {level_a, level_b}:
        return level_a == level_b == "REFERENCE_CATALOG"
    if level_a in INCOMPATIBLE_WITH_REFERENCE or level_b in INCOMPATIBLE_WITH_REFERENCE:
        if "REFERENCE_CATALOG" in {level_a, level_b}:
            return False
    return frozenset({level_a, level_b}) in CROSSWALK_COMPATIBLE_PAIRS
