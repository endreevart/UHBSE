"""Declarative schema contract for the canonical pilot storage.

The contract is the fail-closed authority for Changeset 01: applying the migrations must
produce exactly this shape. Any extra table, missing column, changed type, changed
nullability, missing constraint or missing index is a contract violation.

Every entry traces to artifacts/stage-03/canonical-model.yaml and the accepted
implementation plan v0.3.5. Nothing here may introduce a field the design does not define.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from human_simulator.canonical.constants import (
    CANONICAL_SCHEMA,
    DATA_LEVEL_ENUM_NAME,
    DATA_LEVEL_VALUES,
    EXPECTED_TABLE_OWNER,
    HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES,
    MAPPING_STATUS_ENUM_NAME,
    MAPPING_STATUS_VALUES,
    PILOT_TABLE_LOAD_ORDER,
)

PROVENANCE_CHECK_SUFFIX = "provenance_profile_valid"


def _hardened_provenance_checks(table: str) -> tuple[str, ...]:
    """Constraint names added by migration 0004 to every provenance-bearing table."""
    return tuple(f"{table}{suffix}" for suffix in HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES)


@dataclass(frozen=True)
class ColumnContract:
    name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True)
class ForeignKeyContract:
    name: str
    columns: tuple[str, ...]
    referenced_table: str
    referenced_columns: tuple[str, ...]


@dataclass(frozen=True)
class TableContract:
    name: str
    entity: str
    requires_provenance: bool
    columns: tuple[ColumnContract, ...]
    primary_key: tuple[str, ...]
    unique_constraints: tuple[tuple[str, tuple[str, ...]], ...] = ()
    foreign_keys: tuple[ForeignKeyContract, ...] = ()
    check_constraints: tuple[str, ...] = ()
    indexes: tuple[str, ...] = ()
    null_only_columns: tuple[str, ...] = field(default=())

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def column(self, name: str) -> ColumnContract | None:
        for column in self.columns:
            if column.name == name:
                return column
        return None


def _provenance_column() -> ColumnContract:
    return ColumnContract("provenance", "jsonb", nullable=False)


SOURCE_SYSTEM = TableContract(
    name="source_system",
    entity="SourceSystem",
    requires_provenance=False,
    columns=(
        ColumnContract("source_system_id", "text", nullable=False),
        ColumnContract("source_label", "text", nullable=False),
        ColumnContract("audit_stage_reference", "text", nullable=True),
    ),
    primary_key=("source_system_id",),
    check_constraints=(
        "source_system_id_not_blank",
        "source_system_label_not_blank",
    ),
)

SOURCE_RECORD = TableContract(
    name="source_record",
    entity="SourceRecord",
    requires_provenance=True,
    columns=(
        ColumnContract("source_record_id", "text", nullable=False),
        ColumnContract("source_system_id", "text", nullable=False),
        ColumnContract("source_schema", "text", nullable=False),
        ColumnContract("source_relation", "text", nullable=False),
        ColumnContract("source_record_locator", "text", nullable=False),
        ColumnContract("locator_scheme", "text", nullable=False),
        ColumnContract("locator_key_version", "text", nullable=False),
        ColumnContract("source_created_at", "timestamp with time zone", nullable=True),
        ColumnContract("source_updated_at", "timestamp with time zone", nullable=True),
        _provenance_column(),
    ),
    primary_key=("source_record_id",),
    unique_constraints=(("source_record_locator_unique", ("source_record_locator",)),),
    foreign_keys=(
        ForeignKeyContract(
            "source_record_source_system_fkey",
            ("source_system_id",),
            "source_system",
            ("source_system_id",),
        ),
    ),
    check_constraints=(
        "source_record_locator_scheme_allowed",
        "source_record_locator_not_blank",
        "source_record_key_version_not_blank",
        "source_record_provenance_profile_valid",
        *_hardened_provenance_checks("source_record"),
        "source_record_provenance_matches_columns",
    ),
    indexes=("source_record_source_relation_idx",),
)

SUBJECT = TableContract(
    name="subject",
    entity="Subject",
    requires_provenance=True,
    columns=(
        ColumnContract("subject_id", "text", nullable=False),
        ColumnContract("source_system_id", "text", nullable=False),
        ColumnContract("source_subject_key", "text", nullable=False),
        ColumnContract("subject_role_hint", "text", nullable=True),
        _provenance_column(),
    ),
    primary_key=("subject_id",),
    unique_constraints=(
        (
            "subject_source_local_identity_unique",
            ("source_system_id", "source_subject_key"),
        ),
    ),
    foreign_keys=(
        ForeignKeyContract(
            "subject_source_system_fkey",
            ("source_system_id",),
            "source_system",
            ("source_system_id",),
        ),
    ),
    check_constraints=(
        "subject_source_subject_key_not_blank",
        "subject_provenance_profile_valid",
        *_hardened_provenance_checks("subject"),
    ),
)

SUBJECT_CHARACTERISTIC = TableContract(
    name="subject_characteristic",
    entity="SubjectCharacteristic",
    requires_provenance=True,
    columns=(
        ColumnContract("characteristic_id", "text", nullable=False),
        ColumnContract("subject_id", "text", nullable=False),
        ColumnContract("characteristic_code", "text", nullable=True),
        ColumnContract("concept_id", "text", nullable=True),
        ColumnContract("raw_code", "text", nullable=False),
        ColumnContract("raw_value", "text", nullable=False),
        ColumnContract("date_value", "date", nullable=True),
        ColumnContract("numeric_value", "numeric", nullable=True),
        ColumnContract("text_value", "text", nullable=True),
        ColumnContract("categorical_value", "text", nullable=True),
        ColumnContract("boolean_value", "boolean", nullable=True),
        ColumnContract("raw_unit", "text", nullable=True),
        ColumnContract("normalized_unit", "text", nullable=True),
        ColumnContract("effective_at", "timestamp with time zone", nullable=True),
        ColumnContract("recorded_at", "timestamp with time zone", nullable=True),
        ColumnContract("status", MAPPING_STATUS_ENUM_NAME, nullable=False),
        _provenance_column(),
    ),
    primary_key=("characteristic_id",),
    foreign_keys=(
        ForeignKeyContract(
            "subject_characteristic_subject_fkey",
            ("subject_id",),
            "subject",
            ("subject_id",),
        ),
    ),
    check_constraints=(
        "subject_characteristic_identity_present",
        "subject_characteristic_typed_value_xor",
        "subject_characteristic_raw_value_preserved",
        "subject_characteristic_raw_code_not_blank",
        "subject_characteristic_concept_null_in_pilot",
        "subject_characteristic_normalized_unit_null_in_pilot",
        "subject_characteristic_provenance_profile_valid",
        *_hardened_provenance_checks("subject_characteristic"),
        "subject_characteristic_status_matches_provenance",
    ),
    indexes=("subject_characteristic_subject_idx",),
    null_only_columns=("concept_id", "normalized_unit"),
)

ENCOUNTER = TableContract(
    name="encounter",
    entity="Encounter",
    requires_provenance=True,
    columns=(
        ColumnContract("encounter_id", "text", nullable=False),
        ColumnContract("subject_id", "text", nullable=False),
        ColumnContract("provider_id", "text", nullable=True),
        ColumnContract("encounter_type", "text", nullable=True),
        ColumnContract("occurred_at", "timestamp with time zone", nullable=True),
        ColumnContract("recorded_at", "timestamp with time zone", nullable=True),
        ColumnContract("completed_at", "timestamp with time zone", nullable=True),
        ColumnContract("cancelled_at", "timestamp with time zone", nullable=True),
        ColumnContract("confirmed_at", "timestamp with time zone", nullable=True),
        ColumnContract("status", "text", nullable=True),
        ColumnContract("data_level", DATA_LEVEL_ENUM_NAME, nullable=False),
        ColumnContract("missingness_reason", "text", nullable=True),
        _provenance_column(),
    ),
    primary_key=("encounter_id",),
    foreign_keys=(
        ForeignKeyContract("encounter_subject_fkey", ("subject_id",), "subject", ("subject_id",)),
    ),
    check_constraints=(
        "encounter_provider_null_in_pilot",
        "encounter_missing_clinical_time_documented",
        "encounter_provenance_profile_valid",
        *_hardened_provenance_checks("encounter"),
    ),
    indexes=("encounter_subject_idx",),
    null_only_columns=("provider_id",),
)

OBSERVATION = TableContract(
    name="observation",
    entity="Observation",
    requires_provenance=True,
    columns=(
        ColumnContract("observation_id", "text", nullable=False),
        ColumnContract("subject_id", "text", nullable=False),
        ColumnContract("encounter_id", "text", nullable=True),
        ColumnContract("observed_at", "timestamp with time zone", nullable=True),
        ColumnContract("specimen_collected_at", "timestamp with time zone", nullable=True),
        ColumnContract("result_available_at", "timestamp with time zone", nullable=True),
        ColumnContract("recorded_at", "timestamp with time zone", nullable=True),
        ColumnContract("status", "text", nullable=True),
        ColumnContract("data_level", DATA_LEVEL_ENUM_NAME, nullable=False),
        ColumnContract("raw_code", "text", nullable=True),
        ColumnContract("normalized_concept", "text", nullable=True),
        ColumnContract("raw_value", "text", nullable=True),
        ColumnContract("raw_unit", "text", nullable=True),
        ColumnContract("normalized_unit", "text", nullable=True),
        ColumnContract("reference_range", "jsonb", nullable=True),
        ColumnContract("abnormal_flag", "text", nullable=True),
        ColumnContract("uncertainty", "jsonb", nullable=True),
        ColumnContract("missingness_reason", "text", nullable=True),
        _provenance_column(),
    ),
    primary_key=("observation_id",),
    foreign_keys=(
        ForeignKeyContract("observation_subject_fkey", ("subject_id",), "subject", ("subject_id",)),
    ),
    check_constraints=(
        "observation_encounter_null_in_pilot",
        "observation_normalized_concept_null_in_pilot",
        "observation_normalized_unit_null_in_pilot",
        "observation_missing_clinical_time_documented",
        "observation_reference_range_is_object",
        "observation_uncertainty_is_object",
        "observation_provenance_profile_valid",
        *_hardened_provenance_checks("observation"),
    ),
    indexes=("observation_subject_idx",),
    null_only_columns=("encounter_id", "normalized_concept", "normalized_unit"),
)

OBSERVATION_COMPONENT = TableContract(
    name="observation_component",
    entity="ObservationComponent",
    requires_provenance=True,
    columns=(
        ColumnContract("component_id", "text", nullable=False),
        ColumnContract("observation_id", "text", nullable=False),
        ColumnContract("raw_code", "text", nullable=True),
        ColumnContract("raw_value", "text", nullable=True),
        ColumnContract("numeric_value", "numeric", nullable=True),
        ColumnContract("text_value", "text", nullable=True),
        ColumnContract("categorical_value", "text", nullable=True),
        ColumnContract("boolean_value", "boolean", nullable=True),
        ColumnContract("raw_unit", "text", nullable=True),
        ColumnContract("normalized_unit", "text", nullable=True),
        ColumnContract("reference_range", "jsonb", nullable=True),
        ColumnContract("abnormal_flag", "text", nullable=True),
        ColumnContract("sequence_order", "integer", nullable=True),
        _provenance_column(),
    ),
    primary_key=("component_id",),
    foreign_keys=(
        ForeignKeyContract(
            "observation_component_observation_fkey",
            ("observation_id",),
            "observation",
            ("observation_id",),
        ),
    ),
    check_constraints=(
        "observation_component_normalized_unit_null_in_pilot",
        "observation_component_reference_range_is_object",
        "observation_component_sequence_order_non_negative",
        "observation_component_provenance_profile_valid",
        *_hardened_provenance_checks("observation_component"),
    ),
    indexes=("observation_component_observation_idx",),
    null_only_columns=("normalized_unit",),
)

PILOT_TABLES: tuple[TableContract, ...] = (
    SOURCE_SYSTEM,
    SOURCE_RECORD,
    SUBJECT,
    SUBJECT_CHARACTERISTIC,
    ENCOUNTER,
    OBSERVATION,
    OBSERVATION_COMPONENT,
)

TABLES_BY_NAME: dict[str, TableContract] = {table.name: table for table in PILOT_TABLES}

EXPECTED_ENUMS: dict[str, tuple[str, ...]] = {
    DATA_LEVEL_ENUM_NAME: DATA_LEVEL_VALUES,
    MAPPING_STATUS_ENUM_NAME: MAPPING_STATUS_VALUES,
}


def contract_document() -> dict[str, Any]:
    """Serializable contract used for fingerprinting and for schema reports."""
    return {
        "schema": CANONICAL_SCHEMA,
        "table_load_order": list(PILOT_TABLE_LOAD_ORDER),
        "expected_table_owner": EXPECTED_TABLE_OWNER,
        "enums": {name: list(values) for name, values in sorted(EXPECTED_ENUMS.items())},
        "tables": [
            {
                "table": table.name,
                "entity": table.entity,
                "requires_provenance": table.requires_provenance,
                "columns": [
                    {"name": c.name, "type": c.data_type, "nullable": c.nullable}
                    for c in table.columns
                ],
                "primary_key": list(table.primary_key),
                "unique_constraints": [
                    {"name": name, "columns": list(columns)}
                    for name, columns in table.unique_constraints
                ],
                "foreign_keys": [
                    {
                        "name": fk.name,
                        "columns": list(fk.columns),
                        "references": {
                            "table": fk.referenced_table,
                            "columns": list(fk.referenced_columns),
                        },
                    }
                    for fk in table.foreign_keys
                ],
                "check_constraints": list(table.check_constraints),
                "indexes": list(table.indexes),
                "null_only_columns_in_pilot": list(table.null_only_columns),
            }
            for table in PILOT_TABLES
        ],
    }


def contract_fingerprint() -> str:
    payload = json.dumps(contract_document(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_order_violations() -> list[str]:
    """Foreign keys that would be unsatisfiable under pipeline-plan table_load_order.

    A referenced table must be loaded strictly before the referencing table, so it must
    appear earlier in PILOT_TABLE_LOAD_ORDER. Self references are not used in the pilot.
    """
    position = {name: index for index, name in enumerate(PILOT_TABLE_LOAD_ORDER)}
    violations: list[str] = []
    for table in PILOT_TABLES:
        for fk in table.foreign_keys:
            if fk.referenced_table not in position:
                violations.append(
                    f"{table.name}.{fk.name} references {fk.referenced_table} outside pilot scope"
                )
                continue
            if position[fk.referenced_table] >= position[table.name]:
                violations.append(
                    f"{table.name}.{fk.name} references {fk.referenced_table} "
                    "which is not loaded earlier in table_load_order"
                )
    return violations
