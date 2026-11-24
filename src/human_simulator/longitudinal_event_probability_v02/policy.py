"""Policy — Longitudinal Event Probability Foundation v0.2."""

from __future__ import annotations

from typing import Any

VERSION = "0.2"
ARTIFACT_DIR = (
    "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2"
)
RUNTIME_DIR = "private/longitudinal-event-probability-v02"
LANDMARK_DIR = "private/longitudinal-event-probability-v02/landmarks"
MODELS_DIR = "private/longitudinal-event-probability-v02/models"
REVIEW_ZIP = (
    "stage-03-unified-longitudinal-event-probability-foundation-v0.2-review.zip"
)

ACCEPTED_TRAJ_ZIP = (
    "stage-03-unified-trajectory-regime-time-to-event-foundation-v0.1-review.zip"
)
ACCEPTED_TRAJ_SHA256 = (
    "7236ba12d14f7ba2bcc7345f3a2f00a865f42ba00c8c40c2ca30c5a7199d6421"
)
ACCEPTED_TRAJ_MEMBERS = 703
ACCEPTED_TRAJ_INDEXED = 702
ACCEPTED_TRAJ_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-trajectory-regime-time-to-event-foundation-v0.1"
)

ACCEPTED_CSR_ZIP = (
    "stage-03-first-unified-current-state-representation-applicability-ood-v0.1-review.zip"
)
ACCEPTED_CSR_SHA256 = (
    "5ba19fbd465f6e41ef5d3d3b0923c073aaf78189bc1046316aba8ec24df4af69"
)
ACCEPTED_V0111_ZIP = (
    "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1-review.zip"
)
ACCEPTED_V0111_SHA256 = (
    "9a468aa225cf8ffc7f819152646c4d8788524564bf398bffbfb8e4634c3c0f88"
)

V0111_STATES_DIR = "private/unified-individual-state-v0111/states"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
CSR_TENSOR_DIR = "private/current-state-representation-v01/tensors"
TRAJ_TRANSITIONS = "private/trajectory-regime-tte-v01/transitions"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "longitudinal-event-probability-v02"

# Reliable timestamp bounds (reject extreme corrupt years in Source B)
TS_YEAR_MIN = 1990
TS_YEAR_MAX = 2027
PREDECLARED_MAX_FOLLOWUP_DAYS = 365.0
HORIZONS_DAYS = (30.0, 90.0, 180.0, 365.0)
TIME_BINS_DAYS = (7.0, 14.0, 30.0, 60.0, 90.0, 180.0, 365.0)

# Data / acceptance gates (declared before test)
MIN_TRAIN_SUBJECTS = 80
MIN_VAL_SUBJECTS = 20
MIN_TEST_SUBJECTS = 30
MIN_TRAIN_EVENTS = 30
MIN_VAL_EVENTS = 10
OOD_MAX_VAL_FPR = 0.15
GATE_MIN_VAL_CONCORDANCE = 0.52
GATE_CAL_SLOPE_LO = 0.5
GATE_CAL_SLOPE_HI = 1.5
GATE_MAX_ECE = 0.25
EXCURSION_QUANTILE_LO = 0.025
EXCURSION_QUANTILE_HI = 0.975
MAX_EXCURSION_OUTCOMES = 8
MAX_LANDMARKS_PER_ROLE_EVAL = 8000  # subsample for model fit speed; full accounting separate

PRIOR_ZIPS = {
    "traj_v01": (ACCEPTED_TRAJ_ZIP, ACCEPTED_TRAJ_SHA256),
    "csr_v01": (ACCEPTED_CSR_ZIP, ACCEPTED_CSR_SHA256),
    "v0111": (ACCEPTED_V0111_ZIP, ACCEPTED_V0111_SHA256),
}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "no_encoder_retrain": True,
        "raw_source_aware_features_only": True,
        "no_future_horizon_in_inference": True,
        "no_a_b_semantic_merge": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "regimes_not_runtime_prediction": True,
        "horizons_days": list(HORIZONS_DAYS),
        "time_bins_days": list(TIME_BINS_DAYS),
        "predeclared_max_followup_days": PREDECLARED_MAX_FOLLOWUP_DAYS,
        "ood_max_val_fpr": OOD_MAX_VAL_FPR,
        "gates": {
            "MIN_TRAIN_SUBJECTS": MIN_TRAIN_SUBJECTS,
            "MIN_VAL_SUBJECTS": MIN_VAL_SUBJECTS,
            "MIN_TEST_SUBJECTS": MIN_TEST_SUBJECTS,
            "MIN_TRAIN_EVENTS": MIN_TRAIN_EVENTS,
            "GATE_MIN_VAL_CONCORDANCE": GATE_MIN_VAL_CONCORDANCE,
            "GATE_CAL_SLOPE_LO": GATE_CAL_SLOPE_LO,
            "GATE_CAL_SLOPE_HI": GATE_CAL_SLOPE_HI,
            "GATE_MAX_ECE": GATE_MAX_ECE,
        },
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "seed": SEED,
    }
