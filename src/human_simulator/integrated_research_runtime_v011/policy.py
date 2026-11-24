"""Policy — Integrated Research Runtime Foundation v0.1.1."""

from __future__ import annotations

from typing import Any

from human_simulator.natural_history_rollout_v011.policy import (
    FORBIDDEN_MEDICATION_FIELDS,
    P1_FEATURE_ORDER,
    SELECTED_OUTCOMES_A,
    SELECTED_OUTCOMES_B,
)

VERSION = "0.1.1"
CODE_VERSION = "integrated-research-runtime-v011/0.1.1"
ARTIFACT_DIR = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1"
RUNTIME_DIR = "private/integrated-research-runtime-v011"
MODELS_DIR = "private/integrated-research-runtime-v011/models"
SEQ_DIR = "private/integrated-research-runtime-v011/sequences"
WORKBENCH_DIR = "private/integrated-research-runtime-v011/workbench"
VALIDATION_DIR = "private/integrated-research-runtime-v011/external-validation"
LABEL_DIR = "private/integrated-research-runtime-v011/labels"
REVIEW_ZIP = "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1-review.zip"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "integrated-research-runtime-v011"
N_PATHS_DEFAULT = 16
PI_LO = 0.05
PI_HI = 0.95
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8765
BODY_LIMIT_BYTES = 1_048_576

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
V01_SRC = "src/human_simulator/integrated_research_runtime_v01"
V01_ARTIFACT = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1"
V01_PRIVATE = "private/integrated-research-runtime-v01"
V02_MODELS = "private/joint-dependence-rollout-v02/models"
V02_SEQ = "private/joint-dependence-rollout-v02/sequences"
V031_MATERIALIZED = "private/unified-research-layer-v031/materialized"
V0111_OVERLAP = "private/unified-individual-state-v0111/overlap"
LEP_ARTIFACT = "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2.1.1"
ESKLP_INDEX = "private/medication-reference-v011/diagnostics/esklp-archive-and-index.json"
V01_ORIGINS = "private/integrated-research-runtime-v01/sequences/origins_train_val.parquet"

FREEZE_MANIFEST = "pre-test-freeze-manifest.json"
FREEZE_SIDECAR = "pre-test-freeze-manifest.json.sha256"

V01_EXPECTED_MEMBERS = 853
V01_EXPECTED_INDEXED = 852
V01_EXPECTED_SHA256 = "62e3e46d12b6098b631c1d71e47e3c9ad26c49554521b080b63c831dd2fce93a"

SYN_SOURCE = "synthetic"
SYN_OUTCOMES = ("SYN::alpha::au", "SYN::beta::au")
SYN_HORIZON = 90

PRIOR_ZIPS: dict[str, tuple[str, str]] = {
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


def outcome_unit(outcome_key: str) -> str:
    parts = str(outcome_key).split("::")
    return parts[-1] if len(parts) >= 3 else "UNKNOWN"


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
        "p1_feature_order": list(P1_FEATURE_ORDER),
        "forbidden_medication_fields": list(FORBIDDEN_MEDICATION_FIELDS),
        "selected_outcomes_a": list(SELECTED_OUTCOMES_A),
        "selected_outcomes_b": list(SELECTED_OUTCOMES_B),
        "TEST_ACCESS_LIFECYCLE_STATUS": "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED",
        "open_test_does_not_recompute_joint_gates": True,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "bind": HTTP_HOST,
    }
