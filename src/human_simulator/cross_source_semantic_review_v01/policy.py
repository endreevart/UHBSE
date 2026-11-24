"""Policy — Cross-Source Outcome Semantic Review and Accepted Mapping Closure v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-cross-source-outcome-semantic-review-v0.1"
)
RUNTIME_DIR = "private/cross-source-outcome-review-v01"
REVIEW_ZIP = (
    "stage-03-cross-source-outcome-semantic-review-v0.1-review.zip"
)

ACCEPTED_PRIVACY_XS_ZIP = (
    "stage-03-privacy-boundary-cross-source-longitudinal-harmonization-v0.1-review.zip"
)
ACCEPTED_PRIVACY_XS_SHA256 = (
    "a04df9fb03d85852a0d56c694751a026eddb34f4d8362c8a8943ba415090e231"
)
ACCEPTED_PRIVACY_XS_MEMBERS = 540
ACCEPTED_PRIVACY_XS_INDEXED = 539
ACCEPTED_PRIVACY_XS_ARTIFACT_DIR = (
    "artifacts/stage-03-privacy-boundary-cross-source-longitudinal-harmonization-v0.1"
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

SOURCE_A_SYSTEM_ID = "magerya_api"
SOURCE_B_SYSTEM_ID = "kgz_raw"

# Typed domain decisions (human)
TYPED_DECISIONS = (
    "ACCEPTED_COMPARABLE",
    "ACCEPTED_WITH_RESTRICTIONS",
    "AMBIGUOUS",
    "REJECTED",
    "INSUFFICIENT_EVIDENCE",
)
SCIENTIFICALLY_USABLE = frozenset(
    {"ACCEPTED_COMPARABLE", "ACCEPTED_WITH_RESTRICTIONS"}
)

# Machine candidate classes (pre-decision)
CANDIDATE_CLASSES = (
    "SEMANTICALLY_ALIGNED_CANDIDATE",
    "UNIT_CONFLICT",
    "SPECIMEN_MISSING",
    "SPECIMEN_CONFLICT",
    "ASSAY_MISSING",
    "ASSAY_CONFLICT",
    "ANALYTE_AMBIGUOUS",
    "NUMERIC_SEMANTICS_CONFLICT",
    "INSUFFICIENT_EVIDENCE",
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "cross_source_outcome_semantic_review",
        "accepted_privacy_xs_sha256": ACCEPTED_PRIVACY_XS_SHA256,
        "no_automatic_accepted_from_label_unit": True,
        "no_model_performance_in_ranking": True,
        "no_unverified_unit_conversion": True,
        "no_identity_merge": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "NOT_RUN",
        "ENGINE_CROSS_SOURCE_SHADOW_STATUS": "NOT_RUN",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "CROSS_SOURCE_INDEPENDENCE_STATUS": "INDEPENDENCE_NOT_ESTABLISHED",
    }
