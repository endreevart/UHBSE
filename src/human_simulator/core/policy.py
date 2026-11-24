"""Owner policy: security paused; Core Vertical Slice v0.1.2.1."""

from __future__ import annotations

from typing import Any

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SECURITY_FINDINGS_STATUS = "RECORDED_NON_BLOCKING"
SECURITY_GATE_MODE = "ADVISORY_ONLY"
CORE_DEVELOPMENT_STATUS = "ACTIVE"
AUTHORISED_DATA_ACCESS = "ENABLED"

DEFERRED_PRODUCTION_HARDENING: tuple[str, ...] = (
    "initial_root_token_available",
    "vault_key_custody_decision_required",
    "pgp_keys_shared_keyring_empty_passphrase",
    "multi_custodian_separation_absent",
)

CLOSED_SECURITY_FINDINGS: tuple[str, ...] = (
    "limited_operator_identity_absent",
    "loader_restart_reauth_procedure_absent",
)

CORE_ARTIFACT_DIR = "artifacts/stage-03-core-vertical-slice-v0.1.2.1"
CORE_SLICE_VERSION = "0.1.2.1"
DEFAULT_SUBJECT_LIMIT = 100
TIMELINE_SUBJECT_LIMIT = 10
SNAPSHOT_SUBJECT_LIMIT = 10
SIMULATED_SUBJECT_LIMIT = 1
PER_PATIENT_LAB_LIMIT = 40
PER_RESULT_ITEM_LIMIT = 15
SOURCE_SYSTEM_ID = "magerya_api"
TRANSFORMATION_ID = "core_vertical_slice_v0.1.2.1"
TRANSFORMATION_VERSION = "0.1.2.1"
SNAPSHOT_BUILDER_VERSION = "0.1.2.1"
SELECTION_POLICY_VERSION = "0.1.2"
ID_NAMESPACE_VERSION = "0.7.0"
KEY_VERSION = "1"
COHORT_SAMPLE_CLASS = "TECHNICAL_COVERAGE_BIASED_SAMPLE"
CHECKPOINT_PHASE = "POST_STEP_CHECKPOINT"

# Accepted prior review ZIP digests (immutable)
ACCEPTED_V01_ZIP_SHA256 = "933c34bee1f03af9e22c54be2fb5aa4022228bb7353a35ad2f7e93d3793cb67c"
ACCEPTED_V011_ZIP_SHA256 = "13fbf307fd03eb8ed419a800ff7fed254a8159240482e8ac4b28b5f391941128"
ACCEPTED_V012_ZIP_SHA256 = "d4218dda05cdf8657e03768ce81727e274a691e90abee3ff701bae1018f419f8"

# Frozen baseline row counts from accepted v0.1.2 (no reload in 0.1.2.1)
BASELINE_V012_ROW_COUNTS: dict[str, int] = {
    "source_system": 1,
    "source_record": 12544,
    "subject": 100,
    "subject_characteristic": 200,
    "encounter": 2153,
    "observation": 4000,
    "observation_component": 5333,
}

REQUIRED_DESIGN_CONTRACTS: tuple[str, ...] = (
    "canonical-model.yaml",
    "provenance-contract.yaml",
    "temporal-contract.yaml",
)
DESIGN_CONTENT_MANIFEST = "artifacts/stage-03/design-content-manifest.sha256"


def policy_snapshot() -> dict[str, Any]:
    return {
        "security_stage_status": SECURITY_STAGE_STATUS,
        "security_findings_status": SECURITY_FINDINGS_STATUS,
        "security_gate_mode": SECURITY_GATE_MODE,
        "core_development_status": CORE_DEVELOPMENT_STATUS,
        "authorised_data_access": AUTHORISED_DATA_ACCESS,
        "core_slice_version": CORE_SLICE_VERSION,
        "deferred_production_hardening": list(DEFERRED_PRODUCTION_HARDENING),
        "closed_security_findings": list(CLOSED_SECURITY_FINDINGS),
        "security_blocks_core": False,
        "clinical_validation_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "clinical_rows_read": 0,
        "raw_db_connections": 0,
        "note": "Security findings are advisory only; they must not change core command exit codes",
    }


def security_blocks_core_exit() -> bool:
    return False
