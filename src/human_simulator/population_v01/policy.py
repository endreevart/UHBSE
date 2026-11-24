"""Canonical Population Completion + Multi-Outcome + Intervention Readiness v0.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1"
)
RUNTIME_DIR = "private/unified-runtime/v0.1-full-population"
BATCH_SIZE = 500
NO_LAB_CAP = 10**9

ACCEPTED_V02_ZIP = (
    "stage-03-source-a-scientific-baseline-v0.2-shadow-transfer-v0.1-review.zip"
)
ACCEPTED_V02_SHA256 = (
    "0c1bc7006f684e79bf80a1e02e03158629d8881e8f7f64226a83539f2f25611b"
)
FROZEN_V02_FILE_SHA = (
    "3f47ad41aa8970c8b2efb2887fc235d55f54acd3136dd874993a00471140efa3"
)
FROZEN_V02_IDENTITY_SHA = (
    "7d79c4a07127e7c1abb9d40114263c8b51ccadef323ca7ffd1679b8a45505610"
)

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "scientific_v02_shadow_v01": (ACCEPTED_V02_ZIP, ACCEPTED_V02_SHA256),
    "unified_v0.1.2.1.1": (
        "stage-03-unified-source-expansion-v0.1.2.1.1-review.zip",
        "5f9d10e1e57ed7423b651a0156714ce976b3ec01f5c85306e929f91f7ccdb997",
    ),
    "unified_v0.1.2.1": (
        "stage-03-unified-source-expansion-v0.1.2.1-review.zip",
        "6f6e906eb8f01e7a6868c4c4eb71857b15670c5ce6db6ce49125a343572cba26",
    ),
    "unified_v0.1.2": (
        "stage-03-unified-source-expansion-v0.1.2-review.zip",
        "55b92ce7b9762114040233be30eaa4705b03e1aa2d378097e21be4ef2258b269",
    ),
    "unified_v0.1.1": (
        "stage-03-unified-source-expansion-v0.1.1-review.zip",
        "d0e8a973ecbbee6e618cf5976d8a688abf23023ccc477710668fed3b16072faa",
    ),
    "unified_v0.1": (
        "stage-03-unified-source-expansion-v0.1-review.zip",
        "bf048ed0b7ecfada1d0cdbd522943437d409cdf8aef4b292418b4682cb1a83be",
    ),
    "core_v0.1.2.1": (
        "stage-03-core-vertical-slice-v0.1.2.1-review.zip",
        "9eea316ccc022e6aed75075b47089b10a1263e55e2c58b9fd6852e8201fe1a5f",
    ),
    "sdr_v0.1.1.1": (
        "stage-03-scientific-data-readiness-v0.1.1.1-review.zip",
        "2b23e48fa9e6687171c60ca371b7aa923d04285e6c3edfe5637cd64060edb67e",
    ),
    "roadmap_v0.1.1": (
        "stage-03-public-roadmap-series-v0.1.1-review.zip",
        "780758ec0c69573611ccf04311f22f28866c7efecb40153e8b47175c913aee30",
    ),
}

SOURCE_A = "magerya_api"
SOURCE_B = "kgz_raw"
SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
L2 = 0.1
BOOTSTRAP_ITERS = 500  # lighter for multi-outcome; documented
SHUFFLE_PERMS = 200
MAX_OOD = 0.35
MIN_PAIRS_FOR_BASELINE = 200
MIN_SUBJECTS_WITH_PAIRS = 100
SHORTLIST_MAX = 8

# Prospective tail thresholds (declared before looking at B results in this stage)
TAIL_ABS_ERR_THRESHOLDS = (1.0, 2.0, 5.0)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "canonical_population_ne_scientific_cohort": True,
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "qsp_status": "NOT_STARTED",
        "pkpd_status": "NOT_STARTED",
        "clinical_validation_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "seed": SEED,
        "l2": L2,
        "max_ood_fraction": MAX_OOD,
        "tail_abs_err_thresholds_prospective": list(TAIL_ABS_ERR_THRESHOLDS),
        "no_identity_merge": True,
        "no_b_tuning": True,
    }
