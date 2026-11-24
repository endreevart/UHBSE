"""Policy — Full Cross-Source Laboratory Semantic Discovery A↔B v0.2."""

from __future__ import annotations

from typing import Any

VERSION = "0.2"
ARTIFACT_DIR = (
    "artifacts/stage-03-full-cross-source-laboratory-semantic-discovery-v0.2"
)
RUNTIME_DIR = "private/cross-source-lab-semantic-v02"
REVIEW_PACK_DIR = "private/cross-source-lab-semantic-v02/review-pack"
REVIEW_ZIP = (
    "stage-03-full-cross-source-laboratory-semantic-discovery-v0.2-review.zip"
)

ACCEPTED_V011_ZIP = (
    "stage-03-cross-source-outcome-semantic-review-v0.1.1-review.zip"
)
ACCEPTED_V011_SHA256 = (
    "22ddd1d37ebe27ff59dadb2f462a15467642925f6158f94b86fcfa4afffa3cb0"
)
ACCEPTED_V011_MEMBERS = 557
ACCEPTED_V011_INDEXED = 556

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
ACCEPTED_PRIVACY_XS_MEMBERS = 540
ACCEPTED_PRIVACY_XS_INDEXED = 539

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

# Reuse B split from privacy stage (subset-invariant)
SOURCE_B_SPLIT_NAMESPACE = "source_b_global_split_v01"
SOURCE_B_SPLIT_SEED = 20260825
BUCKET_TRAIN_END = 0.70
BUCKET_VAL_END = 0.85

CANDIDATE_CLASSES = (
    "SEMANTICALLY_ALIGNED_CANDIDATE",
    "ANALYTE_CANDIDATE",
    "SPECIMEN_MISSING",
    "ASSAY_MISSING",
    "UNIT_CONVERSION_REVIEW_REQUIRED",
    "ANALYTE_AMBIGUOUS",
    "UNIT_CONFLICT",
    "SPECIMEN_CONFLICT",
    "ASSAY_CONFLICT",
    "NUMERIC_SEMANTICS_CONFLICT",
    "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH",
    "INSUFFICIENT_EVIDENCE",
)

HARD_CONFLICT_CLASSES = frozenset(
    {
        "ANALYTE_AMBIGUOUS",
        "UNIT_CONFLICT",
        "SPECIMEN_CONFLICT",
        "ASSAY_CONFLICT",
        "NUMERIC_SEMANTICS_CONFLICT",
    }
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "full_cross_source_laboratory_semantic_discovery",
        "accepted_v011_sha256": ACCEPTED_V011_SHA256,
        "no_hardcoded_known_candidates_as_universe": True,
        "no_automatic_accepted": True,
        "no_model_performance_in_ranking": True,
        "no_top500_catalog_cap": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "NOT_RUN",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_PASS": False,
    }
