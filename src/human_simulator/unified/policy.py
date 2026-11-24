"""Unified Source Expansion v0.1 — policy constants."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-03-unified-source-expansion-v0.1"
RUNTIME_DIR = "private/unified-runtime/v0.1"
BATCH_SIZE = 25

# Sentinel: treat lab/item fetches as uncapped (no pilot ROW_NUMBER caps).
NO_LAB_CAP = 10**9

FIXED_OUTCOME_CANDIDATE_ID = "2685c68a3e247ca4"
FIXED_OUTCOME_LABEL = "Т3 св."
FIXED_OUTCOME_UNIT = "пмоль/л"

ACCEPTED_CORE_V0121_ZIP = "stage-03-core-vertical-slice-v0.1.2.1-review.zip"
ACCEPTED_CORE_V0121_SHA256 = (
    "9eea316ccc022e6aed75075b47089b10a1263e55e2c58b9fd6852e8201fe1a5f"
)
ACCEPTED_SDR_V0111_ZIP = "stage-03-scientific-data-readiness-v0.1.1.1-review.zip"
ACCEPTED_SDR_V0111_SHA256 = (
    "2b23e48fa9e6687171c60ca371b7aa923d04285e6c3edfe5637cd64060edb67e"
)
ACCEPTED_ROADMAP_V011_ZIP = "stage-03-public-roadmap-series-v0.1.1-review.zip"
ACCEPTED_ROADMAP_V011_SHA256 = (
    "780758ec0c69573611ccf04311f22f28866c7efecb40153e8b47175c913aee30"
)

SOURCE_A_SYSTEM_ID = "magerya_api"
SOURCE_B_SYSTEM_ID = "kgz_raw"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SECURITY_FINDINGS_STATUS = "RECORDED_NON_BLOCKING"
SECURITY_GATE_MODE = "ADVISORY_ONLY"
CLINICAL_VALIDATION_STATUS = "NOT_STARTED"
INTERVENTION_RESPONSE_MODEL_STATUS = "NOT_STARTED"
PRODUCTION_READINESS = "NOT_CLAIMED"

# Section 11 status vocabulary (suggested truthful values)
STATUS_PASS = "PASS"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAIL = "FAIL"
STATUS_NOT_ESTABLISHED = "NOT_ESTABLISHED"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_NOT_RUN = "NOT_RUN"
STATUS_NOT_STARTED = "NOT_STARTED"
STATUS_NOT_CLAIMED = "NOT_CLAIMED"
STATUS_PAUSED = "PAUSED_NOT_ACCEPTED_BY_OWNER"

SOURCE_B_INTEGRATION_PARTIAL = "SOURCE_B_CANONICAL_INTEGRATION_PARTIAL"
CROSS_SOURCE_NOT_RUN_GATE = "NOT_RUN_DUE_TO_FAILED_GATE"
OUTCOME_NOT_COMPARABLE = "OUTCOME_NOT_COMPARABLE"
INDEPENDENCE_NOT_ESTABLISHED = "INDEPENDENCE_NOT_ESTABLISHED"

MAPPING_EXACT = "EXACT"
MAPPING_SUPPORTED_TRANSFORM = "SUPPORTED_TRANSFORMATION"
MAPPING_HYPOTHESIS = "HYPOTHESIS"
MAPPING_UNKNOWN = "UNKNOWN"
MAPPING_INCOMPATIBLE = "INCOMPATIBLE"

ELIGIBLE_SUBJECTS_EXPECTED_HINT = 8262  # appt≥3 AND lab≥1 (recompute at runtime)
PILOT_SUBJECT_LIMIT = 100

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "core_v0.1.2.1": (ACCEPTED_CORE_V0121_ZIP, ACCEPTED_CORE_V0121_SHA256),
    "sdr_v0.1.1.1": (ACCEPTED_SDR_V0111_ZIP, ACCEPTED_SDR_V0111_SHA256),
    "roadmap_v0.1.1": (ACCEPTED_ROADMAP_V011_ZIP, ACCEPTED_ROADMAP_V011_SHA256),
}

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "scope-and-claims.json",
    "baseline-verification.json",
    "source-snapshot-report.json",
    "source-a-full-expansion-report.json",
    "source-a-relation-accounting.json",
    "source-a-idempotency-report.json",
    "source-b-readiness-report.json",
    "source-b-mapping-decisions.yaml",
    "source-b-relation-accounting.json",
    "source-b-canonical-load-report.json",
    "canonical-counts-before-after.json",
    "multi-source-provenance-report.json",
    "linkage-readiness-assessment.json",
    "source-a-outcome-catalog.json",
    "source-b-outcome-catalog.json",
    "cross-source-outcome-intersection.json",
    "source-a-expanded-backtest.json",
    "cross-source-comparability.json",
    "cross-source-backtest.json",
    "reject-summary.json",
    "truncation-report.json",
    "test-results.json",
    "verification.json",
    "report.md",
    "evidence-manifest.sha256",
    "REPRODUCE.md",
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "unified_version": VERSION,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "security_findings_status": SECURITY_FINDINGS_STATUS,
        "security_gate_mode": SECURITY_GATE_MODE,
        "security_blocks_core": False,
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "accepted_core_baseline_sha256": ACCEPTED_CORE_V0121_SHA256,
        "accepted_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "accepted_roadmap_v011_sha256": ACCEPTED_ROADMAP_V011_SHA256,
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "batch_size": BATCH_SIZE,
        "no_lab_cap": NO_LAB_CAP,
        "source_a_system_id": SOURCE_A_SYSTEM_ID,
        "source_b_system_id": SOURCE_B_SYSTEM_ID,
        "identity_merge": False,
        "migration_0005": False,
    }
