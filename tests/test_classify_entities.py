"""Tests for clinical entity candidate classification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from human_simulator.classify.entities import (
    ClassifyEntitiesError,
    classify_clinical_entities,
    classify_from_artifacts,
)


@pytest.fixture
def schema_profile() -> dict:
    return {
        "relations": [
            {"schema": "public", "name": "patients", "kind": "table"},
            {"schema": "public", "name": "visits", "kind": "table"},
            {"schema": "public", "name": "lab_results", "kind": "table"},
            {"schema": "public", "name": "alembic_version", "kind": "table"},
            {"schema": "public", "name": "misc_data", "kind": "table"},
        ],
        "columns": [
            {"schema": "public", "relation": "patients", "name": "id", "data_type": "integer"},
            {"schema": "public", "relation": "visits", "name": "patient_id", "data_type": "integer"},
            {"schema": "public", "relation": "lab_results", "name": "visit_id", "data_type": "integer"},
        ],
        "foreign_keys": [
            {
                "schema_name": "public",
                "relation_name": "visits",
                "column_name": "patient_id",
                "foreign_schema": "public",
                "foreign_table": "patients",
                "foreign_column": "id",
            },
            {
                "schema_name": "public",
                "relation_name": "lab_results",
                "column_name": "visit_id",
                "foreign_schema": "public",
                "foreign_table": "visits",
                "foreign_column": "id",
            },
        ],
    }


def test_classify_creates_candidate_artifacts(tmp_path: Path, schema_profile: dict) -> None:
    artifacts_dir = tmp_path / "artifacts" / "stage-01"
    result = classify_clinical_entities(schema_profile, artifacts_dir)

    assert (artifacts_dir / "entity-candidates.yaml").exists()
    assert (artifacts_dir / "relation-graph.md").exists()
    assert (artifacts_dir / "unknown-semantics.md").exists()

    patients = result["entity_types"]["patients"]
    assert any(item["relation"] == "patients" for item in patients)
    visits = next(item for item in result["entity_types"]["visits"] if item["relation"] == "visits")
    assert visits["status"] == "CONFIRMED"
    assert any(ev["type"] == "foreign_key" for ev in visits["evidence"])

    patient_candidate = next(item for item in patients if item["relation"] == "patients")
    assert patient_candidate["status"] == "CONFIRMED"
    assert any(ev["type"] == "foreign_key" for ev in patient_candidate["evidence"])

    unknown = {item["relation"] for item in result["unknown_relations"]}
    assert "misc_data" in unknown
    assert "alembic_version" not in unknown


def test_name_only_match_is_likely_not_confirmed(tmp_path: Path) -> None:
    profile = {
        "relations": [{"schema": "public", "name": "doctors", "kind": "table"}],
        "columns": [],
        "foreign_keys": [],
    }
    result = classify_clinical_entities(profile, tmp_path)
    doctor = result["entity_types"]["doctors"][0]
    assert doctor["status"] == "LIKELY"


def test_classify_from_artifacts(tmp_path: Path, schema_profile: dict) -> None:
    artifacts_dir = tmp_path / "artifacts" / "stage-01"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "schema-profile.json").write_text(json.dumps(schema_profile), encoding="utf-8")
    result = classify_from_artifacts(tmp_path, artifacts_dir)
    assert result["entity_types"]["patients"]


def test_classify_from_artifacts_missing_profile(tmp_path: Path) -> None:
    with pytest.raises(ClassifyEntitiesError):
        classify_from_artifacts(tmp_path)


def test_relation_graph_contains_edges(tmp_path: Path, schema_profile: dict) -> None:
    artifacts_dir = tmp_path / "artifacts" / "stage-01"
    classify_clinical_entities(schema_profile, artifacts_dir)
    graph = (artifacts_dir / "relation-graph.md").read_text(encoding="utf-8")
    assert "mermaid" in graph
    assert "public.visits" in graph or "visits" in graph


def test_entity_candidates_yaml_is_valid(tmp_path: Path, schema_profile: dict) -> None:
    artifacts_dir = tmp_path / "artifacts" / "stage-01"
    classify_clinical_entities(schema_profile, artifacts_dir)
    payload = yaml.safe_load((artifacts_dir / "entity-candidates.yaml").read_text(encoding="utf-8"))
    assert "patients" in payload["entity_types"]
