"""Policy — Natural-History Stochastic Rollout Foundation v0.1.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-unified-source-aware-natural-history-stochastic-rollout-v0.1.1"
)
RUNTIME_DIR = "private/natural-history-rollout-v011"
SEQ_DIR = "private/natural-history-rollout-v011/sequences"
MODELS_DIR = "private/natural-history-rollout-v011/models"
REVIEW_ZIP = (
    "stage-03-unified-source-aware-natural-history-stochastic-rollout-v0.1.1-review.zip"
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "natural-history-rollout-v011"
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

MIN_TRAIN_SUBJECTS = 50
MIN_VAL_SUBJECTS = 20
MIN_TEST_SUBJECTS = 30
MIN_TRAIN_TARGETS = 80
MIN_VAL_TARGETS = 30
MIN_TEST_TARGETS = 30
MIN_TEST_OVERLAP_GROUPS = 10

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V0111_MODELS_DIR = "private/unified-individual-state-v0111/models"
V01_SRC = "src/human_simulator/natural_history_rollout_v01"
V01_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-source-aware-natural-history-stochastic-rollout-v0.1"
)
V01_PRIVATE_MODELS = "private/natural-history-rollout-v01/models"

FREEZE_MANIFEST = "pre-test-freeze-manifest.json"
FREEZE_SIDECAR = "pre-test-freeze-manifest.json.sha256"
TEST_OPENED_MARKER = "test-opened.json"
TRAIN_VAL_PARQUET = "origins_train_val.parquet"
TEST_PARQUET = "origins_test.parquet"

TS_YEAR_MIN = 1990
TS_YEAR_MAX = 2027

P1_FEATURE_ORDER = [
    "persistence_value",
    "n_prior_outcome_measurements",
    "days_since_previous",
    "days_since_previous_missing",
    "prior_delta",
    "prior_delta_missing",
    "requested_horizon_days",
    "history_depth",
    "missingness",
]
FORBIDDEN_MEDICATION_FIELDS = (
    "n_medications_before",
    "has_med_history",
    "concurrent_count",
    "polypharmacy",
    "medicine_id",
    "medicine_ref_id",
)

SELECTED_OUTCOMES_A = (
    "A::Лимфоциты::%",
    "A::Моноциты::%",
    "A::Эозинофилы::%",
    "A::Нейтрофилы::%",
    "A::Базофилы::%",
    "A::Общий белок::г/л",
    "A::Лейкоциты::*10^9/л",
    "A::Эритроциты::*10^12/л",
    "A::Тромбоциты::*10^9/л",
    "A::Железо::мкмоль/л",
    "A::25(OH)витамин D::нг/мл",
    "A::Гемоглобин::г/л",
)
SELECTED_OUTCOMES_B = (
    "B::mm_1004::%",
    "B::33::ммоль/л",
    "B::30::ммоль/л",
    "B::28::г/л",
    "B::mm_1002::%",
    "B::48::мкмоль/л",
    "B::16::ммоль/л",
    "B::8::Ед/л",
    "B::9::Ед/л",
    "B::32::ммоль/л",
    "B::928::нг/мл",
    "B::55::пмоль/л",
)

PRIOR_ZIPS: dict[str, tuple[str, str]] = {
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

V01_EXPECTED_MEMBERS = 792
V01_EXPECTED_INDEXED = 791


class TestAccessError(RuntimeError):
    pass


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "NATURAL_HISTORY_ONLY": True,
        "grain_definition": "source_system x outcome x original_unit",
        "cell_definition": "grain x requested_horizon",
        "n_selected_grains": len(SELECTED_OUTCOMES_A) + len(SELECTED_OUTCOMES_B),
        "n_selected_cells": (
            len(SELECTED_OUTCOMES_A) + len(SELECTED_OUTCOMES_B)
        )
        * len(PREDECLARED_ABSOLUTE_GRID_DAYS),
        "requested_absolute_grid_days": list(PREDECLARED_ABSOLUTE_GRID_DAYS),
        "recursive_base_increment_days": RECURSIVE_BASE_INCREMENT_DAYS,
        "endpoint_identity": "t0_plus_requested_absolute_horizon",
        "target_label": "RECORDED_SOURCE_SPECIFIC_OUTCOME_AT_REQUESTED_HORIZON",
        "future_schedule_as_model_input": False,
        "p1_feature_order": list(P1_FEATURE_ORDER),
        "no_medication_features": True,
        "no_a_b_provider_transfer": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "no_rejected_encoder": True,
        "MULTI_OUTCOME_DEPENDENCE_STATUS": "MARGINAL_ONLY_NO_JOINT_MODEL",
        "heldout_requires_quality_gate_not_finite_only": True,
        "teacher_forced_cannot_determine_recursive_acceptance": True,
        "seed": SEED,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
        "min_test_subjects": MIN_TEST_SUBJECTS,
        "min_test_targets": MIN_TEST_TARGETS,
        "min_test_overlap_groups": MIN_TEST_OVERLAP_GROUPS,
        "coverage_range": [COVERAGE_LO, COVERAGE_HI],
        "error_growth_limit": ERROR_GROWTH_LIMIT,
    }


def recursive_n_steps(horizon_days: int) -> int | None:
    if horizon_days <= 0:
        return None
    if horizon_days % RECURSIVE_BASE_INCREMENT_DAYS != 0:
        return None
    return horizon_days // RECURSIVE_BASE_INCREMENT_DAYS
