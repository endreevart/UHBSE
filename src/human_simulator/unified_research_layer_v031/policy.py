"""Policy — Unified A+B Materialized Research Data Plane v0.3.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.3.1"
ARTIFACT_DIR = "artifacts/stage-03-unified-a-b-materialized-research-layer-v0.3.1"
RUNTIME_DIR = "private/unified-research-layer-v031"
REVIEW_PACK_DIR = "private/unified-research-layer-v031/review-pack"
MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
PROVIDER_INPUT_DIR = "private/unified-research-layer-v031/provider-input"
OVERLAP_DIR = "private/unified-research-layer-v031/overlap-groups"
REVIEW_ZIP = "stage-03-unified-a-b-materialized-research-layer-v0.3.1-review.zip"

# Immutable prior baselines
ACCEPTED_V03_ZIP = "stage-03-unified-a-b-clinical-research-layer-v0.3-review.zip"
ACCEPTED_V03_SHA256 = (
    "d78d23bbd8a3984375bcc3891cc2f7f59b17c2c0fb4bdc4f19a92aa3e405eb73"
)
ACCEPTED_V03_MEMBERS = 615
ACCEPTED_V03_INDEXED = 614
ACCEPTED_V03_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-a-b-clinical-research-layer-v0.3"
)

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

PIN_SOURCE_A_SUBJECTS = 43856
PIN_SOURCE_B_SUBJECTS = 49564
PIN_LAB_EXACT_SYNONYM_CANDIDATES = 874
PIN_B_CODE_UNIT_STRATA = 2426
PIN_A_PROVIDER_GRAINS = 95
PIN_LAB_UNRESOLVED = 853
PIN_LAB_CONFLICTS = 1201

REQUIRED_DATASETS = (
    "research_subject",
    "research_encounter",
    "research_event",
    "research_observation",
    "research_observation_component",
    "research_diagnosis",
    "research_condition_history",
    "research_medication_record",
    "research_recommendation",
    "research_procedure",
    "research_document_reference",
    "research_provenance",
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"

INFRASTRUCTURE_SCHEMAS = frozenset({"tiger", "tiger_data", "topology", "pg_catalog", "information_schema"})

NEGATIVE_CONTROL_RELATIONS = frozenset(
    {
        ("magerya_api", "contract_saleorder"),
        ("magerya_api", "evotor_evotororder"),
        ("quest_digital", "analyses_weight"),
        ("quest_digital", "catalog_weights"),
    }
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "unified_a_b_materialized_research_layer",
        "INTEGRATION_FIRST_BEFORE_NEW_MODELING": True,
        "accepted_v03_sha256": ACCEPTED_V03_SHA256,
        "accepted_v0211_sha256": ACCEPTED_V0211_SHA256,
        "no_model_training": True,
        "no_identity_merge": True,
        "no_migration_0005": True,
        "no_automatic_human_accepted": True,
        "source_specific_retention_required": True,
        "row_level_materialization_required": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "INDIVIDUAL_STATE_DATASET_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_PASS": False,
    }
