"""Curated domain classification — regex only for candidates; evidence required for SUPPORTED."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from human_simulator.unified_research_layer_v031.policy import (
    INFRASTRUCTURE_SCHEMAS,
    NEGATIVE_CONTROL_RELATIONS,
    VERSION,
)

# Primary accounting dispositions (exactly one per relation)
DISPOSITIONS = (
    "SOURCE_SPECIFIC_SUPPORTED",
    "REFERENCE_CATALOG",
    "ENTITY_LINK",
    "INFRASTRUCTURE_UNSUPPORTED",
    "UNRESOLVED_RETAINED",
    "REJECTED_FALSE_POSITIVE",
)

# Secondary semantic roles (any number)
SECONDARY_ROLES = (
    "subject_anchor",
    "encounter_anchor",
    "lab_result",
    "lab_component",
    "medication_event",
    "medication_reference",
    "diagnosis_catalog",
    "recommendation_patient_event",
    "recommendation_catalog",
    "document_reference",
    "procedure_event",
    "procedure_catalog",
    "temporal_candidate",
)

# Regex candidate generators (NOT sufficient for SOURCE_SPECIFIC_SUPPORTED)
_CANDIDATE_PATTERNS: dict[str, list[str]] = {
    "subjects_patients": [r"patient", r"account_patient", r"^users$"],
    "encounters": [r"appoint", r"consult", r"encounter", r"visit"],
    "diagnoses": [r"diagnos", r"icd"],
    "medications": [r"medicin", r"medication", r"drug"],
    "recommendations": [r"recommend"],
    "laboratory": [r"analys", r"lab_", r"result"],
    "documents": [r"document"],
    "procedures": [r"procedur", r"manipulat", r"operation"],
    "anthropometry": [r"weight", r"height", r"bmi", r"anthrop"],
    "orders_commerce": [r"order", r"sale", r"evotor", r"payment", r"contract"],
}

# Explicit curated overrides: (schema, relation) -> classification
CURATED: dict[tuple[str, str], dict[str, Any]] = {
    # Source A
    ("magerya_api", "account_patient"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "subjects_patients",
        "secondary_roles": ["subject_anchor"],
        "evidence": ["stage01_entity", "fk_ownership", "canonical_loaded"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("magerya_api", "appointment_appointment"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "encounters",
        "secondary_roles": ["encounter_anchor"],
        "evidence": ["stage01_table_role", "canonical_loaded"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("magerya_api", "document_analysisresult"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "laboratory_results",
        "secondary_roles": ["lab_result"],
        "evidence": ["canonical_observation_load", "stage01"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("magerya_api", "document_analysisresultitem"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "laboratory_components",
        "secondary_roles": ["lab_component"],
        "evidence": ["canonical_component_load"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("magerya_api", "diagnosis_medicineappointments"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "medications",
        "secondary_roles": ["medication_event"],
        "evidence": [
            "column_signature_patient_id_medicine_id_appointment_date",
            "not_ordinary_encounter",
        ],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
        "notes": "Medication appointment/event records; not clinical administration unless proven",
    },
    ("magerya_api", "diagnosis_medicines"): {
        "primary_disposition": "REFERENCE_CATALOG",
        "primary_domain": "medications",
        "secondary_roles": ["medication_reference"],
        "evidence": ["stage01_REFERENCE_CATALOG", "no_patient_fk"],
        "support_status": "UNRESOLVED_RETAINED",
    },
    ("magerya_api", "diagnosis_diagnosis"): {
        "primary_disposition": "REFERENCE_CATALOG",
        "primary_domain": "diagnoses",
        "secondary_roles": ["diagnosis_catalog"],
        "evidence": ["stage01_REFERENCE_CATALOG", "columns_name_description_only"],
        "support_status": "UNRESOLVED_RETAINED",
        "notes": "Catalog — not patient diagnosis facts",
    },
    ("magerya_api", "document_recommendation"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "recommendations",
        "secondary_roles": ["recommendation_patient_event", "document_reference"],
        "evidence": ["appointment_id_link_all_rows", "no_body_in_research_layer"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("magerya_api", "diagnosis_proceduresresult"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "procedures",
        "secondary_roles": ["procedure_event"],
        "evidence": ["patient_id_appointment_date"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("magerya_api", "diagnosis_manipulationsresult"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "procedures",
        "secondary_roles": ["procedure_event"],
        "evidence": ["patient_id_appointment_date"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("magerya_api", "document_procedurelist"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "procedures",
        "secondary_roles": ["procedure_event", "document_reference"],
        "evidence": ["patient_id_appointment_id"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("magerya_api", "contract_saleorder"): {
        "primary_disposition": "REJECTED_FALSE_POSITIVE",
        "primary_domain": "orders_commerce",
        "secondary_roles": [],
        "evidence": ["negative_control_not_lab_order"],
        "support_status": "REJECTED_FALSE_POSITIVE",
    },
    ("magerya_api", "evotor_evotororder"): {
        "primary_disposition": "REJECTED_FALSE_POSITIVE",
        "primary_domain": "orders_commerce",
        "secondary_roles": [],
        "evidence": ["negative_control_not_lab_order"],
        "support_status": "REJECTED_FALSE_POSITIVE",
    },
    # Source B
    ("public", "users"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "subjects_patients",
        "secondary_roles": ["subject_anchor"],
        "evidence": ["stage02_table_role_ENTITY", "canonical_loaded_patient_role"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("public", "consultations"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "encounters",
        "secondary_roles": ["encounter_anchor"],
        "evidence": ["stage02_EVENT_PATIENT_EVENT", "canonical_loaded"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("public", "documents"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "documents",
        "secondary_roles": ["document_reference"],
        "evidence": ["user_id_ownership", "reference_only_no_body"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("quest_digital", "analyses_pool"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "laboratory_results",
        "secondary_roles": ["lab_result"],
        "evidence": ["canonical_observation_load"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("quest_digital", "analyses_constructor"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "laboratory_components",
        "secondary_roles": ["lab_component"],
        "evidence": ["canonical_component_load"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
    },
    ("quest_digital", "analyses_catalog"): {
        "primary_disposition": "REFERENCE_CATALOG",
        "primary_domain": "laboratory_results",
        "secondary_roles": [],
        "evidence": ["catalog"],
        "support_status": "UNRESOLVED_RETAINED",
    },
    ("quest_digital", "recommendations_user"): {
        "primary_disposition": "SOURCE_SPECIFIC_SUPPORTED",
        "primary_domain": "recommendations",
        "secondary_roles": ["recommendation_patient_event"],
        "evidence": ["consultations_id_fk", "patient_event_not_catalog"],
        "support_status": "SOURCE_SPECIFIC_SUPPORTED",
        "notes": "Patient-linked recommendation assignments; description text excluded from materialization",
    },
    ("quest_digital", "recommendations_list"): {
        "primary_disposition": "REFERENCE_CATALOG",
        "primary_domain": "recommendations",
        "secondary_roles": ["recommendation_catalog"],
        "evidence": ["catalog_template"],
        "support_status": "UNRESOLVED_RETAINED",
    },
    ("quest_digital", "recommendations_category"): {
        "primary_disposition": "REFERENCE_CATALOG",
        "primary_domain": "recommendations",
        "secondary_roles": ["recommendation_catalog"],
        "evidence": ["catalog"],
        "support_status": "UNRESOLVED_RETAINED",
    },
    ("quest_digital", "link_analyses"): {
        "primary_disposition": "ENTITY_LINK",
        "primary_domain": "entity_links",
        "secondary_roles": [],
        "evidence": ["link_table"],
        "support_status": "UNRESOLVED_RETAINED",
    },
    ("quest_digital", "analyses_weight"): {
        "primary_disposition": "REJECTED_FALSE_POSITIVE",
        "primary_domain": "anthropometry",
        "secondary_roles": [],
        "evidence": ["negative_control_not_patient_anthropometry", "stage02_REFERENCE"],
        "support_status": "REJECTED_FALSE_POSITIVE",
    },
    ("quest_digital", "catalog_weights"): {
        "primary_disposition": "REJECTED_FALSE_POSITIVE",
        "primary_domain": "anthropometry",
        "secondary_roles": [],
        "evidence": ["negative_control_not_patient_weight", "stage02_REFERENCE"],
        "support_status": "REJECTED_FALSE_POSITIVE",
    },
}


def _load_prior_roles(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for rel in (
        "artifacts/stage-01/entity-candidates.yaml",
        "artifacts/stage-02/entity-candidates-kgz.yaml",
    ):
        path = Path(root) / rel
        if not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for section in ("table_roles", "role_classified_relations", "infrastructure_inventory"):
            for row in data.get(section) or []:
                if not isinstance(row, dict):
                    continue
                key = (row.get("schema"), row.get("relation"))
                if key[0] and key[1]:
                    out[key] = row  # type: ignore[index]
    return out


def _candidate_domains(relation: str) -> list[str]:
    hits = []
    for domain, pats in _CANDIDATE_PATTERNS.items():
        for p in pats:
            if re.search(p, relation, re.I):
                hits.append(domain)
                break
    return hits


def classify_relation(
    *,
    schema: str,
    relation: str,
    kind: str,
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    key = (schema, relation)
    candidates = _candidate_domains(relation)

    if schema in INFRASTRUCTURE_SCHEMAS:
        return {
            "schema": schema,
            "relation": relation,
            "kind": kind,
            "candidate_domains": candidates,
            "primary_disposition": "INFRASTRUCTURE_UNSUPPORTED",
            "primary_domain": "infrastructure",
            "secondary_roles": [],
            "support_status": "INFRASTRUCTURE_UNSUPPORTED",
            "evidence": ["infrastructure_schema"],
            "regex_only_supported": False,
        }

    if key in CURATED:
        c = CURATED[key]
        return {
            "schema": schema,
            "relation": relation,
            "kind": kind,
            "candidate_domains": candidates,
            **c,
            "regex_only_supported": False,
        }

    if key in NEGATIVE_CONTROL_RELATIONS:
        return {
            "schema": schema,
            "relation": relation,
            "kind": kind,
            "candidate_domains": candidates,
            "primary_disposition": "REJECTED_FALSE_POSITIVE",
            "primary_domain": candidates[0] if candidates else "unknown",
            "secondary_roles": [],
            "support_status": "REJECTED_FALSE_POSITIVE",
            "evidence": ["negative_control"],
            "regex_only_supported": False,
        }

    # infrastructure-like names in application schemas
    infra_name = re.search(
        r"(migration|session|oauth|spatial_ref|django|auth_|payment|celery|cache)",
        relation,
        re.I,
    )
    if infra_name or (prior and prior.get("status") == "INFRASTRUCTURE"):
        return {
            "schema": schema,
            "relation": relation,
            "kind": kind,
            "candidate_domains": candidates,
            "primary_disposition": "INFRASTRUCTURE_UNSUPPORTED",
            "primary_domain": "infrastructure",
            "secondary_roles": [],
            "support_status": "INFRASTRUCTURE_UNSUPPORTED",
            "evidence": ["name_or_prior_infrastructure"],
            "regex_only_supported": False,
        }

    if prior and prior.get("data_level") == "REFERENCE_CATALOG":
        return {
            "schema": schema,
            "relation": relation,
            "kind": kind,
            "candidate_domains": candidates,
            "primary_disposition": "REFERENCE_CATALOG",
            "primary_domain": candidates[0] if candidates else "reference_catalogs",
            "secondary_roles": [],
            "support_status": "UNRESOLVED_RETAINED",
            "evidence": ["prior_REFERENCE_CATALOG"],
            "regex_only_supported": False,
        }

    if prior and prior.get("role") == "LINK":
        return {
            "schema": schema,
            "relation": relation,
            "kind": kind,
            "candidate_domains": candidates,
            "primary_disposition": "ENTITY_LINK",
            "primary_domain": "entity_links",
            "secondary_roles": [],
            "support_status": "UNRESOLVED_RETAINED",
            "evidence": ["prior_LINK"],
            "regex_only_supported": False,
        }

    # Regex alone never grants SOURCE_SPECIFIC_SUPPORTED
    return {
        "schema": schema,
        "relation": relation,
        "kind": kind,
        "candidate_domains": candidates,
        "primary_disposition": "UNRESOLVED_RETAINED",
        "primary_domain": candidates[0] if candidates else "unknown_clinical_relations",
        "secondary_roles": [],
        "support_status": "UNRESOLVED_RETAINED",
        "evidence": ["no_curated_or_fk_proof"],
        "regex_only_supported": False,
        "notes": "Candidate via regex only — retained unresolved",
    }


def classify_inventory(
    *, root: Path, inventory: dict[str, Any], source_system: str | None = None
) -> dict[str, Any]:
    prior = _load_prior_roles(root)
    classified = []
    primary_seen: dict[tuple[str, str], int] = {}
    disposition_counts: dict[str, int] = {}
    regressions = []

    for rel in inventory.get("relations") or []:
        key = (rel["schema"], rel["relation"])
        row = classify_relation(
            schema=rel["schema"],
            relation=rel["relation"],
            kind=rel.get("kind") or "table",
            prior=prior.get(key),
        )
        row["exact_row_count"] = rel.get("exact_row_count")
        classified.append(row)
        pk = (row["schema"], row["relation"])
        primary_seen[pk] = primary_seen.get(pk, 0) + 1
        d = row["primary_disposition"]
        disposition_counts[d] = disposition_counts.get(d, 0) + 1

    # regression assertions as evidence objects
    for key, expected in [
        (("magerya_api", "contract_saleorder"), "REJECTED_FALSE_POSITIVE"),
        (("magerya_api", "evotor_evotororder"), "REJECTED_FALSE_POSITIVE"),
        (("quest_digital", "analyses_weight"), "REJECTED_FALSE_POSITIVE"),
        (("quest_digital", "catalog_weights"), "REJECTED_FALSE_POSITIVE"),
        (("magerya_api", "diagnosis_medicines"), "REFERENCE_CATALOG"),
        (("magerya_api", "diagnosis_medicineappointments"), "SOURCE_SPECIFIC_SUPPORTED"),
        (("public", "users"), "SOURCE_SPECIFIC_SUPPORTED"),
        (("public", "consultations"), "SOURCE_SPECIFIC_SUPPORTED"),
    ]:
        hit = next((c for c in classified if (c["schema"], c["relation"]) == key), None)
        ok = hit is not None and hit["primary_disposition"] == expected
        regressions.append(
            {
                "relation": f"{key[0]}.{key[1]}",
                "expected": expected,
                "observed": None if hit is None else hit["primary_disposition"],
                "ok": ok,
            }
        )

    dup_primary = [f"{s}.{r}" for (s, r), n in primary_seen.items() if n != 1]
    ss = source_system or inventory.get("source_system") or ""
    require_b_anchors = ss in {"kgz_raw", "source_b"} or any(
        c["schema"] == "quest_digital" for c in classified
    )
    users_present = any(
        c["schema"] == "public" and c["relation"] == "users" for c in classified
    )
    consult_present = any(
        c["schema"] == "public" and c["relation"] == "consultations" for c in classified
    )
    anchors_ok = (users_present and consult_present) if require_b_anchors else True
    classified_keys = {(c["schema"], c["relation"]) for c in classified}

    def _reg_applies(reg: dict[str, Any]) -> bool:
        rel = reg.get("relation") or ""
        if "." not in rel:
            return False
        schema, name = rel.split(".", 1)
        key = (schema, name)
        # Only enforce when the relation exists in this inventory
        if key not in classified_keys:
            return False
        return True

    return {
        "version": VERSION,
        "CURATED_DOMAIN_CLASSIFICATION_STATUS": (
            "PASS"
            if all(r["ok"] for r in regressions if _reg_applies(r))
            and not dup_primary
            and anchors_ok
            else "FAIL"
        ),
        "n_classified": len(classified),
        "disposition_counts": disposition_counts,
        "primary_domain_uniqueness_violations": dup_primary,
        "source_b_users_observed": users_present,
        "source_b_consultations_observed": consult_present,
        "regex_false_positive_regressions": regressions,
        "relations": classified,
        "ok": all(r["ok"] for r in regressions if _reg_applies(r))
        and not dup_primary
        and anchors_ok,
    }
