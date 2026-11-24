"""Policy pins for medication-knowledge representation v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-03-medication-knowledge-representation-v0.1"
RUNTIME_DIR = "private/medication-knowledge-v01"
EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)

ACCEPTED_V011_ZIP = (
    "stage-03-first-medication-association-baseline-v0.1.1-review.zip"
)
ACCEPTED_V011_SHA256 = (
    "7c2d1bc1fcf3a96130bc2a8cf944850a88f5727ee7f3be43fca969fa1dcaa963"
)
ACCEPTED_V011_MEMBERS = 53
ACCEPTED_V011_INDEXED = 52

REVIEW_ZIP = "stage-03-medication-knowledge-representation-v0.1-review.zip"

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "medication_association_v0.1.1": (ACCEPTED_V011_ZIP, ACCEPTED_V011_SHA256),
    "medication_association_v0.1": (
        "stage-03-first-medication-association-baseline-v0.1-review.zip",
        "11975e730197e61792288ac30bd81137c2aa0e05a1b9f07217f26da9336615fc",
    ),
    "population_v0.1.1": (
        "stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1-review.zip",
        "35a35dd48612590fedf064e3916aa1ae14ab70bd2626e257889b70c11a55d796",
    ),
}

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SOURCE_A = "magerya_api"
SEED = 42
L2 = 0.1
N_BOOTSTRAP = 2000
N_PERMUTATION = 500
HASH_DIMS = (32, 64, 128, 256)
HASH_SEED = 42
EXPECTED_MEDICINE_IDS = 487

V01_COHORTS = (
    ("Лимфоциты", "%"),
    ("Средний объем эритроцитов (MCV)", "фл"),
    ("Моноциты", "%"),
    ("Нейтрофилы", "%"),
    ("Эозинофилы", "%"),
)

MIN_ACCEPTED_SEMANTICS_FOR_M2SEM = 50

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
        "recorded_medication_association_is_not_confirmed_administration": True,
        "association_is_not_intervention_response": True,
        "prediction_is_not_treatment_effect": True,
        "seed": SEED,
        "l2": L2,
        "hash_dims": list(HASH_DIMS),
        "primary_estimand": "mean_subject_macro_mae_improvement_m1_minus_candidate",
        "expected_source_medicine_ids": EXPECTED_MEDICINE_IDS,
    }
