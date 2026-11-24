"""Policy — Medication Semantic Matcher v0.1.2 + Hierarchical Exposure Cohort Planner v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.2"
HIERARCHY_VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-03-medication-semantic-matcher-v0.1.2"
RUNTIME_DIR = "private/medication-reference-v012"
# Read-only reuse of v0.1.1 ESKLP snapshot + append-only decision log
V011_RUNTIME_DIR = "private/medication-reference-v011"
EXPECTED_ESKLP_SNAPSHOT = (
    "private/medication-reference-v011/provider-snapshots/esklp/esklp.zip"
)
EXPECTED_SNAPSHOT_SHA256 = (
    "ecb7d0644dd3363c4bb14b7b1e85754a2a47f11edc35fa74092da90920341bae"
)
PRIOR_CONCEPT_REGISTRY = (
    "private/medication-concept-v01/registry/medication-concept-registry.private.jsonl"
)
V011_MAPPING_REGISTRY = (
    "private/medication-reference-v011/registry/medication-reference-mapping.private.jsonl"
)
V011_DECISION_LOG = "private/medication-reference-v011/review/decision-log.jsonl"
EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)

ACCEPTED_PRIOR_ZIP = (
    "stage-03-medication-reference-acquisition-first-concept-cohorts-v0.1-review.zip"
)
ACCEPTED_PRIOR_SHA256 = (
    "d45c57b3ee35a3a3bae560b79a101343c8d0e1ed9c64e36228c455932eff7534"
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
EXPECTED_MEDICINE_IDS = 487
TOP_N_REVIEW = 20
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

# Permanent regression rejects (append-only log; do not rewrite)
REGRESSION_REJECTS: tuple[tuple[str, str], ...] = (
    ("449", "21.10.51.123-000006-1-00052-2000001276271"),
    ("48", "21.10.51.123-000006-1-00052-2000001276271"),
    ("810", "21.10.51.123-000002-1-00040-2000001577781"),
    ("405", "21.10.51.123-000002-1-00040-2000001577781"),
    ("31", "21.20.10.158-000006-1-00072-2000000980402"),
    ("510", "21.20.10.158-000006-1-00072-2000000980402"),
)

MARKETING_ZERO_WEIGHT_TOKENS = frozenset(
    {
        "про",
        "плюс",
        "форте",
        "актив",
        "max",
        "maxi",
        "макси",
        "extra",
        "экстра",
        "premium",
        "премиум",
        "bio",
        "био",
        "жизнивек",
        "snt",
        "solgar",
        "now",
        "дикироген",
        "adult",
        "взрослые",
        "дети",
        "детский",
    }
)

CANDIDATE_CLASS = frozenset(
    {
        "REGISTERED_DRUG_CANDIDATE",
        "DIETARY_SUPPLEMENT_CANDIDATE",
        "TOPICAL_PRODUCT_CANDIDATE",
        "COMBINATION_PRODUCT_CANDIDATE",
        "INSUFFICIENT_SEMANTIC_DATA",
    }
)

FINAL_STATUS = frozenset(
    {
        "EXACT_PROVIDER_MATCH",
        "SUPPORTED_TRANSFORM",
        "AMBIGUOUS",
        "NO_MATCH",
        "HARD_CONFLICT",
        "SUPPLEMENT_REFERENCE_REQUIRED",
        "PROVIDER_GAP",
        "INSUFFICIENT_SOURCE_DATA",
    }
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "hierarchy_version": HIERARCHY_VERSION,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "gates": {
            "min_subjects": GATE_MIN_SUBJECTS,
            "min_episodes": GATE_MIN_EPISODES,
            "min_test_subjects": GATE_MIN_TEST_SUBJECTS,
        },
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "causal_effect_status": "NOT_EVALUATED",
        "qsp_status": "NOT_STARTED",
        "pkpd_status": "NOT_STARTED",
        "clinical_validation_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "association_baseline_status": "NOT_RUN",
        "appointment_date_semantics": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
        "recorded_medication_association_neq_administration": True,
    }
