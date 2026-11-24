"""Policy — First Source-Aware Medication Residual Foundation v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1"
)
RUNTIME_DIR = "private/medication-residual-v01"
LANDMARK_DIR = "private/medication-residual-v01/landmarks"
MODELS_DIR = "private/medication-residual-v01/models"
REVIEW_ZIP = (
    "stage-03-first-source-aware-medication-residual-foundation-v0.1-review.zip"
)

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "medication-residual-v01"
L2 = 0.01
N_BOOTSTRAP = 200
N_PERMUTATION = 200
N_VAL_FOLDS = 5
HASH_DIMS = (32, 64, 128, 256)
HASH_SENSITIVITY_DIM = 64
HASH_SEED = 42
MIN_VOCAB_TRAIN_COUNT = 3
MAX_VOCAB = 256
POLYPHARMACY_MIN = 2

MIN_UNIQUE_SUBJECTS = 100
MIN_UNIQUE_RESIDUAL_TARGETS = 300
MIN_TEST_SUBJECTS = 30
MIN_TRAIN_SUBJECTS = 80
MIN_VAL_SUBJECTS = 20
MIN_TRAIN_TARGETS_PER_CELL = 80
MIN_VAL_TARGETS_PER_CELL = 30

TS_YEAR_MIN = 1990
TS_YEAR_MAX = 2027
PREDECLARED_HORIZONS_DAYS = (30, 90, 180, 365)
TARGET_WINDOW_OPEN = "left_open_right_closed"  # (t0, t0+H]
TIMESTAMP_SEMANTICS = "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP"
MEDICATION_RECORD_CLASS = "RECORDED_MEDICATION_CONTEXT"
ADMINISTRATION_CLAIM = "NOT_CLAIMED"

HUMAN_REJECTED_SOURCE_MEDICINE_IDS = ("31", "48", "405", "449", "510", "810")
HISTORICAL_EXACT_NOT_SCIENTIFICALLY_USABLE = "813"
HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT = 0
SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT = 0

EPISODE_JSONL = (
    "private/intervention-association-v01/episodes/"
    "episodes_appointment_date_h365.jsonl"
)
EPISODE_EXPANSION_PIN = 202374
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
V0111_STATES_DIR = "private/unified-individual-state-v0111/states"
V0111_OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
V0111_MODELS_DIR = "private/unified-individual-state-v0111/models"
CSR_ENCODER = "private/current-state-representation-v01/models/frozen-encoder.json"
LEP_V0211_SRC = "src/human_simulator/longitudinal_event_probability_v0211"
LEP_V0211_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-longitudinal-event-probability-foundation-v0.2.1.1"
)

FREEZE_MANIFEST = "pre-test-freeze-manifest.json"
TEST_OPENED_MARKER = "test-opened.json"
TRAIN_VAL_PARQUET = "residual_train_val.parquet"
TEST_PARQUET = "residual_test.parquet"

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
SOURCE_A_LABEL = "A"
SOURCE_B_LABEL = "B"

# Predeclared Source A outcome×unit keys from UIS v0.1.1.1 (structure only).
PREDECLARED_OUTCOME_KEYS_A = (
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

R1_FEATURE_ORDER = [
    "persistence_value",
    "n_prior_outcome_measurements",
    "days_since_previous_outcome",
    "days_since_previous_missing",
    "prior_delta",
    "prior_delta_missing",
    "requested_horizon_days",
    "n_obs_before",
    "n_events_before",
    "n_encounters_before",
    "longitudinal_age_days",
    "source_is_a",
    "missingness_lab",
]

R2COUNT_EXTRA = [
    "concurrent_count",
    "polypharmacy",
    "n_prior_recorded_medication_events",
    "days_since_last_prior_med",
    "days_since_last_prior_med_missing",
]

FORBIDDEN_R1_MEDICATION_FIELDS = (
    "n_medications_before",
    "has_med_history",
    "concurrent_count",
    "polypharmacy",
    "medicine_id",
    "medicine_ref_id",
)

NH_PROVIDER_ID = "M0_LAST_VALUE_CARRY_FORWARD"
NH_PROVIDER_METHOD = "last_value_at_or_before_t0_medication_free"

UPSTREAM_PROBABILITY_CONSUMPTION_STATUS = (
    "NOT_USED_FOR_MEDICATION_RESIDUAL_DUE_TO_HELDOUT_LIMITATION"
)

PRIOR_ZIPS: dict[str, tuple[str, str]] = {
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
    "concept_pilot_v01": (
        "stage-03-first-concept-bounded-technical-medication-pilot-v0.1-review.zip",
        "aba265d5a4d6f01560b02c3e3fa68d827aba9bd3e1e594d4974d53d4bef8c7b9",
    ),
    "medication_association_v011": (
        "stage-03-first-medication-association-baseline-v0.1.1-review.zip",
        "7c2d1bc1fcf3a96130bc2a8cf944850a88f5727ee7f3be43fca969fa1dcaa963",
    ),
    "medication_knowledge_v01": (
        "stage-03-medication-knowledge-representation-v0.1-review.zip",
        "ae0943317facef424097f3784274192ae379aa1add33ab78653dc1811542ca3c",
    ),
    "medication_concept_v01": (
        "stage-03-medication-concept-harmonization-categorical-baseline-v0.1-review.zip",
        "be8b24391bcdc21dcef215e0de157fdcb06216b7dafd19e45dafac84adf82982",
    ),
    "lep_v021": (
        "stage-03-unified-longitudinal-event-probability-foundation-v0.2.1-review.zip",
        "d0036ecacb52a4e622cf363e9acea27ffadf0163300c596b9fcf2a7bfa2e90dd",
    ),
}


class TestAccessError(RuntimeError):
    pass


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "appointment_date_semantics": TIMESTAMP_SEMANTICS,
        "medication_record_class": MEDICATION_RECORD_CLASS,
        "administration_claim": ADMINISTRATION_CLAIM,
        "HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT": HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT,
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT": (
            SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT
        ),
        "HUMAN_REJECTED_SOURCE_MEDICINE_IDS": list(HUMAN_REJECTED_SOURCE_MEDICINE_IDS),
        "historical_exact_813_not_scientifically_usable": True,
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "no_source_b_medication_transfer": True,
        "no_ordinal_medication_encoding": True,
        "no_state_encoder_retrain": True,
        "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
        "no_intervention_response": True,
        "no_treatment_effect": True,
        "no_causal_effect": True,
        "no_qsp": True,
        "no_pkpd": True,
        "no_identity_merge": True,
        "no_new_a_b_semantic_mappings": True,
        "predeclared_horizons_days": list(PREDECLARED_HORIZONS_DAYS),
        "target_window": TARGET_WINDOW_OPEN,
        "gates": {
            "min_unique_subjects": MIN_UNIQUE_SUBJECTS,
            "min_unique_residual_targets": MIN_UNIQUE_RESIDUAL_TARGETS,
            "min_test_subjects": MIN_TEST_SUBJECTS,
            "min_val_subjects": MIN_VAL_SUBJECTS,
        },
        "authoritative_comparisons": ["R1_vs_R2COUNT", "R1_vs_R2ID"],
        "R2HASH_status": "SENSITIVITY_ONLY",
        "R2SEM_status": "NOT_RUN_NO_SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPTS",
        "UPSTREAM_PROBABILITY_CONSUMPTION_STATUS": (
            UPSTREAM_PROBABILITY_CONSUMPTION_STATUS
        ),
        "no_v02112_republication": True,
        "seed": SEED,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "r1_feature_order": list(R1_FEATURE_ORDER),
        "r2count_extra": list(R2COUNT_EXTRA),
        "nh_provider_id": NH_PROVIDER_ID,
        "episode_expansion_pin_is_not_administrations": True,
        "episode_expansion_pin": EPISODE_EXPANSION_PIN,
    }
