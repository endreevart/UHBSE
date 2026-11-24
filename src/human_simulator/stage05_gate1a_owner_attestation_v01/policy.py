"""Pins for the owner attestation. Frozen Gate 1A records stay unchanged."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-05-gate-1a-owner-attestation-v0.1"
PRIOR_RECORDS = "artifacts/stage-05-gate-1a-v0.1/decision-records.json"
COMPLETION_RECORDS = "artifacts/stage-05-gate-1a-completion-v0.1/superseding-decision-records.json"
ANSWER_RECORD = "artifacts/exposure-source-discovery-v0.2.2/owner-answer-record.json"

EXPECTED_DECISION_RECORDS_SHA = "7a9eebdb30c978f3838545f7ea1ea632577fe7554829f152f0041572f107eccc"
EXPECTED_COMPLETION_SHA = "8cbb7caeda8a573e3e8caaf3ef69a72992da6b453279613aa4ed9514e9665e63"
EXPECTED_ANSWER_RECORD_SHA = "2c7c87dbcf681d9e92282fff2e85d703c870b2b503687e9aa6eff0439a74a77c"

REVIEWER_ROLE = "system_architect"
REVIEWER_LABEL = "system-architect"
DECIDED_AT = "2026-11-17T14:00:00Z"
REPOSITORY = "magerya/magerya"
COMMIT_SHA = "b3629363693936afef9b5f5420f92fe55a1cebb1"

BLOCKERS = ("B_IDENTITY", "B_DRUGS", "B_VITAMINS", "B_CHANGE", "B_DECLINE", "B_SHORT")

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
        "gate": "stage-05-gate-1a-owner-attestation",
        "medication_extractor": False,
        "model_training": False,
        "gate_1b_started": False,
        "scientific_ceiling": SCIENTIFIC_CEILING,
    }
