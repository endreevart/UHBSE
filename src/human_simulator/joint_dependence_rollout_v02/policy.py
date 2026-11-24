"""Policy — Joint Dependence and Coherent Multi-Outcome Rollout Foundation v0.2."""

from __future__ import annotations

from typing import Any

from human_simulator.natural_history_rollout_v011.policy import (
    FORBIDDEN_MEDICATION_FIELDS,
    P1_FEATURE_ORDER,
    SELECTED_OUTCOMES_A,
    SELECTED_OUTCOMES_B,
)

VERSION = "0.2"
ARTIFACT_DIR = (
    "artifacts/stage-03-source-specific-joint-dependence-coherent-multi-outcome-rollout-v0.2"
)
RUNTIME_DIR = "private/joint-dependence-rollout-v02"
SEQ_DIR = "private/joint-dependence-rollout-v02/sequences"
MODELS_DIR = "private/joint-dependence-rollout-v02/models"
REVIEW_ZIP = (
    "stage-03-source-specific-joint-dependence-coherent-multi-outcome-rollout-v0.2-review.zip"
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "joint-dependence-rollout-v02"
L2 = 0.1
N_BOOTSTRAP = 100
N_PATHS_DEFAULT = 16
N_OOF_FOLDS = 5
PREDECLARED_ABSOLUTE_GRID_DAYS = (30, 90, 180, 365)
RECURSIVE_BASE_INCREMENT_DAYS = 30
HORIZON_BIN_REL_TOL = 0.5
ERROR_GROWTH_LIMIT = 3.0
COVERAGE_LO = 0.50
COVERAGE_HI = 0.99
PI_LO = 0.05
PI_HI = 0.95
OOS_Z = 8.0
COPULA_SHRINK = 15.0
MARGINAL_CRPS_TOL = 1.05
STABILITY_FROB_LIMIT = 0.25

MIN_TRAIN_SUBJECTS = 50
MIN_VAL_SUBJECTS = 20
MIN_TEST_SUBJECTS = 30
MIN_TRAIN_TARGETS = 80
MIN_VAL_TARGETS = 30
MIN_TEST_TARGETS = 30
MIN_TEST_OVERLAP_GROUPS = 10

MIN_JOINT_SUBJECTS = 50
MIN_JOINT_GROUPS = 10
MIN_JOINT_PANELS = 80
MIN_JOINT_OUTCOMES = 2
MIN_PAIRWISE_SUPPORT = 30

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V011_SRC = "src/human_simulator/natural_history_rollout_v011"
V011_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-source-aware-natural-history-stochastic-rollout-v0.1.1"
)
V011_PRIVATE = "private/natural-history-rollout-v011"

FREEZE_MANIFEST = "pre-test-freeze-manifest.json"
FREEZE_SIDECAR = "pre-test-freeze-manifest.json.sha256"
TEST_OPENED_MARKER = "test-opened.json"
TRAIN_VAL_PARQUET = "origins_train_val.parquet"
TEST_PARQUET = "origins_test.parquet"
PANELS_TRAIN_VAL = "panels_train_val.parquet"
PANELS_TEST = "panels_test.parquet"

TS_YEAR_MIN = 1990
TS_YEAR_MAX = 2027

PRIOR_ZIPS: dict[str, tuple[str, str]] = {
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
    "global_split_v011": (
        "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1-review.zip",
        "86643de61303d772b43b7abddf048f0cb42f355dd649c885457dacc43b44a96d",
    ),
    "traj_expansion_v011": (
        "stage-03-source-a-single-outcome-trajectory-expansion-v0.1.1-review.zip",
        "922158a22212aedd903f5a62ea532119465da7cb74faf16326e07c1beaba6c0d",
    ),
}

V011_EXPECTED_MEMBERS = 812
V011_EXPECTED_INDEXED = 811


class TestAccessError(RuntimeError):
    pass


def recursive_n_steps(horizon_days: int) -> int | None:
    if horizon_days <= 0:
        return None
    if horizon_days % RECURSIVE_BASE_INCREMENT_DAYS != 0:
        return None
    return horizon_days // RECURSIVE_BASE_INCREMENT_DAYS


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "NATURAL_HISTORY_ONLY": True,
        "joint_models_source_specific": True,
        "no_a_b_outcome_mixing": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "no_medication_features": True,
        "p1_feature_order": list(P1_FEATURE_ORDER),
        "forbidden_medication_fields": list(FORBIDDEN_MEDICATION_FIELDS),
        "selected_outcomes_a": list(SELECTED_OUTCOMES_A),
        "selected_outcomes_b": list(SELECTED_OUTCOMES_B),
        "requested_absolute_grid_days": list(PREDECLARED_ABSOLUTE_GRID_DAYS),
        "recursive_base_increment_days": RECURSIVE_BASE_INCREMENT_DAYS,
        "target_alignment": "WINDOW_ALIGNED_RECORDED_SOURCE_SPECIFIC_OUTCOME",
        "closest_horizon_unique_assignment": True,
        "actual_label_offset_in_runtime_features": False,
        "TEST_SET_NOVELTY_STATUS": "REUSED_HISTORICAL_HELDOUT_NOT_EXTERNAL_VALIDATION",
        "heldout_requires_quality_gate_not_finite_only": True,
        "path_summary": "path_median",
        "error_growth_limit": ERROR_GROWTH_LIMIT,
        "copula_shrink": COPULA_SHRINK,
        "marginal_crps_tolerance": MARGINAL_CRPS_TOL,
        "seed": SEED,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": "NOT_CONSUMED_NOT_ACCEPTED",
    }
