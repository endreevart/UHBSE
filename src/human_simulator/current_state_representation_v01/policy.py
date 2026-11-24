"""Policy — Current State Representation + Applicability/OOD v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-first-unified-current-state-representation-applicability-ood-v0.1"
)
RUNTIME_DIR = "private/current-state-representation-v01"
TENSOR_DIR = "private/current-state-representation-v01/tensors"
MODELS_DIR = "private/current-state-representation-v01/models"
REVIEW_ZIP = (
    "stage-03-first-unified-current-state-representation-applicability-ood-v0.1-review.zip"
)

# Immutable prior — individual-state baseline v0.1.1.1
ACCEPTED_V0111_ZIP = (
    "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1-review.zip"
)
ACCEPTED_V0111_SHA256 = (
    "9a468aa225cf8ffc7f819152646c4d8788524564bf398bffbfb8e4634c3c0f88"
)
ACCEPTED_V0111_MEMBERS = 672
ACCEPTED_V0111_INDEXED = 671
ACCEPTED_V0111_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1"
)

V0111_STATES_DIR = "private/unified-individual-state-v0111/states"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V0111_MODELS_DIR = "private/unified-individual-state-v0111/models"
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "current-state-representation-v01"
MODEL_NAME = "UnifiedSourceAwareStateEncoderV01"

# Vocabulary thresholds (train-only selection; held-out support required)
MIN_TRAIN_SUBJECTS = 100
MIN_TRAIN_TARGETS = 300
MIN_VAL_SUBJECTS = 20
MIN_TEST_SUBJECTS = 30

# Encoder (deterministic subsample; pure-Python GD feasibility)
ENC_RANK = 8
ENC_EPOCHS = 5
ENC_LR = 0.03
ENC_L2 = 0.05
MAX_TRAIN_STATES = 1500
METHOD_VERSION = "csr-encoder-ood-v01"

# Outcome channels per vocabulary entry
OUTCOME_CHANNELS = (
    "last_norm",
    "mask",
    "time_since",
    "n_prior",
    "prev_norm",
    "delta_norm",
    "slope_norm",
    "var_norm",
)

PRIOR_ZIPS = {
    "v0111": (ACCEPTED_V0111_ZIP, ACCEPTED_V0111_SHA256),
    "v011": (
        "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1-review.zip",
        "b1ae73f6f2b971be904a853f32c378352e61f0122712dbcb4810e0090abb2f57",
    ),
    "v01": (
        "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1-review.zip",
        "751f63eea364424ba50cc5c6cbde2104a511b3e829eff85360bca9a5e5b0c1a3",
    ),
    "v031": (
        "stage-03-unified-a-b-materialized-research-layer-v0.3.1-review.zip",
        "ccf2627c10b472e10591f54c528170ad1e98ae259ecdf97e2d0b3c85722f54e9",
    ),
}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "model_name": MODEL_NAME,
        "no_a_b_semantic_merge": True,
        "no_unit_conversion": True,
        "no_clinical_current_state_classifier": True,
        "no_medication_residual": True,
        "prior_m2_not_accepted_foundation": True,
        "DOMAIN_ACCEPTED_MAPPING_COUNT_default": 0,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "seed": SEED,
        "vocabulary_thresholds": {
            "MIN_TRAIN_SUBJECTS": MIN_TRAIN_SUBJECTS,
            "MIN_TRAIN_TARGETS": MIN_TRAIN_TARGETS,
            "MIN_VAL_SUBJECTS": MIN_VAL_SUBJECTS,
            "MIN_TEST_SUBJECTS": MIN_TEST_SUBJECTS,
        },
        "outcome_channels": list(OUTCOME_CHANNELS),
    }
