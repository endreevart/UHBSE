"""Policy for exposure-source discovery v0.2. Not a Stage 05 gate."""

from __future__ import annotations

from typing import Any

VERSION = "0.2"
ARTIFACT_DIR = "artifacts/exposure-source-discovery-v0.2"
V01_DIR = "artifacts/exposure-source-discovery-v0.1"
V01_DISCOVER = "src/human_simulator/exposure_source_discovery_v01/discover.py"

BASELINE_SHA256 = {
    "src/human_simulator/exposure_source_discovery_v01/discover.py":
        "5d93e43b5269cf00c29f3becb5d38db537d93576ee28539fcb64e2c34045e92d",
    "artifacts/exposure-source-discovery-v0.1/discovery-report.md":
        "cba48005d11fd19643e9348140bbcefd055260c2928bc4c24a9b15f47445ff58",
    "artifacts/exposure-source-discovery-v0.1/source-a-discovery.json":
        "b33edb7005d4896e389fbe1888ff90b889f026e67d9972a89fdf3ea567d0bb4f",
    "artifacts/exposure-source-discovery-v0.1/source-b-discovery.json":
        "9775003c1569032b2174a452cc4f31fc15962f16dae1b08c2c4b4631982276ae",
    "artifacts/exposure-source-discovery-v0.1/followup-discovery.json":
        "0d7096e9fc02deb8f3bde2a517136243cf85684ae438d4a981b4958ad4744df5",
    "artifacts/exposure-source-discovery-v0.1/query-log.json":
        "0d70bb96f849c6df86c248a26f972d6d1b4b1b5f16a930c66aa08bcb61468a06",
    "artifacts/exposure-source-discovery-v0.1/privacy-scan.json":
        "b60ed25a62549ce5a0be51d2dab325c5993b1204ee442a1188acaa08361ad37c",
}

REQUIRED_ARTIFACTS = (
    "baseline-verification.json",
    "v01-method-limitations-reproduction.json",
    "source-a-recommendation-localization.json",
    "source-a-structured-linkage.json",
    "source-b-schema-contract.json",
    "source-b-sentinel-profile.json",
    "source-b-identity-linkage-audit.json",
    "source-b-temporal-sequence-audit.json",
    "candidate-exposure-chain.json",
    "owner-questions.md",
    "owner-response-template.json",
    "semantic-decision.schema.json",
    "query-log.json",
    "negative-control-results.json",
    "privacy-scan.json",
    "status-contract.json",
    "verification.json",
    "discovery-report.md",
    "evidence-manifest.sha256",
)

SECTION_SUPPORT_MIN = 50
STATEMENT_TIMEOUT_MS = 300000
LOCK_TIMEOUT_MS = 10000

SCIENTIFIC_CEILING = {
    "PATIENT_REPORTED_INTAKE_TIER_STATUS": "NOT_ACCEPTED_PENDING_SEMANTIC_REVIEW",
    "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": 0,
    "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
    "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
    "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
    "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
    "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
    "PRODUCTION_READINESS": "NOT_CLAIMED",
    "OWNER_SEMANTIC_REVIEW_STATUS": "AWAITING_OWNER_CONFIRMATION",
    "SOURCE_B_FEEDBACK_SEMANTICS_STATUS": "UNKNOWN_PENDING_HUMAN_REVIEW",
}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage_05_gate": False,
        "model_training": False,
        "cohort_construction": False,
        "external_review_zip": False,
        "scientific_ceiling": SCIENTIFIC_CEILING,
    }
