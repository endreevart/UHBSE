"""The pilot keeps slots as candidates and does not invent a gold label."""

from __future__ import annotations

import json

from human_simulator.stage05_gate1b_extractor_pilot_v01.controls import controls_pass, run_controls
from human_simulator.stage05_gate1b_extractor_pilot_v01.extract import accumulate, parse_field
from human_simulator.stage05_gate1b_extractor_pilot_v01.policy import SCIENTIFIC_CEILING, policy_snapshot


def test_slots_are_flags_and_yes_is_not_intake() -> None:
    text = "магний 400 мг 1 раз в день 30 дней"
    parsed = parse_field(text, "CURRENT_INTAKE")
    assert text not in json.dumps(parsed)
    assert parsed["dose"] is True
    assert parsed["frequency"] is True
    assert parsed["duration"] is True
    assert parsed["name_candidate"] is True
    assert parsed["accepted_administration"] is False
    yes = parse_field("да", "CURRENT_INTAKE")
    assert yes["name_candidate"] is False
    assert yes["yes_is_confirmed_intake"] is False
    assert parse_field("нет", "DISCONTINUATION")["event_stated"] is False
    assert parse_field("отменила препарат", "DISCONTINUATION")["earlier_than_recommended"] is False


def test_fields_stay_separate_and_controls_reject_widening() -> None:
    summary = accumulate([
        ("магний 400 мг", "витамин д", "нет", "отменила препарат", "ранее препарат"),
        ("да", None, "заменила препарат", "нет", None),
    ])
    assert summary["fields"]["drugs"]["rows"] == 2
    assert summary["fields"]["vitamins"]["name_candidate_rows"] == 1
    assert summary["fields"]["drugs"]["affirmative_not_confirmed_rows"] == 1
    assert summary["fields"]["change_drugs"]["event_stated_rows"] == 1
    assert summary["fields"]["decline_drugs"]["event_stated_rows"] == 1
    assert summary["drugs_merged_with_vitamins"] is False
    assert summary["positive_changes_extracted"] is False
    assert summary["timing_rows_assigned"] == 0
    assert summary["source_text_retained"] is False
    status = {
        "policy": policy_snapshot(),
        "PRECISION_RECALL_STATUS": "NOT_MEASURED",
        "PRIVATE_LABEL_SET_STATUS": "ABSENT",
        "GATE_2_STATUS": "CLOSED",
        "B_POSITIVE": "DEFERRED_NOT_EXTRACTED",
        **SCIENTIFIC_CEILING,
    }
    assert controls_pass(run_controls(status))
    widened = dict(status)
    widened["PRECISION_RECALL_STATUS"] = "MEASURED"
    assert controls_pass(run_controls(widened)) is False
