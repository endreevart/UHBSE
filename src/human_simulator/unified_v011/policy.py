"""Unified Source Expansion v0.1.1 — policy constants."""

from __future__ import annotations

import hashlib
import json
from typing import Any

VERSION = "0.1.1"
ARTIFACT_DIR = "artifacts/stage-03-unified-source-expansion-v0.1.1"
RUNTIME_DIR = "private/unified-runtime/v0.1.1"
BATCH_SIZE = 25
SOURCE_B_BATCH_SIZE = 500
SEED = 42
BOOTSTRAP_ITERS = 2000
SHUFFLE_PERMS = 500

FIXED_OUTCOME_CANDIDATE_ID = "2685c68a3e247ca4"
FIXED_OUTCOME_LABEL = "Т3 св."
FIXED_OUTCOME_UNIT = "пмоль/л"

# Accepted immutable baselines
ACCEPTED_UNIFIED_V01_ZIP = "stage-03-unified-source-expansion-v0.1-review.zip"
ACCEPTED_UNIFIED_V01_SHA256 = (
    "bf048ed0b7ecfada1d0cdbd522943437d409cdf8aef4b292418b4682cb1a83be"
)
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
TREATMENT_EFFECT_STATUS = "NOT_EVALUATED"
PRODUCTION_READINESS = "NOT_CLAIMED"

SOURCE_B_INTEGRATION_PARTIAL = "SOURCE_B_CANONICAL_INTEGRATION_PARTIAL"
CROSS_SOURCE_TRANSFER_NAME = "CROSS_SOURCE_TRANSFER_EXPLORATION"
CROSS_SOURCE_NOT_RUN_GATE = "NOT_RUN_DUE_TO_FAILED_GATE"
OUTCOME_NOT_COMPARABLE = "OUTCOME_NOT_COMPARABLE"
INDEPENDENCE_NOT_ESTABLISHED = "INDEPENDENCE_NOT_ESTABLISHED"
NO_DETECTED_OVERLAP_AFTER_EXCLUSION = "NO_DETECTED_OVERLAP_AFTER_CONSERVATIVE_EXCLUSION"

# Forbidden ambiguous status from v0.1
FORBIDDEN_SIGNAL_STATUS = "INCREMENTAL_SIGNAL_DETECTED"

PREDICTIVE_SIGNAL_STATUSES = (
    "NO_INCREMENTAL_PREDICTIVE_SIGNAL",
    "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_CANDIDATE",
    "EXPLORATORY_INCREMENTAL_PREDICTIVE_SIGNAL_SUPPORTED",
    "PREDICTIVE_SIGNAL_NOT_ROBUST",
    "INSUFFICIENT_DATA",
)

UNCERTAINTY_STATUSES = (
    "UNCERTAINTY_INTERVAL_CONSTRUCTION_PASS",
    "UNCERTAINTY_COVERAGE_ESTIMATED",
    "UNCERTAINTY_OVERCONSERVATIVE",
    "UNCERTAINTY_UNDERCOVERING",
    "UNCERTAINTY_CALIBRATION_AND_SHARPNESS_PASS",
    "UNCERTAINTY_CALIBRATION_AND_SHARPNESS_NOT_ESTABLISHED",
)

MAPPING_EXACT = "EXACT"
MAPPING_SUPPORTED_TRANSFORM = "SUPPORTED_TRANSFORMATION"
MAPPING_HYPOTHESIS = "HYPOTHESIS"
MAPPING_UNKNOWN = "UNKNOWN"
MAPPING_INCOMPATIBLE = "INCOMPATIBLE"

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "unified_v0.1": (ACCEPTED_UNIFIED_V01_ZIP, ACCEPTED_UNIFIED_V01_SHA256),
    "core_v0.1.2.1": (ACCEPTED_CORE_V0121_ZIP, ACCEPTED_CORE_V0121_SHA256),
    "sdr_v0.1.1.1": (ACCEPTED_SDR_V0111_ZIP, ACCEPTED_SDR_V0111_SHA256),
    "roadmap_v0.1.1": (ACCEPTED_ROADMAP_V011_ZIP, ACCEPTED_ROADMAP_V011_SHA256),
}

# Brief §12 required artifacts
REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "scope-and-claims.json",
    "baseline-verification.json",
    "source-a-locator-accounting.json",
    "source-a-expansion-reconciliation.json",
    "source-a-idempotency-verification.json",
    "source-a-expanded-backtest-robustness.json",
    "source-a-subject-cluster-bootstrap.json",
    "source-a-horizon-sensitivity.json",
    "source-a-shuffled-label-control.json",
    "source-a-uncertainty-evaluation.json",
    "source-b-role-graph.json",
    "source-b-consultation-semantics.json",
    "source-b-laboratory-semantics.json",
    "source-b-grouping-analysis.json",
    "source-b-mapping-decisions.yaml",
    "source-b-validation-slice.json",
    "source-b-canonical-load-report.json",
    "source-b-relation-accounting.json",
    "source-b-idempotency-report.json",
    "source-b-outcome-catalog.json",
    "linkage-readiness-corrected.json",
    "cross-source-outcome-intersection.json",
    "cross-source-comparability.json",
    "cross-source-transfer-backtest.json",
    "canonical-counts-before-after.json",
    "multi-source-provenance-report.json",
    "reject-summary.json",
    "truncation-report.json",
    "test-results.json",
    "verification.json",
    "release-verification.json",
    "report.md",
    "evidence-manifest.sha256",
    "REPRODUCE.md",
)

# Pre-declared uncertainty sharpness policy (hashed before recomputation)
UNCERTAINTY_SHARPNESS_POLICY: dict[str, Any] = {
    "nominal_coverage": 0.90,
    "overcoverage_threshold": 0.05,
    "undercoverage_threshold": 0.05,
    "max_mean_width_vs_outcome_iqr": 2.0,
    "require_persistence_interval_comparison": True,
    "forbid_post_hoc_threshold_tuning": True,
    "seed": SEED,
}


def uncertainty_policy_hash() -> str:
    return hashlib.sha256(
        json.dumps(UNCERTAINTY_SHARPNESS_POLICY, sort_keys=True).encode()
    ).hexdigest()


def policy_snapshot() -> dict[str, Any]:
    return {
        "unified_version": VERSION,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "security_findings_status": SECURITY_FINDINGS_STATUS,
        "security_gate_mode": SECURITY_GATE_MODE,
        "security_blocks_core": False,
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "treatment_effect_status": TREATMENT_EFFECT_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "accepted_unified_v01_sha256": ACCEPTED_UNIFIED_V01_SHA256,
        "accepted_core_baseline_sha256": ACCEPTED_CORE_V0121_SHA256,
        "accepted_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "accepted_roadmap_v011_sha256": ACCEPTED_ROADMAP_V011_SHA256,
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "bootstrap_iters": BOOTSTRAP_ITERS,
        "shuffle_perms": SHUFFLE_PERMS,
        "seed": SEED,
        "batch_size": BATCH_SIZE,
        "source_a_system_id": SOURCE_A_SYSTEM_ID,
        "source_b_system_id": SOURCE_B_SYSTEM_ID,
        "identity_merge": False,
        "migration_0005": False,
        "forbidden_signal_status": FORBIDDEN_SIGNAL_STATUS,
        "uncertainty_policy_hash": uncertainty_policy_hash(),
    }
