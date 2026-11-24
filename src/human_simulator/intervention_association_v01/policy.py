"""Policy pins for First Technical Medication-Association Baseline v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-03-first-medication-association-baseline-v0.1"
RUNTIME_DIR = "private/intervention-association-v01"
EPISODE_DIR = f"{RUNTIME_DIR}/episodes"

ACCEPTED_V011_ZIP = (
    "stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1-review.zip"
)
ACCEPTED_V011_SHA256 = (
    "35a35dd48612590fedf064e3916aa1ae14ab70bd2626e257889b70c11a55d796"
)
ACCEPTED_V011_MEMBERS = 365
ACCEPTED_V011_INDEXED = 364

REVIEW_ZIP = "stage-03-first-medication-association-baseline-v0.1-review.zip"

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "population_v0.1.1": (ACCEPTED_V011_ZIP, ACCEPTED_V011_SHA256),
    "population_v0.1": (
        "stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1-review.zip",
        "58c6b6d6a13b6da17da4eee3cbe1840b91228deed869b74ca4138ef7ef98af1f",
    ),
    "scientific_v02_shadow_v01": (
        "stage-03-source-a-scientific-baseline-v0.2-shadow-transfer-v0.1-review.zip",
        "0c1bc7006f684e79bf80a1e02e03158629d8881e8f7f64226a83539f2f25611b",
    ),
    "unified_v0.1.2.1.1": (
        "stage-03-unified-source-expansion-v0.1.2.1.1-review.zip",
        "5f9d10e1e57ed7423b651a0156714ce976b3ec01f5c85306e929f91f7ccdb997",
    ),
    "core_v0.1.2.1": (
        "stage-03-core-vertical-slice-v0.1.2.1-review.zip",
        "9eea316ccc022e6aed75075b47089b10a1263e55e2c58b9fd6852e8201fe1a5f",
    ),
}

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
L2 = 0.1
N_BOOTSTRAP = 2000
N_PERMUTATION = 500
HORIZONS_DAYS = (30, 90, 180, 365)
PRIMARY_HORIZON_DAYS = 365

# Predeclared gates (before reading test performance)
MIN_LEVEL5_SUBJECTS = 200
MIN_LEVEL5_EPISODES = 500
MIN_TEST_SUBJECTS = 50
MIN_TEST_EPISODES = 100
MIN_COHORT_TRAIN_EPISODES = 100
MIN_COHORT_TRAIN_SUBJECTS = 40

SPLIT_FRACTIONS = (0.70, 0.15, 0.15)

M1_FEATURES = (
    "pre_value",
    "n_prior_measurements",
    "prior_slope",
    "days_since_previous",
    "horizon_days",
    "prior_slope_missing",
    "days_since_previous_missing",
)
M2_EXTRA_FEATURES = (
    "medicine_id_hash",
    "polypharmacy_flag",
    "concurrent_med_count",
)

CLINICAL_USE_PROHIBITED = "CLINICAL_USE_PROHIBITED"
CAUSAL_INTERPRETATION_PROHIBITED = "CAUSAL_INTERPRETATION_PROHIBITED"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "causal_effect_status": "NOT_EVALUATED",
        "clinical_validation_status": "NOT_STARTED",
        "qsp_status": "NOT_STARTED",
        "pkpd_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "clinical_use": CLINICAL_USE_PROHIBITED,
        "causal_interpretation": CAUSAL_INTERPRETATION_PROHIBITED,
        "predictive_association_is_not_treatment_response": True,
        "no_identity_merge": True,
        "seed": SEED,
        "l2": L2,
        "n_bootstrap": N_BOOTSTRAP,
        "n_permutation": N_PERMUTATION,
        "horizons_days": list(HORIZONS_DAYS),
        "primary_horizon_days": PRIMARY_HORIZON_DAYS,
        "level5_gates": {
            "min_subjects": MIN_LEVEL5_SUBJECTS,
            "min_episodes": MIN_LEVEL5_EPISODES,
            "min_test_subjects": MIN_TEST_SUBJECTS,
            "min_test_episodes": MIN_TEST_EPISODES,
        },
        "m1_features": list(M1_FEATURES),
        "m2_extra_features": list(M2_EXTRA_FEATURES),
    }
