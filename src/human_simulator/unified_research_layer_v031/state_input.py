"""State-input layer — not individual states."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_research_layer_v031.policy import VERSION


def build_state_input_layer(*, materialization: dict[str, Any]) -> dict[str, Any]:
    ds = materialization.get("datasets") or {}
    required = [
        "research_observation",
        "research_observation_component",
        "research_diagnosis",
        "research_medication_record",
        "research_recommendation",
        "research_encounter",
        "research_event",
        "research_provenance",
    ]
    availability = {
        name: {
            "rows": (ds.get(name) or {}).get("rows") or 0,
            "file_exists": (ds.get(name) or {}).get("exists") or False,
        }
        for name in required
    }
    built = all(v["file_exists"] for v in availability.values()) and (
        availability["research_observation"]["rows"] > 0
        and availability["research_event"]["rows"] > 0
    )
    return {
        "version": VERSION,
        "UNIFIED_STATE_INPUT_LAYER_STATUS": "BUILT" if built else "FAIL",
        "INDIVIDUAL_STATE_DATASET_STATUS": "NOT_STARTED",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "n_individual_state_records": 0,
        "cutoff_x_subject_states_created": False,
        "feature_availability_inventory": availability,
        "missingness_metadata": {
            "diagnosis_patient_facts": "ABSENT_STRUCTURED",
            "medication_administration": "NOT_CLAIMED",
            "recommendation_body_text": "EXCLUDED_PRIVACY",
        },
        "source_specific_semantic_keys_present": True,
        "accepted_shared_keys": 0,
        "ok": built,
    }
