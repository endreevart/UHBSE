"""Policy — Privacy Boundary + Cross-Source Longitudinal Harmonization A↔B v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-privacy-boundary-cross-source-longitudinal-harmonization-v0.1"
)
RUNTIME_DIR = "private/privacy-cross-source-v01"
REVIEW_ZIP = (
    "stage-03-privacy-boundary-cross-source-longitudinal-harmonization-v0.1-review.zip"
)

# Accepted primary baseline — Global State v0.1.1
ACCEPTED_GS011_ZIP = (
    "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1-review.zip"
)
ACCEPTED_GS011_SHA256 = (
    "86643de61303d772b43b7abddf048f0cb42f355dd649c885457dacc43b44a96d"
)
ACCEPTED_GS011_MEMBERS = 531
ACCEPTED_GS011_INDEXED = 530
ACCEPTED_GS011_ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1"
)

# Prior immutable pins (must not change)
ACCEPTED_GS01_ZIP = (
    "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1-review.zip"
)
ACCEPTED_GS01_SHA256 = (
    "3f98628fca0c7c78f29310cd88fb5cf30903720bb2528451dba6661bfb200ffc"
)
ACCEPTED_TRAJ011_ZIP = (
    "stage-03-source-a-single-outcome-trajectory-expansion-v0.1.1-review.zip"
)
ACCEPTED_TRAJ011_SHA256 = (
    "922158a22212aedd903f5a62ea532119465da7cb74faf16326e07c1beaba6c0d"
)
ACCEPTED_UNIFIED_V01211_ZIP = (
    "stage-03-unified-source-expansion-v0.1.2.1.1-review.zip"
)
ACCEPTED_UNIFIED_V01211_SHA256 = (
    "5f9d10e1e57ed7423b651a0156714ce976b3ec01f5c85306e929f91f7ccdb997"
)
ACCEPTED_UNIFIED_V012_ZIP = "stage-03-unified-source-expansion-v0.1.2-review.zip"
ACCEPTED_UNIFIED_V012_SHA256 = (
    "55b92ce7b9762114040233be30eaa4705b03e1aa2d378097e21be4ef2258b269"
)
ACCEPTED_CONCEPT_PILOT_ZIP = (
    "stage-03-first-concept-bounded-technical-medication-pilot-v0.1-review.zip"
)
ACCEPTED_CONCEPT_PILOT_SHA256 = (
    "aba265d5a4d6f01560b02c3e3fa68d827aba9bd3e1e594d4974d53d4bef8c7b9"
)

# Carried facts (baseline pins — drift if live differs)
CARRIED_SOURCE_A_SUBJECTS = 43856
CARRIED_SOURCE_B_SUBJECTS = 49564
CARRIED_SOURCE_A_GLOBAL_TEST = 6635
CARRIED_V011_HORIZON_ALIGNED_SUBJECTS = 623
CARRIED_V011_PRIMARY_TARGETS = 19195
CARRIED_V011_PROVIDERS = 95
CARRIED_V011_EVALUABLE = 85
CARRIED_V011_DIAGNOSTIC_ONLY = 10
CARRIED_V011_IN_SUPPORT_SUM = 18311  # reporting defect: 19195-18311=884 unclassified

SOURCE_A_SYSTEM_ID = "magerya_api"
SOURCE_B_SYSTEM_ID = "kgz_raw"
SOURCE_A_RESEARCH_NAMESPACE = "uhbse-research-v01|source-a|magerya_api"
SOURCE_B_RESEARCH_NAMESPACE = "uhbse-research-v01|source-b|kgz_raw"
SOURCE_B_SPLIT_NAMESPACE = "source-b-global-state-v01"
SOURCE_B_SPLIT_SEED = 42
BUCKET_TRAIN_END = 0.70
BUCKET_VAL_END = 0.85

MAPPING_STATUSES = (
    "EXACT",
    "SUPPORTED_TRANSFORM",
    "HYPOTHESIS",
    "AMBIGUOUS",
    "CONFLICT",
    "UNKNOWN",
    "NOT_COMPARABLE",
)
# Scientifically accepted for transfer / zero-shot
ACCEPTED_MAPPING_STATUSES = frozenset({"EXACT", "SUPPORTED_TRANSFORM"})

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
DEIDENTIFIED_VIEW_STATUS = "DEIDENTIFIED_RESEARCH_VIEW"
PSEUDONYMOUS_VIEW_STATUS = "PSEUDONYMOUS_RESTRICTED_VIEW"
CLAIM_LEVEL_SHADOW = "TECHNICAL_CROSS_SOURCE_SHADOW_ONLY"

HORIZON_BINS = (
    ("1_30", 1.0, 30.0),
    ("31_90", 30.0, 90.0),
    ("91_180", 90.0, 180.0),
    ("181_365", 180.0, 365.0),
    ("gt_365", 365.0, float("inf")),
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "privacy_boundary_cross_source_longitudinal_harmonization",
        "accepted_gs011_sha256": ACCEPTED_GS011_SHA256,
        "carried_source_a_subjects": CARRIED_SOURCE_A_SUBJECTS,
        "carried_source_b_subjects": CARRIED_SOURCE_B_SUBJECTS,
        "do_not_sum_as_unique_patients": True,
        "no_identity_merge": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "claim_level_if_shadow_runs": CLAIM_LEVEL_SHADOW,
        "not_anonymous_claim": True,
        "deidentified_status_label": DEIDENTIFIED_VIEW_STATUS,
        "pseudonymous_status_label": PSEUDONYMOUS_VIEW_STATUS,
    }
