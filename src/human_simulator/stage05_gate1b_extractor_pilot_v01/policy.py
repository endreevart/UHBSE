"""Gate 1B pilot limits. Frozen Gate 1A files stay unchanged."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-05-gate-1b-extractor-pilot-v0.1"
OPENED_AT = "2026-11-17T14:53:00Z"
OPENING_INSTRUCTION = "открыть Gate 1B."

FROZEN = {
    "artifacts/stage-05-gate-1a-v0.1/decision-records.json":
        "7a9eebdb30c978f3838545f7ea1ea632577fe7554829f152f0041572f107eccc",
    "artifacts/stage-05-gate-1a-completion-v0.1/superseding-decision-records.json":
        "8cbb7caeda8a573e3e8caaf3ef69a72992da6b453279613aa4ed9514e9665e63",
    "artifacts/exposure-source-discovery-v0.2.2/owner-answer-record.json":
        "2c7c87dbcf681d9e92282fff2e85d703c870b2b503687e9aa6eff0439a74a77c",
}

FIELDS = (
    ("drugs", "CURRENT_INTAKE"),
    ("vitamins", "CURRENT_INTAKE"),
    ("change_drugs", "REPLACEMENT"),
    ("decline_drugs", "DISCONTINUATION"),
    ("drugs_first", "PREVIOUSLY_PRESCRIBED"),
)

SCIENTIFIC_CEILING = {
    "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
    "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
    "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
    "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
    "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
    "PRODUCTION_READINESS": "NOT_CLAIMED",
    "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": 0,
    "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "gate": "stage-05-gate-1b-extractor-pilot",
        "model_training": False,
        "cohort_construction": False,
        "exposure_episode": False,
        "response_label": False,
        "gate_2_started": False,
        "synthetic_labels_created": False,
        "source_a_used": False,
        "scientific_ceiling": SCIENTIFIC_CEILING,
    }
