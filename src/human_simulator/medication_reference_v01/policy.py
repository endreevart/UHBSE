"""Policy — Medication Reference Acquisition, First Accepted Concepts, Corrected Shadow v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-medication-reference-acquisition-first-concept-cohorts-v0.1"
)
RUNTIME_DIR = "private/medication-reference-v01"
EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)
PRIOR_CONCEPT_REGISTRY = (
    "private/medication-concept-v01/registry/medication-concept-registry.private.jsonl"
)

ACCEPTED_PRIOR_ZIP = (
    "stage-03-medication-concept-harmonization-categorical-baseline-v0.1-review.zip"
)
ACCEPTED_PRIOR_SHA256 = (
    "be8b24391bcdc21dcef215e0de157fdcb06216b7dafd19e45dafac84adf82982"
)
ACCEPTED_PRIOR_MEMBERS = 397
ACCEPTED_PRIOR_INDEXED = 396

REVIEW_ZIP = (
    "stage-03-medication-reference-acquisition-first-concept-cohorts-v0.1-review.zip"
)

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "medication_concept_harmonization_v0.1": (
        ACCEPTED_PRIOR_ZIP,
        ACCEPTED_PRIOR_SHA256,
    ),
    "medication_knowledge_v0.1": (
        "stage-03-medication-knowledge-representation-v0.1-review.zip",
        "ae0943317facef424097f3784274192ae379aa1add33ab78653dc1811542ca3c",
    ),
    "medication_association_v0.1.1": (
        "stage-03-first-medication-association-baseline-v0.1.1-review.zip",
        "7c2d1bc1fcf3a96130bc2a8cf944850a88f5727ee7f3be43fca969fa1dcaa963",
    ),
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
EXPECTED_MEDICINE_IDS = 487

V01_COHORTS = (
    ("Лимфоциты", "%"),
    ("Средний объем эритроцитов (MCV)", "фл"),
    ("Моноциты", "%"),
    ("Нейтрофилы", "%"),
    ("Эозинофилы", "%"),
)

GATE_MIN_SUBJECTS = 100
GATE_MIN_EPISODES = 300
GATE_MIN_TEST_SUBJECTS = 30

ACCEPTED_STATUSES = frozenset(
    {"EXACT_PROVIDER_MATCH", "SUPPORTED_TRANSFORM", "HUMAN_ACCEPTED"}
)

# Documented RxNav REST base (RxNorm APIs)
RXNORM_REST_BASE = "https://rxnav.nlm.nih.gov/REST"

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
        "scope_correction": {
            "M2ID_ONEHOT_REPRESENTATION_STATUS": "EVALUATED",
            "M2ID_ONEHOT_MODEL_FREEZE_STATUS": "NOT_DONE_IN_PRIOR_RELEASE",
            "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": "NOT_RUN_IN_PRIOR_RELEASE",
            "prior_engine_shadow_pass_applies_only_to": "frozen_M1_M2C",
            "onehot_demo_is_not_model_inference": True,
        },
        "authoritative_comparison": ["M0", "M1", "M2ID_ONEHOT"],
        "sensitivity_only": ["M2EXPOSURE_COUNT"],
        "seed": SEED,
        "l2": L2,
        "expected_source_medicine_ids": EXPECTED_MEDICINE_IDS,
        "rxnorm_documented_base": RXNORM_REST_BASE,
    }
