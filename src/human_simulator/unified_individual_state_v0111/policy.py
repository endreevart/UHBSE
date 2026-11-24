"""Policy — Individual State Baseline v0.1.1.1 corrective."""

from __future__ import annotations

from typing import Any

VERSION = "0.1.1.1"
ARTIFACT_DIR = (
    "artifacts/stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1"
)
RUNTIME_DIR = "private/unified-individual-state-v0111"
STATES_DIR = "private/unified-individual-state-v0111/states"
OVERLAP_DIR = "private/unified-individual-state-v0111/overlap"
MODELS_DIR = "private/unified-individual-state-v0111/models"
REVIEW_ZIP = (
    "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1-review.zip"
)

# Immutable prior — published v0.1.1
ACCEPTED_V011_UIS_ZIP = (
    "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1-review.zip"
)
ACCEPTED_V011_UIS_SHA256 = (
    "b1ae73f6f2b971be904a853f32c378352e61f0122712dbcb4810e0090abb2f57"
)
ACCEPTED_V011_UIS_MEMBERS = 665
ACCEPTED_V011_UIS_INDEXED = 664
ACCEPTED_V011_UIS_ARTIFACT_DIR = (
    "artifacts/stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1"
)

# Prior v0.1 and v0.3.1
ACCEPTED_V01_UIS_ZIP = (
    "stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1-review.zip"
)
ACCEPTED_V01_UIS_SHA256 = (
    "751f63eea364424ba50cc5c6cbde2104a511b3e829eff85360bca9a5e5b0c1a3"
)
ACCEPTED_V031_ZIP = (
    "stage-03-unified-a-b-materialized-research-layer-v0.3.1-review.zip"
)
ACCEPTED_V031_SHA256 = (
    "ccf2627c10b472e10591f54c528170ad1e98ae259ecdf97e2d0b3c85722f54e9"
)
V031_MATERIALIZED_DIR = "private/unified-research-layer-v031/materialized"
V011_OVERLAP_DIR = "private/unified-individual-state-v011/overlap"
V011_RUNTIME = "private/unified-individual-state-v011"

STAGE02_LINKAGE_ASSESSMENT = "artifacts/stage-02/identity-linkage-assessment.json"
PRIOR_CONFIRMED_PAIRS = 22
PRIOR_CANDIDATE_OVERLAP = 2274
PRIOR_AMBIGUOUS = 133
PRIOR_CONFLICTING = 21
LIVE_V011_CONFIRMED = 20
LIVE_V011_CANDIDATE = 2234
LIVE_V011_GROUPS = 2254

SECURITY_STAGE_STATUS = "PAUSED_NOT_ACCEPTED_BY_OWNER"
SEED = 42
NAMESPACE = "unified-a-b-individual-state-v0111"

MIN_TRAIN_SUBJECTS_PER_OUTCOME = 50
MIN_TRAIN_TARGETS_PER_OUTCOME = 80
MAX_OUTCOMES_PER_SOURCE = 12
MIN_VAL_SUBJECTS_EVALUABLE = 20
MIN_TEST_SUBJECTS_EVALUABLE = 30

RIDGE_L2_GRID = (0.01, 0.1, 1.0)
RIDGE_L2_DEFAULT = 0.1
M2_RANK = 8
M2_EPOCHS = 8
M2_LR = 0.05
M2_L2 = 0.1
METHOD_VERSION = "role-invariant-targets-m2-joint-v0111"

# Other immutable priors for before=after
PRIOR_ZIPS = {
    "v011_uis": (ACCEPTED_V011_UIS_ZIP, ACCEPTED_V011_UIS_SHA256),
    "v01_uis": (ACCEPTED_V01_UIS_ZIP, ACCEPTED_V01_UIS_SHA256),
    "v031": (ACCEPTED_V031_ZIP, ACCEPTED_V031_SHA256),
    "v03": (
        "stage-03-unified-a-b-clinical-research-layer-v0.3-review.zip",
        "d78d23bbd8a3984375bcc3891cc2f7f59b17c2c0fb4bdc4f19a92aa3e405eb73",
    ),
    "v0211": (
        "stage-03-cross-source-laboratory-metadata-privacy-closure-v0.2.1.1-review.zip",
        "3214b5414f533e59bba620ed8bcfa3fd23e7197de557583a0c0cb257e9dc9066",
    ),
    "v021": (
        "stage-03-cross-source-laboratory-analyte-ontology-metadata-closure-v0.2.1-review.zip",
        "d10c0a0202a9590d41105e6e56ec406980076a30c953535300d8277212fe5c13",
    ),
    "v02": (
        "stage-03-full-cross-source-laboratory-semantic-discovery-v0.2-review.zip",
        "5e2ebf7a45b5dec207d333e515c635a5323074e8b9b01f774b51386304f0d99d",
    ),
    "v011_sem": (
        "stage-03-cross-source-outcome-semantic-review-v0.1.1-review.zip",
        "22ddd1d37ebe27ff59dadb2f462a15467642925f6158f94b86fcfa4afffa3cb0",
    ),
    "privacy": (
        "stage-03-privacy-boundary-cross-source-longitudinal-harmonization-v0.1-review.zip",
        "a04df9fb03d85852a0d56c694751a026eddb34f4d8362c8a8943ba415090e231",
    ),
    "gs011": (
        "stage-03-source-a-global-split-individual-multi-outcome-state-v0.1.1-review.zip",
        "86643de61303d772b43b7abddf048f0cb42f355dd649c885457dacc43b44a96d",
    ),
}


def policy_snapshot() -> dict[str, Any]:
    return {
        "version": VERSION,
        "corrects": "v0.1.1 role-dependent targets, held-out evidence tiers, fake M2 status",
        "role_invariant_target_selection": True,
        "all_eligible_transitions_all_roles": True,
        "min_val_subjects_evaluable": MIN_VAL_SUBJECTS_EVALUABLE,
        "min_test_subjects_evaluable": MIN_TEST_SUBJECTS_EVALUABLE,
        "no_identity_merge": True,
        "DOMAIN_ACCEPTED_MAPPING_COUNT_default": 0,
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
        "seed": SEED,
        "m2_rank": M2_RANK,
        "m2_epochs": M2_EPOCHS,
        "pooled_raw_mae_across_units": "FORBIDDEN",
    }
