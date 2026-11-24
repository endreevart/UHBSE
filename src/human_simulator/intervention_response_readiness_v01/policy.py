"""Policy — Intervention Response Readiness and Exposure Semantics v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
CODE_VERSION = "intervention-response-readiness-v01/0.1"
STAGE_NAME = "STAGE 05 — INTERVENTION RESPONSE READINESS AND EXPOSURE SEMANTICS"
ARTIFACT_DIR = "artifacts/stage-05-intervention-response-readiness-and-exposure-semantics-v0.1"
REVIEW_ZIP = "stage-05-intervention-response-readiness-and-exposure-semantics-v0.1-review.zip"
NAMESPACE = "intervention-response-readiness-v01"
SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"

GATES = (
    "G0_SOURCE_AND_PROVENANCE_IDENTITY",
    "G1_EXACT_VOCABULARY_MAPPING_IDENTITY",
    "G2_DOMAIN_ACCEPTANCE",
    "G3_EXPOSURE_SEMANTIC_ELIGIBILITY",
    "G4_TEMPORALLY_VALID_T0_START_END",
    "G5_OUTCOME_AND_NATIVE_UNIT_IDENTITY",
    "G6_PRE_POST_OBSERVATION_AVAILABILITY",
    "G7_SUBJECT_DISJOINT_LEAKAGE_SAFE_SPLIT",
    "G8_CONFOUNDING_AND_INDICATION_BIAS_INVENTORY",
    "G9_MINIMUM_AGGREGATE_SUPPORT",
    "G10_FUTURE_MODEL_ELIGIBILITY",
)

EXPOSURE_TIERS = (
    "UNKNOWN",
    "RECOMMENDED",
    "RECORDED_MEDICATION_ASSOCIATION",
    "PRESCRIBED_OR_ORDERED_EXPOSURE",
    "DISPENSED_OR_ADMINISTERED_EXPOSURE",
    "INGESTION_UNVERIFIED",
    "CAUSAL_INTERVENTION_EVIDENCE",
)

IR_ELIGIBLE_TIERS = frozenset(
    {
        "PRESCRIBED_OR_ORDERED_EXPOSURE",
        "DISPENSED_OR_ADMINISTERED_EXPOSURE",
    }
)

# Physical ZIP pins from the Stage 05 specification. Do not overwrite these files.
PRIOR_ZIPS: dict[str, tuple[str, str]] = {
    "irr_v016": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6-review.zip",
        "3c856824a2856fe5b85c4186dd2c0134954e5c6930df2ab655a784ffaa38be4a",
    ),
    "irr_v015": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.5-review.zip",
        "71b30884b2ab527af41df2edd828a31b3ac1f31a1da48fde0872d0c2f2ca5300",
    ),
    "irr_v014": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.4-review.zip",
        "1c3d8ed10c069fb46f75fbd5052b7cb398e6f4697be34e24c9e3e3e5bd15ebf7",
    ),
    "irr_v013": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.3-review.zip",
        "351febd77c018dacf1f04117d2a9a11d6022749d8c34b9f1f4a0c3514eaafa65",
    ),
    "irr_v012": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.2-review.zip",
        "2e0e7e8efa6b563c4363b34e4b040738c7d8e58de864c1ee83a819cd57ead7e3",
    ),
    "irr_v011": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1-review.zip",
        "e940199fdbf978241ad2dc1db22d7def015942a5d42f82cb842360d094fbeeb6",
    ),
    "irr_v01": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1-review.zip",
        "62e3e46d12b6098b631c1d71e47e3c9ad26c49554521b080b63c831dd2fce93a",
    ),
}

V016_EXPECTED_MEMBERS = 1023
V016_EXPECTED_INDEXED = 1022

EVIDENCE_PATHS = {
    "irr_v016_status": "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6/status-contract.json",
    "irr_v016_protocol": (
        "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6/"
        "external-validation-protocol.json"
    ),
    "medres_status": (
        "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/"
        "status-contract.json"
    ),
    "medres_cells": (
        "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/"
        "cell-registry-public.json"
    ),
    "medres_accounting": (
        "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/"
        "medication-source-accounting.json"
    ),
    "medres_confounding": (
        "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/"
        "confounding-inventory.json"
    ),
    "pop_schema": (
        "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/"
        "source-a-medication-schema-profile.json"
    ),
    "pop_time": (
        "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/"
        "source-a-medication-time-semantics.json"
    ),
    "pop_status_sem": (
        "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/"
        "source-a-medication-status-semantics.json"
    ),
    "pop_hierarchy": (
        "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/"
        "medication-event-hierarchy.json"
    ),
}

MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"

REQUIRED_ARTIFACTS = (
    "baseline-verification.json",
    "phase0-readiness-gaps.json",
    "exposure-semantics-contract.json",
    "intervention-evidence-registry.json",
    "candidate-cell-gate-matrix.json",
    "source-a-readiness.json",
    "source-b-readiness.json",
    "medication-residual-consumption-decision.json",
    "temporal-eligibility-audit.json",
    "confounding-and-indication-bias-inventory.json",
    "negative-control-results.json",
    "privacy-scan.json",
    "status-contract.json",
    "stage-report.md",
    "verification.json",
    "tests.json",
    "tests-evidence.json",
    "evidence-manifest.sha256",
)

FORBIDDEN_TECHNICAL_TIMESTAMPS = frozenset(
    {"appointment_date", "created", "modified", "created_at", "updated_at"}
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "code_version": CODE_VERSION,
        "stage_name": STAGE_NAME,
        "artifact_dir": ARTIFACT_DIR,
        "review_zip": REVIEW_ZIP,
        "namespace": NAMESPACE,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "source_a": SOURCE_A,
        "source_b": SOURCE_B,
        "gates": list(GATES),
        "exposure_tiers": list(EXPOSURE_TIERS),
        "hard_bans": [
            "no_intervention_response_model_training",
            "no_heldout_reopen_or_recompute",
            "no_frozen_nhr_d0_lep_mutation",
            "no_treatment_effect_claim",
            "no_causal_effect_claim",
            "no_algorithmic_or_llm_mapping_as_domain_accepted",
            "no_source_a_to_source_b_medication_transfer",
            "no_a_b_identity_merge",
            "no_appointment_as_administration",
            "no_recommendation_as_administration",
            "no_recorded_association_as_administration",
            "no_synthetic_source_substitute",
            "no_patient_level_publication",
            "no_iros_contact_or_calendar",
            "no_security_stage_resume_without_owner",
        ],
    }
