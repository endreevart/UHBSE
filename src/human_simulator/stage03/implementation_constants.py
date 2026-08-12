"""Stage 03 implementation planning constants."""

from __future__ import annotations

STAGE03_DESIGN_VERSION = "0.7.5"
STAGE03_IMPLEMENTATION_PLAN_VERSION = "0.3.6"
STAGE03_DESIGN_BASELINE_FROZEN_VERSION = "0.7.4"
STAGE03_IMPLEMENTATION_PLAN_FROZEN_VERSION = "0.3.5"

PILOT_SOURCE_SYSTEM = "magerya_api"
PILOT_AUDIT_ROLE = "mg_audit_ro"

PILOT_SOURCE_RELATIONS: tuple[str, ...] = (
    "magerya_api.account_patient",
    "magerya_api.appointment_appointment",
    "magerya_api.document_analysisresult",
    "magerya_api.document_analysisresultitem",
)

PILOT_TABLE_ENTITIES: tuple[str, ...] = (
    "SourceSystem",
    "SourceRecord",
    "Subject",
    "SubjectCharacteristic",
    "Encounter",
    "Observation",
    "ObservationComponent",
)

PILOT_EMBEDDED_COMPONENTS: tuple[str, ...] = ("Provenance",)

PILOT_ENTITIES: tuple[str, ...] = PILOT_TABLE_ENTITIES + PILOT_EMBEDDED_COMPONENTS

SOURCE_A_PILOT_CONSTRUCTION_GROUPS: tuple[str, ...] = (
    "source_a_source_record_account_patient",
    "source_a_source_record_appointment",
    "source_a_source_record_analysisresult",
    "source_a_source_record_analysisresultitem",
    "source_a_account_patient_subject",
    "source_a_account_patient_characteristics",
    "source_a_appointment_encounter",
    "source_a_observation_header",
    "source_a_observation_component",
)

SOURCE_A_SOURCE_RECORD_GROUPS: tuple[str, ...] = SOURCE_A_PILOT_CONSTRUCTION_GROUPS[:4]

STAGE01_PRECONDITION_ARTIFACTS: tuple[str, ...] = (
    "artifacts/stage-01/schema-profile.json",
    "artifacts/stage-01/stage-01-report.md",
)

STAGE02_PRECONDITION_ARTIFACTS: tuple[str, ...] = (
    "artifacts/stage-02/verify-stage-02.json",
    "artifacts/stage-02/stage-02-report.md",
    "artifacts/stage-02/stage-02-final-manifest.sha256",
    "artifacts/stage-02/entity-crosswalk.yaml",
    "artifacts/stage-02/identity-linkage-assessment.json",
    "artifacts/stage-02/subject-root-analysis.json",
)

# Stage 01/02 inputs Stage 03 depends on that are not part of the precondition gate
# but must still be byte-controlled during implementation planning.
STAGE03_PRIOR_STAGE_DEPENDENCY_ARTIFACTS: tuple[str, ...] = (
    "artifacts/stage-02/schema-profile-kgz.json",
)

IMPLEMENTATION_CONTENT_ARTIFACTS: tuple[str, ...] = (
    "implementation-plan.yaml",
    "physical-storage-plan.yaml",
    "pilot-slice.yaml",
    "pipeline-plan.yaml",
    "validation-plan.yaml",
    "security-runtime-plan.yaml",
    "unresolved-implementation-decisions.yaml",
    "design-baseline-manifest.sha256",
)

IMPLEMENTATION_PLAN_MANIFEST_NAME = "implementation-plan-manifest.sha256"
IMPLEMENTATION_PLAN_REPORT_NAME = "implementation-plan-report.md"
IMPLEMENTATION_PLAN_VERIFICATION_NAME = "implementation-plan-verification.json"
DESIGN_BASELINE_MANIFEST_NAME = "design-baseline-manifest.sha256"

FORBIDDEN_IN_IMPLEMENTATION_MANIFEST: frozenset[str] = frozenset(
    {
        IMPLEMENTATION_PLAN_MANIFEST_NAME,
        IMPLEMENTATION_PLAN_REPORT_NAME,
        IMPLEMENTATION_PLAN_VERIFICATION_NAME,
    }
)

FORBIDDEN_IMPLEMENTATION_PATH_PATTERNS: tuple[str, ...] = (
    "migrations/",
    "alembic/",
    "ddl/",
    "etl/",
    "sql/canonical/",
    "models/canonical_db",
)

from human_simulator.stage03.review_dependencies import get_implementation_review_bundle_paths

REVIEW_BUNDLE_REQUIRED_PATHS: tuple[str, ...] = get_implementation_review_bundle_paths()
