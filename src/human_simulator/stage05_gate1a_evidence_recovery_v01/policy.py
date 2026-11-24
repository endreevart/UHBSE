"""Pins and gate rules for primary evidence recovery. The concatenated pin is rejected."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-05-gate-1a-evidence-recovery-v0.1"

DECISION_RECORDS = "artifacts/stage-05-gate-1a-v0.1/decision-records.json"
ANSWER_RECORD = "artifacts/exposure-source-discovery-v0.2.2/owner-answer-record.json"
SUPERSEDING_RECORDS = "artifacts/stage-05-gate-1a-completion-v0.1/superseding-decision-records.json"
COMPLETION_RECOVERY = "artifacts/stage-05-gate-1a-completion-v0.1/evidence-recovery.json"
COMPLETION_STATUS = "artifacts/stage-05-gate-1a-completion-v0.1/status-contract.json"
TEMPORAL_LEDGER = "artifacts/exposure-source-discovery-v0.2.1/feedback-exclusive-classification.json"

# The first value is a deliberately concatenated string and must never be accepted.
REJECTED_DECISION_RECORDS_SHA = (
    "7a9eebdb30c978f3838545f7ea1ea632577fe7554829ad434e2a949096f2fc60bda4ce284d296f2fc60"
)
EXPECTED_DECISION_RECORDS_SHA = "7a9eebdb30c978f3838545f7ea1ea632577fe7554829f152f0041572f107eccc"
EXPECTED_ANSWER_RECORD_SHA = "2c7c87dbcf681d9e92282fff2e85d703c870b2b503687e9aa6eff0439a74a77c"
EXPECTED_SUPERSEDING_SHA = "8cbb7caeda8a573e3e8caaf3ef69a72992da6b453279613aa4ed9514e9665e63"

PINS = {
    DECISION_RECORDS: EXPECTED_DECISION_RECORDS_SHA,
    ANSWER_RECORD: EXPECTED_ANSWER_RECORD_SHA,
    SUPERSEDING_RECORDS: EXPECTED_SUPERSEDING_SHA,
}

GATE_1B_BLOCKERS = ("B_IDENTITY", "B_DRUGS", "B_VITAMINS", "B_CHANGE", "B_DECLINE", "B_SHORT")
EXPOSURE_DEFERRED = ("B_POSITIVE",)
SOURCE_A_OPEN = ("A_RECOMMENDATION_ITEMS", "A_MEDICATION_CODE_SET", "A_DOCUMENT_FINAL")
SCOPED_QUESTIONS = ("B_TIMING", "B_PERIOD")
FORM_FIELDS = ("drugs", "vitamins", "change_drugs", "decline_drugs", "drugs_first", "positive_changes")
EXACT_IDENTIFIERS = (
    "feedback",
    "recommendations_user",
    "recommendations_list",
    "change_drugs",
    "decline_drugs",
    "drugs_first",
    "positive_changes",
    "outside_doctor_medicine",
    "vitamins",
    "consultations.patient_id",
    "feedback.user_id",
    "document_recommendation",
    "recommendations[].items",
    "diagnosis_medicineappointments",
    "DoctorFeedback",
)
STRUCTURAL_SYMBOLS = (
    "RecommendationItemData",
    "ActiveRelatedAppointmentOrReadOnly",
    "class DoctorFeedback",
    "class Recommendation(",
)
NUMERIC_PHRASE = "NUMERIC_KEY_AGREEMENT_OBSERVED_NOT_IDENTITY_PROOF"
SCOPE = "WORKFLOW_INTENT_NOT_ROW_LEVEL_PROOF"
FORBIDDEN_ABSENCE_CLAIM = "FORM_SCHEMA_NOT_FOUND_IN_SOURCE_B_CODE"

COVERAGE_CLASSES = (
    "python",
    "javascript_typescript",
    "react_vue",
    "mobile",
    "sql_migrations",
    "openapi",
    "json_yaml_schemas",
    "html_templates",
    "database_dumps",
    "technical_documentation",
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

REQUIRED_ARTIFACTS = (
    "baseline-verification.json",
    "prior-evidence-recovery-limitations.json",
    "repository-inventory.json",
    "search-coverage.json",
    "source-b-identity-evidence.json",
    "source-b-form-evidence.json",
    "source-a-recommendation-items-evidence.json",
    "source-a-section-code-evidence.json",
    "source-a-document-lifecycle-evidence.json",
    "effective-decision-resolution.json",
    "new-superseding-decision-records.json",
    "blocking-question-status.json",
    "negative-control-results.json",
    "privacy-scan.json",
    "status-contract.json",
    "verification.json",
    "gate-1a-evidence-recovery-report.md",
    "MANIFEST.json",
)

BASELINE_TREES = (
    "artifacts/exposure-source-discovery-v0.1",
    "artifacts/exposure-source-discovery-v0.2",
    "artifacts/exposure-source-discovery-v0.2.1",
    "artifacts/exposure-source-discovery-v0.2.2",
    "artifacts/stage-05-gate-1a-v0.1",
    "artifacts/stage-05-gate-1a-completion-v0.1",
    "src/human_simulator/exposure_source_discovery_v01",
    "src/human_simulator/exposure_source_discovery_v02",
    "src/human_simulator/exposure_source_discovery_v021",
    "src/human_simulator/exposure_source_discovery_v022",
    "src/human_simulator/stage05_gate_1a_v01",
    "src/human_simulator/stage05_gate_1a_completion_v01",
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "gate": "stage-05-gate-1a-evidence-recovery",
        "database_access": "read_only_catalog",
        "medication_extractor": False,
        "model_training": False,
        "cohort_construction": False,
        "external_review_zip": False,
        "automatic_contact": False,
        "scientific_ceiling": SCIENTIFIC_CEILING,
    }
