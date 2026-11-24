"""Unified Source Expansion v0.1.2.1.1 — publication / evidence integrity correction."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER as _SCIENCE_FEATURE_ORDER

VERSION = "0.1.2.1.1"
ARTIFACT_DIR = "artifacts/stage-03-unified-source-expansion-v0.1.2.1.1"
PRIOR_ARTIFACT_DIR = "artifacts/stage-03-unified-source-expansion-v0.1.2.1"
RUNTIME_DIR = "private/unified-runtime/v0.1.2.1.1"
SEED = 42

FIXED_OUTCOME_CANDIDATE_ID = "2685c68a3e247ca4"
FIXED_OUTCOME_LABEL = "Т3 св."
FIXED_OUTCOME_UNIT = "пмоль/л"
PREFERRED_B_CODE = "53"
PREFERRED_B_UNIT = "пмоль/л"

SOURCE_A_SYSTEM_ID = "magerya_api"
SOURCE_B_SYSTEM_ID = "kgz_raw"

# Immutable baselines — NEVER overwrite
ACCEPTED_UNIFIED_V0121_ZIP = "stage-03-unified-source-expansion-v0.1.2.1-review.zip"
ACCEPTED_UNIFIED_V0121_SHA256 = (
    "6f6e906eb8f01e7a6868c4c4eb71857b15670c5ce6db6ce49125a343572cba26"
)
ACCEPTED_UNIFIED_V0121_MEMBERS = 282
ACCEPTED_UNIFIED_V0121_INDEXED = 281

ACCEPTED_UNIFIED_V012_ZIP = "stage-03-unified-source-expansion-v0.1.2-review.zip"
ACCEPTED_UNIFIED_V012_SHA256 = (
    "55b92ce7b9762114040233be30eaa4705b03e1aa2d378097e21be4ef2258b269"
)
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

# Expected file SHA when frozen model bytes are copied unchanged from v0.1.2.1
EXPECTED_FROZEN_FILE_SHA256_IF_UNCHANGED = (
    "ae69a70ba7acc9c1cd2ea069aab8cd9a3adcbea223deb4a32efab8e3b7f5dd9f"
)
EXPECTED_FROZEN_IDENTITY_SHA256 = (
    "cc5009b7accc7f0f0672a9dfd6e1eb751893d36828c201aff4a48c5bc4426657"
)

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "unified_v0.1.2.1": (ACCEPTED_UNIFIED_V0121_ZIP, ACCEPTED_UNIFIED_V0121_SHA256),
    "unified_v0.1.2": (ACCEPTED_UNIFIED_V012_ZIP, ACCEPTED_UNIFIED_V012_SHA256),
    "unified_v0.1.1": (ACCEPTED_UNIFIED_V011_ZIP, ACCEPTED_UNIFIED_V011_SHA256),
    "unified_v0.1": (ACCEPTED_UNIFIED_V01_ZIP, ACCEPTED_UNIFIED_V01_SHA256),
    "core_v0.1.2.1": (ACCEPTED_CORE_V0121_ZIP, ACCEPTED_CORE_V0121_SHA256),
    "sdr_v0.1.1.1": (ACCEPTED_SDR_V0111_ZIP, ACCEPTED_SDR_V0111_SHA256),
    "roadmap_v0.1.1": (ACCEPTED_ROADMAP_V011_ZIP, ACCEPTED_ROADMAP_V011_SHA256),
}

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SECURITY_FINDINGS_STATUS = "RECORDED_NON_BLOCKING"
SECURITY_GATE_MODE = "ADVISORY_ONLY"
CLINICAL_VALIDATION_STATUS = "NOT_STARTED"
INTERVENTION_RESPONSE_MODEL_STATUS = "NOT_STARTED"
TREATMENT_EFFECT_STATUS = "NOT_EVALUATED"
PRODUCTION_READINESS = "NOT_CLAIMED"

CROSS_SOURCE_TRANSFER_NAME = "CROSS_SOURCE_TRANSFER_EXPLORATION"
NOT_RUN_DUE_TO_FAILED_GATE = "NOT_RUN_DUE_TO_FAILED_GATE"
DOMAIN_REVIEW_REQUIRED = "DOMAIN_REVIEW_REQUIRED"

FEATURE_ORDER = _SCIENCE_FEATURE_ORDER

# Declared before viewing transfer metrics (engineering thresholds only)
APPLICABILITY_MAX_OOD_FRACTION = 0.35

REQUIRED_STATUSES: tuple[str, ...] = (
    "baseline_verification_status",
    "publication_evidence_correction_status",
    "report_consistency_status",
    "frozen_model_file_hash_status",
    "frozen_model_identity_hash_status",
    "frozen_model_semantic_payload_status",
    "source_a_population_lineage_status",
    "source_a_provenance_isolation_status",
    "source_a_uncertainty_evidence_status",
    "applicability_reference_status",
    "applicability_status",
    "applicability_gate_integrity_status",
    "t3_semantic_harmonization_status",
    "cross_source_transfer_status",
    "evidence_closure_status",
    "technical_multi_source_pipeline_status",
    "clinical_validation_status",
    "intervention_response_model_status",
    "production_readiness",
    "security_stage_status",
    "content_verification_status",
    "pre_pack_manifest_status",
    "clean_staging_test_status",
    "post_pack_publication_verification",
)

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "scope-and-claims.json",
    "baseline-verification.json",
    "before-after-hash-matrix.json",
    "source-a-population-lineage.json",
    "source-a-provenance-isolation.json",
    "source-a-uncertainty-recomputation.json",
    "frozen-source-a-model.json",
    "frozen-source-a-model.json.sha256",
    "frozen-source-a-model.identity.json",
    "applicability-report.json",
    "transfer-gate.json",
    "transfer-results.json",
    "transfer-non-execution.json",
    "report.md",
    "report.json",
    "verification.json",
    "release-verification.json",
    "consistency-check.json",
    "test-results.json",
    "evidence-manifest.sha256",
    "REPRODUCE.md",
    "changed-files.json",
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "unified_version": VERSION,
        "changeset": "Publication and Scientific Evidence Integrity Correction",
        "security_stage_status": SECURITY_STAGE_STATUS,
        "security_findings_status": SECURITY_FINDINGS_STATUS,
        "security_gate_mode": SECURITY_GATE_MODE,
        "security_blocks_core": False,
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "treatment_effect_status": TREATMENT_EFFECT_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "accepted_unified_v0121_sha256": ACCEPTED_UNIFIED_V0121_SHA256,
        "accepted_unified_v012_sha256": ACCEPTED_UNIFIED_V012_SHA256,
        "accepted_unified_v011_sha256": ACCEPTED_UNIFIED_V011_SHA256,
        "accepted_unified_v01_sha256": ACCEPTED_UNIFIED_V01_SHA256,
        "accepted_core_baseline_sha256": ACCEPTED_CORE_V0121_SHA256,
        "accepted_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "accepted_roadmap_v011_sha256": ACCEPTED_ROADMAP_V011_SHA256,
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "preferred_b_code": PREFERRED_B_CODE,
        "preferred_b_unit": PREFERRED_B_UNIT,
        "source_a_system_id": SOURCE_A_SYSTEM_ID,
        "source_b_system_id": SOURCE_B_SYSTEM_ID,
        "feature_order": list(FEATURE_ORDER),
        "applicability_max_ood_fraction": APPLICABILITY_MAX_OOD_FRACTION,
        "no_retrain": True,
        "no_transfer_execution": True,
    }
