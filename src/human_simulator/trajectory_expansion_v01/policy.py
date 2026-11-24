"""Policy — Source A Single-Outcome Trajectory Expansion v0.1."""

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
from human_simulator.scientific_v02.policy import (
    BOOTSTRAP_ITERS,
    L2,
    SEED,
    SHUFFLE_PERMS,
)

# Expansion-scale Monte Carlo (same algorithms as scientific_v02; iteration counts
# recorded here for multi-grain tractability — not HPO, not test-tuned).
BOOTSTRAP_ITERS_EXPANSION = 500
SHUFFLE_PERMS_EXPANSION = 100
ACCEPTED_BOOTSTRAP_ITERS = BOOTSTRAP_ITERS
ACCEPTED_SHUFFLE_PERMS = SHUFFLE_PERMS


VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-source-a-single-outcome-trajectory-expansion-v0.1"
)
RUNTIME_DIR = "private/trajectory-expansion-v01"
REVIEW_ZIP = (
    "stage-03-source-a-single-outcome-trajectory-expansion-v0.1-review.zip"
)

THRESHOLD_OPTIONS_PATH = "private/post-pilot-audit-v01/threshold-options.json"
INVENTORY_PATH = (
    "private/post-pilot-audit-v01/source-a-longitudinal-inventory.json"
)
PRIMARY_THRESHOLD_PROFILE = "conservative"
EXPECTED_GRAIN_COUNT = 104

PILOT_ZIP = (
    "stage-03-first-concept-bounded-technical-medication-pilot-v0.1-review.zip"
)
PILOT_ZIP_SHA256 = (
    "aba265d5a4d6f01560b02c3e3fa68d827aba9bd3e1e594d4974d53d4bef8c7b9"
)

# Methodology pin — authoritative values from scientific / scientific_v02 code
METHODOLOGY_PIN = {
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
        "iteration counts reduced for 104-grain tractability and recorded here."
    ),
    "residual_std_calibrated_on": "validation",
}

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SOURCE_A_SYSTEM_ID = "magerya_api"


def threshold_options_sha256(root: Path) -> str:
    return hashlib.sha256((root / THRESHOLD_OPTIONS_PATH).read_bytes()).hexdigest()


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "PRIMARY_THRESHOLD_PROFILE": PRIMARY_THRESHOLD_PROFILE,
        "EXPECTED_GRAIN_COUNT": EXPECTED_GRAIN_COUNT,
        "global_policy_changed": False,
        "medication_gates_changed": False,
        "methodology_pin": METHODOLOGY_PIN,
        "MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "no_medication_features": True,
        "no_hpo": True,
        "seed": SEED,
        "l2": L2,
    }
