"""Policy — Intervention Response Readiness v0.1.1 point correction.

Scientific readiness is unchanged from v0.1. This package corrects evidence
provenance and clean-extraction replay. It does not train a model.
"""

from __future__ import annotations

from typing import Any

VERSION = "0.1.1"
CODE_VERSION = "intervention-response-readiness-v011/0.1.1"
STAGE_NAME = "STAGE 05 — INTERVENTION RESPONSE READINESS AND EXPOSURE SEMANTICS"
ARTIFACT_DIR = "artifacts/stage-05-intervention-response-readiness-and-exposure-semantics-v0.1.1"
REVIEW_ZIP = "stage-05-intervention-response-readiness-and-exposure-semantics-v0.1.1-review.zip"
NAMESPACE = "intervention-response-readiness-v011"
SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
SNAPSHOT_DIRNAME = "upstream-evidence"

V01_ZIP = "stage-05-intervention-response-readiness-and-exposure-semantics-v0.1-review.zip"
V01_SHA256 = "6605a4b643ea68ae893d6b52d0a0a196e1e2ad2ec505adad5691a41df70cf992"
V01_MEMBERS = 1025
V01_INDEXED = 1024
V01_ARTIFACT_DIR = "artifacts/stage-05-intervention-response-readiness-and-exposure-semantics-v0.1"

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

IRR_V016_BUNDLE = (
    "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6-review.zip",
    "3c856824a2856fe5b85c4186dd2c0134954e5c6930df2ab655a784ffaa38be4a",
)
MEDRES_BUNDLE = (
    "stage-03-first-source-aware-medication-residual-foundation-v0.1-review.zip",
    "a08ded64ed4790660861fe79b57eff54a3de1889d2c6ea796bc85d9fc487c612",
)
POPULATION_BUNDLE = (
    "stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1-review.zip",
    "35a35dd48612590fedf064e3916aa1ae14ab70bd2626e257889b70c11a55d796",
)

# Keys whose workspace bytes may differ from the originating bundle member
# only in post-pack publication bookkeeping. Scientific keys must still match.
BUNDLE_MEMBER_BOOKKEEPING_KEYS = {
    "medres_status": frozenset(
        {"PUBLICATION_INTEGRITY_STATUS", "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"}
    ),
}

