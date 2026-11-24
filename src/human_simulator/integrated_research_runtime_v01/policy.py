"""Policy — UHBSE Integrated Research Runtime Foundation v0.1."""

from __future__ import annotations

from typing import Any

from human_simulator.natural_history_rollout_v011.policy import (
    FORBIDDEN_MEDICATION_FIELDS,
    P1_FEATURE_ORDER,
    SELECTED_OUTCOMES_A,
    SELECTED_OUTCOMES_B,
)

VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1"
RUNTIME_DIR = "private/integrated-research-runtime-v01"
SEQ_DIR = "private/integrated-research-runtime-v01/sequences"
MODELS_DIR = "private/integrated-research-runtime-v01/models"
WORKBENCH_DIR = "private/integrated-research-runtime-v01/workbench"
VALIDATION_DIR = "private/integrated-research-runtime-v01/external-validation"
LABEL_DIR = "private/integrated-research-runtime-v01/labels"
QSP_DIR = "private/integrated-research-runtime-v01/qsp"
REVIEW_ZIP = "stage-04-uhbse-integrated-research-runtime-foundation-v0.1-review.zip"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "integrated-research-runtime-v01"
CODE_VERSION = "integrated-research-runtime-v01/0.1"
L2 = 0.1
N_BOOTSTRAP = 100
N_PATHS_DEFAULT = 16
N_OOF_FOLDS = 5
PREDECLARED_ABSOLUTE_GRID_DAYS = (30, 90, 180, 365)
COPULA_SHRINK = 15.0
MARGINAL_CRPS_TOL = 1.05
PI_LO = 0.05
PI_HI = 0.95
COVERAGE_LO = 0.50
COVERAGE_HI = 0.99
STABILITY_SEEDS = (42, 43, 44)
STABILITY_PATH_COUNTS = (8, 16)

MIN_JOINT_SUBJECTS = 50
MIN_JOINT_GROUPS = 10
MIN_JOINT_PANELS = 80
MIN_JOINT_OUTCOMES = 2
MIN_PAIRWISE_SUPPORT = 30

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"

V02_PRIVATE = "private/joint-dependence-rollout-v02"
V02_MODELS = "private/joint-dependence-rollout-v02/models"
V02_SEQ = "private/joint-dependence-rollout-v02/sequences"
V02_ARTIFACT = "artifacts/stage-03-source-specific-joint-dependence-coherent-multi-outcome-rollout-v0.2"
V02_SRC = "src/human_simulator/joint_dependence_rollout_v02"
V011_MODELS = "private/natural-history-rollout-v011/models"
V031_MATERIALIZED = "private/unified-research-layer-v031/materialized"
V0111_OVERLAP = "private/unified-individual-state-v0111/overlap"
LEP_ARTIFACT = "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2.1.1"
ESKLP_INDEX = "private/medication-reference-v011/diagnostics/esklp-archive-and-index.json"

FREEZE_MANIFEST = "pre-test-freeze-manifest.json"
FREEZE_SIDECAR = "pre-test-freeze-manifest.json.sha256"
TEST_OPENED_MARKER = "test-opened.json"
TRAIN_VAL_PARQUET = "origins_train_val.parquet"
TEST_PARQUET = "origins_test.parquet"

V02_EXPECTED_MEMBERS = 833
V02_EXPECTED_INDEXED = 832
V02_EXPECTED_SHA256 = "c513c0467a5d63c2424870ba413f8d52ce04226a425c99d2a20881d1dab036bb"

CONNECTOR_STATUSES = (
    "CONNECTED_READ_ONLY",
    "CONNECTED_FROZEN_SNAPSHOT",
    "PROVIDER_INPUT_REQUIRED",
    "NETWORK_UNAVAILABLE",
    "LICENSE_REVIEW_REQUIRED",
    "NOT_CONFIGURED",
    "CLINICAL_DATA_TRANSFER_PROHIBITED",
)

LABEL_STATUSES = (
    "CANDIDATE_TECHNICAL_LABEL",
    "DOMAIN_REVIEW_REQUIRED",
    "DOMAIN_ACCEPTED",
    "REJECTED",
    "DEPRECATED",
)

PRIOR_ZIPS: dict[str, tuple[str, str]] = {
    "nhr_joint_v02": (
        "stage-03-source-specific-joint-dependence-coherent-multi-outcome-rollout-v0.2-review.zip",
        V02_EXPECTED_SHA256,
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


class TestAccessError(RuntimeError):
    pass


def outcome_unit(outcome_key: str) -> str:
    parts = str(outcome_key).split("::")
    return parts[-1] if len(parts) >= 3 else "UNKNOWN"


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "code_version": CODE_VERSION,
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "CAUSAL_INTERPRETATION_PROHIBITED": True,
        "joint_models_source_specific": True,
        "no_a_b_outcome_mixing": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "no_medication_features": True,
        "no_patient_data_to_external_providers": True,
        "strict_panel_contract": "STRICT_COOBSERVED_TARGET_PANEL",
        "async_vector_contract": "ASYNCHRONOUS_HORIZON_ALIGNED_OUTCOME_VECTOR",
        "async_not_for_dependence_acceptance": True,
        "d0": "INDEPENDENT_NORMALIZED_MARGINAL_RESIDUALS",
        "d1": "SOURCE_SPECIFIC_MASKED_GAUSSIAN_COPULA",
        "d1_residuals": "TRAIN_GROUP_OOF",
        "scores": "NORMALIZED_ENERGY_AND_VARIOGRAM_ONLY",
        "raw_unit_pooled_scoring": False,
        "p1_feature_order": list(P1_FEATURE_ORDER),
        "forbidden_medication_fields": list(FORBIDDEN_MEDICATION_FIELDS),
        "selected_outcomes_a": list(SELECTED_OUTCOMES_A),
        "selected_outcomes_b": list(SELECTED_OUTCOMES_B),
        "requested_absolute_grid_days": list(PREDECLARED_ABSOLUTE_GRID_DAYS),
        "copula_shrink": COPULA_SHRINK,
        "marginal_crps_tolerance": MARGINAL_CRPS_TOL,
        "acceptance_requires_paired_group_bootstrap_ci": True,
        "test_does_not_change_gates": True,
        "TEST_SET_NOVELTY_STATUS": "REUSED_HISTORICAL_HELDOUT_NOT_EXTERNAL_VALIDATION",
        "seed": SEED,
        "stability_seeds": list(STABILITY_SEEDS),
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
        "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
        "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
        "SAFETY_BOUNDARY_CLASSIFIER_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
    }
