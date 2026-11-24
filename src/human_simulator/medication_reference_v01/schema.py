"""Separated medication concept schema (design + runtime records)."""

from __future__ import annotations

from typing import Any, Literal

EntityKind = Literal[
    "SourceMedicationRecord",
    "MedicationProductConcept",
    "IngredientConcept",
    "Strength",
    "DoseForm",
    "Route",
    "DrugClass",
    "ExposureEvent",
    "AdministrationEvent",
    "Intervention",
]

SCHEMA_INVARIANTS = {
    "table_join_is_not_drug_harmonization": True,
    "brand_is_not_ingredient_without_evidence": True,
    "prescription_is_not_administration": True,
    "free_text_dose_route_frequency_not_accepted": True,
    "ddd_is_not_individual_dose": True,
    "multi_ingredient_must_preserve_components": True,
    "administration_event_supported_in_source_a": False,
    "intervention_supported_from_source_a_rows": False,
}


def schema_document() -> dict[str, Any]:
    return {
        "entities": [
            {
                "kind": "SourceMedicationRecord",
                "fields": ["source_system", "medicine_id", "name", "description"],
                "note": "Local clinic catalog row",
            },
            {
                "kind": "MedicationProductConcept",
                "fields": ["product_id", "brand_or_clinical_name", "provider", "snapshot_hash"],
            },
            {
                "kind": "IngredientConcept",
                "fields": ["ingredient_id", "name", "provider", "snapshot_hash"],
            },
            {
                "kind": "Strength",
                "fields": ["value", "unit"],
                "accepted_only_with_provider_evidence": True,
            },
            {"kind": "DoseForm", "fields": ["code_or_label", "provider"]},
            {"kind": "Route", "fields": ["code_or_label", "provider"]},
            {
                "kind": "DrugClass",
                "fields": ["system", "code", "provider"],
                "example": "ATC",
            },
            {
                "kind": "ExposureEvent",
                "fields": ["source_medicine_id", "timestamp_hypothesis"],
                "note": "Recorded association only",
            },
            {
                "kind": "AdministrationEvent",
                "supported": False,
                "note": "Not confirmed in current Source A data",
            },
            {
                "kind": "Intervention",
                "supported": False,
                "note": "Not confirmed from these rows",
            },
        ],
        "invariants": SCHEMA_INVARIANTS,
    }
