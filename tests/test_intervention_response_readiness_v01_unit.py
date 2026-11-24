"""Unit tests — intervention-response readiness v0.1."""

from __future__ import annotations

from pathlib import Path

from human_simulator.intervention_response_readiness_v01.evaluate import (
    build_registry,
    consumption_decision,
    lanes_from_registry,
)
from human_simulator.intervention_response_readiness_v01.exposure import (
    classify_tier,
    no_auto_promote,
)
from human_simulator.intervention_response_readiness_v01.mutations import run_negative_controls
from human_simulator.intervention_response_readiness_v01.policy import PRIOR_ZIPS, REVIEW_ZIP
from human_simulator.intervention_response_readiness_v01.reconciliation import reconcile_final_report
from human_simulator.intervention_response_readiness_v01.report import render_stage_report

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


def test_recorded_association_is_not_administration() -> None:
    tier = classify_tier(
        record_class="RECORDED_MEDICATION_CONTEXT",
        mapping_status="unknown",
        administration_claim="NOT_CLAIMED",
        event_time_semantics="CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
    )
    assert tier == "RECORDED_MEDICATION_ASSOCIATION"
    assert no_auto_promote(tier, "DISPENSED_OR_ADMINISTERED_EXPOSURE") is True
    assert no_auto_promote(tier, "CAUSAL_INTERVENTION_EVIDENCE") is True


def test_domain_accepted_zero_forces_not_ready() -> None:
    registry = build_registry(_PHASE0)
    lanes = lanes_from_registry(registry)
    assert registry["DOMAIN_ACCEPTED_MAPPING_COUNT"] == 0
    assert registry["INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0
    assert lanes["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
    assert all(not c.get("intervention_response_eligible") for c in registry["cells"])


def test_consumption_not_consumed_from_counts() -> None:
    decision = consumption_decision(_PHASE0)
    assert decision["MEDICATION_RESIDUAL_CONSUMPTION_STATUS"] == "NOT_CONSUMED"
    assert decision["engine_eligible_cell_count"] == 0
    assert decision["computed_not_handwritten"] is True


def test_negative_controls_reject(tmp_path: Path) -> None:
    status = {
        "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "TECHNICAL_AUDIT_STATUS": "PASS",
        "PUBLICATION_INTEGRITY_STATUS": "NOT_PACKED",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY",
    }
    result = run_negative_controls(_PHASE0, status, tmp=tmp_path)
    assert result["ok"] is True
    assert result["n_cases"] == 11
    assert result["n_rejected"] == 11


def test_full_key_reconciliation_not_whitelist() -> None:
    status = {
        "ALPHA_STATUS": "ONE",
        "BETA_STATUS": "TWO",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY",
    }
    report = render_stage_report(status)
    recon = reconcile_final_report(report_text=report, status=status)
    assert recon["ok"] is True
    assert recon["comparison_mode"] == "ALL_COMMON_UPPERCASE_STATUS_KEYS"
    assert "ALPHA_STATUS" in recon["compared_keys"]
    assert "BETA_STATUS" in recon["compared_keys"]
    flipped = report.replace("- `ALPHA_STATUS`=ONE", "- `ALPHA_STATUS`=NOPE", 1)
    bad = reconcile_final_report(report_text=flipped, status=status)
    assert bad["ok"] is False
    assert any(m["key"] == "ALPHA_STATUS" for m in bad["mismatches"])


def test_prior_zip_pins_include_v016() -> None:
    assert PRIOR_ZIPS["irr_v016"][1] == (
        "3c856824a2856fe5b85c4186dd2c0134954e5c6930df2ab655a784ffaa38be4a"
    )
    assert REVIEW_ZIP.startswith("stage-05-intervention-response-readiness")
