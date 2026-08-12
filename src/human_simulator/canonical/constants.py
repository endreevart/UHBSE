"""Canonical storage constants for Stage 03 Implementation Changeset 01.

Every value here traces to an accepted artifact. Nothing in this module may widen the
pilot scope defined by artifacts/stage-03-implementation/pilot-slice.yaml.
"""

from __future__ import annotations

CHANGESET_ID = "stage-03-implementation-changeset-01"
CHANGESET_TITLE = "Canonical Storage Foundation"
CHANGESET_VERSION = "0.2.3"
DESIGN_BASELINE_VERSION = "0.7.4"
IMPLEMENTATION_PLAN_VERSION = "0.3.5"

# Accepted bytes of every migration published so far. 0001-0003 were accepted with
# Changeset 01 v0.1 and are immutable: a schema correction may only arrive as a new
# forward-only migration. 0004 is added by v0.2.
ACCEPTED_MIGRATION_SHA256: dict[str, str] = {
    "0001_roles_and_schema.sql":
        "65f0647ff09994e0bd0ede693179f0431061224059d75871b997d7dd79b704e0",
    "0002_pilot_evidence_tables.sql":
        "81bd54f9a37480a285f79f587cc8552daf86c8a3b3b61429c7a852df974f0009",
    "0003_pilot_grants.sql":
        "56948f3066bb4c95efc4e7aa24a97986930c3257878d89e693a95517dd65396b",
}
FROZEN_MIGRATION_FILENAMES: tuple[str, ...] = tuple(sorted(ACCEPTED_MIGRATION_SHA256))
HARDENING_MIGRATION_FILENAME = "0004_storage_contract_hardening.sql"

# artifacts/stage-03-implementation/physical-storage-plan.yaml :: planned_topology
CANONICAL_SERVICE_NAME = "human-simulator-canonical"
CANONICAL_DATABASE = "uhbse_canonical_dev"
CANONICAL_SCHEMA = "canonical_evidence"
CANONICAL_POSTGRES_VERSION = "16"
CANONICAL_PORT = 5436
CANONICAL_VOLUME = "uhbse_canonical_dev_data"

# Migration bookkeeping lives outside canonical_evidence so that the evidence schema
# contains exactly the pilot entity tables and nothing else.
MIGRATION_SCHEMA = "canonical_migration"
MIGRATION_HISTORY_TABLE = "schema_migration_history"

# artifacts/stage-03-implementation/physical-storage-plan.yaml :: database_roles
ROLE_OWNER = "canonical_owner"
ROLE_MIGRATOR = "canonical_migrator"
ROLE_LOADER = "canonical_loader"
ROLE_VALIDATOR_RO = "canonical_validator_ro"
CANONICAL_ROLES: tuple[str, ...] = (ROLE_OWNER, ROLE_MIGRATOR, ROLE_LOADER, ROLE_VALIDATOR_RO)

# artifacts/stage-03-implementation/physical-storage-plan.yaml :: connection_policy.forbidden_targets
FORBIDDEN_CANONICAL_TARGET_DATABASES: tuple[str, ...] = ("magerya_api", "kgz_raw")
RAW_SOURCE_PORTS: tuple[int, ...] = (5434, 5435)

# artifacts/stage-03-implementation/pilot-slice.yaml :: pilot_entities (table_entity: true)
# artifacts/stage-03-implementation/pipeline-plan.yaml :: table_load_order
PILOT_ENTITY_LOAD_ORDER: tuple[str, ...] = (
    "SourceSystem",
    "SourceRecord",
    "Subject",
    "SubjectCharacteristic",
    "Encounter",
    "Observation",
    "ObservationComponent",
)

# Provenance is embedded, never a table (pilot-slice.yaml :: Provenance.table_entity false,
# physical-storage-plan.yaml :: provenance_storage.separate_provenance_table forbidden_in_pilot).
EMBEDDED_COMPONENTS: tuple[str, ...] = ("Provenance",)

ENTITY_TABLE_NAMES: dict[str, str] = {
    "SourceSystem": "source_system",
    "SourceRecord": "source_record",
    "Subject": "subject",
    "SubjectCharacteristic": "subject_characteristic",
    "Encounter": "encounter",
    "Observation": "observation",
    "ObservationComponent": "observation_component",
}

PILOT_TABLE_LOAD_ORDER: tuple[str, ...] = tuple(
    ENTITY_TABLE_NAMES[entity] for entity in PILOT_ENTITY_LOAD_ORDER
)

# artifacts/stage-03/canonical-model.yaml :: data_level_enum
DATA_LEVEL_ENUM_NAME = "canonical_data_level"
DATA_LEVEL_VALUES: tuple[str, ...] = (
    "PATIENT_EVENT",
    "OBSERVATION_HEADER",
    "OBSERVATION_VALUE",
    "ATTRIBUTE_CONTAINER",
    "REFERENCE_CATALOG",
    "WORKFLOW",
    "PAYLOAD",
    "UNKNOWN",
)

# artifacts/stage-03/provenance-contract.yaml :: mapping_status_values
MAPPING_STATUS_ENUM_NAME = "canonical_mapping_status"
MAPPING_STATUS_VALUES: tuple[str, ...] = (
    "CONFIRMED_SCHEMA",
    "CANDIDATE",
    "HYPOTHESIS",
    "UNRESOLVED",
    "NOT_MAPPED",
)

