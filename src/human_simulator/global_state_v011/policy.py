"""Policy — Global Split Individual Multi-Outcome State v0.1.1 (corrective)."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1"
)
RUNTIME_DIR = "private/global-state-v011"
REVIEW_ZIP = (
    "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1-review.zip"
)

ACCEPTED_V01_ZIP = (
    "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1-review.zip"
)
ACCEPTED_V01_SHA256 = (
    "3f98628fca0c7c78f29310cd88fb5cf30903720bb2528451dba6661bfb200ffc"
)
ACCEPTED_V01_MEMBERS = 612
ACCEPTED_V01_INDEXED = 611
ACCEPTED_V01_ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-global-split-individual-multi-outcome-state-v0.1"
)
ACCEPTED_V01_RUNTIME_DIR = "private/global-state-v01"

TRAJ_V011_ZIP = (
    "stage-03-source-a-single-outcome-trajectory-expansion-v0.1.1-review.zip"
)
TRAJ_V011_SHA256 = (
    "922158a22212aedd903f5a62ea532119465da7cb74faf16326e07c1beaba6c0d"
)

MIN_TEST_SUBJECTS_EVALUABLE = 30
V01_FIXED_PREDICTION_HORIZON_DAYS = 30.0
HORIZON_BINS = (
    ("1_30", 1.0, 30.0),
    ("31_90", 30.0, 90.0),
    ("91_180", 90.0, 180.0),
    ("181_365", 180.0, 365.0),
    ("gt_365", 365.0, float("inf")),
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
CLAIM_LEVEL = "SECONDARY_EXPLORATORY_RETROSPECTIVE_BACKTEST"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "corrective_over": "v0.1",
        "accepted_v01_sha256": ACCEPTED_V01_SHA256,
        "no_provider_refit": True,
        "horizon_alignment_required": True,
        "v01_fixed_prediction_horizon_days": V01_FIXED_PREDICTION_HORIZON_DAYS,
        "min_test_subjects_evaluable": MIN_TEST_SUBJECTS_EVALUABLE,
        "claim_level": CLAIM_LEVEL,
        "not_joint_multi_outcome_ml": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
    }
