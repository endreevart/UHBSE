"""Stage 03 Alignment Candidate — constants."""

from __future__ import annotations

from pathlib import Path

ALIGNMENT_ID = "stage-03-alignment-candidate"
ALIGNMENT_VERSION = "0.1.2"
ALIGNMENT_TITLE = "Stage 03 Design v0.7.5 / Plan v0.3.6 Alignment"

ALIGNMENT_DIR = Path("artifacts") / "stage-03-alignment-candidate"
EXTERNAL_REVIEW_DIR = Path("artifacts") / "external-review"

DESIGN_VERSION = "0.7.5"
PLAN_VERSION = "0.3.6"
FROZEN_DESIGN_VERSION = "0.7.4"
FROZEN_PLAN_VERSION = "0.3.5"

BUNDLE_ZIP_NAME = "stage-03-alignment-v0.1.2-review.zip"
BUNDLE_SHA256_NAME = "stage-03-alignment-v0.1.2-review.zip.sha256"
BUNDLE_ATTESTATION_NAME = "stage-03-alignment-v0.1.2-review.attestation.json"

ACCEPTED_PLAN_V035_ZIP_SHA256 = (
    "c93b8270ede688cda67cdcaed8e5522df3466e63572012e896fc59a38d89895c"
)

RECOVERY_REPORT_NAME = "baseline-recovery-report.md"

FROZEN_DESIGN_ZIP_RECOVERED = (
    EXTERNAL_REVIEW_DIR / f"stage-03-design-v{FROZEN_DESIGN_VERSION}-recovered-review.zip"
)
FROZEN_PLAN_ZIP_RECOVERED = (
    EXTERNAL_REVIEW_DIR / f"stage-03-implementation-plan-v{FROZEN_PLAN_VERSION}-recovered-review.zip"
)

ALIGNMENT_EXPECTED_CHANGED_FILES: tuple[str, ...] = (
    "canonical-model.yaml",
    "canonical-id-contract.yaml",
    "temporal-contract.yaml",
    "record-construction-contract.yaml",
    "source-a-mapping-draft.yaml",
    "field-semantics-register.yaml",
    "validation-rules.yaml",
    "artifact-conflict-resolutions.yaml",
    "unresolved-design-decisions.md",
    "implementation-plan.yaml",
    "security-runtime-plan.yaml",
    "pilot-slice.yaml",
    "pipeline-plan.yaml",
    "design-baseline-manifest.sha256",
)

DECISION_SECRET_PROVIDER_NAME = "decision-required-secret-provider.yaml"
EXTRACTED_MANIFEST_VERIFICATION_NAME = "extracted-manifest-verification.json"
BASELINE_VERIFICATION_NAME = "baseline-verification.json"
CANDIDATE_GATE_RESULT_NAME = "alignment-pre-live-load-gate.json"
BEFORE_AFTER_MATRIX_NAME = "before-after-hash-matrix.json"
CANDIDATE_DECISION_NAME = "alignment-candidate-decision.json"

RELATIONSHIP_MANIFEST_SHA_ACCEPTED = (
    "13aae26b37032730c533740bc513872cb2a6890429b64ebd2fb923ffcf672974"
)

MIGRATION_FILES: tuple[str, ...] = (
    "migrations/canonical/0001_roles_and_schema.sql",
    "migrations/canonical/0002_pilot_evidence_tables.sql",
    "migrations/canonical/0003_pilot_grants.sql",
    "migrations/canonical/0004_storage_contract_hardening.sql",
)

OPEN_BLOCKER_IDS_EXPECTED_PARTIAL: tuple[str, ...] = (
    "canonical_loader_runtime_principal_undefined",
    "source_subject_key_opacity_undefined",
    "temporal_precision_field_absent_from_model",
    "encounter_provider_id_population_disagreement",
)
