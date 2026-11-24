"""Owner attestation keeps drugs separate from vitamins and does not open Gate 1B."""

from __future__ import annotations

import json
from pathlib import Path

from human_simulator.exposure_source_discovery_v022.decisions import canonical_sha256
from human_simulator.stage05_gate1a_owner_attestation_v01.records import build_records, reviewer_digest

ROOT = Path(__file__).resolve().parents[1]


def test_prior_timing_hash_matches_the_completion_record() -> None:
    prior = json.loads((ROOT / "artifacts/stage-05-gate-1a-v0.1/decision-records.json").read_text(encoding="utf-8"))["responses"]
    timing = next(record for record in prior if record["question_id"] == "B_TIMING")
    assert canonical_sha256(timing) == "66e3f084e875baf87b8149b556db0ae82199cf8d07c129f06c506c2c1eb69b7f"


def test_answers_are_not_widened_and_fields_stay_separate() -> None:
    prior = json.loads((ROOT / "artifacts/stage-05-gate-1a-v0.1/decision-records.json").read_text(encoding="utf-8"))["responses"]
    records = {record["question_id"]: record for record in build_records(prior)}
    assert records["B_DRUGS"]["decision"] == "CURRENT_INTAKE"
    assert records["B_VITAMINS"]["decision"] == "CURRENT_INTAKE"
    assert records["B_DRUGS"]["drugs_merged_with_vitamins"] is False
    assert records["B_CHANGE"]["decision"] == "REPLACEMENT"
    assert records["B_DECLINE"]["decision"] == "DISCONTINUATION"
    assert records["B_DRUGS_FIRST"]["decision"] == "PREVIOUSLY_PRESCRIBED"
    assert records["B_DRUGS_FIRST"]["prior_question_present"] is False
    assert records["B_IDENTITY"]["decision"] == "SAME_USERS_ID"
    assert records["B_IDENTITY"]["row_level_proof"] is False
    assert records["B_SHORT"]["yes_is_confirmed_intake"] is False
    assert all(record["closes_question"] is True for record in records.values())
    assert reviewer_digest() == "42487641f54106eedef42133516ce7be202bf3f458ae29695b641c50d501a57a"
