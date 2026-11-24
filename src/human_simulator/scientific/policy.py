"""Scientific Data Readiness v0.1.1.1 — uncertainty + shuffle evidence correction."""

from __future__ import annotations

from statistics import NormalDist
from typing import Any

SCIENTIFIC_VERSION = "0.1.1.1"
ARTIFACT_DIR = "artifacts/stage-03-scientific-data-readiness-v0.1.1.1"
RUNTIME_DIR = "private/scientific-runtime/v0.1.1.1"
SEED = 42

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SECURITY_FINDINGS_STATUS = "RECORDED_NON_BLOCKING"
SECURITY_GATE_MODE = "ADVISORY_ONLY"
CLINICAL_VALIDATION_STATUS = "NOT_STARTED"
INTERVENTION_RESPONSE_MODEL_STATUS = "NOT_STARTED"
PRODUCTION_READINESS = "NOT_CLAIMED"

ACCEPTED_CORE_V0121_ZIP = "stage-03-core-vertical-slice-v0.1.2.1-review.zip"
ACCEPTED_CORE_V0121_SHA256 = (
    "9eea316ccc022e6aed75075b47089b10a1263e55e2c58b9fd6852e8201fe1a5f"
)
ACCEPTED_SDR_V01_ZIP = "stage-03-scientific-data-readiness-v0.1-review.zip"
ACCEPTED_SDR_V01_SHA256 = (
    "023e8e2b4ad90d966cd792ab44d1fb6b9ace5557ec432e7021e7897eb74fd6fd"
)
ACCEPTED_SDR_V011_ZIP = "stage-03-scientific-data-readiness-v0.1.1-review.zip"
ACCEPTED_SDR_V011_SHA256 = (
    "3db322611437e69be5249a150b4519da50ad11657b67a3e524f7cc3bd7dc1e07"
)

MIN_SUBJECTS_WITH_REPEAT = 15
MIN_CONSECUTIVE_PAIRS = 20
MIN_NUMERIC_PARSE_RATE = 0.90
MIN_UNIT_DOMINANCE = 0.70
MIN_INDEPENDENT_SUBJECTS_FOR_SPLIT = 12
MIN_TEST_SUBJECTS_FOR_INCREMENTAL = 5
MIN_VAL_FOR_INTERVAL_CONSTRUCTION = 10
MIN_TEST_SUBJECTS_FOR_UNCERTAINTY_CALIBRATION = 10
MIN_TEST_PAIRS_FOR_UNCERTAINTY_CALIBRATION = 10
NOMINAL_COVERAGE = 0.90
N_LABEL_PERMUTATIONS = 20

SPLIT_TRAIN = 0.70
SPLIT_VAL = 0.15
SPLIT_TEST = 0.15
SPLIT_CLASS = "EXPLORATORY_SUBJECT_DISJOINT_SPLIT"

FORBIDDEN_MODEL_LABELS = (
    "intervention-response",
    "intervention_response",
    "treatment effect",
    "clinical validated",
    "clinically validated",
    "production ready",
)

PRIOR_IMMUTABLE_ZIPS = {
    "core_v0.1": (
        "stage-03-core-vertical-slice-v0.1-review.zip",
        "933c34bee1f03af9e22c54be2fb5aa4022228bb7353a35ad2f7e93d3793cb67c",
    ),
    "core_v0.1.1": (
        "stage-03-core-vertical-slice-v0.1.1-review.zip",
        "13fbf307fd03eb8ed419a800ff7fed254a8159240482e8ac4b28b5f391941128",
    ),
    "core_v0.1.2": (
        "stage-03-core-vertical-slice-v0.1.2-review.zip",
        "d4218dda05cdf8657e03768ce81727e274a691e90abee3ff701bae1018f419f8",
    ),
    "core_v0.1.2.1": (ACCEPTED_CORE_V0121_ZIP, ACCEPTED_CORE_V0121_SHA256),
    "sdr_v0.1": (ACCEPTED_SDR_V01_ZIP, ACCEPTED_SDR_V01_SHA256),
    "sdr_v0.1.1": (ACCEPTED_SDR_V011_ZIP, ACCEPTED_SDR_V011_SHA256),
}


def gaussian_interval_multiplier(nominal_coverage: float) -> float:
    """Z for equal-tailed Gaussian interval at nominal coverage (e.g. 0.90 → ~1.64485)."""
    if not 0.0 < nominal_coverage < 1.0:
        raise ValueError("nominal_coverage must be in (0, 1)")
    return float(NormalDist().inv_cdf((1.0 + nominal_coverage) / 2.0))


def policy_snapshot() -> dict[str, Any]:
    return {
        "scientific_version": SCIENTIFIC_VERSION,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "security_findings_status": SECURITY_FINDINGS_STATUS,
        "security_gate_mode": SECURITY_GATE_MODE,
        "security_blocks_core": False,
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "accepted_core_baseline_sha256": ACCEPTED_CORE_V0121_SHA256,
        "accepted_sdr_v01_sha256": ACCEPTED_SDR_V01_SHA256,
        "accepted_sdr_v011_sha256": ACCEPTED_SDR_V011_SHA256,
        "split_class": SPLIT_CLASS,
        "pair_definition": "strict_consecutive_neighbors_only",
        "nominal_coverage": NOMINAL_COVERAGE,
        "gaussian_interval_multiplier": gaussian_interval_multiplier(NOMINAL_COVERAGE),
    }
