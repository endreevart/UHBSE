"""Policy — Unified Trajectory Regime Discovery and Time-to-Event Foundation v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-unified-trajectory-regime-time-to-event-foundation-v0.1"
)
RUNTIME_DIR = "private/trajectory-regime-tte-v01"
TRANSITIONS_DIR = "private/trajectory-regime-tte-v01/transitions"
TTE_DIR = "private/trajectory-regime-tte-v01/tte"
MODELS_DIR = "private/trajectory-regime-tte-v01/models"
REVIEW_ZIP = (
    "stage-03-unified-trajectory-regime-time-to-event-foundation-v0.1-review.zip"
)

# Accepted CSR v0.1 baseline
ACCEPTED_CSR_ZIP = (
    "stage-03-first-unified-current-state-representation-applicability-ood-v0.1-review.zip"
)
ACCEPTED_CSR_SHA256 = (
    "5ba19fbd465f6e41ef5d3d3b0923c073aaf78189bc1046316aba8ec24df4af69"
)
ACCEPTED_CSR_MEMBERS = 686
ACCEPTED_CSR_INDEXED = 685
ACCEPTED_CSR_ARTIFACT_DIR = (
    "artifacts/stage-03-first-unified-current-state-representation-applicability-ood-v0.1"
)

ACCEPTED_V0111_ZIP = (
    "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1-review.zip"
)
ACCEPTED_V0111_SHA256 = (
    "9a468aa225cf8ffc7f819152646c4d8788524564bf398bffbfb8e4634c3c0f88"
)

CSR_TENSOR_DIR = "private/current-state-representation-v01/tensors"
CSR_RUNTIME = "private/current-state-representation-v01"
V0111_STATES_DIR = "private/unified-individual-state-v0111/states"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V0111_MODELS_DIR = "private/unified-individual-state-v0111/models"
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "trajectory-regime-tte-v01"
MODEL_NAME = "DenoisingSourceAwareStateEncoderV01"

# Train-only vocabulary inclusion
MIN_TRAIN_SUBJECTS = 100
MIN_TRAIN_TARGETS = 300
# Evidence tiers only (not inclusion)
MIN_VAL_SUBJECTS_EVAL = 20
MIN_TEST_SUBJECTS_EVAL = 30

# Denoising encoder
ENC_RANK = 8
ENC_EPOCHS = 6
ENC_LR = 0.02
ENC_L2 = 0.05
CORRUPTION_FRAC = 0.35
MAX_TRAIN_STATES = 2500
METHOD_VERSION = "traj-tte-denoising-v01"

# Pre-declared foundation gates (validation only)
GATE_RECON_BEAT_TRAIN_MEAN_BOTH_SOURCES = True
GATE_MIN_TRAJECTORY_BETTER_THAN_ACTIVE = 3  # of comparable outcomes

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
    "csr_v01": (ACCEPTED_CSR_ZIP, ACCEPTED_CSR_SHA256),
    "v0111": (ACCEPTED_V0111_ZIP, ACCEPTED_V0111_SHA256),
    "v011": (
        "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1-review.zip",
        "b1ae73f6f2b971be904a853f32c378352e61f0122712dbcb4810e0090abb2f57",
    ),
    "v01": (
        "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1-review.zip",
        "751f63eea364424ba50cc5c6cbde2104a511b3e829eff85360bca9a5e5b0c1a3",
    ),
}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "model_name": MODEL_NAME,
        "no_a_b_semantic_merge": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "prior_encoder_not_accepted_initialization": True,
        "foundation_gates": {
            "GATE_RECON_BEAT_TRAIN_MEAN_BOTH_SOURCES": GATE_RECON_BEAT_TRAIN_MEAN_BOTH_SOURCES,
            "GATE_MIN_TRAJECTORY_BETTER_THAN_ACTIVE": GATE_MIN_TRAJECTORY_BETTER_THAN_ACTIVE,
        },
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "seed": SEED,
        "corruption_frac": CORRUPTION_FRAC,
        "vocabulary_train_only_inclusion": True,
    }
