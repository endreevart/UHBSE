"""Unified Source Expansion v0.1.2.1 — policy constants."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER as _SCIENCE_FEATURE_ORDER

VERSION = "0.1.2.1"
ARTIFACT_DIR = "artifacts/stage-03-unified-source-expansion-v0.1.2.1"
RUNTIME_DIR = "private/unified-runtime/v0.1.2.1"
SEED = 42

FIXED_OUTCOME_CANDIDATE_ID = "2685c68a3e247ca4"
FIXED_OUTCOME_LABEL = "Т3 св."
FIXED_OUTCOME_UNIT = "пмоль/л"
PREFERRED_B_CODE = "53"
PREFERRED_B_UNIT = "пмоль/л"

# Immutable baselines — NEVER overwrite
ACCEPTED_UNIFIED_V012_ZIP = "stage-03-unified-source-expansion-v0.1.2-review.zip"
ACCEPTED_UNIFIED_V012_SHA256 = (
    "55b92ce7b9762114040233be30eaa4705b03e1aa2d378097e21be4ef2258b269"
)
ACCEPTED_UNIFIED_V012_MEMBERS = 276
ACCEPTED_UNIFIED_V012_INDEXED = 275

ACCEPTED_UNIFIED_V011_ZIP = "stage-03-unified-source-expansion-v0.1.1-review.zip"
ACCEPTED_UNIFIED_V011_SHA256 = (
    "d0e8a973ecbbee6e618cf5976d8a688abf23023ccc477710668fed3b16072faa"
)
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

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "unified_v0.1.2": (ACCEPTED_UNIFIED_V012_ZIP, ACCEPTED_UNIFIED_V012_SHA256),
    "unified_v0.1.1": (ACCEPTED_UNIFIED_V011_ZIP, ACCEPTED_UNIFIED_V011_SHA256),
    "unified_v0.1": (ACCEPTED_UNIFIED_V01_ZIP, ACCEPTED_UNIFIED_V01_SHA256),
    "core_v0.1.2.1": (ACCEPTED_CORE_V0121_ZIP, ACCEPTED_CORE_V0121_SHA256),
    "sdr_v0.1.1.1": (ACCEPTED_SDR_V0111_ZIP, ACCEPTED_SDR_V0111_SHA256),
    "roadmap_v0.1.1": (ACCEPTED_ROADMAP_V011_ZIP, ACCEPTED_ROADMAP_V011_SHA256),
}

SOURCE_A_SYSTEM_ID = "magerya_api"
SOURCE_B_SYSTEM_ID = "kgz_raw"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SECURITY_FINDINGS_STATUS = "RECORDED_NON_BLOCKING"
SECURITY_GATE_MODE = "ADVISORY_ONLY"
CLINICAL_VALIDATION_STATUS = "NOT_STARTED"
INTERVENTION_RESPONSE_MODEL_STATUS = "NOT_STARTED"
TREATMENT_EFFECT_STATUS = "NOT_EVALUATED"
PRODUCTION_READINESS = "NOT_CLAIMED"

CROSS_SOURCE_TRANSFER_NAME = "CROSS_SOURCE_TRANSFER_EXPLORATION"
NOT_RUN_DUE_TO_FAILED_GATE = "NOT_RUN_DUE_TO_FAILED_GATE"
EXECUTED_EXPLORATORY_TRANSFER = "EXECUTED_EXPLORATORY_FROZEN_MODEL_TRANSFER"
DOMAIN_REVIEW_REQUIRED = "DOMAIN_REVIEW_REQUIRED"
INSUFFICIENT_METADATA = "INSUFFICIENT_METADATA"
OUTCOME_NOT_COMPARABLE = "OUTCOME_NOT_COMPARABLE"
OUTCOME_COMPARABLE = "OUTCOME_COMPARABLE"
OUTCOME_COMPARABLE_WITH_LIMITATIONS = "OUTCOME_COMPARABLE_WITH_LIMITATIONS"
REQUIRES_FUTURE_SCHEMA_DECISION = "REQUIRES_FUTURE_SCHEMA_DECISION"

# Engineering thresholds only (not clinical claims)
MIN_B_SUBJECTS_WITH_PAIRS = 100
MIN_B_PAIRS = 200

VALIDATION_ID_PREFIX = "v0121test_"
VALIDATION_NONCE = "validation-slice-v0121"

EMPTY_HEADER_POLICY = "KEEP_ROWS_EXCLUDE_FROM_SCIENCE"

DISPOSITION_KEYS = ("accepted", "rejected", "unsupported", "quarantined")

ALLOWED_TRANSFER_RESULT_STATUSES: tuple[str, ...] = (
    NOT_RUN_DUE_TO_FAILED_GATE,
    EXECUTED_EXPLORATORY_TRANSFER,
    "INSUFFICIENT_SOURCE_B_PAIRS",
    "APPLICABILITY_FAIL",
    "FROZEN_MODEL_UNAVAILABLE",
)

REQUIRED_STATUSES: tuple[str, ...] = (
    "evidence_closure_status",
    "source_b_accounting_status",
    "baseline_verification_status",
    "source_row_accounting_status",
    "observation_header_accounting_status",
    "observation_component_accounting_status",
    "source_record_accounting_status",
    "empty_component_observation_semantics_status",
    "insertion_rollback_validation_status",
    "source_a_uncertainty_recomputation_status",
    "t3_semantic_harmonization_status",
    "source_b_temporal_dataset_status",
    "source_b_pair_construction_status",
    "frozen_source_a_model_status",
    "applicability_status",
    "transfer_gate_status",
    "cross_source_transfer_status",
    "technical_multi_source_pipeline_status",
    "identity_linkage_status",
    "pre_publish_verification_status",
    "post_publish_integrity_status",
    "publication_integrity_status",
    "clinical_validation_status",
    "intervention_response_model_status",
    "treatment_effect_status",
    "production_readiness",
    "security_stage_status",
)

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "scope-and-claims.json",
    "baseline-verification.json",
    "before-after-hash-matrix.json",
    "source-row-accounting.json",
    "observation-header-accounting.json",
    "observation-component-accounting.json",
    "source-record-accounting.json",
    "empty-component-analysis.json",
    "empty-component-policy.yaml",
    "insertion-rollback-validation.json",
    "source-a-uncertainty-recomputation.json",
    "t3-semantic-comparison-matrix.json",
    "source-b-pair-construction.json",
    "frozen-source-a-model.json",
    "frozen-source-a-model.json.sha256",
    "applicability-report.json",
    "transfer-gate.json",
    "transfer-results.json",
    "report.md",
    "report.json",
    "verification.json",
    "release-verification.json",
    "test-results.json",
    "evidence-manifest.sha256",
    "REPRODUCE.md",
    "changed-files.json",
)

# Re-export science feature contract (do not fork)
FEATURE_ORDER = _SCIENCE_FEATURE_ORDER


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
        "accepted_unified_v012_sha256": ACCEPTED_UNIFIED_V012_SHA256,
        "accepted_unified_v011_sha256": ACCEPTED_UNIFIED_V011_SHA256,
        "accepted_unified_v01_sha256": ACCEPTED_UNIFIED_V01_SHA256,
        "accepted_core_baseline_sha256": ACCEPTED_CORE_V0121_SHA256,
        "accepted_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "accepted_roadmap_v011_sha256": ACCEPTED_ROADMAP_V011_SHA256,
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "preferred_b_code": PREFERRED_B_CODE,
        "preferred_b_unit": PREFERRED_B_UNIT,
        "feature_order": list(FEATURE_ORDER),
        "seed": SEED,
        "identity_merge": False,
        "migration_0005": False,
        "empty_header_policy": EMPTY_HEADER_POLICY,
    }
