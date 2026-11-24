"""Policy — Unified A+B Individual State + Source-Aware Multi-Outcome Baseline v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1"
)
RUNTIME_DIR = "private/unified-individual-state-v01"
STATES_DIR = "private/unified-individual-state-v01/states"
OVERLAP_DIR = "private/unified-individual-state-v01/overlap"
PROVENANCE_DIR = "private/unified-individual-state-v01/provenance"
MODELS_DIR = "private/unified-individual-state-v01/models"
REVIEW_ZIP = (
    "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1-review.zip"
)

# Immutable baseline — unified research layer v0.3.1
ACCEPTED_V031_ZIP = (
    "stage-03-unified-a-b-materialized-research-layer-v0.3.1-review.zip"
)
ACCEPTED_V031_SHA256 = (
    "ccf2627c10b472e10591f54c528170ad1e98ae259ecdf97e2d0b3c85722f54e9"
)
ACCEPTED_V031_MEMBERS = 635
ACCEPTED_V031_INDEXED = 634
ACCEPTED_V031_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-a-b-materialized-research-layer-v0.3.1"
)
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"

# Prior immutable ZIPs
ACCEPTED_V03_ZIP = "stage-03-unified-a-b-clinical-research-layer-v0.3-review.zip"
ACCEPTED_V03_SHA256 = (
    "d78d23bbd8a3984375bcc3891cc2f7f59b17c2c0fb4bdc4f19a92aa3e405eb73"
)
ACCEPTED_V0211_ZIP = (
    "stage-03-cross-source-laboratory-metadata-privacy-closure-v0.2.1.1-review.zip"
)
ACCEPTED_V0211_SHA256 = (
    "3214b5414f533e59bba620ed8bcfa3fd23e7197de557583a0c0cb257e9dc9066"
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

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "unified-a-b-individual-state-v01"
BUCKET_TRAIN_END = 0.70
BUCKET_VAL_END = 0.85

# Predeclared outcome selection thresholds (train only)
MIN_TRAIN_SUBJECTS_PER_OUTCOME = 50
MIN_TRAIN_TARGETS_PER_OUTCOME = 80
MAX_OUTCOMES_PER_SOURCE = 12

REQUIRED_V031_DATASETS = (
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


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "unified_a_b_individual_state_multi_outcome_baseline",
        "INTEGRATION_FIRST_BEFORE_NEW_MODELING": True,
        "accepted_v031_sha256": ACCEPTED_V031_SHA256,
        "no_model_training_before_state_gates": True,
        "no_identity_merge": True,
        "no_migration_0005": True,
        "no_false_cross_source_mappings": True,
        "DOMAIN_ACCEPTED_MAPPING_COUNT_default": 0,
        "does_not_block_source_aware_heads": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "seed": SEED,
        "cutoff_policy_predeclared": True,
        "cutoff_policy": {
            "train": "all_eligible_internal_cutoffs_with_prior_history_and_future_target",
            "validation_test": "one_deterministic_eligible_cutoff_per_subject",
            "same_time_target_forbidden": True,
            "post_cutoff_features_forbidden": True,
        },
    }