EVIDENCE_CATALOG: tuple[dict[str, str], ...] = (
    {
        "key": "irr_v016_status",
        "canonical_source_path": (
            "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6/status-contract.json"
        ),
        "originating_bundle_name": IRR_V016_BUNDLE[0],
        "originating_bundle_sha256": IRR_V016_BUNDLE[1],
        "evidence_role": "integrated_runtime_status_contract",
        "privacy_classification": "AGGREGATE_STATUS_ONLY",
    },
    {
        "key": "irr_v016_protocol",
        "canonical_source_path": (
            "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6/"
            "external-validation-protocol.json"
        ),
        "originating_bundle_name": IRR_V016_BUNDLE[0],
        "originating_bundle_sha256": IRR_V016_BUNDLE[1],
        "evidence_role": "external_validation_protocol",
        "privacy_classification": "AGGREGATE_STATUS_ONLY",
    },
    {
        "key": "medres_status",
        "canonical_source_path": (
            "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/status-contract.json"
        ),
        "originating_bundle_name": MEDRES_BUNDLE[0],
        "originating_bundle_sha256": MEDRES_BUNDLE[1],
        "evidence_role": "medication_residual_status_contract",
        "privacy_classification": "AGGREGATE_STATUS_ONLY",
    },
    {
        "key": "medres_cells",
        "canonical_source_path": (
            "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/cell-registry-public.json"
        ),
        "originating_bundle_name": MEDRES_BUNDLE[0],
        "originating_bundle_sha256": MEDRES_BUNDLE[1],
        "evidence_role": "medication_residual_public_cell_registry",
        "privacy_classification": "AGGREGATE_PUBLIC_CELL_REGISTRY",
    },
    {
        "key": "medres_accounting",
        "canonical_source_path": (
            "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/"
            "medication-source-accounting.json"
        ),
        "originating_bundle_name": MEDRES_BUNDLE[0],
        "originating_bundle_sha256": MEDRES_BUNDLE[1],
        "evidence_role": "medication_source_accounting",
        "privacy_classification": "AGGREGATE_COUNTS_ONLY",
    },
    {
        "key": "medres_confounding",
        "canonical_source_path": (
            "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/confounding-inventory.json"
        ),
        "originating_bundle_name": MEDRES_BUNDLE[0],
        "originating_bundle_sha256": MEDRES_BUNDLE[1],
        "evidence_role": "confounding_inventory",
        "privacy_classification": "AGGREGATE_STATUS_ONLY",
    },
    {
        "key": "pop_schema",
        "canonical_source_path": (
            "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/"
            "source-a-medication-schema-profile.json"
        ),
        "originating_bundle_name": POPULATION_BUNDLE[0],
        "originating_bundle_sha256": POPULATION_BUNDLE[1],
        "evidence_role": "source_a_medication_schema_profile",
        "privacy_classification": "AGGREGATE_SCHEMA_AND_COUNTS",
    },
    {
        "key": "pop_time",
        "canonical_source_path": (
            "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/"
            "source-a-medication-time-semantics.json"
        ),
        "originating_bundle_name": POPULATION_BUNDLE[0],
        "originating_bundle_sha256": POPULATION_BUNDLE[1],
        "evidence_role": "source_a_medication_time_semantics",
        "privacy_classification": "AGGREGATE_SCHEMA_AND_COUNTS",
    },
    {
        "key": "pop_status_sem",
        "canonical_source_path": (
            "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/"
            "source-a-medication-status-semantics.json"
        ),
        "originating_bundle_name": POPULATION_BUNDLE[0],
        "originating_bundle_sha256": POPULATION_BUNDLE[1],
        "evidence_role": "source_a_medication_status_semantics",
        "privacy_classification": "AGGREGATE_SCHEMA_AND_COUNTS",
    },
    {
        "key": "pop_hierarchy",
        "canonical_source_path": (
            "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1/"
            "medication-event-hierarchy.json"
        ),
        "originating_bundle_name": POPULATION_BUNDLE[0],
        "originating_bundle_sha256": POPULATION_BUNDLE[1],
        "evidence_role": "medication_event_hierarchy",
        "privacy_classification": "AGGREGATE_SCHEMA_AND_COUNTS",
    },
)

COMPARE_FILES = (
    "phase0-readiness-gaps.json",
    "exposure-semantics-contract.json",
    "intervention-evidence-registry.json",
    "candidate-cell-gate-matrix.json",
    "source-a-readiness.json",
    "source-b-readiness.json",
    "medication-residual-consumption-decision.json",
    "negative-control-results.json",
    "status-contract.json",
)

STATUS_COMPARE_IGNORE = frozenset(
    {
        "CORE_READINESS_REPLAY_STATUS",
        "CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS",
        "PUBLICATION_INTEGRITY_STATUS",
        "ZIP_CONTENT_VERIFICATION_STATUS",
    }
)

UNSTABLE_KEYS = frozenset(
    {
        "generated_at",
        "duration_seconds",
        "output_tail",
        "live_repo_output_tail",
        "literal_command",
        "mutation_render_bytes",
    }
)

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
    "upstream-evidence-manifest.json",
    "upstream-evidence-verification.json",
    "v01-defect-reproduction.json",
    "clean-replay-comparison.json",
)

FORBIDDEN_TRAINING_MARKERS = (
    "sklearn",
    ".fit(",
    "train_model",
    "xgboost",
    "torch",
    "joblib",
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "code_version": CODE_VERSION,
        "stage_name": STAGE_NAME,
        "artifact_dir": ARTIFACT_DIR,
        "review_zip": REVIEW_ZIP,
        "point_correction_of": V01_ZIP,
        "scientific_status_upgrade": False,
        "intervention_response_model_training": False,
        "evidence_snapshot_count": len(EVIDENCE_CATALOG),
        "security_stage_status": SECURITY_STAGE_STATUS,
    }
