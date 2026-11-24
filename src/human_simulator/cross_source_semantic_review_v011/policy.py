"""Policy — Cross-Source Outcome Semantic Review corrective v0.1.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.1"
ARTIFACT_DIR = "artifacts/stage-03-cross-source-outcome-semantic-review-v0.1.1"
RUNTIME_DIR = "private/cross-source-outcome-review-v011"
REVIEW_ZIP = "stage-03-cross-source-outcome-semantic-review-v0.1.1-review.zip"

ACCEPTED_V01_ZIP = "stage-03-cross-source-outcome-semantic-review-v0.1-review.zip"
ACCEPTED_V01_SHA256 = (
    "cf0c6982bcfd8933bb1a43e6c90b10d2294c5045abfb627a26988dd89beac84f"
)
ACCEPTED_V01_MEMBERS = 600
ACCEPTED_V01_INDEXED = 599
ACCEPTED_V01_ARTIFACT_DIR = (
    "artifacts/stage-03-cross-source-outcome-semantic-review-v0.1"
)

ACCEPTED_PRIVACY_XS_ZIP = (
    "stage-03-privacy-boundary-cross-source-longitudinal-harmonization-v0.1-review.zip"
)
ACCEPTED_PRIVACY_XS_SHA256 = (
    "a04df9fb03d85852a0d56c694751a026eddb34f4d8362c8a8943ba415090e231"
)
ACCEPTED_PRIVACY_XS_MEMBERS = 540
ACCEPTED_PRIVACY_XS_INDEXED = 539

ACCEPTED_GS011_ZIP = (
    "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1-review.zip"
)
ACCEPTED_GS011_SHA256 = (
    "86643de61303d772b43b7abddf048f0cb42f355dd649c885457dacc43b44a96d"
)

TYPED_DECISIONS = (
    "ACCEPTED_COMPARABLE",
    "ACCEPTED_WITH_RESTRICTIONS",
    "AMBIGUOUS",
    "REJECTED",
    "INSUFFICIENT_EVIDENCE",
)

# Restrictions that block scientific usability even if domain accepts with restrictions
NON_USABLE_RESTRICTIONS = frozenset(
    {
        "analyte_unverified",
        "specimen_unverified",
        "assay_unverified",
        "unit_unverified",
        "numeric_semantics_unverified",
    }
)

HARD_CONFLICT_CLASSES = frozenset(
    {
        "UNIT_CONFLICT",
        "SPECIMEN_CONFLICT",
        "ASSAY_CONFLICT",
        "ANALYTE_AMBIGUOUS",
        "NUMERIC_SEMANTICS_CONFLICT",
    }
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "cross_source_outcome_semantic_review_corrective",
        "accepted_v01_sha256": ACCEPTED_V01_SHA256,
        "accepted_privacy_xs_sha256": ACCEPTED_PRIVACY_XS_SHA256,
        "no_automatic_accepted_from_label_unit": True,
        "no_exhaustive_discovery_in_this_release": True,
        "no_new_human_decisions_in_this_release": True,
        "no_threshold_owner_decision_in_this_release": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "NOT_RUN",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "EXHAUSTIVE_CROSS_SOURCE_CANDIDATE_DISCOVERY_STATUS": "NOT_RUN",
        "SCIENTIFIC_PASS": False,
    }
