"""Phase 0 — probability v0.2.1.1 is published but not consumed for medication residual."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.medication_residual_v01.policy import (
    LEP_V0211_ARTIFACT_DIR,
    LEP_V0211_SRC,
    PRIOR_ZIPS,
    UPSTREAM_PROBABILITY_CONSUMPTION_STATUS,
    VERSION,
)


def _src_contains(root: Path, name: str, needle: str) -> bool:
    path = root / LEP_V0211_SRC / name
    if not path.is_file():
        return False
    return needle in path.read_text(encoding="utf-8")


def inspect_heldout_limitations(root: Path) -> dict[str, Any]:
    """Record the two known v0.2.1.1 limitations. Do not republish LEP."""
    root = Path(root).resolve()
    survival = (root / LEP_V0211_SRC / "survival.py").read_text(encoding="utf-8")
    freeze_reads_test = (
        'test = [r for r in rows if r["split_role"] == "test"]' in survival
        and "n_test_subjects" in survival
        and "test_held_rows" in survival
        and "_subsample_complete_groups" in survival
    )
    km_from_test = (
        "km0_use = kaplan_meier(" in survival
        and 'split_label="heldout_test"' in survival
    )
    # Frozen train KM is built as km0 from train_f, but held-out eval rebuilds KM on test.
    train_km_exists = "km0 = kaplan_meier([r[\"time_days\"] for r in train_f]" in survival
    return {
        "limitation_1_train_and_freeze_reads_test_before_physical_freeze": freeze_reads_test,
        "limitation_1_stores_test_held_rows": "test_held_rows" in survival,
        "limitation_2_heldout_m0_km_built_on_test_outcomes": km_from_test,
        "limitation_2_not_loaded_as_frozen_train_m0": train_km_exists and km_from_test,
        "v02112_not_created": True,
        "source_files": {
            "survival.py": (root / LEP_V0211_SRC / "survival.py").is_file(),
            "freeze.py": (root / LEP_V0211_SRC / "freeze.py").is_file(),
        },
    }


def build_consumption_policy(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    limits = inspect_heldout_limitations(root)
    art = root / LEP_V0211_ARTIFACT_DIR
    published = (art / "status-contract.json").is_file()
    return {
        "version": VERSION,
        "UPSTREAM_PROBABILITY_CONSUMPTION_STATUS": (
            UPSTREAM_PROBABILITY_CONSUMPTION_STATUS
        ),
        "probability_v0211_accepted_as": "PUBLISHED_TECHNICAL_PARTIAL_RESULT",
        "held_out_confirmation_used_as_medication_foundation": False,
        "survival_probabilities_used_as_medication_features": False,
        "survival_probabilities_used_as_labels": False,
        "survival_probabilities_used_as_baseline_predictions": False,
        "accepted_cells_used_as_cohort_gates": False,
        "engine_eligibility_used_as_cohort_gates": False,
        "separate_v02112_created": False,
        "lep_v0211_sha256": PRIOR_ZIPS["lep_v0211"][1],
        "published_status_contract_present": published,
        "known_limitations": limits,
        "ok": (
            limits["limitation_1_train_and_freeze_reads_test_before_physical_freeze"]
            and limits["limitation_2_heldout_m0_km_built_on_test_outcomes"]
            and not False
        ),
    }


def foundation_acceptance_matrix() -> dict[str, Any]:
    return {
        "version": VERSION,
        "probability_v0211": {
            "status": "PUBLISHED_TECHNICAL_PARTIAL_RESULT",
            "consume_for_medication_residual": False,
            "reason": UPSTREAM_PROBABILITY_CONSUMPTION_STATUS,
        },
        "research_layer_v031": {
            "status": "ACCEPTED_AS_MATERIALIZED_INPUT",
            "consume": True,
            "role": "medication_inventory_and_observation_lineage",
        },
        "uis_v0111": {
            "status": "ACCEPTED_FOR_SPLIT_AND_OUTCOME_KEYS",
            "frozen_m1_ridge": "NOT_USED_MEDICATION_FEATURES_AND_NO_REQUESTED_HORIZON",
            "state_encoder": "NOT_USED_NOT_ACCEPTED",
        },
        "global_split_v011": {
            "status": "ACCEPTED_OVERLAP_GUARDED_SPLIT",
            "consume": True,
        },
        "traj_expansion_v011": {
            "status": "ACCEPTED_AS_IMMUTABLE_PRIOR",
            "consume_for_residual_features": False,
        },
        "concept_pilot_v01": {
            "status": "ACCEPTED_AS_IMMUTABLE_PRIOR",
            "scientifically_usable_accepted_drug_concepts": 0,
        },
        "medication_association_v011": {
            "status": "ACCEPTED_AS_LINEAGE_FOR_EXPANSION_ACCOUNTING",
            "episode_rows_are_not_administrations": True,
        },
        "medication_knowledge_v01": {
            "status": "ACCEPTED_AS_IMMUTABLE_PRIOR",
            "exposure_not_claimed": True,
        },
        "medication_concept_v01": {
            "status": "ACCEPTED_AS_IMMUTABLE_PRIOR",
            "no_automatic_concept_acceptance": True,
        },
        "rejected_state_encoders": "NOT_USED",
        "no_v02112": True,
    }


def prior_medication_evidence_reconciliation() -> dict[str, Any]:
    return {
        "version": VERSION,
        "HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT": 0,
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT": 0,
        "historical_automatic_exact_813": {
            "scientifically_usable": False,
            "requires_typed_human_review": True,
            "does_not_authorize_R2SEM": True,
        },
        "HUMAN_REJECTED_SOURCE_MEDICINE_IDS": ["31", "48", "405", "449", "510", "810"],
        "rejected_pairs_remain_excluded": True,
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "episode_expansion_pin": 202374,
        "episode_expansion_pin_meaning": (
            "medication_times_outcome_jsonl_rows_not_prescriptions_or_administrations"
        ),
        "R2SEM_STATUS": "NOT_RUN_NO_SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPTS",
    }
