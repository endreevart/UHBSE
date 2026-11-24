"""Unified Source Expansion v0.1.2 — policy constants (brief §13 / §14)."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.2"
ARTIFACT_DIR = "artifacts/stage-03-unified-source-expansion-v0.1.2"
RUNTIME_DIR = "private/unified-runtime/v0.1.2"
SOURCE_B_OBS_BATCH_SIZE = 2000
CHECKPOINT_EVERY_N_BATCHES = 10
SEED = 42
SHUFFLE_PERMS = 500

# Finite-sample shuffle / permutation correction (brief §2.3)
# p = (n_extreme + 1) / (n_permutations + 1)
SHUFFLE_FINITE_SAMPLE_FORMULA = "(n_extreme + 1) / (n_permutations + 1)"

FIXED_OUTCOME_CANDIDATE_ID = "2685c68a3e247ca4"
FIXED_OUTCOME_LABEL = "Т3 св."
FIXED_OUTCOME_UNIT = "пмоль/л"

# Immutable baselines
ACCEPTED_UNIFIED_V011_ZIP = "stage-03-unified-source-expansion-v0.1.1-review.zip"
ACCEPTED_UNIFIED_V011_SHA256 = (
    "d0e8a973ecbbee6e618cf5976d8a688abf23023ccc477710668fed3b16072faa"
)
ACCEPTED_UNIFIED_V011_MEMBERS = 256
ACCEPTED_UNIFIED_V011_INDEX_ROWS = 255  # REVIEW_INDEX excludes itself

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
TECHNICAL_MULTI_SOURCE_PIPELINE_PASS = "TECHNICAL_MULTI_SOURCE_PIPELINE_PASS"
CROSS_SOURCE_TRANSFER_NAME = "CROSS_SOURCE_TRANSFER_EXPLORATION"
CROSS_SOURCE_NOT_RUN_GATE = "NOT_RUN_DUE_TO_FAILED_GATE"
OUTCOME_NOT_COMPARABLE = "OUTCOME_NOT_COMPARABLE"
OUTCOME_COMPARABLE = "OUTCOME_COMPARABLE"
OUTCOME_COMPARABLE_WITH_LIMITATIONS = "OUTCOME_COMPARABLE_WITH_LIMITATIONS"
DOMAIN_REVIEW_REQUIRED = "DOMAIN_REVIEW_REQUIRED"
INSUFFICIENT_SOURCE_B_DATA = "INSUFFICIENT_SOURCE_B_DATA"
NO_DETECTED_OVERLAP_AFTER_EXCLUSION = "NO_DETECTED_OVERLAP_AFTER_CONSERVATIVE_EXCLUSION"
INDEPENDENCE_NOT_ESTABLISHED = "INDEPENDENCE_NOT_ESTABLISHED"

MAPPING_EXACT = "EXACT"
MAPPING_SUPPORTED_TRANSFORM = "SUPPORTED_TRANSFORMATION"
MAPPING_HYPOTHESIS = "HYPOTHESIS"
MAPPING_UNKNOWN = "UNKNOWN"
MAPPING_INCOMPATIBLE = "INCOMPATIBLE"

# Expected Source B Subject/Encounter from v0.1.1 (do not rewrite unless defect)
EXPECTED_SOURCE_B_SUBJECTS = 49564
EXPECTED_SOURCE_B_ENCOUNTERS = 88867
EXPECTED_ANALYSES_CONSTRUCTOR_ROWS = 2183297
EXPECTED_POOL_COUNT = 59741

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "unified_v0.1.1": (ACCEPTED_UNIFIED_V011_ZIP, ACCEPTED_UNIFIED_V011_SHA256),
    "unified_v0.1": (ACCEPTED_UNIFIED_V01_ZIP, ACCEPTED_UNIFIED_V01_SHA256),
    "core_v0.1.2.1": (ACCEPTED_CORE_V0121_ZIP, ACCEPTED_CORE_V0121_SHA256),
    "sdr_v0.1.1.1": (ACCEPTED_SDR_V0111_ZIP, ACCEPTED_SDR_V0111_SHA256),
    "roadmap_v0.1.1": (ACCEPTED_ROADMAP_V011_ZIP, ACCEPTED_ROADMAP_V011_SHA256),
}

# Brief §13 required status keys
REQUIRED_STATUSES: tuple[str, ...] = (
    "source_a_canonical_status",
    "source_a_predictive_signal_status",
    "source_a_uncertainty_status",
    "source_b_subject_mapping_status",
    "source_b_encounter_mapping_status",
    "source_b_encounter_audit_status",
    "source_b_observation_semantics_status",
    "source_b_observation_contract_status",
    "source_b_observation_load_status",
    "source_b_observation_idempotency_status",
    "source_b_outcome_catalog_status",
    "cross_source_outcome_comparability_status",
    "cross_source_overlap_control_status",
    "cross_source_transfer_status",
    "identity_linkage_status",
    "multi_source_canonical_status",
    "pre_publish_verification_status",
    "post_publish_integrity_status",
    "clinical_validation_status",
    "intervention_response_model_status",
    "treatment_effect_status",
    "production_readiness",
    "security_stage_status",
)

# Brief §14 required artifacts
REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "scope-and-claims.json",
    "baseline-verification.json",
    "publication-defect-corrections.json",
    "source-a-quantile-correction.json",
    "source-a-permutation-correction.json",
    "source-b-schema-relationship-graph.json",
    "source-b-subject-ownership.json",
    "source-b-encounter-audit.json",
    "source-b-encounter-construction-policy.yaml",
    "source-b-laboratory-value-classification.json",
    "source-b-unit-resolution.json",
    "source-b-pool-grouping-analysis.json",
    "source-b-timestamp-analysis.json",
    "source-b-extra-payload-schema.json",
    "source-b-observation-construction-contract.yaml",
    "source-b-mapping-decisions.yaml",
    "source-b-validation-slice.json",
    "source-b-observation-load-report.json",
    "source-b-relation-accounting.json",
    "source-b-idempotency-report.json",
    "source-b-outcome-catalog.json",
    "cross-source-t3-comparability.json",
    "cross-source-overlap-exclusion.json",
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


def shuffle_finite_sample_p(n_extreme: int, n_permutations: int) -> float:
    """Finite-sample corrected permutation probability."""
    return (int(n_extreme) + 1) / (int(n_permutations) + 1)


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
        "accepted_unified_v011_sha256": ACCEPTED_UNIFIED_V011_SHA256,
        "accepted_unified_v01_sha256": ACCEPTED_UNIFIED_V01_SHA256,
        "accepted_core_baseline_sha256": ACCEPTED_CORE_V0121_SHA256,
        "accepted_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "accepted_roadmap_v011_sha256": ACCEPTED_ROADMAP_V011_SHA256,
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "shuffle_perms": SHUFFLE_PERMS,
        "shuffle_finite_sample_formula": SHUFFLE_FINITE_SAMPLE_FORMULA,
        "source_b_obs_batch_size": SOURCE_B_OBS_BATCH_SIZE,
        "seed": SEED,
        "source_a_system_id": SOURCE_A_SYSTEM_ID,
        "source_b_system_id": SOURCE_B_SYSTEM_ID,
        "identity_merge": False,
        "migration_0005": False,
    }
