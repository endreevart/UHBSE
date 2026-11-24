"""Policy — Lab Semantic Discovery corrective v0.2.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.2.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-cross-source-laboratory-analyte-ontology-metadata-closure-v0.2.1"
)
RUNTIME_DIR = "private/cross-source-lab-semantic-v021"
REVIEW_PACK_DIR = "private/cross-source-lab-semantic-v021/review-pack"
REVIEW_ZIP = (
    "stage-03-cross-source-laboratory-analyte-ontology-metadata-closure-v0.2.1-review.zip"
)

ACCEPTED_V02_ZIP = (
    "stage-03-full-cross-source-laboratory-semantic-discovery-v0.2-review.zip"
)
ACCEPTED_V02_SHA256 = (
    "5e2ebf7a45b5dec207d333e515c635a5323074e8b9b01f774b51386304f0d99d"
)
ACCEPTED_V02_MEMBERS = 572
ACCEPTED_V02_ARTIFACT_DIR = (
    "artifacts/stage-03-full-cross-source-laboratory-semantic-discovery-v0.2"
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

SOURCE_A_SYSTEM_ID = "magerya_api"
SOURCE_B_SYSTEM_ID = "kgz_raw"

IDENTITY_LEVELS = (
    "EXACT_ANALYTE_IDENTITY",
    "APPROVED_ANALYTE_SYNONYM",
    "ANALYTE_FAMILY_RETRIEVAL_ONLY",
    "ANALYTE_SUBTYPE_CONFLICT",
    "DERIVED_MEASURE_CONFLICT",
    "INSUFFICIENT_ANALYTE_EVIDENCE",
)

CANDIDATE_CLASSES = (
    "SEMANTICALLY_ALIGNED_CANDIDATE",
    "ANALYTE_CANDIDATE",
    "ANALYTE_FAMILY_RETRIEVAL_ONLY",
    "SPECIMEN_MISSING",
    "ASSAY_MISSING",
    "UNIT_CONVERSION_REVIEW_REQUIRED",
    "ANALYTE_AMBIGUOUS",
    "ANALYTE_SUBTYPE_CONFLICT",
    "DERIVED_MEASURE_CONFLICT",
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
        "ANALYTE_SUBTYPE_CONFLICT",
        "DERIVED_MEASURE_CONFLICT",
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
        "stage": "lab_semantic_analyte_ontology_metadata_closure",
        "accepted_v02_sha256": ACCEPTED_V02_SHA256,
        "family_never_sets_analyte_ok": True,
        "no_automatic_accepted": True,
        "no_human_accept_in_this_release": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "NOT_RUN",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_PASS": False,
    }