# artifacts/stage-03/canonical-model.yaml :: layers.evidence.record_origins
EVIDENCE_RECORD_ORIGINS: tuple[str, ...] = (
    "OBSERVED",
    "CORRECTED",
    "NORMALIZED",
    "ANNOTATED",
    "DERIVED",
    "IMPUTED",
)
# canonical-model.yaml :: layers.evidence.forbidden_origins
FORBIDDEN_EVIDENCE_RECORD_ORIGINS: tuple[str, ...] = ("SYNTHETIC", "PREDICTED")

# artifacts/stage-03/provenance-contract.yaml :: profiles.SOURCE_BACKED
SOURCE_BACKED_RECORD_ORIGINS: tuple[str, ...] = (
    "OBSERVED",
    "CORRECTED",
    "NORMALIZED",
    "ANNOTATED",
)
SOURCE_BACKED_REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "record_origin",
    "source_system",
    "source_schema",
    "source_relation",
    "source_record_locator",
    "transformation_id",
    "transformation_version",
    "transformed_at",
    "input_artifact_sha256",
    "confidence",
    "mapping_status",
)

# artifacts/stage-03/provenance-contract.yaml :: profiles.COMPUTED
COMPUTED_RECORD_ORIGINS: tuple[str, ...] = ("DERIVED", "IMPUTED")
COMPUTED_REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "record_origin",
    "input_record_references",
    "computation_method",
    "computation_version",
    "uncertainty",
    "transformation_id",
    "transformation_version",
    "transformed_at",
    "input_artifact_sha256",
    "confidence",
    "mapping_status",
)
COMPUTED_FORBIDDEN_PROVENANCE_FIELDS: tuple[str, ...] = ("source_record_locator",)

# artifacts/stage-03/canonical-id-contract.yaml
ID_NAMESPACE_VERSION = "0.7.0"
LOCATOR_SCHEME = "deterministic_hmac_locator"

# Identifier column names that must never exist (canonical-model.yaml ::
# Subject.identity.forbidden, pilot-slice.yaml :: forbidden_in_pilot).
FORBIDDEN_COLUMN_NAMES: tuple[str, ...] = (
    "global_patient_id",
    "global_subject_id",
    "source_primary_key",
    "raw_primary_key",
)

# pilot-slice.yaml deferred_fields + pipeline-plan.yaml fk_dependencies (deferred_null_for_pilot)
# and record-construction-contract.yaml constant_fields that pin these to null.
PILOT_NULL_ONLY_COLUMNS: dict[str, tuple[str, ...]] = {
    "subject_characteristic": ("concept_id", "normalized_unit"),
    "encounter": ("provider_id",),
    "observation": ("encounter_id", "normalized_concept", "normalized_unit"),
    "observation_component": ("normalized_unit",),
}

# canonical-model.yaml :: constraints.subject_characteristic_value_constraint
SUBJECT_CHARACTERISTIC_TYPED_VALUE_COLUMNS: tuple[str, ...] = (
    "date_value",
    "numeric_value",
    "text_value",
    "categorical_value",
    "boolean_value",
)

# The accepted plan defines no reverse DDL. pipeline-plan.yaml :: rollback limits rollback to
# staging rows and states published records are never deleted; physical-storage-plan.yaml only
# names a forward migration role. Migrations are therefore forward-only.
DOWN_MIGRATIONS_SUPPORTED = False

# provenance-contract.yaml :: origin_specific_rules
ORIGIN_SPECIFIC_REQUIRED_PROVENANCE_FIELDS: dict[str, tuple[str, ...]] = {
    "CORRECTED": ("prior_record_reference", "correction_reason"),
    "NORMALIZED": ("normalization_lineage",),
    "ANNOTATED": ("annotation_text", "annotated_at"),
}

# Constraint names added by migration 0004. Every provenance-bearing pilot table carries
# the first three; the last two are table specific.
HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES: tuple[str, ...] = (
    "_provenance_required_values_present",
    "_provenance_origin_specific_fields",
    "_provenance_profiles_exclusive",
)
PROVENANCE_BEARING_TABLES: tuple[str, ...] = (
    "source_record",
    "subject",
    "subject_characteristic",
    "encounter",
    "observation",
    "observation_component",
)

# physical-storage-plan.yaml :: database_roles. Privileges the verifier requires on the
# canonical schema itself, distinct from table privileges.
EXPECTED_SCHEMA_PRIVILEGES: dict[str, tuple[str, ...]] = {
    ROLE_OWNER: ("CREATE", "USAGE"),
    ROLE_MIGRATOR: ("CREATE", "USAGE"),
    ROLE_LOADER: ("USAGE",),
    ROLE_VALIDATOR_RO: ("USAGE",),
}
EXPECTED_TABLE_PRIVILEGES: dict[str, tuple[str, ...]] = {
    ROLE_LOADER: ("INSERT", "SELECT"),
    ROLE_VALIDATOR_RO: ("SELECT",),
}
# Privileges no role in the canonical schema may ever hold on evidence tables. Raw data is
# append-only evidence: correction happens by new versioned records, never in place.
FORBIDDEN_TABLE_PRIVILEGES: tuple[str, ...] = (
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
EXPECTED_TABLE_OWNER = ROLE_OWNER
EXPECTED_SCHEMA_OWNER = ROLE_OWNER
