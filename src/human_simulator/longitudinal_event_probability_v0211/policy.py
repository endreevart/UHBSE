"""Policy — Longitudinal Event Probability Foundation v0.2.1.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.2.1.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2.1.1"
)
RUNTIME_DIR = "private/longitudinal-event-probability-v0211"
LANDMARK_DIR = "private/longitudinal-event-probability-v0211/landmarks"
MODELS_DIR = "private/longitudinal-event-probability-v0211/models"
REVIEW_ZIP = (
    "stage-03-unified-longitudinal-event-probability-foundation-v0.2.1.1-review.zip"
)

ACCEPTED_V021_ZIP = (
    "stage-03-unified-longitudinal-event-probability-foundation-v0.2.1-review.zip"
)
ACCEPTED_V021_SHA256 = (
    "d0036ecacb52a4e622cf363e9acea27ffadf0163300c596b9fcf2a7bfa2e90dd"
)
ACCEPTED_V021_MEMBERS = 734
ACCEPTED_V021_INDEXED = 733
ACCEPTED_V021_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2.1"
)

ACCEPTED_V02_ZIP = (
    "stage-03-unified-longitudinal-event-probability-foundation-v0.2-review.zip"
)
ACCEPTED_V02_SHA256 = (
    "4a92d40dafeaece94cde0a5c29b170c39c000bed1f44793ee8294fdddc88b8d6"
)
ACCEPTED_TRAJ_ZIP = (
    "stage-03-unified-trajectory-regime-time-to-event-foundation-v0.1-review.zip"
)
ACCEPTED_TRAJ_SHA256 = (
    "7236ba12d14f7ba2bcc7345f3a2f00a865f42ba00c8c40c2ca30c5a7199d6421"
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

V021_SRC = "src/human_simulator/longitudinal_event_probability_v021"
V021_RUNTIME = "private/longitudinal-event-probability-v021"
V021_ARTIFACT_DIR = ACCEPTED_V021_ARTIFACT_DIR
FREEZE_MANIFEST = "pre-test-freeze-manifest.json"
PRETEST_REGISTRY = "pre-test-accepted-probability-registry.json"
TEST_OPENED_MARKER = "test-opened.json"

V0111_STATES_DIR = "private/unified-individual-state-v0111/states"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
TRAJ_TRANSITIONS = "private/trajectory-regime-tte-v01/transitions"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "longitudinal-event-probability-v0211"

TS_YEAR_MIN = 1990
TS_YEAR_MAX = 2027
PREDECLARED_MAX_FOLLOWUP_DAYS = 365.0
CANDIDATE_HORIZONS_DAYS = (30.0, 90.0, 180.0, 365.0)
TIME_BINS_DAYS = (7.0, 14.0, 30.0, 60.0, 90.0, 180.0, 365.0)

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
GATE_G_HAT_FLOOR = 1e-3
GATE_MIN_IPCW_EFFECTIVE_N = 20
GATE_MIN_EVENT_FREE_GROUPS = 20
EXCURSION_QUANTILE_LO = 0.025
EXCURSION_QUANTILE_HI = 0.975
MAX_EXCURSION_OUTCOMES_PER_SOURCE = 4
MAX_LANDMARKS_PER_ROLE_EVAL = 8000
HORIZON_BOUNDARY_EPS = 1e-6

PRIOR_ZIPS = {
    "lep_v021": (ACCEPTED_V021_ZIP, ACCEPTED_V021_SHA256),
    "lep_v02": (ACCEPTED_V02_ZIP, ACCEPTED_V02_SHA256),
    "traj_v01": (ACCEPTED_TRAJ_ZIP, ACCEPTED_TRAJ_SHA256),
    "csr_v01": (ACCEPTED_CSR_ZIP, ACCEPTED_CSR_SHA256),
    "v0111": (ACCEPTED_V0111_ZIP, ACCEPTED_V0111_SHA256),
}

FEATURE_ORDER = [
    "longitudinal_age_days",
    "days_since_last_event",
    "n_events_before",
    "n_obs_before",
    "n_encounters_before",
    "n_medications_before",
    "n_recommendations_before",
    "n_documents_before",
    "n_procedures_before",
    "source_is_a",
    "source_is_b",
    "missingness_lab",
    "has_lab_history",
    "has_med_history",
    "cutoff_ordinal",
]

EXCURSION_FEATURE_SUFFIX = [
    "outcome_last_value",
    "outcome_last_value_train_z",
    "days_since_last_outcome",
    "n_prior_outcome_measurements",
    "outcome_prev_value",
    "outcome_delta_t0",
    "outcome_history_mask",
]

EXCURSION_ENDPOINT = "TIME_TO_FIRST_RECORDED_SOURCE_SPECIFIC_OUTCOME_EXCURSION"


def cell_key(
    source_system: str,
    endpoint: str,
    outcome_key: str | None,
    horizon_days: int | float,
) -> tuple[str, str, str | None, int]:
    return (source_system, endpoint, outcome_key, int(horizon_days))


def cell_id_sha256(
    source_system: str,
    endpoint: str,
    outcome_key: str | None,
    *,
    version: str = VERSION,
) -> str:
    import hashlib

    outcome = outcome_key if outcome_key is not None else "null"
    canonical = f"{source_system}|{endpoint}|{outcome}|{version}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "no_encoder_retrain": True,
        "no_new_regime_model": True,
        "no_medication_residual": True,
        "raw_source_aware_features_only": True,
        "no_future_horizon_in_inference": True,
        "no_a_b_semantic_merge": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "regimes_not_runtime_prediction": True,
        "candidate_horizons_days": list(CANDIDATE_HORIZONS_DAYS),
        "predeclared_max_followup_days": PREDECLARED_MAX_FOLLOWUP_DAYS,
        "do_not_replace_365_after_test": True,
        "ipcw_brier_estimator": "graf_ipcw_brier_divide_by_n",
        "calibration_method": "ipcw_weighted_logit_slope",
        "calibration_eval_independent_of_fit": True,
        "physical_pre_test_freeze": True,
        "GATE_G_HAT_FLOOR": GATE_G_HAT_FLOOR,
        "GATE_MIN_IPCW_EFFECTIVE_N": GATE_MIN_IPCW_EFFECTIVE_N,
        "GATE_MIN_EVENT_FREE_GROUPS": GATE_MIN_EVENT_FREE_GROUPS,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "REGIME_FOUNDATION_ACCEPTANCE_STATUS": "NOT_ACCEPTED_RETROSPECTIVE_ONLY",
        "seed": SEED,
        "feature_order": list(FEATURE_ORDER),
        "excursion_feature_suffix": list(EXCURSION_FEATURE_SUFFIX),
        "excursion_endpoint": EXCURSION_ENDPOINT,
    }
