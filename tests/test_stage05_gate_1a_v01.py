"""Gate 1A records owner answers without upgrading readiness."""

from __future__ import annotations

from pathlib import Path

from human_simulator.stage05_gate_1a_v01.attest import (
    build_records,
    load_answers,
    load_reviewer,
    outside_gate,
    validate_records,
)
from human_simulator.stage05_gate_1a_v01.contract import derive, violations
from human_simulator.stage05_gate_1a_v01.mutations import EXPECTED_CASES, run_negative_controls
from human_simulator.stage05_gate_1a_v01.policy import DECISION_SCHEMA, SCIENTIFIC_CEILING

ROOT = Path(__file__).resolve().parents[1]
ACCEPTED = {"A_MEDICATION_CODE_MEDICINES", "B_AUTHOR", "B_TIMING", "B_PERIOD"}


def _records() -> tuple[list[dict], list[dict]]:
    answers = load_answers(ROOT)
    return answers, build_records(answers, load_reviewer(ROOT))


def test_checklist_accepts_only_stated_answers_that_address_the_question() -> None:
    answers, records = _records()
    validation = validate_records(records, DECISION_SCHEMA)
    assert validation["ok"], validation
    assert {record["question_id"] for record in records if record["attestation"] == "accepted"} == ACCEPTED
    assert all(record["closes_question"] == (record["attestation"] == "accepted") for record in records)
    status = derive(records)
    assert status["SOURCE_B_FEEDBACK_SEMANTICS_STATUS"] == "PARTIALLY_ATTESTED"
    assert status["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"] == "INSUFFICIENT_ATTESTATION_NOT_DATA_PROOF"
    assert status["PATIENT_REPORTED_INTAKE_TIER_STATUS"] == "NOT_ACCEPTED_INSUFFICIENT_ATTESTATION"
    assert status["SOURCE_A_RECOMMENDATION_SEMANTICS_STATUS"] == "PARTIALLY_ATTESTED"
    assert status["GATE_1A_ATTESTATION_STATUS"] == "INCOMPLETE"
    for key, value in SCIENTIFIC_CEILING.items():
        assert status[key] == value
    assert not violations(status, records, answers)
    assert {item["answer_key"] for item in outside_gate(answers)} == {"A4", "B6", "B10", "B11"}


def test_full_acceptance_still_leaves_readiness_closed() -> None:
    _, records = _records()
    for record in records:
        record["attestation"] = "accepted"
        record["closes_question"] = True
    status = derive(records)
    assert status["GATE_1A_ATTESTATION_STATUS"] == "ATTESTED"
    assert status["SOURCE_B_FEEDBACK_SEMANTICS_STATUS"] == "CONFIRMED"
    assert status["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"] == "OWNER_ATTESTED_NOT_DATA_PROOF"
    assert status["PATIENT_REPORTED_INTAKE_TIER_STATUS"] == "ATTESTED_PATIENT_REPORTED_NOT_ADMINISTRATION"
    assert status["SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS"] == "NOT_ESTABLISHED"
    assert status["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
    assert status["INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0
    assert status["INTERVENTION_RESPONSE_MODEL_STATUS"] == "NOT_STARTED"
    assert status["CONFIRMED_ADMINISTRATION_MAPPING_COUNT"] == 0


def test_negative_controls(tmp_path: Path) -> None:
    result = run_negative_controls(ROOT, tmp_path)
    assert result["baseline_accepted"] is True
    assert result["n_rejected"] == EXPECTED_CASES, [case for case in result["cases"] if not case["rejected"]]
    assert result["NEGATIVE_CONTROL_STATUS"] == "PASS"
