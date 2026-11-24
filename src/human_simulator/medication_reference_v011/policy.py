"""Policy — Medication Provider Snapshot Integration and Evidence-Bound Review v0.1.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-medication-provider-snapshot-reviewed-concepts-v0.1.1"
)
RUNTIME_DIR = "private/medication-reference-v011"
EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)
PRIOR_CONCEPT_REGISTRY = (
    "private/medication-concept-v01/registry/medication-concept-registry.private.jsonl"
)

# Immutable v0.1 medication-reference acquisition baseline
ACCEPTED_PRIOR_ZIP = (
    "stage-03-medication-reference-acquisition-first-concept-cohorts-v0.1-review.zip"
)
ACCEPTED_PRIOR_SHA256 = (
    "d45c57b3ee35a3a3bae560b79a101343c8d0e1ed9c64e36228c455932eff7534"
)
ACCEPTED_PRIOR_MEMBERS = 412
ACCEPTED_PRIOR_INDEXED = 411

# Carried technical statuses from v0.1
CARRIED_FROM_V01 = {
    "M2ID_ONEHOT_MODEL_FREEZE_STATUS": "FROZEN",
    "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": "PASS",
    "DRUG_CONCEPT_ACCEPTED_COUNT": 0,
    "FIRST_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
}

V01_ARTIFACT_DIR = (
    "artifacts/stage-03-medication-reference-acquisition-first-concept-cohorts-v0.1"
)

EXPECTED_ESKLP_SNAPSHOT = (
    "private/medication-reference-v011/provider-snapshots/esklp/esklp.zip"
)
OPTIONAL_RXNORM_GLOB = (
    "private/medication-reference-v011/provider-snapshots/rxnorm/RxNorm_full_prescribe_*.zip"
)

REVIEW_ZIP = (
    "stage-03-medication-provider-snapshot-reviewed-concepts-v0.1.1-review.zip"
)

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "medication_reference_v0.1": (ACCEPTED_PRIOR_ZIP, ACCEPTED_PRIOR_SHA256),
    "medication_concept_harmonization_v0.1": (
        "stage-03-medication-concept-harmonization-categorical-baseline-v0.1-review.zip",
        "be8b24391bcdc21dcef215e0de157fdcb06216b7dafd19e45dafac84adf82982",
    ),
    "medication_knowledge_v0.1": (
        "stage-03-medication-knowledge-representation-v0.1-review.zip",
        "ae0943317facef424097f3784274192ae379aa1add33ab78653dc1811542ca3c",
    ),
    "medication_association_v0.1.1": (
        "stage-03-first-medication-association-baseline-v0.1.1-review.zip",
        "7c2d1bc1fcf3a96130bc2a8cf944850a88f5727ee7f3be43fca969fa1dcaa963",
    ),
}

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SOURCE_A = "magerya_api"
SEED = 42
L2 = 0.1
EXPECTED_MEDICINE_IDS = 487
TOP_N_REVIEW = 20
# Baseline top-20 episode coverage pin (from accepted concept/reference work)
TOP20_EPISODE_COVERAGE_PIN = 112047
TOTAL_EPISODES_PIN = 202374

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
APPROVED_PROVIDERS = frozenset({"ESKLP", "RxNorm"})

RXNORM_REST_BASE = "https://rxnav.nlm.nih.gov/REST"

CLINICAL_USE_PROHIBITED = "CLINICAL_USE_PROHIBITED"
CAUSAL_INTERPRETATION_PROHIBITED = "CAUSAL_INTERPRETATION_PROHIBITED"

# Scientific fact from frozen M2ID_ONEHOT baseline (v0.1 freeze metrics)
M2ID_ONEHOT_DID_NOT_IMPROVE_OVER_M1 = True


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
        "carried_from_v01": dict(CARRIED_FROM_V01),
        "expected_esklp_snapshot": EXPECTED_ESKLP_SNAPSHOT,
        "approved_providers": sorted(APPROVED_PROVIDERS),
        "m2id_onehot_did_not_improve_over_m1": M2ID_ONEHOT_DID_NOT_IMPROVE_OVER_M1,
        "seed": SEED,
        "l2": L2,
        "expected_source_medicine_ids": EXPECTED_MEDICINE_IDS,
        "rxnorm_documented_base": RXNORM_REST_BASE,
    }
