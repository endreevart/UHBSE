"""Regression tests for data_level assignment and crosswalk compatibility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from human_simulator.classify.data_levels import (
    assign_data_level,
    data_levels_compatible,
)
from human_simulator.classify.entities import classify_clinical_entities
from human_simulator.stage01.settings import MAGERYA_APPLICATION_SCHEMAS
from human_simulator.stage02.compare_source_audits import (
    _build_entity_crosswalk,
    _count_unique_candidate_relations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
KGZ_PROFILE = REPO_ROOT / "artifacts" / "stage-02" / "schema-profile-kgz.json"


def _candidate(result: dict, schema: str, relation: str, entity_type: str) -> dict | None:
    for item in result["entity_types"].get(entity_type, []):
        if item["schema"] == schema and item["relation"] == relation:
            return item
    return None


def _role_classified(result: dict, schema: str, relation: str) -> dict | None:
    for item in result.get("role_classified_relations", []):
        if item["schema"] == schema and item["relation"] == relation:
            return item
    return None


def test_reference_catalog_incompatible_with_patient_event() -> None:
    assert not data_levels_compatible("REFERENCE_CATALOG", "PATIENT_EVENT")
    assert not data_levels_compatible("REFERENCE_CATALOG", "OBSERVATION_VALUE")
    assert data_levels_compatible("REFERENCE_CATALOG", "REFERENCE_CATALOG")


def test_observation_header_value_compatible() -> None:
    assert data_levels_compatible("OBSERVATION_HEADER", "OBSERVATION_VALUE")


@pytest.mark.parametrize(
    ("schema", "relation", "role", "expected_level"),
    [
        ("magerya_api", "diagnosis_diagnosis", "REFERENCE", "REFERENCE_CATALOG"),
        ("magerya_api", "document_analysisresult", "OBSERVATION", "OBSERVATION_HEADER"),
        ("magerya_api", "document_analysisresultitem", "OBSERVATION", "OBSERVATION_VALUE"),
        ("quest_digital", "analyses_pool", "WORKFLOW", "WORKFLOW"),
        ("quest_digital", "lab_result", "OBSERVATION", "PAYLOAD"),
        ("public", "profilaxys_analyses", "OBSERVATION", "OBSERVATION_VALUE"),
    ],
)
def test_data_level_overrides(schema: str, relation: str, role: str, expected_level: str) -> None:
    assert assign_data_level(schema, relation, role) == expected_level


def test_source_a_diagnosis_catalogs_not_entity_candidates(tmp_path: Path) -> None:
    profile = {
        "database": "magerya_api",
        "relations": [
            {"schema": "magerya_api", "name": name, "kind": "table"}
            for name in (
                "diagnosis_diagnosis",
                "diagnosis_medicines",
                "diagnosis_functionalstudies",
                "diagnosis_manipulations",
                "diagnosis_procedures",
            )
        ],
        "columns": [],
        "foreign_keys": [],
    }
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    for entity_items in result["entity_types"].values():
        for item in entity_items:
            assert item["relation"] not in {
                "diagnosis_diagnosis",
                "diagnosis_medicines",
                "diagnosis_functionalstudies",
                "diagnosis_manipulations",
                "diagnosis_procedures",
            }

    medicines = _role_classified(result, "magerya_api", "diagnosis_medicines")
    assert medicines is not None
    assert medicines["role"] == "REFERENCE"
    assert medicines["data_level"] == "REFERENCE_CATALOG"
    assert medicines["clinical_domain"] == "medications"


def test_source_a_analysis_result_header_and_item(tmp_path: Path) -> None:
    profile = {
        "database": "magerya_api",
        "relations": [
            {"schema": "magerya_api", "name": "document_analysisresult", "kind": "table"},
            {"schema": "magerya_api", "name": "document_analysisresultitem", "kind": "table"},
        ],
        "columns": [],
        "foreign_keys": [
            {
                "schema_name": "magerya_api",
                "relation_name": "document_analysisresultitem",
                "column_name": "analysis_result_id",
                "foreign_schema": "magerya_api",
                "foreign_table": "document_analysisresult",
                "foreign_column": "id",
            }
        ],
    }
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    header = _candidate(result, "magerya_api", "document_analysisresult", "laboratory_results")
    item = _candidate(result, "magerya_api", "document_analysisresultitem", "laboratory_results")
    assert header is not None
    assert item is not None
    assert header["data_level"] == "OBSERVATION_HEADER"
    assert item["data_level"] == "OBSERVATION_VALUE"
    assert any(ev["type"] == "structural_fk" for ev in item["evidence"])


@pytest.mark.skipif(not KGZ_PROFILE.exists(), reason="schema-profile-kgz.json not present")
def test_source_b_lab_classifications() -> None:
    profile = json.loads(KGZ_PROFILE.read_text(encoding="utf-8"))
    result = classify_clinical_entities(profile, REPO_ROOT / "artifacts" / "stage-02")

    profilaxys = _candidate(result, "public", "profilaxys_analyses", "measurements")
    assert profilaxys is not None
    assert _candidate(result, "public", "profilaxys_analyses", "laboratory_results") is None
    assert profilaxys["data_level"] == "OBSERVATION_VALUE"

    pool = _role_classified(result, "quest_digital", "analyses_pool")
    assert pool is not None
    assert pool["role"] == "WORKFLOW"
    assert pool["data_level"] == "WORKFLOW"

    constructor = _candidate(result, "quest_digital", "analyses_constructor", "laboratory_results")
    assert constructor is not None
    assert constructor["data_level"] == "OBSERVATION_VALUE"

    lab_result = _candidate(result, "quest_digital", "lab_result", "laboratory_results")
    assert lab_result is not None
    assert lab_result["data_level"] == "PAYLOAD"
    assert any(ev.get("type") == "snapshot_note" for ev in lab_result["evidence"])


def test_crosswalk_includes_data_levels_and_blocks_reference(tmp_path: Path) -> None:
    candidates_a = {
        "entity_types": {
            "diagnoses": [
                {
                    "schema": "magerya_api",
                    "relation": "diagnosis_diagnosis",
                    "role": "REFERENCE",
                    "data_level": "REFERENCE_CATALOG",
                    "status": "CANDIDATE",
                }
            ],
            "laboratory_results": [
                {
                    "schema": "magerya_api",
                    "relation": "document_analysisresult",
                    "role": "OBSERVATION",
                    "data_level": "OBSERVATION_HEADER",
                    "status": "CANDIDATE",
                }
            ],
        }
    }
    candidates_b = {
        "entity_types": {
            "laboratory_results": [
                {
                    "schema": "quest_digital",
                    "relation": "analyses_constructor",
                    "role": "OBSERVATION",
                    "data_level": "OBSERVATION_VALUE",
                    "status": "CANDIDATE",
                }
            ]
        }
    }
    crosswalk = _build_entity_crosswalk(candidates_a, candidates_b, {}, {})
    lab_mapping = crosswalk["entity_types"]["laboratory_results"]["mappings"][0]
    assert lab_mapping["source_a_data_level"] == "OBSERVATION_HEADER"
    assert lab_mapping["source_b_data_level"] == "OBSERVATION_VALUE"


def test_unique_candidate_relations_count() -> None:
    payload = {
        "entity_types": {
            "visits": [{"schema": "public", "relation": "consultations"}],
            "appointments": [{"schema": "public", "relation": "consultations"}],
        }
    }
    assert _count_unique_candidate_relations(payload) == 1
    assert sum(len(v) for v in payload["entity_types"].values()) == 2
