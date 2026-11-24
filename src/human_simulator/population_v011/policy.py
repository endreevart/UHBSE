"""Canonical Population / Multi-Outcome / Intervention Readiness v0.1.1."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1.1"
)
RUNTIME_DIR = "private/unified-runtime/v0.1.1"

ACCEPTED_V01_ZIP = (
    "stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1-review.zip"
)
ACCEPTED_V01_SHA256 = (
    "58c6b6d6a13b6da17da4eee3cbe1840b91228deed869b74ca4138ef7ef98af1f"
)
ACCEPTED_V01_MEMBERS = 340
ACCEPTED_V01_INDEXED = 339

ACCEPTED_V02_ZIP = (
    "stage-03-source-a-scientific-baseline-v0.2-shadow-transfer-v0.1-review.zip"
)
ACCEPTED_V02_SHA256 = (
    "0c1bc7006f684e79bf80a1e02e03158629d8881e8f7f64226a83539f2f25611b"
)

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "population_v0.1": (ACCEPTED_V01_ZIP, ACCEPTED_V01_SHA256),
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
TAIL_ABS_ERR_THRESHOLDS = (1.0, 2.0, 5.0)

# Predeclared Level-5 modeling cohort gates (before reading test performance)
MIN_LEVEL5_SUBJECTS = 200
MIN_LEVEL5_EPISODES = 500
MIN_TEST_SUBJECTS = 50
MIN_TEST_EPISODES = 100

V01_ARTIFACT_DIR = (
    "artifacts/stage-03-canonical-population-multi-outcome-intervention-readiness-v0.1"
)


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "clinical_validation_status": "NOT_STARTED",
        "qsp_status": "NOT_STARTED",
        "pkpd_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "causal_interpretation_allowed": False,
        "treatment_effect_estimated": False,
        "clinical_response_claimed": False,
        "no_identity_merge": True,
        "no_b_tuning": True,
        "seed": SEED,
        "l2": L2,
        "tail_abs_err_thresholds_prospective": list(TAIL_ABS_ERR_THRESHOLDS),
        "level5_gates": {
            "min_subjects": MIN_LEVEL5_SUBJECTS,
            "min_episodes": MIN_LEVEL5_EPISODES,
            "min_test_subjects": MIN_TEST_SUBJECTS,
            "min_test_episodes": MIN_TEST_EPISODES,
        },
    }
