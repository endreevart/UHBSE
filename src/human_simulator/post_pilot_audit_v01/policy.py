"""Policy — Post-Pilot Evidence Audit and Longitudinal Data Readiness v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_PRIVATE_DIR = "private/post-pilot-audit-v01"
ARTIFACT_PUBLIC_DIR = (
    "artifacts/stage-03-post-pilot-evidence-audit-longitudinal-readiness-v0.1"
)

PILOT_ZIP = (
    "stage-03-first-concept-bounded-technical-medication-pilot-v0.1-review.zip"
)
PILOT_ZIP_SHA256 = (
    "aba265d5a4d6f01560b02c3e3fa68d827aba9bd3e1e594d4974d53d4bef8c7b9"
)
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

V011_DECISION_LOG = "private/medication-reference-v011/review/decision-log.jsonl"
V011_DECISION_LOG_SHA256 = (
    "ece32342bab902195d25a24a7e9bbc06f491d5d0e36a22eae997353d4d9d4234"
)

EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)
PILOT_ARTIFACT_DIR = (
    "artifacts/stage-03-first-concept-bounded-technical-medication-pilot-v0.1"
)

V01_OUTCOME_GRAINS = (
    ("Лимфоциты", "%"),
    ("Средний объем эритроцитов (MCV)", "фл"),
    ("Моноциты", "%"),
    ("Нейтрофилы", "%"),
    ("Эозинофилы", "%"),
)

PILOT_COHORTS: tuple[dict[str, Any], ...] = (
    {
        "cohort_id": "udca_oral_tablet_500mg",
        "capable_source_medicine_ids": ("418", "739"),
        "provider_neutral_concept_id": "pnconc_64fe025b2e44ee1a6fb1666cf242",
        "primary_outcome": ("Лимфоциты", "%"),
        "reported_total_concept_episodes": 1617,
        "reported_primary_episodes": 50,
        "reported_subjects": 65,
    },
    {
        "cohort_id": "levothyroxine_oral_tablet_50mcg",
        "capable_source_medicine_ids": ("7",),
        "provider_neutral_concept_id": "pnconc_9ffb1713d04998948e5848a14e4c",
        "primary_outcome": ("Средний объем эритроцитов (MCV)", "фл"),
        "reported_total_concept_episodes": 1692,
        "reported_primary_episodes": 45,
        "reported_subjects": 57,
    },
    {
        "cohort_id": "udca_oral_tablet_250mg",
        "capable_source_medicine_ids": ("595",),
        "provider_neutral_concept_id": "pnconc_03084c1421d6a5713d30878da9da",
        "primary_outcome": ("Средний объем эритроцитов (MCV)", "фл"),
        "reported_total_concept_episodes": 1005,
        "reported_primary_episodes": 29,
        "reported_subjects": 37,
    },
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "MODEL_TRAINING_STATUS": "NOT_RUN",
        "PUBLICATION_STATUS": "NOT_PUBLISHED_AUDIT_ONLY",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "no_multi_outcome_natural_history_baseline": True,
        "no_policy_threshold_acceptance": True,
        "THRESHOLD_DECISION_STATUS": "THRESHOLD_DECISION_REQUIRED",
    }
