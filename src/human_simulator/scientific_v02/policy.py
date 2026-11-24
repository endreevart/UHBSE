"""Source A Scientific Baseline v0.2 + shared artifact policy."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import FEATURE_ORDER as _FO

VERSION = "0.2"
SHADOW_VERSION = "0.1"
ARTIFACT_DIR = "artifacts/stage-03-source-a-scientific-baseline-v0.2-shadow-transfer-v0.1"
SEED = 42
L2 = 0.1
BOOTSTRAP_ITERS = 2000
SHUFFLE_PERMS = 500
MAX_OOD_FRACTION = 0.35  # declared before shadow metrics

FIXED_OUTCOME_CANDIDATE_ID = "2685c68a3e247ca4"
FIXED_OUTCOME_LABEL = "Т3 св."
FIXED_OUTCOME_UNIT = "пмоль/л"
SOURCE_A_SYSTEM_ID = "magerya_api"
SOURCE_B_SYSTEM_ID = "kgz_raw"
PREFERRED_B_CODE = "53"
PREFERRED_B_UNIT = "пмоль/л"

FEATURE_ORDER = _FO

ACCEPTED_UNIFIED_V01211_ZIP = "stage-03-unified-source-expansion-v0.1.2.1.1-review.zip"
ACCEPTED_UNIFIED_V01211_SHA256 = (
    "5f9d10e1e57ed7423b651a0156714ce976b3ec01f5c85306e929f91f7ccdb997"
)
ACCEPTED_UNIFIED_V01211_MEMBERS = 291
ACCEPTED_UNIFIED_V01211_INDEXED = 290

PRIOR_IMMUTABLE_ZIPS: dict[str, tuple[str, str]] = {
    "unified_v0.1.2.1.1": (ACCEPTED_UNIFIED_V01211_ZIP, ACCEPTED_UNIFIED_V01211_SHA256),
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

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
CLINICAL_VALIDATION_STATUS = "NOT_STARTED"
INTERVENTION_RESPONSE_MODEL_STATUS = "NOT_STARTED"
TREATMENT_EFFECT_STATUS = "NOT_EVALUATED"
PRODUCTION_READINESS = "NOT_CLAIMED"
DOMAIN_REVIEW_REQUIRED = "DOMAIN_REVIEW_REQUIRED"
DOMAIN_REVIEW_PENDING = "DOMAIN_REVIEW_PENDING"

TECHNICAL_SHADOW_TRANSFER_EXECUTED = "TECHNICAL_SHADOW_TRANSFER_EXECUTED"
TECHNICAL_SHADOW_TRANSFER_EXECUTED_OUTSIDE_APPLICABILITY = (
    "TECHNICAL_SHADOW_TRANSFER_EXECUTED_OUTSIDE_APPLICABILITY"
)
TECHNICAL_SHADOW_TRANSFER_FAILED = "TECHNICAL_SHADOW_TRANSFER_FAILED"
TECHNICAL_SHADOW_TRANSFER_NOT_RUN = "TECHNICAL_SHADOW_TRANSFER_NOT_RUN_ENGINEERING_GATE"
SCIENTIFIC_CROSS_SOURCE_TRANSFER_NOT_RUN = "NOT_RUN_DOMAIN_REVIEW_REQUIRED"
INDEPENDENCE_NOT_ESTABLISHED = "INDEPENDENCE_NOT_ESTABLISHED"


def policy_snapshot() -> dict[str, Any]:
    return {
        "scientific_baseline_version": VERSION,
        "shadow_transfer_version": SHADOW_VERSION,
        "seed": SEED,
        "l2": L2,
        "bootstrap_iters": BOOTSTRAP_ITERS,
        "shuffle_perms": SHUFFLE_PERMS,
        "max_ood_fraction": MAX_OOD_FRACTION,
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "fixed_outcome_label": FIXED_OUTCOME_LABEL,
        "fixed_outcome_unit": FIXED_OUTCOME_UNIT,
        "feature_order": list(FEATURE_ORDER),
        "source_a_system_id": SOURCE_A_SYSTEM_ID,
        "source_b_system_id": SOURCE_B_SYSTEM_ID,
        "preferred_b_code": PREFERRED_B_CODE,
        "preferred_b_unit": PREFERRED_B_UNIT,
        "security_stage_status": SECURITY_STAGE_STATUS,
        "clinical_validation_status": CLINICAL_VALIDATION_STATUS,
        "intervention_response_model_status": INTERVENTION_RESPONSE_MODEL_STATUS,
        "treatment_effect_status": TREATMENT_EFFECT_STATUS,
        "production_readiness": PRODUCTION_READINESS,
        "accepted_unified_v01211_sha256": ACCEPTED_UNIFIED_V01211_SHA256,
        "no_b_tuning": True,
        "no_raw_writes": True,
        "no_canonical_writes": True,
    }
