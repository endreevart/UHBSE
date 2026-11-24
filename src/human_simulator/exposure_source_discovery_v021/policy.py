"""Policy for the v0.2.1 temporal accounting correction. Not a Stage 05 gate."""

from __future__ import annotations

from typing import Any

VERSION = "0.2.1"
ARTIFACT_DIR = "artifacts/exposure-source-discovery-v0.2.1"
V01_DIR = "artifacts/exposure-source-discovery-v0.1"
V02_DIR = "artifacts/exposure-source-discovery-v0.2"
V01_SOURCE = "src/human_simulator/exposure_source_discovery_v01"
V02_SOURCE = "src/human_simulator/exposure_source_discovery_v02"

STAGE05_SHA256 = {
    "artifacts/external-review/stage-05-intervention-response-readiness-and-exposure-semantics-v0.1-review.zip":
        "6605a4b643ea68ae893d6b52d0a0a196e1e2ad2ec505adad5691a41df70cf992",
    "artifacts/external-review/stage-05-intervention-response-readiness-and-exposure-semantics-v0.1.1-review.zip":
        "1a53215e69e5de22c57c1396fab3d93d0124c667315331a450e0712a166b20ef",
}

TEMPORAL_CATEGORIES = (
    "CONSULTATION_ID_NULL",
    "CONSULTATION_ID_PRESENT_TARGET_NOT_FOUND",
    "CONSULTATION_TARGET_FOUND_TIME_BEFORE",
    "CONSULTATION_TARGET_FOUND_TIME_SAME_DAY",
    "CONSULTATION_TARGET_FOUND_TIME_AFTER",
    "CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE",
)

SUBJECT_CATEGORIES = (
    "SUBJECT_KEYS_BOTH_PRESENT_EQUAL",
    "SUBJECT_KEYS_BOTH_PRESENT_UNEQUAL",
    "FEEDBACK_USER_ID_NULL",
    "CONSULTATION_PATIENT_ID_NULL",
    "BOTH_SUBJECT_KEYS_NULL",
    "SUBJECT_COMPARISON_NOT_RUN_TARGET_MISSING",
)

REQUIRED_ARTIFACTS = (
    "baseline-verification.json",
    "v02-temporal-accounting-defect-reproduction.json",
    "feedback-exclusive-classification.json",
    "consultation-target-accounting.json",
    "subject-key-comparison-accounting.json",
    "source-b-temporal-sequence-audit.json",
    "temporal-accounting-reconciliation.json",
    "negative-control-results.json",
    "query-log.json",
    "privacy-scan.json",
    "status-contract.json",
    "verification.json",
    "discovery-report.md",
    "MANIFEST.json",
)

SCIENTIFIC_CEILING = {
    "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS": "NOT_ESTABLISHED",
    "OWNER_SEMANTIC_REVIEW_STATUS": "AWAITING_OWNER_CONFIRMATION",
    "PATIENT_REPORTED_INTAKE_TIER_STATUS": "NOT_ACCEPTED_PENDING_SEMANTIC_REVIEW",
    "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": 0,
    "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
    "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
    "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
    "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
    "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
    "PRODUCTION_READINESS": "NOT_CLAIMED",
}

DRUG_CATEGORY_TITLE = "Препараты"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage_05_gate": False,
        "model_training": False,
        "cohort_construction": False,
        "medication_extractor": False,
        "external_review_zip": False,
        "scientific_ceiling": SCIENTIFIC_CEILING,
    }
