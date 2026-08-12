"""Names and paths for Stage 02 Maintenance 01.

Maintenance 01 diagnoses the `stage02_relationship_manifest_drift` defect and prepares a repair.
It does not apply one. `artifacts/stage-02/` is read here and never written.
"""

from __future__ import annotations

from pathlib import Path

MAINTENANCE_ID = "stage-02-maintenance-01"
MAINTENANCE_VERSION = "0.1"
PROMOTION_VERSION = "0.1.1"
MAINTENANCE_TITLE = "Relationship Manifest Drift Diagnosis"
DEFECT_ID = "stage02_relationship_manifest_drift"

STAGE_02_DIR = Path("artifacts") / "stage-02"
MAINTENANCE_DIR = Path("artifacts") / MAINTENANCE_ID
CANDIDATE_DIR = MAINTENANCE_DIR / "candidate"
EXTERNAL_REVIEW_DIR = Path("artifacts") / "external-review"

DRIFT_DIAGNOSIS_NAME = "drift-diagnosis.md"
HASH_MATRIX_NAME = "before-after-hash-matrix.json"
DECISION_NAME = "maintenance-decision.json"
QUERY_LOG_NAME = "sanitised-query-log.json"
REPRODUCTION_NAME = "reproduction-result.json"
ISOLATED_VALIDATION_NAME = "isolated-validation.json"
SEMANTIC_COMPARISON_NAME = "semantic-comparison.json"

MAINTENANCE_CONTENT_ARTIFACTS: tuple[str, ...] = (
    DRIFT_DIAGNOSIS_NAME,
    HASH_MATRIX_NAME,
    DECISION_NAME,
    QUERY_LOG_NAME,
    REPRODUCTION_NAME,
    ISOLATED_VALIDATION_NAME,
    SEMANTIC_COMPARISON_NAME,
)

BUNDLE_ZIP_NAME = f"{MAINTENANCE_ID}-review.zip"
BUNDLE_SHA256_NAME = f"{BUNDLE_ZIP_NAME}.sha256"
ATTESTATION_NAME = f"{MAINTENANCE_ID}-review.attestation.json"

PROMOTION_REPORT_JSON = "promotion-report.json"
PROMOTION_REPORT_MD = "promotion-report.md"
PROMOTION_VERIFICATION_JSON = "promotion-verification.json"
PROMOTION_MANIFEST_NAME = "promotion-manifest.sha256"

PROMOTION_BUNDLE_ZIP_NAME = f"{MAINTENANCE_ID}-promotion-review.zip"
PROMOTION_BUNDLE_SHA256_NAME = f"{PROMOTION_BUNDLE_ZIP_NAME}.sha256"
PROMOTION_ATTESTATION_NAME = f"{MAINTENANCE_ID}-promotion-review.attestation.json"

PROMOTION_BUNDLE_V011_ZIP_NAME = f"{MAINTENANCE_ID}-promotion-v0.1.1-review.zip"
PROMOTION_BUNDLE_V011_SHA256_NAME = f"{PROMOTION_BUNDLE_V011_ZIP_NAME}.sha256"
PROMOTION_BUNDLE_V011_ATTESTATION_NAME = f"{MAINTENANCE_ID}-promotion-v0.1.1-review.attestation.json"

# Authorised repair: only the working manifest may change, and only to this exact content.
EXPECTED_MANIFEST_SHA_BEFORE = "19b932cc2f27684013d743444b0b8d66f560e200fffc73a571e387178b6ec6f2"
EXPECTED_MANIFEST_SHA_AFTER = "13aae26b37032730c533740bc513872cb2a6890429b64ebd2fb923ffcf672974"

# Stage 02 FINAL artifacts that must not move during a manifest-only repair.
FORBIDDEN_STAGE_02_CHANGES: tuple[str, ...] = (
    "stage-02-report.md",
    "verify-stage-02.json",
    "stage-02-final-manifest.sha256",
)

# After repair the gate must still fail, but only on these four contract/conflict blockers.
EXPECTED_REMAINING_GATE_FAILURES: tuple[str, ...] = (
    "canonical_loader_runtime_principal_undefined",
    "source_subject_key_opacity_undefined",
    "temporal_precision_field_absent_from_model",
    "encounter_provider_id_population_disagreement",
)

PROMOTION_CONTENT_ARTIFACTS: tuple[str, ...] = (
    PROMOTION_REPORT_JSON,
    PROMOTION_REPORT_MD,
    PROMOTION_VERIFICATION_JSON,
    HASH_MATRIX_NAME,
    DECISION_NAME,
    DRIFT_DIAGNOSIS_NAME,
)

# The only field that has ever differed between published copies of the two drifted artifacts.
# Every other key is compared byte-for-byte; nothing else is tolerated as volatile.
VOLATILE_FIELDS: tuple[str, ...] = ("assessed_at",)

# Fields whose equality is what makes a byte difference safe to accept. A timestamp may move; a
# verdict, a denominator or a conflict definition may not.
SEMANTIC_FIELDS: dict[str, tuple[str, ...]] = {
    "subject-root-analysis.json": ("coverage_threshold_confirmed", "source_a", "source_b", "notes"),
    "identity-linkage-assessment.json": (
        "method",
        "hmac_key_present_in_runtime",
        "hmac_key_persisted_in_artifacts",
        "hmac_key_source",
        "source_a_subject_table",
        "source_b_subject_resolution",
        "source_a_aggregates",
        "source_b_aggregates",
        "overlap_aggregates",
        "conflict_definition",
        "identity_verdict",
        "notes",
    ),
}
