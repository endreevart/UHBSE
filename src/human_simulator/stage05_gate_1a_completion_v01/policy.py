"""Scope correction over frozen Gate 1A v0.1 records. Those records are not rewritten."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-05-gate-1a-completion-v0.1"
PRIOR_DIR = "artifacts/stage-05-gate-1a-v0.1"
PRIOR_RECORDS = f"{PRIOR_DIR}/decision-records.json"
PRIOR_SOURCE = "src/human_simulator/stage05_gate_1a_v01"
ANSWER_RECORD = "artifacts/exposure-source-discovery-v0.2.2/owner-answer-record.json"
TEMPORAL_LEDGER = "artifacts/exposure-source-discovery-v0.2.1/feedback-exclusive-classification.json"

SCOPE = "WORKFLOW_INTENT_NOT_ROW_LEVEL_PROOF"
UNCOMPARABLE = "CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE"
REVIEWER_ROLE = "gate_review"
REVIEWER_LABEL = "gate-1a-scope-review"
DECIDED_AT = "2026-11-07T14:04:00Z"

SCOPED_QUESTIONS = ("B_TIMING", "B_PERIOD")
GATE_1B_BLOCKERS = ("B_IDENTITY", "B_DRUGS", "B_VITAMINS", "B_CHANGE", "B_DECLINE", "B_SHORT")
EXPOSURE_DEFERRED = ("B_POSITIVE",)
SOURCE_A_OPEN = ("A_RECOMMENDATION_ITEMS", "A_MEDICATION_CODE_SET", "A_DOCUMENT_FINAL")
SOURCE_B_TOKENS = ("change_drugs", "decline_drugs", "drugs_first", "positive_changes")

SCIENTIFIC_CEILING = {
    "SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS": "NOT_ESTABLISHED",
    "CROSS_SOURCE_IDENTITY_LINKAGE_STATUS": "NOT_PERFORMED",
    "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": 0,
    "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
    "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
    "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
    "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
    "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
    "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
    "PRODUCTION_READINESS": "NOT_CLAIMED",
}

REQUIRED_ARTIFACTS = (
    "superseding-decision-record.schema.json",
    "superseding-decision-records.json",
    "answer-evidence-binding.json",
    "workflow-scope.json",
    "evidence-recovery.json",
    "gate-1b-blockers.json",
    "negative-control-results.json",
    "baseline-verification.json",
    "privacy-scan.json",
    "status-contract.json",
    "verification.json",
    "gate-1a-completion-report.md",
    "MANIFEST.json",
)

SUPERSEDING_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "uhbse/stage-05/gate-1a/superseding-decision-record/0.1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "question_id",
        "source_system",
        "field_path",
        "proposition",
        "decision",
        "role",
        "reviewer_digest",
        "prior_role",
        "prior_reviewer_digest",
        "decided_at",
        "basis",
        "evidence_sha256",
        "prior_record_sha256",
        "attestation",
        "attestation_scope",
        "closes_question",
        "row_level_proof",
        "requires_first_vs_repeat_visit_classification",
        "decision_schema_version",
        "supersedes_artifact",
    ],
    "properties": {
        "question_id": {"enum": list(SCOPED_QUESTIONS)},
        "source_system": {"const": "kgz_raw"},
        "field_path": {"type": "string", "minLength": 3},
        "proposition": {"type": "string", "minLength": 3},
        "decision": {"type": "string", "minLength": 1},
        "role": {"const": REVIEWER_ROLE},
        "reviewer_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "prior_role": {"const": "system_architect"},
        "prior_reviewer_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "decided_at": {"const": DECIDED_AT},
        "basis": {"type": "string", "minLength": 1},
        "evidence_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "prior_record_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "attestation": {"const": "accepted"},
        "attestation_scope": {"const": SCOPE},
        "closes_question": {"const": False},
        "row_level_proof": {"const": False},
        "requires_first_vs_repeat_visit_classification": {"type": "boolean"},
        "decision_schema_version": {"const": "0.1.1"},
        "supersedes_artifact": {"const": PRIOR_RECORDS},
    },
}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "gate": "stage-05-gate-1a-completion",
        "database_access": False,
        "model_training": False,
        "medication_extractor": False,
        "rewrites_prior_decision_records": False,
        "scientific_ceiling": SCIENTIFIC_CEILING,
    }
