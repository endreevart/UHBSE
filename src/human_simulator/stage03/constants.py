"""Shared Stage 03 design constants."""

from __future__ import annotations

DATA_LEVELS: frozenset[str] = frozenset(
    {
        "PATIENT_EVENT",
        "OBSERVATION_HEADER",
        "OBSERVATION_VALUE",
        "ATTRIBUTE_CONTAINER",
        "REFERENCE_CATALOG",
        "WORKFLOW",
        "PAYLOAD",
        "UNKNOWN",
    }
)

MAPPING_STATUSES: frozenset[str] = frozenset(
    {
        "CONFIRMED_SCHEMA",
        "CANDIDATE",
        "HYPOTHESIS",
        "UNRESOLVED",
        "NOT_MAPPED",
        "DEFERRED_UNTIL_PROVIDER_CONSTRUCTION",
    }
)

RECORD_ORIGINS: frozenset[str] = frozenset(
    {
        "OBSERVED",
        "CORRECTED",
        "NORMALIZED",
        "ANNOTATED",
        "DERIVED",
        "IMPUTED",
        "PREDICTED",
        "SYNTHETIC",
    }
)

PROVENANCE_PROFILES: frozenset[str] = frozenset(
    {"SOURCE_BACKED", "COMPUTED", "SCENARIO", "MODEL_OUTPUT"}
)

REQUIRED_ENTITIES: tuple[str, ...] = (
    "SourceSystem",
    "SourceRecord",
    "Subject",
    "SubjectCharacteristic",
    "Provider",
    "Encounter",
    "Observation",
    "ObservationComponent",
    "ClinicalAssertion",
    "Intervention",
    "MedicationExposure",
    "SupplementExposure",
    "NutritionExposure",
    "ActivityExposure",
    "Procedure",
    "ClinicalDocument",
    "Concept",
    "Unit",
    "Provenance",
    "Scenario",
    "ScenarioBranch",
    "ScenarioEvent",
    "ScenarioIntervention",
    "SimulationRun",
    "EvidenceStateSnapshot",
    "StateSnapshotComponent",
    "ScenarioCheckpoint",
    "ScenarioCheckpointState",
    "PredictedState",
)

ENTITIES_WITHOUT_ROW_PROVENANCE: frozenset[str] = frozenset({"SourceSystem", "Provenance"})

STAGE03_CONTENT_ARTIFACTS: tuple[str, ...] = (
    "canonical-model.yaml",
    "canonical-id-contract.yaml",
    "provenance-contract.yaml",
    "temporal-contract.yaml",
    "state-snapshot-contract.yaml",
    "record-construction-contract.yaml",
    "source-a-mapping-draft.yaml",
    "source-b-mapping-draft.yaml",
    "field-semantics-register.yaml",
    "validation-rules.yaml",
    "artifact-conflict-resolutions.yaml",
    "unresolved-design-decisions.md",
)
