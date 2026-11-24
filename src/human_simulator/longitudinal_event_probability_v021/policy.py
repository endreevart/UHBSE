"""Policy — Longitudinal Event Probability Foundation v0.2.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.2.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2.1"
)
RUNTIME_DIR = "private/longitudinal-event-probability-v021"
LANDMARK_DIR = "private/longitudinal-event-probability-v021/landmarks"
MODELS_DIR = "private/longitudinal-event-probability-v021/models"
REVIEW_ZIP = (
    "stage-03-unified-longitudinal-event-probability-foundation-v0.2.1-review.zip"
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

V02_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2"
)
V02_SRC = "src/human_simulator/longitudinal_event_probability_v02"
V02_RUNTIME = "private/longitudinal-event-probability-v02"

V0111_STATES_DIR = "private/unified-individual-state-v0111/states"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
TRAJ_TRANSITIONS = "private/trajectory-regime-tte-v01/transitions"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "longitudinal-event-probability-v021"

TS_YEAR_MIN = 1990
TS_YEAR_MAX = 2027
PREDECLARED_MAX_FOLLOWUP_DAYS = 365.0
# Candidate evaluation horizons. A horizon is supported only if the cell is accepted.
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
EXCURSION_QUANTILE_LO = 0.025
EXCURSION_QUANTILE_HI = 0.975
MAX_EXCURSION_OUTCOMES_PER_SOURCE = 4
MAX_LANDMARKS_PER_ROLE_EVAL = 8000

# Rejected v0.2 engine routing evidence
V02_ENGINE_USED_MODEL_HASH = (
    "b6a6d2471f6eb43af351ccdf815237bf6663384500497fcd298f74883206ca98"
)
V02_ACCEPTED_B_OBS_MODEL_HASH = (
    "69cc7375257943b30bb087f579c551104abbc7eb6ffeb13d27a3bb89d1c1dce3"
)

PRIOR_ZIPS = {
    "lep_v02": (ACCEPTED_V02_ZIP, ACCEPTED_V02_SHA256),
    "traj_v01": (ACCEPTED_TRAJ_ZIP, ACCEPTED_TRAJ_SHA256),
    "csr_v01": (ACCEPTED_CSR_ZIP, ACCEPTED_CSR_SHA256),
    "v0111": (ACCEPTED_V0111_ZIP, ACCEPTED_V0111_SHA256),
}

# t0-assignable regime features only (option A)
REGIME_T0_FEATURE_NAMES = (
    "history_depth_t0",
    "mask_density_t0",
    "n_medications_before",
    "days_since_last_event",
    "longitudinal_age_days",
)

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
        "raw_source_aware_features_only": True,
        "no_future_horizon_in_inference": True,
        "no_a_b_semantic_merge": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "regimes_not_runtime_prediction": True,
        "regime_contract": "t0_assignable",
        "candidate_horizons_days": list(CANDIDATE_HORIZONS_DAYS),
        "time_bins_days": list(TIME_BINS_DAYS),
        "predeclared_max_followup_days": PREDECLARED_MAX_FOLLOWUP_DAYS,
        "administrative_window_is_not_continuous_observation": True,
        "ipcw_brier_estimator": "graf_ipcw_brier_divide_by_n",
        "calibration_method": "ipcw_weighted_logit_slope",
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
        "feature_order": list(FEATURE_ORDER),
    }
