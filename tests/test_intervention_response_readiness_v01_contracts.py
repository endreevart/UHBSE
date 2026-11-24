"""Contract tests — intervention-response readiness v0.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from human_simulator.intervention_response_readiness_v01.evaluate import build_registry, lanes_from_registry
from human_simulator.intervention_response_readiness_v01.exposure import exposure_contract
from human_simulator.intervention_response_readiness_v01.policy import (
    ARTIFACT_DIR,
    EXPOSURE_TIERS,
    GATES,
    IR_ELIGIBLE_TIERS,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    SECURITY_STAGE_STATUS,
)
from human_simulator.intervention_response_readiness_v01.publish import PublicationError, publish

_PHASE0 = {
    "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
    "STATE_ENCODER_STATUS": "NOT_ACCEPTED",
    "MEDICATION_RESIDUAL_FOUNDATION_STATUS": "NOT_CONSUMED_NOT_ACCEPTED",
    "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT": 0,
    "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT": 0,
    "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT": 0,
    "residual_engine_eligible_listed": 0,
    "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS": "NO_INCREMENTAL_SIGNAL",
    "source_a_medication_rows": 25726,
    "source_b_medication_rows": 0,
    "source_a_record_class": "RECORDED_MEDICATION_CONTEXT",
    "source_a_administration_claim": "NOT_CLAIMED",
    "chosen_technical_timestamp_candidate": "appointment_date",
    "clinical_event_time_status": "CANDIDATE_ONLY",
    "medicine_catalog_columns": ["unit_of_measurement_id", "form_id", "reception_frequency_id"],
    "form_table_n_rows": 0,
    "inventory": [
        {
            "source_system": "magerya_api",
            "outcome_key": "A::synth-outcome::u",
            "native_outcome_unit": "u",
            "horizon_days": 90,
            "residual_engine_eligible": False,
        }
    ],
    "materialized": {"live_row_recount_status": "NOT_RUN_SOURCE_UNAVAILABLE"},
    "confounding": {"indication_confounding": "UNRESOLVED"},
}


def test_gates_are_g0_through_g10() -> None:
    assert GATES[0].startswith("G0_")
    assert GATES[-1].startswith("G10_")
    assert len(GATES) == 11


def test_recorded_association_is_not_ir_eligible_tier() -> None:
    assert "RECORDED_MEDICATION_ASSOCIATION" in EXPOSURE_TIERS
    assert "RECORDED_MEDICATION_ASSOCIATION" not in IR_ELIGIBLE_TIERS
    contract = exposure_contract()
    assert contract["promotion"] == "FORBIDDEN_AUTOMATIC"
    assert contract["associational_does_not_raise_causal"] is True
    assert contract["appointment_date_is_not_administration"] is True


def test_security_paused_and_no_training_defaults() -> None:
    assert SECURITY_STAGE_STATUS == "PAUSED_NOT_ACCEPTED_BY_OWNER"
    assert ARTIFACT_DIR.startswith("artifacts/stage-05-")
    assert REVIEW_ZIP.endswith("-v0.1-review.zip")
    assert len(PRIOR_ZIPS) == 7


def test_publish_refuses_existing_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    external = root / "artifacts" / "external-review"
    external.mkdir(parents=True)
    (external / REVIEW_ZIP).write_bytes(b"no")
    with pytest.raises(PublicationError, match="refuse overwrite"):
        publish(root)


def test_inventory_is_not_intervention_response() -> None:
    registry = build_registry(_PHASE0)
    lanes = lanes_from_registry(registry)
    assert lanes["descriptive_recorded_association"]["counts_as_intervention_response"] is False
    assert registry["ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0
    assert registry["ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0
    assert registry["CONFIRMED_ADMINISTRATION_MAPPING_COUNT"] == 0
