"""Policy — Source A Global Subject Split and Individual Multi-Outcome State v0.1."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER, feature_schema_hash
from human_simulator.scientific_v02.policy import L2, SEED

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-global-split-individual-multi-outcome-state-v0.1"
)
RUNTIME_DIR = "private/global-state-v01"
REVIEW_ZIP = (
    "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1-review.zip"
)

ACCEPTED_V011_ZIP = (
    "stage-03-source-a-single-outcome-trajectory-expansion-v0.1.1-review.zip"
)
ACCEPTED_V011_SHA256 = (
    "922158a22212aedd903f5a62ea532119465da7cb74faf16326e07c1beaba6c0d"
)
ACCEPTED_V011_MEMBERS = 594
ACCEPTED_V011_INDEXED = 593
ACCEPTED_V011_ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-single-outcome-trajectory-expansion-v0.1.1"
)
ACCEPTED_V01_ZIP = (
    "stage-03-source-a-single-outcome-trajectory-expansion-v0.1-review.zip"
)
ACCEPTED_V01_SHA256 = (
    "ef3e53c3732691ac371599dfbd3181d317d74b6c1663cec76a40ee34e5373602"
)

GLOBAL_SPLIT_NAMESPACE = "source-a-global-state-v01"
GLOBAL_SPLIT_SEED = 42
# Fixed bucket boundaries on [0, 1) from hash fraction — subset-invariant.
BUCKET_TRAIN_END = 0.70
BUCKET_VAL_END = 0.85  # train [0,0.70), val [0.70,0.85), test [0.85,1.0)

THRESHOLD_CRITERIA = {
    "min_subjects_with_ge2": 100,
    "min_strict_consecutive_pairs": 300,
    "min_test_subjects_if_split": 30,
}

BOOTSTRAP_ITERS = 500
SHUFFLE_PERMS = 100
NOMINAL_COVERAGE = 0.90
OOD_FRACTION_THRESHOLD = 0.10

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
CLAIM_LEVEL = "SECONDARY_EXPLORATORY_RETROSPECTIVE_BACKTEST"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "accepted_v011_sha256": ACCEPTED_V011_SHA256,
        "global_split_namespace": GLOBAL_SPLIT_NAMESPACE,
        "global_split_seed": GLOBAL_SPLIT_SEED,
        "bucket_boundaries": {
            "train": [0.0, BUCKET_TRAIN_END],
            "validation": [BUCKET_TRAIN_END, BUCKET_VAL_END],
            "test": [BUCKET_VAL_END, 1.0],
        },
        "seed": SEED,
        "l2": L2,
        "feature_schema_hash": feature_schema_hash(),
        "feature_order": list(FEATURE_ORDER),
        "claim_level": CLAIM_LEVEL,
        "not_joint_multi_outcome_ml": True,
        "not_untouched_external_validation": True,
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
    }
