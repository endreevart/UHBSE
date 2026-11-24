"""Policy — First Concept-Bounded Technical Medication Pilot v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-first-concept-bounded-technical-medication-pilot-v0.1"
)
RUNTIME_DIR = "private/concept-pilot-v01"
EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)
V014_CLUSTERS = (
    "private/medication-reference-v014/review-pack/strict-concept-clusters.json"
)
V014_SUMMARY = (
    "artifacts/stage-03-intervention-cohort-discovery-v0.1.4/"
    "cohort-discovery-summary.json"
)
V011_DECISION_LOG = "private/medication-reference-v011/review/decision-log.jsonl"

REVIEW_ZIP = (
    "stage-03-first-concept-bounded-technical-medication-pilot-v0.1-review.zip"
)

# Scientific gates — immutable, not used to gate technical pilot
SCIENTIFIC_GATE_MIN_SUBJECTS = 100
SCIENTIFIC_GATE_MIN_EPISODES = 300
SCIENTIFIC_GATE_MIN_TEST_SUBJECTS = 30

SEED = 42
L2 = 0.1
N_FOLDS = 5
N_PERMUTATION = 200  # train-fold shuffles; finite p

V01_OUTCOME_GRAINS = (
    ("Лимфоциты", "%"),
    ("Средний объем эритроцитов (MCV)", "фл"),
    ("Моноциты", "%"),
    ("Нейтрофилы", "%"),
    ("Эозинофилы", "%"),
)

# Predeclared before metrics (hashes from v0.1.4)
PILOT_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "udca_oral_tablet_500mg",
        "role": "primary",
        "provider_neutral_concept_id": "pnconc_64fe025b2e44ee1a6fb1666cf242",
        "cluster_key": "ursodeoxycholic_acid|udca_unspecified|oral|tablet|500_мг",
        "candidate_semantic_label": "UDCA · oral · tablet · 500 mg",
        "capable_source_medicine_ids": ("418", "739"),
        "strength_stratum": "500_мг",
    },
    {
        "cohort_id": "levothyroxine_oral_tablet_50mcg",
        "role": "primary",
        "provider_neutral_concept_id": "pnconc_9ffb1713d04998948e5848a14e4c",
        "cluster_key": "levothyroxine|levothyroxine_unspecified_salt|oral|tablet|50_мкг",
        "candidate_semantic_label": "Levothyroxine · oral · tablet · 50 mcg",
        "capable_source_medicine_ids": ("7",),
        "strength_stratum": "50_мкг",
    },
    {
        "cohort_id": "udca_oral_tablet_250mg",
        "role": "sensitivity",
        "provider_neutral_concept_id": "pnconc_03084c1421d6a5713d30878da9da",
        "cluster_key": "ursodeoxycholic_acid|udca_unspecified|oral|tablet|250_мг",
        "candidate_semantic_label": "UDCA · oral · tablet · 250 mg",
        "capable_source_medicine_ids": ("595",),
        "strength_stratum": "250_мг",
    },
)

ENRICHMENT_GAP_IDS = ("506", "507", "583", "331", "559")

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
CLINICAL_USE_PROHIBITED = "CLINICAL_USE_PROHIBITED"
CAUSAL_INTERPRETATION_PROHIBITED = "CAUSAL_INTERPRETATION_PROHIBITED"

PRIOR_MEDICATION_ASSOC_ZIP = (
    "stage-03-first-medication-association-baseline-v0.1.1-review.zip"
)
PRIOR_MEDICATION_ASSOC_SHA256 = (
    "7c2d1bc1fcf3a96130bc2a8cf944850a88f5727ee7f3be43fca969fa1dcaa963"
)
PRIOR_CONCEPT_COHORTS_ZIP = (
    "stage-03-medication-reference-acquisition-first-concept-cohorts-v0.1-review.zip"
)
PRIOR_CONCEPT_COHORTS_SHA256 = (
    "d45c57b3ee35a3a3bae560b79a101343c8d0e1ed9c64e36228c455932eff7534"
)
V011_DECISION_LOG_SHA256 = (
    "ece32342bab902195d25a24a7e9bbc06f491d5d0e36a22eae997353d4d9d4234"
)
EXPECTED_V011_DECISION_COUNT = 6
EXPECTED_COMPATIBLE_CANDIDATES = 85
EXPECTED_STRICT_CLUSTERS = 69
EXPECTED_CAPABLE_CLUSTERS = 43


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "scientific_gates_unchanged": {
            "min_subjects": SCIENTIFIC_GATE_MIN_SUBJECTS,
            "min_episodes": SCIENTIFIC_GATE_MIN_EPISODES,
            "min_test_subjects": SCIENTIFIC_GATE_MIN_TEST_SUBJECTS,
        },
        "TECHNICAL_CV_ONLY_NOT_EXTERNAL_VALIDATION": True,
        "appointment_date_semantics": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        "seed": SEED,
        "l2": L2,
        "n_folds": N_FOLDS,
        "no_hyperparameter_search": True,
    }
