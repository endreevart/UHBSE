"""Policy pins for medication-association baseline v0.1.1 corrections."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.1"
ARTIFACT_DIR = "artifacts/stage-03-first-medication-association-baseline-v0.1.1"
EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)

ACCEPTED_V01_ZIP = (
    "stage-03-first-medication-association-baseline-v0.1-review.zip"
)
ACCEPTED_V01_SHA256 = (
    "11975e730197e61792288ac30bd81137c2aa0e05a1b9f07217f26da9336615fc"
)
ACCEPTED_V01_MEMBERS = 57
ACCEPTED_V01_INDEXED = 56

REVIEW_ZIP = "stage-03-first-medication-association-baseline-v0.1.1-review.zip"

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "medication_association_v0.1": (ACCEPTED_V01_ZIP, ACCEPTED_V01_SHA256),
    "population_v0.1.1": (
        "stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1-review.zip",
        "35a35dd48612590fedf064e3916aa1ae14ab70bd2626e257889b70c11a55d796",
    ),
    "population_v0.1": (
        "stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1-review.zip",
        "58c6b6d6a13b6da17da4eee3cbe1840b91228deed869b74ca4138ef7ef98af1f",
    ),
}

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
L2 = 0.1
N_BOOTSTRAP = 2000
N_PERMUTATION = 500
PRIMARY_HORIZON_DAYS = 365
TIMESTAMP_HYPOTHESIS = "appointment_date"

# Predeclared M2C signed feature-hash dimension (chosen before reading test results)
M2C_HASH_DIM = 32
M2C_HASH_SEED = 42
MIN_FREQ_FOR_NAMED_CATEGORY = 20  # documented; hashing used as primary representation

M1_FEATURES = (
    "pre_value",
    "n_prior_measurements",
    "prior_slope",
    "days_since_previous",
    "horizon_days",
    "prior_slope_missing",
    "days_since_previous_missing",
)
M2C_EXTRA_FEATURES = tuple(f"med_signed_hash_{i}" for i in range(M2C_HASH_DIM)) + (
    "polypharmacy_flag",
    "concurrent_med_count",
)
LEGACY_M2_EXTRA = (
    "medicine_id_ordinal_index",  # LEGACY_ORDINAL_MEDICATION_ENCODING
    "polypharmacy_flag",
    "concurrent_med_count",
)

MIN_COHORT_TRAIN_EPISODES = 100
MIN_COHORT_TRAIN_SUBJECTS = 40
MIN_VAL_FOR_UNCERTAINTY = 30
MIN_VAL_FOR_CALIBRATION_CLAIM = 100
NOMINAL_COVERAGE = 0.90

V01_COHORTS = (
    ("Лимфоциты", "%"),
    ("Средний объем эритроцитов (MCV)", "фл"),
    ("Моноциты", "%"),
    ("Нейтрофилы", "%"),
    ("Эозинофилы", "%"),
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
        "authoritative_comparison": "M1_vs_M2C",
        "legacy_ordinal_m2": "LEGACY_ORDINAL_MEDICATION_ENCODING",
        "m2c_representation": "deterministic_signed_feature_hashing",
        "m2c_hash_dim": M2C_HASH_DIM,
        "m2c_hash_seed": M2C_HASH_SEED,
        "seed": SEED,
        "l2": L2,
        "n_bootstrap": N_BOOTSTRAP,
        "n_permutation": N_PERMUTATION,
        "nominal_coverage": NOMINAL_COVERAGE,
        "permutation_tail": "upper_ge_observed_improvement",
        "uncertainty_method": "validation_empirical_residual_quantile",
    }
