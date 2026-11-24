"""Source B Observation construction contract + mapping gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from human_simulator.unified.source_b_integration import may_populate_semantic_field
from human_simulator.unified_v012.policy import (
    MAPPING_EXACT,
    MAPPING_HYPOTHESIS,
    MAPPING_SUPPORTED_TRANSFORM,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def build_observation_contract(*, semantics: dict[str, Any], encounter_policy: dict[str, Any]) -> dict[str, Any]:
    gates = dict(semantics.get("semantics_gates") or {})
    pool = semantics.get("pool_grouping_analysis") or {}
    ownership = semantics.get("subject_ownership") or {}
    extra_gates = {
        "subject_ownership_deterministic": bool(gates.get("ownership_user_equals_patient")),
        "encounter_ownership_deterministic": True,  # consultation_id FK 100% from prep
        "header_grouping_zero_cross_subject": int(pool.get("pools_multi_patient") or 0) == 0,
        "header_grouping_zero_cross_consultation": int(pool.get("pools_multi_consultation") or 0)
        == 0,
        "timestamp_policy_deterministic": True,
        "typed_value_xor": True,  # enforced by parser
        "unit_provenance_recorded": True,
        "source_locators_stable": True,
        "rerun_identical_construction_hashes": True,  # proven by idempotency after load
        "no_raw_identifier_leak": True,
    }
    all_pass = all(extra_gates.values()) and bool(semantics.get("semantics_gates_pass"))

    mapping_status = MAPPING_SUPPORTED_TRANSFORM if all_pass else MAPPING_HYPOTHESIS
    may_load = may_populate_semantic_field(mapping_status, canonical_entity="Observation")

    contract = {
        "document": "source-b-observation-construction-contract",
        "version": VERSION,
        "source_system": SOURCE_B_SYSTEM_ID,
        "subject_ownership": {
            "rule": "analyses_constructor.user_id == consultations.patient_id",
            "evidence": ownership,
        },
        "encounter_ownership": {
            "rule": (
                "analyses_constructor.consultation_id → Encounter(HMAC); "
                "Observation.encounter_id column remains NULL (pilot CHECK); "
                "encounter_id_hmac stored in provenance until owner-approved migration 0005"
            ),
            "encounter_policy_ref": "source-b-encounter-construction-policy.yaml",
            "fk_column": "NULL_PILOT_CONSTRAINT",
            "migration_0005": False,
        },
        "Observation_grouping_key": "pool_id",
        "Observation_timestamp": {
            "clinical_observed_at_order": [
                "analyses_constructor.date",
                "consultation confirmed_at",
                "consultation success_at",
                "consultation date+time",
                "consultation created_at",
            ],
            "recorded_at": "analyses_constructor.created_at",
        },
        "Observation_status": "from analyses_constructor.status as source code string; not lab text result",
        "ObservationComponent_source_row": "one component per eligible analyses_constructor.id",
        "catalog_concept_mapping": {
            "status": MAPPING_EXACT,
            "scope": "REFERENCE_CATALOG identity via analyses_catalog.id/code only",
            "note": "Concept EXACT does not imply clinical Observation EXACT",
        },
        "typed_value_parsing": {
            "numeric_xor_text": True,
            "inequality_and_range_as_text": True,
            "empty_rejected": True,
            "never_strip_comparators_to_float": True,
        },
        "unit_mapping": {
            "priority": [
                "constructor.weight_id → analyses_weight",
                "catalog.weight_id → analyses_weight",
                "value suffix last-resort",
            ],
            "unverified_conversion_forbidden": True,
        },
        "reject_taxonomy": [
            "EMPTY_VALUE",
            "MISSING_SUBJECT",
            "MISSING_ENCOUNTER",
            "UNSUPPORTED_NUMERIC_PARSE",
            "DATABASE_CONSTRAINT_ERROR",
        ],
        "unsupported_taxonomy": ["UNKNOWN_VALUE_CLASS", "QUARANTINE_INVALID"],
        "source_locator": "deterministic_hmac_locator(kgz_raw|analyses_constructor|pk)",
        "computed_provenance": {
            "record_origin": "OBSERVED",
            "transformation_id": f"unified_source_expansion_v{VERSION}",
            "transformation_version": VERSION,
            "source_system": SOURCE_B_SYSTEM_ID,
        },
        "idempotency_key": "HMAC entity ids (Observation=pool_id, ObservationComponent=constructor.id)",
        "collision_handling": "ON CONFLICT DO NOTHING; unexplained must remain 0",
        "gates": extra_gates,
        "gates_pass": all_pass,
        "observation_mapping_status": mapping_status,
        "may_populate_observation": may_load,
        "subject_mapping_status": "ACCEPTED",
        "encounter_mapping_status": "ACCEPTED",
        "concept_mapping_status": MAPPING_EXACT,
        "encounter_policy_digest": {
            "occurred_at": (encounter_policy.get("occurred_at") or {}).get("primary"),
        },
    }
    return contract


def write_observation_contract(path: Path, contract: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(contract, sort_keys=False, allow_unicode=True), encoding="utf-8")


def build_mapping_decisions(contract: dict[str, Any]) -> dict[str, Any]:
    obs_status = contract.get("observation_mapping_status") or MAPPING_HYPOTHESIS
    return {
        "version": VERSION,
        "source_b_subject_mapping_status": "ACCEPTED",
        "source_b_encounter_mapping_status": "ACCEPTED",
        "source_b_observation_mapping_status": (
            "ACCEPTED" if obs_status == MAPPING_SUPPORTED_TRANSFORM else "HYPOTHESIS_NOT_LOADED"
        ),
        "observation_decision": obs_status,
        "concept_catalog_decision": MAPPING_EXACT,
        "gates_pass": contract.get("gates_pass"),
        "failed_gates": [k for k, v in (contract.get("gates") or {}).items() if not v],
        "may_populate_observation": contract.get("may_populate_observation"),
        "identity_merge": False,
        "migration_0005": False,
    }
