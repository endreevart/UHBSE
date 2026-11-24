"""Policy — Integrated Research Runtime Foundation v0.1.4."""

from __future__ import annotations

from typing import Any

from human_simulator.natural_history_rollout_v011.policy import (
    FORBIDDEN_MEDICATION_FIELDS,
    P1_FEATURE_ORDER,
    SELECTED_OUTCOMES_A,
    SELECTED_OUTCOMES_B,
)

VERSION = "0.1.4"
CODE_VERSION = "integrated-research-runtime-v014/0.1.4"
ARTIFACT_DIR = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.4"
RUNTIME_DIR = "private/integrated-research-runtime-v014"
MODELS_DIR = "private/integrated-research-runtime-v014/models"
WORKBENCH_DIR = "private/integrated-research-runtime-v014/workbench"
VALIDATION_DIR = "private/integrated-research-runtime-v014/external-validation"
LABEL_DIR = "private/integrated-research-runtime-v014/labels"
REVIEW_ZIP = "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.4-review.zip"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "integrated-research-runtime-v014"
N_PATHS_DEFAULT = 16
N_PATHS_MAX = 64
PI_LO = 0.05
PI_HI = 0.95
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8768
BODY_LIMIT_BYTES = 1_048_576

NS_SYN = "SYNTHETIC_FIXTURE"
NS_A = "SOURCE_A"
NS_B = "SOURCE_B"
SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
SYN_SOURCE = "synthetic"
SYN_OUTCOMES = ("SYN::alpha::au", "SYN::beta::au")
SYN_HORIZON = 90
P0_FEATURE_ORDER = ("persistence_value",)

V011_SRC = "src/human_simulator/integrated_research_runtime_v011"
V011_ARTIFACT = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1"
V01_ARTIFACT = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1"
V01_ORIGINS = "private/integrated-research-runtime-v01/sequences/origins_train_val.parquet"
NHR_MODELS = "private/natural-history-rollout-v011/models"
V02_MODELS = "private/joint-dependence-rollout-v02/models"
V031_MATERIALIZED = "private/unified-research-layer-v031/materialized"
V0111_OVERLAP = "private/unified-individual-state-v0111/overlap"
LEP_MODELS = "private/longitudinal-event-probability-v0211/models"
LEP_ARTIFACT = "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2.1.1"
ESKLP_INDEX = "private/medication-reference-v011/diagnostics/esklp-archive-and-index.json"

FREEZE_MANIFEST = "pre-test-freeze-manifest.json"
FREEZE_SIDECAR = "pre-test-freeze-manifest.json.sha256"

V013_EXPECTED_MEMBERS = 934
V013_EXPECTED_INDEXED = 933
V013_EXPECTED_SHA256 = "351febd77c018dacf1f04117d2a9a11d6022749d8c34b9f1f4a0c3514eaafa65"
V013_ARTIFACT = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.3"
V012_EXPECTED_MEMBERS = 916
V012_EXPECTED_INDEXED = 915
V012_EXPECTED_SHA256 = "2e0e7e8efa6b563c4363b34e4b040738c7d8e58de864c1ee83a819cd57ead7e3"
V011_EXPECTED_MEMBERS = 876
V011_EXPECTED_INDEXED = 875
V011_EXPECTED_SHA256 = "e940199fdbf978241ad2dc1db22d7def015942a5d42f82cb842360d094fbeeb6"
V01_EXPECTED_SHA256 = "62e3e46d12b6098b631c1d71e47e3c9ad26c49554521b080b63c831dd2fce93a"
V01_EXPECTED_MEMBERS = 853
V01_EXPECTED_INDEXED = 852
V012_ARTIFACT = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.2"
IDENTITY_REQUIRED_FIELDS = (
    "active_payload_sha256",
    "feature_order_sha256",
    "scaler_sha256",
    "residual_distribution_sha256",
    "unit",
    "source_system",
    "requested_horizon_days",
)
SOURCE_NAMESPACE_PAIRS = {
    "synthetic": "SYNTHETIC_FIXTURE",
    "magerya_api": "SOURCE_A",
    "kgz_raw": "SOURCE_B",
}

FROZEN_A_H90 = ("A::Гемоглобин::г/л", "A::Эритроциты::*10^12/л")
FROZEN_B_P0_H90 = "B::32::ммоль/л"

