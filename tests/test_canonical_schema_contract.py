"""Static contract tests for the canonical pilot schema.

These run without a database. They prove that the declared contract matches the accepted
design and plan artifacts and never widens the pilot scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from human_simulator.canonical.constants import (
    CANONICAL_DATABASE,
    CANONICAL_PORT,
    CANONICAL_POSTGRES_VERSION,
    CANONICAL_ROLES,
    CANONICAL_SCHEMA,
    CANONICAL_VOLUME,
    DATA_LEVEL_VALUES,
    FORBIDDEN_COLUMN_NAMES,
    MAPPING_STATUS_VALUES,
    PILOT_ENTITY_LOAD_ORDER,
    PILOT_NULL_ONLY_COLUMNS,
    PILOT_TABLE_LOAD_ORDER,
    SUBJECT_CHARACTERISTIC_TYPED_VALUE_COLUMNS,
)
from human_simulator.canonical.schema_contract import (
    EXPECTED_ENUMS,
    PILOT_TABLES,
    TABLES_BY_NAME,
    contract_document,
    contract_fingerprint,
    load_order_violations,
)

DESIGN_DIR = Path("artifacts") / "stage-03"
IMPL_DIR = Path("artifacts") / "stage-03-implementation"


@pytest.fixture
def canonical_model(repo_root: Path) -> dict:
    return yaml.safe_load((repo_root / DESIGN_DIR / "canonical-model.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def pilot_slice(repo_root: Path) -> dict:
    return yaml.safe_load((repo_root / IMPL_DIR / "pilot-slice.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def pipeline_plan(repo_root: Path) -> dict:
    return yaml.safe_load((repo_root / IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def storage_plan(repo_root: Path) -> dict:
    return yaml.safe_load(
        (repo_root / IMPL_DIR / "physical-storage-plan.yaml").read_text(encoding="utf-8")
    )


def test_contract_covers_exactly_the_pilot_table_entities(pilot_slice: dict) -> None:
    declared = {
        entry["entity"]
        for entry in pilot_slice["pilot_entities"]
        if entry.get("table_entity") is True
    }
    assert declared == set(PILOT_ENTITY_LOAD_ORDER)
    assert {table.entity for table in PILOT_TABLES} == declared
    assert len(PILOT_TABLES) == 7


def test_provenance_is_embedded_and_has_no_table(pilot_slice: dict) -> None:
    provenance = next(e for e in pilot_slice["pilot_entities"] if e["entity"] == "Provenance")
    assert provenance["table_entity"] is False
    assert provenance["embedded"] is True
    assert "provenance" not in TABLES_BY_NAME


def test_no_entity_outside_pilot_scope_has_a_table(canonical_model: dict) -> None:
    model_entities = set(canonical_model["entities"])
    out_of_scope = model_entities - set(PILOT_ENTITY_LOAD_ORDER) - {"Provenance"}
    contract_entities = {table.entity for table in PILOT_TABLES}
    assert not (out_of_scope & contract_entities)


def test_every_contract_column_exists_in_the_canonical_model(canonical_model: dict) -> None:
    for table in PILOT_TABLES:
        declared = set(canonical_model["entities"][table.entity]["fields"])
        for column in table.columns:
            assert column.name in declared, f"{table.entity}.{column.name} is not in the model"


def test_every_model_field_has_a_column(canonical_model: dict) -> None:
    for table in PILOT_TABLES:
        for field in canonical_model["entities"][table.entity]["fields"]:
            assert table.column(field) is not None, f"{table.entity}.{field} has no column"


def test_provenance_requirement_matches_the_model(canonical_model: dict) -> None:
    for table in PILOT_TABLES:
        expected = canonical_model["entities"][table.entity]["requires_provenance"]
        assert table.requires_provenance is expected
        if expected:
            column = table.column("provenance")
            assert column is not None and column.data_type == "jsonb" and not column.nullable
        else:
            assert table.column("provenance") is None


def test_nullability_matches_the_model(canonical_model: dict) -> None:
    for table in PILOT_TABLES:
        fields = canonical_model["entities"][table.entity]["fields"]
        for column in table.columns:
            if column.name == "provenance":
                continue
            assert column.nullable is bool(fields[column.name]["nullable"])


def test_temporal_columns_are_timezone_aware() -> None:
    for table in PILOT_TABLES:
        for column in table.columns:
            if column.name.endswith("_at"):
                assert column.data_type == "timestamp with time zone"


def test_no_forbidden_identifier_column_exists() -> None:
    for table in PILOT_TABLES:
        for column in table.columns:
            assert column.name not in FORBIDDEN_COLUMN_NAMES


def test_subject_identity_is_source_local_only(canonical_model: dict) -> None:
    identity = canonical_model["entities"]["Subject"]["identity"]
    assert identity["scope"] == "source_local"
    assert identity["key"] == ["source_system_id", "source_subject_key"]
    subject = TABLES_BY_NAME["subject"]
    assert any(
        columns == ("source_system_id", "source_subject_key")
        for _, columns in subject.unique_constraints
    )


def test_source_locator_is_unique() -> None:
    source_record = TABLES_BY_NAME["source_record"]
    assert any(
        columns == ("source_record_locator",) for _, columns in source_record.unique_constraints
    )


def test_every_pilot_table_has_a_single_column_canonical_primary_key() -> None:
    for table in PILOT_TABLES:
        assert len(table.primary_key) == 1


def test_foreign_keys_match_the_accepted_fk_dependencies(pipeline_plan: dict) -> None:
    expected = {
        "subject.source_system_id": "source_system.source_system_id",
        "subject_characteristic.subject_id": "subject.subject_id",
        "encounter.subject_id": "subject.subject_id",
        "observation.subject_id": "subject.subject_id",
        "observation_component.observation_id": "observation.observation_id",
    }
    actual = {
        f"{table.name}.{fk.columns[0]}": f"{fk.referenced_table}.{fk.referenced_columns[0]}"
        for table in PILOT_TABLES
        for fk in table.foreign_keys
    }
    # source_record.source_system_id is required by the canonical model relationships and is
    # not listed in fk_dependencies, which only enumerates the clinical load dependencies.
    assert actual.pop("source_record.source_system_id") == "source_system.source_system_id"
    assert actual == expected

    deferred = {
        key
        for key, value in pipeline_plan["fk_dependencies"].items()
        if value == "deferred_null_for_pilot"
    }
    assert deferred == {"Encounter.provider_id", "Observation.encounter_id"}


def test_deferred_and_out_of_scope_references_have_no_foreign_key() -> None:
    for table_name, columns in PILOT_NULL_ONLY_COLUMNS.items():
        table = TABLES_BY_NAME[table_name]
        fk_columns = {column for fk in table.foreign_keys for column in fk.columns}
        for column in columns:
            assert column not in fk_columns
            assert column in table.null_only_columns


def test_load_order_has_no_violation_and_matches_the_plan(pipeline_plan: dict) -> None:
    assert load_order_violations() == []
    plan_entities = [
        entry["entity"]
        for entry in pipeline_plan["table_load_order"]
        if entry.get("kind") != "technical_metadata"
    ]
    assert plan_entities == list(PILOT_ENTITY_LOAD_ORDER)


def test_subject_characteristic_typed_value_constraint_matches_the_model(canonical_model: dict) -> None:
    expected = canonical_model["constraints"]["subject_characteristic_value_constraint"][
        "exactly_one_typed_value"
    ]
    assert list(SUBJECT_CHARACTERISTIC_TYPED_VALUE_COLUMNS) == expected
    table = TABLES_BY_NAME["subject_characteristic"]
    assert "subject_characteristic_typed_value_xor" in table.check_constraints


def test_subject_characteristic_identity_is_not_xor(canonical_model: dict) -> None:
    identity = canonical_model["constraints"]["subject_characteristic_identity"]
    assert identity["both_allowed"] is True
    assert identity["forbidden"] == "XOR-only identity constraint"
    table = TABLES_BY_NAME["subject_characteristic"]
    assert "subject_characteristic_identity_present" in table.check_constraints


def test_observation_component_typed_value_xor_is_not_invented(canonical_model: dict) -> None:
    assert "observation_component_value_constraint" not in canonical_model["constraints"]
    table = TABLES_BY_NAME["observation_component"]
    assert not any("typed_value_xor" in name for name in table.check_constraints)


def test_raw_value_is_preserved_on_subject_characteristic(canonical_model: dict) -> None:
    assert (
        canonical_model["constraints"]["subject_characteristic_value_constraint"][
            "raw_value_preserved"
        ]
        is True
    )
    column = TABLES_BY_NAME["subject_characteristic"].column("raw_value")
    assert column is not None and not column.nullable


def test_enum_values_come_from_the_accepted_artifacts(canonical_model: dict, repo_root: Path) -> None:
    assert list(DATA_LEVEL_VALUES) == canonical_model["data_level_enum"]
    provenance = yaml.safe_load(
        (repo_root / DESIGN_DIR / "provenance-contract.yaml").read_text(encoding="utf-8")
    )
    assert list(MAPPING_STATUS_VALUES) == provenance["mapping_status_values"]
    assert set(EXPECTED_ENUMS) == {"canonical_data_level", "canonical_mapping_status"}


def test_topology_matches_the_physical_storage_plan(storage_plan: dict) -> None:
    topology = storage_plan["planned_topology"]
    assert topology["database_name"] == CANONICAL_DATABASE
    assert topology["schema_name"] == CANONICAL_SCHEMA
    assert topology["postgresql_version"] == CANONICAL_POSTGRES_VERSION
    assert topology["local_container"]["port"] == CANONICAL_PORT
    assert topology["local_container"]["volume"] == CANONICAL_VOLUME


def test_roles_match_the_physical_storage_plan(storage_plan: dict) -> None:
    planned = set(storage_plan["database_roles"]) - {"mg_audit_ro"}
    assert planned == set(CANONICAL_ROLES)


def test_separate_provenance_table_is_forbidden(storage_plan: dict) -> None:
    assert storage_plan["provenance_storage"]["embedded_jsonb"] is True
    assert storage_plan["provenance_storage"]["separate_provenance_table"] == "forbidden_in_pilot"


def test_contract_fingerprint_is_deterministic() -> None:
    assert contract_fingerprint() == contract_fingerprint()
    assert len(contract_fingerprint()) == 64


def test_contract_document_lists_the_pilot_load_order() -> None:
    document = contract_document()
    assert document["table_load_order"] == list(PILOT_TABLE_LOAD_ORDER)
    assert document["schema"] == CANONICAL_SCHEMA
    assert len(document["tables"]) == 7
