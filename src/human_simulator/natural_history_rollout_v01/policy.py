"""Policy — Unified Source-Aware Natural-History Stochastic Rollout Foundation v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-unified-source-aware-natural-history-stochastic-rollout-v0.1"
)
RUNTIME_DIR = "private/natural-history-rollout-v01"
SEQ_DIR = "private/natural-history-rollout-v01/sequences"
MODELS_DIR = "private/natural-history-rollout-v01/models"
REVIEW_ZIP = (
    "stage-03-unified-source-aware-natural-history-stochastic-rollout-v0.1-review.zip"
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "natural-history-rollout-v01"
L2 = 0.1
N_BOOTSTRAP = 100
N_PATHS_DEFAULT = 16
MAX_STEPS = 4
PREDECLARED_HORIZONS_DAYS = (30, 90, 180, 365)
ERROR_GROWTH_LIMIT = 3.0
COVERAGE_LO = 0.50
COVERAGE_HI = 0.99
PI_LO = 0.05
PI_HI = 0.95
OOS_Z = 8.0
HORIZON_BIN_REL_TOL = 0.5

MIN_TRAIN_SUBJECTS = 50
MIN_VAL_SUBJECTS = 20
MIN_TEST_SUBJECTS = 30
MIN_TRAIN_TRANSITIONS = 80
MIN_VAL_TRANSITIONS = 30

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V0111_MODELS_DIR = "private/unified-individual-state-v0111/models"
CSR_ENCODER = "private/current-state-representation-v01/models/frozen-encoder.json"
MEDRES_SRC = "src/human_simulator/medication_residual_v01"
MEDRES_ARTIFACT_DIR = (
    "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1"
)
LEP_V0211_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2.1.1"
)

FREEZE_MANIFEST = "pre-test-freeze-manifest.json"
TEST_OPENED_MARKER = "test-opened.json"
TRAIN_VAL_PARQUET = "sequences_train_val.parquet"
TEST_PARQUET = "sequences_test.parquet"

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


class TestAccessError(RuntimeError):
    pass


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "NATURAL_HISTORY_ONLY": True,
        "no_medication_effects": True,
        "no_medication_residual_consumption": True,
        "no_a_b_provider_transfer": True,
        "no_unit_conversion": True,
        "no_identity_merge": True,
        "no_rejected_encoder": True,
        "no_joint_neural_model": True,
        "MULTI_OUTCOME_DEPENDENCE_STATUS": "MARGINAL_ONLY_NO_JOINT_MODEL",
        "predeclared_horizons_days": list(PREDECLARED_HORIZONS_DAYS),
        "max_steps": MAX_STEPS,
        "error_growth_limit": ERROR_GROWTH_LIMIT,
        "coverage_range": [COVERAGE_LO, COVERAGE_HI],
        "p1_feature_order": list(P1_FEATURE_ORDER),
        "seed": SEED,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
        "OBSERVATION_PROCESS_SCHEDULER_STATUS": (
            "TECHNICAL_OPTIONAL_WITH_UPSTREAM_LIMITATION"
        ),
        "PRIOR_MEDICATION_RESIDUAL_FOUNDATION_STATUS": (
            "NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL_FOR_EVALUATED_CONSTRUCTION"
        ),
    }