PRIOR_ZIPS: dict[str, tuple[str, str]] = {
    "irr_v013": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.3-review.zip",
        V013_EXPECTED_SHA256,
    ),
    "irr_v012": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.2-review.zip",
        V012_EXPECTED_SHA256,
    ),
    "irr_v011": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1-review.zip",
        V011_EXPECTED_SHA256,
    ),
    "irr_v01": (
        "stage-04-uhbse-integrated-research-runtime-foundation-v0.1-review.zip",
        V01_EXPECTED_SHA256,
    ),
    "nhr_joint_v02": (
        "stage-03-source-specific-joint-dependence-coherent-multi-outcome-rollout-v0.2-review.zip",
        "c513c0467a5d63c2424870ba413f8d52ce04226a425c99d2a20881d1dab036bb",
    ),
    "nhr_v011": (
        "stage-03-unified-source-aware-natural-history-stochastic-rollout-v0.1.1-review.zip",
        "ea8225df953f0bc36098992e89806d34a2c38ec0d45434de56e103fe405b4926",
    ),
    "nhr_v01": (
        "stage-03-unified-source-aware-natural-history-stochastic-rollout-v0.1-review.zip",
        "bb9f04cd49f9282220e089c7eef419a97684611c21cb260e7beb46dfbe5eb1da",
    ),
    "medres_v01": (
        "stage-03-first-source-aware-medication-residual-foundation-v0.1-review.zip",
        "a08ded64ed4790660861fe79b57eff54a3de1889d2c6ea796bc85d9fc487c612",
    ),
    "lep_v0211": (
        "stage-03-unified-longitudinal-event-probability-foundation-v0.2.1.1-review.zip",
        "151e085ec92c77a189de5aa49a79869e07eddda3fc825c78ea134787f7f30d9c",
    ),
    "research_layer_v031": (
        "stage-03-unified-a-b-materialized-research-layer-v0.3.1-review.zip",
        "ccf2627c10b472e10591f54c528170ad1e98ae259ecdf97e2d0b3c85722f54e9",
    ),
    "uis_v0111": (
        "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1-review.zip",
        "9a468aa225cf8ffc7f819152646c4d8788524564bf398bffbfb8e4634c3c0f88",
    ),
}

FUTURE_SOURCES = (
    "laboratory_reference_ontology",
    "drug_labels",
    "supplements",
    "nutrition",
    "activity_wearables",
    "diagnoses_anamnesis",
    "biomedical_knowledge",
    "external_governed_validation_datasets",
)


def outcome_unit(outcome_key: str) -> str:
    parts = str(outcome_key).split("::")
    return parts[-1] if len(parts) >= 3 else "UNKNOWN"


def none_scaler_identity(provider: str = "P0") -> dict[str, Any]:
    return {"scaler": None, "active_provider": provider}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "code_version": CODE_VERSION,
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "endpoint_type": "SOURCE_SPECIFIC_JOINT_OUTCOME_DISTRIBUTION_AT_REQUESTED_HORIZON",
        "CROSS_HORIZON_DEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "D1_not_accepted": True,
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": 0,
        "JOINT_HELDOUT_CONFIRMED_ROUTE_COUNT": 0,
        "no_a_b_outcome_mixing": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "namespaces": [NS_SYN, NS_A, NS_B],
        "synthetic_cells_cannot_serve_source_a_or_b": True,
        "source_namespace_pairs": dict(SOURCE_NAMESPACE_PAIRS),
        "identity_required_fields": list(IDENTITY_REQUIRED_FIELDS),
        "feature_order_hash_is_not_model_identity": True,
        "p1_feature_order": list(P1_FEATURE_ORDER),
        "p0_feature_order": list(P0_FEATURE_ORDER),
        "forbidden_medication_fields": list(FORBIDDEN_MEDICATION_FIELDS),
        "selected_outcomes_a": list(SELECTED_OUTCOMES_A),
        "selected_outcomes_b": list(SELECTED_OUTCOMES_B),
        "n_paths_max": N_PATHS_MAX,
        "TEST_ACCESS_LIFECYCLE_STATUS": "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED",
        "open_test_does_not_recompute_joint_gates": True,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "bind": HTTP_HOST,
        "PUBLICATION_INTEGRITY_STATUS": "DETACHED_SIDECAR_AUTHORITATIVE",
    }
