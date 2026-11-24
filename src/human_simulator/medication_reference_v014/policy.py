"""Policy — Evidence-Backed Intervention Cohort Discovery v0.1.4."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.4"
ARTIFACT_DIR = "artifacts/stage-03-intervention-cohort-discovery-v0.1.4"
RUNTIME_DIR = "private/medication-reference-v014"

EXPECTED_SNAPSHOT_SHA256 = (
    "ecb7d0644dd3363c4bb14b7b1e85754a2a47f11edc35fa74092da90920341bae"
)
EXPECTED_ESKLP_SNAPSHOT = (
    "private/medication-reference-v011/provider-snapshots/esklp/esklp.zip"
)
V011_MAPPING = (
    "private/medication-reference-v011/registry/medication-reference-mapping.private.jsonl"
)
V011_DECISION_LOG = "private/medication-reference-v011/review/decision-log.jsonl"
V012_MAPPING = (
    "private/medication-reference-v012/registry/semantic-mapping.private.jsonl"
)
V012_PROFILES = (
    "private/medication-reference-v012/semantics/source-semantic-profiles.private.jsonl"
)
V013_TYPED_LOG = (
    "private/medication-reference-v013/review/typed-decision-log.jsonl"
)
V013_SUMMARY = (
    "artifacts/stage-03-medication-acceptance-semantics-v0.1.3/"
    "acceptance-semantics-summary.json"
)
EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)

EXPECTED_MEDICINE_IDS = 487
EXPECTED_COMPATIBLE_CANDIDATES = 85

REGRESSION_REJECTS = (
    ("449", "21.10.51.123-000006-1-00052-2000001276271"),
    ("48", "21.10.51.123-000006-1-00052-2000001276271"),
    ("810", "21.10.51.123-000002-1-00040-2000001577781"),
    ("405", "21.10.51.123-000002-1-00040-2000001577781"),
    ("31", "21.20.10.158-000006-1-00072-2000000980402"),
    ("510", "21.20.10.158-000006-1-00072-2000000980402"),
)

TYPED_LEVELS = frozenset(
    {
        "PRODUCT_IDENTITY_CANDIDATE",
        "INGREDIENT_SET_CANDIDATE",
        "INGREDIENT_FORM_ROUTE_CANDIDATE",
        "INGREDIENT_FORM_ROUTE_STRENGTH_CANDIDATE",
        "INGREDIENT_FAMILY_ONLY",
        "INSUFFICIENT_SOURCE_EVIDENCE",
        "HARD_CONFLICT",
    }
)

# Levels eligible for authoritative / capable provisional decision sets
CAPABLE_LEVELS = frozenset(
    {
        "PRODUCT_IDENTITY_CANDIDATE",
        "INGREDIENT_FORM_ROUTE_CANDIDATE",
        "INGREDIENT_FORM_ROUTE_STRENGTH_CANDIDATE",
    }
)

AUTHORITATIVE_DECISIONS = frozenset(
    {
        "PRODUCT_IDENTITY_ACCEPTED",
        "INGREDIENT_FORM_ROUTE_ACCEPTED",
    }
)

GATE_MIN_SUBJECTS = 100
GATE_MIN_EPISODES = 300
GATE_MIN_TEST_SUBJECTS = 30

V01_COHORTS = (
    ("Лимфоциты", "%"),
    ("Средний объем эритроцитов (MCV)", "фл"),
    ("Моноциты", "%"),
    ("Нейтрофилы", "%"),
    ("Эозинофилы", "%"),
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"

# Broad families that cannot form authoritative intervention concepts alone
BROAD_FAMILY_INGREDIENTS = frozenset(
    {
        "vitamin_a",
        "vitamin_d",
        "vitamin_e",
        "vitamin_c",
        "magnesium",
        "zinc",
        "selenium",
        "iodine",
        "omega3",
        "iron",
        "carnitine",
        "taurine",
        "inositol",
        "methylfolate",
    }
)

FORBIDDEN_RANK_KEYS = frozenset(
    {
        "mae",
        "test_mae",
        "subject_macro_mae",
        "bootstrap",
        "permutation",
        "auc",
        "accuracy",
        "model_improvement",
    }
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "gates": {
            "min_subjects": GATE_MIN_SUBJECTS,
            "min_episodes": GATE_MIN_EPISODES,
            "min_test_subjects": GATE_MIN_TEST_SUBJECTS,
        },
        "association_baseline_status": "NOT_RUN",
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "causal_effect_status": "NOT_EVALUATED",
        "qsp_status": "NOT_STARTED",
        "pkpd_status": "NOT_STARTED",
        "clinical_validation_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "family_only_cannot_open_authoritative_cohort": True,
        "provisional_ready_always_false": True,
        "ranking_forbids_model_metrics": True,
        "appointment_date_semantics": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
    }
