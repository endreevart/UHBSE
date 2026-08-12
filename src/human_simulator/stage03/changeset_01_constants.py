"""Artifact layout for Stage 03 Implementation Changeset 01."""

from __future__ import annotations

from pathlib import Path

CHANGESET_ID = "stage-03-implementation-changeset-01"
CHANGESET_VERSION = "0.2.3"
CHANGESET_TITLE = "Canonical Storage Foundation"
CHANGESET_SUBTITLE = "Contract Authority and Semantic Validation Hardening"

CHANGESET_DIR = Path("artifacts") / CHANGESET_ID

BASELINE_VERIFICATION_NAME = "baseline-verification.json"
CHANGESET_PLAN_NAME = "changeset-01-plan.yaml"
CHANGESET_REPORT_NAME = "changeset-01-report.md"
CHANGESET_VERIFICATION_NAME = "changeset-01-verification.json"
UNRESOLVED_DECISIONS_NAME = "unresolved-changeset-01-decisions.yaml"
ARTIFACT_CONFLICTS_NAME = "accepted-artifact-conflicts.yaml"
SCHEMA_CONTRACT_NAME = "canonical-schema-contract.json"
MIGRATION_RESULT_NAME = "migration-result.json"
PERMISSION_REPORT_NAME = "permission-report.json"
GATE_RESULT_NAME = "stage02-pre-live-load-gate.json"
PRIOR_STAGE_INTEGRITY_NAME = "prior-stage-integrity.json"
RELEASE_VERIFICATION_NAME = "release-verification.json"
CHANGESET_MANIFEST_NAME = "changeset-01-manifest.sha256"
DEFINITION_BASELINE_NAME = "canonical-definition-baseline.json"
MIGRATION_IMMUTABILITY_NAME = "migration-immutability.json"
PRE_LIVE_LOAD_BLOCKERS_NAME = "pre-live-load-blockers.yaml"
LIVE_LOAD_CONTRACT_SCHEMA_NAME = "live-load-contract-schema.yaml"
CONTRACT_AUTHORITY_POLICY_NAME = "contract-authority-policy.yaml"
DESIGN_ARCHIVE_FINDING_NAME = "design-archive-evidence-finding.json"

# Hand-authored content artifacts covered by the changeset manifest. Generated evidence
# (verification, reports, gate result, manifest itself) is deliberately excluded so the
# manifest has no cyclic hash dependency.
CHANGESET_CONTENT_ARTIFACTS: tuple[str, ...] = (
    CHANGESET_PLAN_NAME,
    UNRESOLVED_DECISIONS_NAME,
    ARTIFACT_CONFLICTS_NAME,
    SCHEMA_CONTRACT_NAME,
    DEFINITION_BASELINE_NAME,
    PRE_LIVE_LOAD_BLOCKERS_NAME,
    LIVE_LOAD_CONTRACT_SCHEMA_NAME,
    CONTRACT_AUTHORITY_POLICY_NAME,
)

FORBIDDEN_IN_CHANGESET_MANIFEST: frozenset[str] = frozenset(
    {
        CHANGESET_MANIFEST_NAME,
        CHANGESET_REPORT_NAME,
        CHANGESET_VERIFICATION_NAME,
        RELEASE_VERIFICATION_NAME,
    }
)

DESIGN_DIR = Path("artifacts") / "stage-03"
IMPLEMENTATION_DIR = Path("artifacts") / "stage-03-implementation"
DESIGN_CONTENT_MANIFEST_NAME = "design-content-manifest.sha256"
IMPLEMENTATION_PLAN_MANIFEST_NAME = "implementation-plan-manifest.sha256"

COMPOSE_FILE = Path("docker-compose.yml")
CANONICAL_ENV_TEMPLATE = Path("config") / "canonical-db.env.template"
CANONICAL_ENV_FILE = "canonical-db.env"

# Raw relation names must never appear in canonical storage code or migrations.
RAW_RELATION_TOKENS: tuple[str, ...] = (
    "account_patient",
    "appointment_appointment",
    "document_analysisresult",
    "document_analysisresultitem",
    "users_profile",
    "profilaxys_profile",
    "consultations",
)
