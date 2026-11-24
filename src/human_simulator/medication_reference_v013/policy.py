"""Policy — Medication Acceptance Semantics v0.1.3."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.3"
ARTIFACT_DIR = "artifacts/stage-03-medication-acceptance-semantics-v0.1.3"
RUNTIME_DIR = "private/medication-reference-v013"
V011_RUNTIME = "private/medication-reference-v011"
V012_RUNTIME = "private/medication-reference-v012"

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
EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)

EXPECTED_MEDICINE_IDS = 487
OMEGA3_PRIORITY_IDS = ("809", "663", "506", "507", "55")
EXACT_REVIEW_ID = "813"
OMACOR_ESKLP_ID = "21.20.10.149-000028-1-00079-2000001410348"

REGRESSION_REJECTS = (
    ("449", "21.10.51.123-000006-1-00052-2000001276271"),
    ("48", "21.10.51.123-000006-1-00052-2000001276271"),
    ("810", "21.10.51.123-000002-1-00040-2000001577781"),
    ("405", "21.10.51.123-000002-1-00040-2000001577781"),
    ("31", "21.20.10.158-000006-1-00072-2000000980402"),
    ("510", "21.20.10.158-000006-1-00072-2000000980402"),
)

DECISION_TYPES = frozenset(
    {
        "PRODUCT_IDENTITY_ACCEPTED",
        "INGREDIENT_SET_ACCEPTED",
        "INGREDIENT_FORM_ROUTE_ACCEPTED",
        "INGREDIENT_FAMILY_ONLY",
        "AMBIGUOUS",
        "INSUFFICIENT_SOURCE_EVIDENCE",
        "HUMAN_REJECTED",
    }
)

# Levels that may drive authoritative readiness (never FAMILY_ONLY)
AUTHORITATIVE_ACCEPTANCE_LEVELS = frozenset(
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
        "ingredient_family_cannot_open_authoritative_cohort": True,
        "provisional_cannot_be_ready": True,
        "llm_cannot_create_accepted_decision": True,
    }
