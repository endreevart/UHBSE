"""Policy — Source A Single-Outcome Trajectory Expansion v0.1.1 (corrective)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER, feature_schema_hash
from human_simulator.scientific.policy import (
    SPLIT_CLASS,
    SPLIT_TEST,
    SPLIT_TRAIN,
    SPLIT_VAL,
)
from human_simulator.scientific_v02.policy import BOOTSTRAP_ITERS, L2, SEED, SHUFFLE_PERMS

VERSION = "0.1.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-single-outcome-trajectory-expansion-v0.1.1"
)
RUNTIME_DIR = "private/trajectory-expansion-v011"
REVIEW_ZIP = (
    "stage-03-source-a-single-outcome-trajectory-expansion-v0.1.1-review.zip"
)

ACCEPTED_V01_ZIP = (
    "stage-03-source-a-single-outcome-trajectory-expansion-v0.1-review.zip"
)
ACCEPTED_V01_SHA256 = (
    "ef3e53c3732691ac371599dfbd3181d317d74b6c1663cec76a40ee34e5373602"
)
ACCEPTED_V01_MEMBERS = 141
ACCEPTED_V01_INDEXED = 140
ACCEPTED_V01_ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-single-outcome-trajectory-expansion-v0.1"
)
ACCEPTED_V01_RUNTIME_DIR = "private/trajectory-expansion-v01"

THRESHOLD_OPTIONS_PATH = "private/post-pilot-audit-v01/threshold-options.json"
INVENTORY_PATH = "private/post-pilot-audit-v01/source-a-longitudinal-inventory.json"
PRIMARY_THRESHOLD_PROFILE = "conservative"
EXPECTED_REGISTRY_COUNT_V01 = 104

PILOT_ZIP = (
    "stage-03-first-concept-bounded-technical-medication-pilot-v0.1-review.zip"
)
PILOT_ZIP_SHA256 = (
    "aba265d5a4d6f01560b02c3e3fa68d827aba9bd3e1e594d4974d53d4bef8c7b9"
)

BOOTSTRAP_ITERS_EXPANSION = 500
SHUFFLE_PERMS_EXPANSION = 100
ACCEPTED_BOOTSTRAP_ITERS = BOOTSTRAP_ITERS
ACCEPTED_SHUFFLE_PERMS = SHUFFLE_PERMS
NOMINAL_COVERAGE = 0.90
OOD_FRACTION_THRESHOLD = 0.10

FORBIDDEN_PUBLIC_KEYS = (
    "opaque_subject_key",
    "pair_id",
    "component_id",
    "observation_id",
    "y_t0",
    "y_t1",
    "t0",
    "t1",
)

SOURCE_A_SYSTEM_ID = "magerya_api"

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"

METHODOLOGY_PIN: dict[str, Any] = {
    "source_paths": [
        "src/human_simulator/scientific/models.py",
        "src/human_simulator/scientific/dataset.py",
        "src/human_simulator/scientific/splits.py",
        "src/human_simulator/scientific_v02/policy.py",
        "src/human_simulator/scientific_v02/train.py",
        "src/human_simulator/scientific_v02/evaluate.py",
        "src/human_simulator/scientific_v02/uncertainty.py",
        "src/human_simulator/scientific_v02/applicability.py",
    ],
    "seed": SEED,
    "l2": L2,
    "feature_order": list(FEATURE_ORDER),
    "feature_schema_hash": feature_schema_hash(),
    "split_class": SPLIT_CLASS,
    "split_fractions": {
        "train": SPLIT_TRAIN,
        "validation": SPLIT_VAL,
        "test": SPLIT_TEST,
    },
    "pair_definition": "strict_consecutive_neighbors_only",
    "preprocessing": "standardize_fit_train_only",
    "bootstrap_iters_accepted_scientific_v02": ACCEPTED_BOOTSTRAP_ITERS,
    "shuffle_perms_accepted_scientific_v02": ACCEPTED_SHUFFLE_PERMS,
    "bootstrap_iters": BOOTSTRAP_ITERS_EXPANSION,
    "shuffle_perms": SHUFFLE_PERMS_EXPANSION,
    "monte_carlo_note": (
        "Same bootstrap/permutation algorithms as scientific_v02; "
        "iteration counts reduced for multi-grain tractability and recorded here."
    ),
    "residual_calibration": "active_provider_validation_residuals",
    "uncertainty_method": "active_provider_validation_residual_interval",
    "nominal_coverage": NOMINAL_COVERAGE,
    "corrective_vs_v01": (
        "v0.1 published Ridge intervals even when active_provider=persistence; "
        "v0.1.1 binds intervals to the active provider."
    ),
}


def threshold_options_sha256(root: Path) -> str:
    return hashlib.sha256((root / THRESHOLD_OPTIONS_PATH).read_bytes()).hexdigest()


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "corrective_release_over": "v0.1",
        "accepted_v01_sha256": ACCEPTED_V01_SHA256,
        "primary_threshold_profile": PRIMARY_THRESHOLD_PROFILE,
        "scope": "single-outcome-trajectory-expansion-v0.1.1_only",
        "global_policy_changed": False,
        "medication_gates_changed": False,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "methodology_pin": METHODOLOGY_PIN,
        "split_class": SPLIT_CLASS,
        "seed": SEED,
        "l2": L2,
        "feature_order": list(FEATURE_ORDER),
        "feature_schema_hash": feature_schema_hash(),
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
    }
