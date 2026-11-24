"""Policy — Laboratory Metadata Probe and Privacy Closure v0.2.1.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.2.1.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-cross-source-laboratory-metadata-privacy-closure-v0.2.1.1"
)
RUNTIME_DIR = "private/cross-source-lab-semantic-v0211"
REVIEW_PACK_DIR = "private/cross-source-lab-semantic-v0211/review-pack"
PROVIDER_INPUT_DIR = "private/cross-source-lab-semantic-v0211/provider-input"
REVIEW_ZIP = (
    "stage-03-cross-source-laboratory-metadata-privacy-closure-v0.2.1.1-review.zip"
)

ACCEPTED_V021_ZIP = (
    "stage-03-cross-source-laboratory-analyte-ontology-metadata-closure-v0.2.1-review.zip"
)
ACCEPTED_V021_SHA256 = (
    "d10c0a0202a9590d41105e6e56ec406980076a30c953535300d8277212fe5c13"
)
ACCEPTED_V021_MEMBERS = 590
ACCEPTED_V021_INDEXED = 589
ACCEPTED_V021_ARTIFACT_DIR = (
    "artifacts/stage-03-cross-source-laboratory-analyte-ontology-metadata-closure-v0.2.1"
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

SOURCE_A_SYSTEM_ID = "magerya_api"
SOURCE_B_SYSTEM_ID = "kgz_raw"
SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"

# Seed laboratory relations for Source A (proven clinical lab path)
SOURCE_A_LAB_SEED_RELATIONS = (
    ("magerya_api", "document_analysisresult"),
    ("magerya_api", "document_analysisresultitem"),
)

SOURCE_B_LAB_SEED_RELATIONS = (
    ("quest_digital", "analyses_catalog"),
    ("quest_digital", "analyses_constructor"),
    ("quest_digital", "analyses_pool"),
    ("quest_digital", "analyses_labs"),
    ("quest_digital", "analyses_codes"),
    ("quest_digital", "analyses_weight"),
    ("quest_digital", "analyses_tags"),
    ("quest_digital", "link_analyses"),
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "lab_metadata_privacy_closure",
        "accepted_v021_sha256": ACCEPTED_V021_SHA256,
        "analyte_ontology_preserved_from": "0.2.1",
        "no_global_substring_scan": True,
        "no_row_derived_hashes_in_public": True,
        "no_automatic_accepted": True,
        "no_human_accept_in_this_release": True,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": "NOT_RUN",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_PASS": False,
    }
