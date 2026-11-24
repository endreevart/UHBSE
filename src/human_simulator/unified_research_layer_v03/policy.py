"""Policy — Unified A+B Clinical Research Layer v0.3."""

from __future__ import annotations

from typing import Any

VERSION = "0.3"
ARTIFACT_DIR = "artifacts/stage-03-unified-a-b-clinical-research-layer-v0.3"
RUNTIME_DIR = "private/unified-research-layer-v03"
REVIEW_PACK_DIR = "private/unified-research-layer-v03/review-pack"
RESEARCH_LAYER_DIR = "private/unified-research-layer-v03/research-layer"
PROVIDER_INPUT_DIR = "private/unified-research-layer-v03/provider-input"
REVIEW_ZIP = "stage-03-unified-a-b-clinical-research-layer-v0.3-review.zip"

ACCEPTED_V0211_ZIP = (
    "stage-03-cross-source-laboratory-metadata-privacy-closure-v0.2.1.1-review.zip"
)
ACCEPTED_V0211_SHA256 = (
    "3214b5414f533e59bba620ed8bcfa3fd23e7197de557583a0c0cb257e9dc9066"
)
ACCEPTED_V0211_MEMBERS = 602
ACCEPTED_V0211_INDEXED = 601
ACCEPTED_V0211_ARTIFACT_DIR = (
    "artifacts/stage-03-cross-source-laboratory-metadata-privacy-closure-v0.2.1.1"
)

ACCEPTED_V021_ZIP = (
    "stage-03-cross-source-laboratory-analyte-ontology-metadata-closure-v0.2.1-review.zip"
)
ACCEPTED_V021_SHA256 = (
    "d10c0a0202a9590d41105e6e56ec406980076a30c953535300d8277212fe5c13"
)
ACCEPTED_V02_ZIP = (
    "stage-03-full-cross-source-laboratory-semantic-discovery-v0.2-review.zip"
)
ACCEPTED_V02_SHA256 = (
    "5e2ebf7a45b5dec207d333e515c635a5323074e8b9b01f774b51386304f0d99d"
)
ACCEPTED_V011_ZIP = (
    "stage-03-cross-source-outcome-semantic-review-v0.1.1-review.zip"
)
ACCEPTED_V011_SHA256 = (
    "22ddd1d37ebe27ff59dadb2f462a15467642925f6158f94b86fcfa4afffa3cb0"
)
ACCEPTED_V01_ZIP = (
    "stage-03-cross-source-outcome-semantic-review-v0.1-review.zip"
)
ACCEPTED_V01_SHA256 = (
    "cf0c6982bcfd8933bb1a43e6c90b10d2294c5045abfb627a26988dd89beac84f"
)
ACCEPTED_PRIVACY_XS_ZIP = (
    "stage-03-privacy-boundary-cross-source-longitudinal-harmonization-v0.1-review.zip"
)
ACCEPTED_PRIVACY_XS_SHA256 = (
    "a04df9fb03d85852a0d56c694751a026eddb34f4d8362c8a8943ba415090e231"
)
ACCEPTED_GS011_ZIP = (
    "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1-review.zip"
)
ACCEPTED_GS011_SHA256 = (
    "86643de61303d772b43b7abddf048f0cb42f355dd649c885457dacc43b44a96d"
)
ACCEPTED_GS011_ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1"
)

# Live-verified pins (must match live or explain)
PIN_SOURCE_A_SUBJECTS = 43856
PIN_SOURCE_B_SUBJECTS = 49564
PIN_LAB_EXACT_SYNONYM_CANDIDATES = 874
PIN_B_CODE_UNIT_STRATA = 2426
PIN_A_PROVIDER_GRAINS = 95

SEMANTIC_TIERS = (
    "CROSS_SOURCE_ACCEPTED",
    "SOURCE_SPECIFIC_SUPPORTED",
    "UNRESOLVED_RETAINED",
    "REJECTED_CONFLICT",
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"

DOMAINS = (
    "subjects_patients",
    "encounters_consultations_appointments",
    "diagnoses",
    "anamnesis_history",
    "complaints",
    "anthropometry_vitals",
    "laboratory_orders",
    "laboratory_results",
    "laboratory_components",
    "medications",
    "prescriptions_recorded_medication_events",
    "dosage_strength_form_frequency_route",
    "recommendations",
    "procedures_interventions",
    "medical_documents",
    "structured_conclusions",
    "clinical_event_timestamps",
    "reference_catalogs",
    "entity_links",
    "unstructured_medical_text",
    "unknown_clinical_relations",
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "unified_a_b_clinical_research_layer",
        "INTEGRATION_FIRST_BEFORE_NEW_MODELING": True,
        "accepted_v0211_sha256": ACCEPTED_V0211_SHA256,
        "no_model_training": True,
        "no_identity_merge": True,
        "no_migration_0005": True,
        "no_automatic_human_accepted": True,
        "source_specific_retention_required": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_PASS": False,
    }
