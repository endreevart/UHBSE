"""Primary evidence recovery: pins, applicability, supersession, and negative controls."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from human_simulator.stage05_gate1a_evidence_recovery_v01.adjudicate import closes, gate_outcome
from human_simulator.stage05_gate1a_evidence_recovery_v01.limitations import reproduce
from human_simulator.stage05_gate1a_evidence_recovery_v01.mutations import EXPECTED_CASES, run_negative_controls
from human_simulator.stage05_gate1a_evidence_recovery_v01.pins import pin_accepted, verify_files
from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import (
    EXPECTED_DECISION_RECORDS_SHA,
    GATE_1B_BLOCKERS,
    REJECTED_DECISION_RECORDS_SHA,
    SCIENTIFIC_CEILING,
    SCOPE,
)
from human_simulator.stage05_gate1a_evidence_recovery_v01.report import render
from human_simulator.stage05_gate1a_evidence_recovery_v01.resolve import resolve, row_assignments

ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION = {"database_binding": True, "unambiguous_production": True, "applicability": "PRODUCTION"}


def test_concatenated_pin_is_rejected_and_exact_pin_matches_disk() -> None:
    assert pin_accepted(REJECTED_DECISION_RECORDS_SHA, REJECTED_DECISION_RECORDS_SHA) is False
    assert pin_accepted(EXPECTED_DECISION_RECORDS_SHA, REJECTED_DECISION_RECORDS_SHA) is False
    assert pin_accepted(EXPECTED_DECISION_RECORDS_SHA, EXPECTED_DECISION_RECORDS_SHA) is True
    assert len(REJECTED_DECISION_RECORDS_SHA) != 64
    verified = verify_files(ROOT)
    assert verified["ok"] is True
    assert verified["rejected_concatenated_pin_accepted"] is False


def test_applicability_blocks_name_fixture_and_unrelated_form() -> None:
    assert closes("B_DRUGS", {"level": "E0", "basis": "COLUMN_NAME", "applicability": "NAMING_ONLY"}) is False
    assert closes("B_DRUGS", {"level": "E3", "object": "DoctorFeedback", **_PRODUCTION}) is False
    assert closes("B_IDENTITY", {"level": "E1", "relation_contract": "PROVEN_SINGLE_ENTITY", "basis": "NUMERIC_KEY_AGREEMENT"}) is False
    assert closes("B_IDENTITY", {"level": "E1", "relation_contract": "NOT_FOUND"}) is False
    assert closes("B_IDENTITY", {"level": "E2", "relation_contract": "PROVEN_SINGLE_ENTITY", "applicability": "PRODUCTION"}) is True
    assert closes("A_RECOMMENDATION_ITEMS", {"level": "E2", "object": "document_analysis.items", **_PRODUCTION}) is False
    assert closes("A_MEDICATION_CODE_SET", {"level": "E2", "sole_section_from_name": True, **_PRODUCTION}) is False
    assert closes("A_DOCUMENT_FINAL", {"level": "E1", "basis": "ROW_EXISTS"}) is False
    assert closes("B_VITAMINS", {"level": "E3", "auto_merged": True, **_PRODUCTION}) is False
    assert closes("B_SHORT", {"level": "E3", "accepted_from_token": True, **_PRODUCTION}) is False
    assert closes("B_DRUGS", {"level": "E3", **_PRODUCTION}) is True
    assert closes("B_DRUGS", {"level": "E3", "database_binding": False, "unambiguous_production": True, "applicability": "PRODUCTION"}) is False
    assert closes("B_VITAMINS", {"level": "E1", "database_binding": True, "applicability": "PRODUCTION"}) is False


def test_one_open_blocker_keeps_gate_1b_blocked_and_readiness_unchanged() -> None:
    closed = {question_id: True for question_id in GATE_1B_BLOCKERS}
    closed["B_SHORT"] = False
    blocked = gate_outcome(closed)
    assert blocked["GATE_1A_STATUS"] == "PARTIALLY_ATTESTED_OPEN"
    assert blocked["GATE_1B_STATUS"] == "BLOCKED"
    accepted = gate_outcome({question_id: True for question_id in GATE_1B_BLOCKERS})
    assert accepted["GATE_1B_STATUS"] == "READY_FOR_EXPLICIT_OWNER_OPENING"
    combined = {**accepted, **SCIENTIFIC_CEILING, "medication_extractor": False, "model_training": False}
    assert combined["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
    assert combined["INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0
    assert combined["INTERVENTION_RESPONSE_MODEL_STATUS"] == "NOT_STARTED"


def test_newer_scope_wins_and_assigns_no_rows() -> None:
    prior = json.loads((ROOT / "artifacts/stage-05-gate-1a-v0.1/decision-records.json").read_text(encoding="utf-8"))["responses"]
    newer = json.loads((ROOT / "artifacts/stage-05-gate-1a-completion-v0.1/superseding-decision-records.json").read_text(encoding="utf-8"))["responses"]
    resolved = resolve(prior, newer)
    assert resolved["SUPERSESSION_RESOLUTION_STATUS"] == "PASS"
    assert resolved["EFFECTIVE_B_TIMING_CLOSES_QUESTION"] is False
    assert resolved["EFFECTIVE_B_PERIOD_CLOSES_QUESTION"] is False
    timing = next(item for item in resolved["questions"] if item["question_id"] == "B_TIMING")
    assert timing["source"] == "superseding"
    assert timing["attestation_scope"] == SCOPE
    ledger = json.loads((ROOT / "artifacts/exposure-source-discovery-v0.2.1/feedback-exclusive-classification.json").read_text(encoding="utf-8"))
    assigned = row_assignments(ledger)
    assert assigned["observed_row_count"] == 41407
    assert assigned["B_TIMING_ROW_LEVEL_ASSIGNMENT_COUNT"] == 0
    assert assigned["B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT"] == 0
    assert assigned["workflow_applied_row_count"] == 0
    assert set(assigned["assignment_by_temporal_category"]) == set(ledger["categories"])
    assert all(value == 0 for value in assigned["assignment_by_temporal_category"].values())


def test_prior_search_limitations_and_twenty_four_controls() -> None:
    limitations = reproduce(ROOT)
    assert limitations["PRIOR_EVIDENCE_RECOVERY_LIMITATIONS_STATUS"] == "REPRODUCED"
    assert limitations["points"][3]["python_files_scanned"] == 1106
    prior = json.loads((ROOT / "artifacts/stage-05-gate-1a-v0.1/decision-records.json").read_text(encoding="utf-8"))["responses"]
    newer = json.loads((ROOT / "artifacts/stage-05-gate-1a-completion-v0.1/superseding-decision-records.json").read_text(encoding="utf-8"))["responses"]
    with tempfile.TemporaryDirectory() as tmp:
        controls = run_negative_controls(Path(tmp), prior, newer)
    assert controls["n_cases"] >= EXPECTED_CASES
    assert controls["n_rejected"] == controls["n_cases"]
    assert controls["NEGATIVE_CONTROL_STATUS"] == "PASS"


def test_report_repeats_blocked_status() -> None:
    text = render({
        "GATE_1A_EVIDENCE_RECOVERY_STATUS": "PASS",
        "GATE_1A_STATUS": "PARTIALLY_ATTESTED_OPEN",
        "GATE_1A_SOURCE_B_EXPOSURE_ROUTE_STATUS": "BLOCKED",
        "GATE_1B_STATUS": "BLOCKED",
        "SOURCE_B_APPLICATION_CODE_ACCESS_STATUS": "NOT_AVAILABLE",
        "SOURCE_B_FORM_SEMANTICS_STATUS": "NOT_RECOVERED_APPLICATION_CODE_NOT_AVAILABLE",
        "SUPERSESSION_RESOLUTION_STATUS": "PASS",
        "EFFECTIVE_B_TIMING_CLOSES_QUESTION": False,
        "EFFECTIVE_B_PERIOD_CLOSES_QUESTION": False,
        "B_TIMING_ROW_LEVEL_ASSIGNMENT_COUNT": 0,
        "B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT": 0,
        "NEW_SUPERSEDING_RECORD_COUNT": 0,
        "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY",
        "NEGATIVE_CONTROL_STATUS": "PASS",
    })
    assert "`GATE_1A_STATUS`=PARTIALLY_ATTESTED_OPEN" in text
    assert "`GATE_1B_STATUS`=BLOCKED" in text
    assert "FORM_SCHEMA_NOT_FOUND_IN_SOURCE_B_CODE" not in text


def test_two_process_replay() -> None:
    code = (
        "from human_simulator.stage05_gate1a_evidence_recovery_v01.pins import pin_accepted; "
        "from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import EXPECTED_DECISION_RECORDS_SHA, REJECTED_DECISION_RECORDS_SHA, SCOPE; "
        "from human_simulator.stage05_gate1a_evidence_recovery_v01.resolve import resolve; "
        "prior=[{'question_id':'B_TIMING','closes_question':True,'attestation':'accepted'},"
        "{'question_id':'B_PERIOD','closes_question':True,'attestation':'accepted'}]; "
        "newer=[{'question_id':'B_TIMING','closes_question':False,'attestation':'accepted','attestation_scope':SCOPE},"
        "{'question_id':'B_PERIOD','closes_question':False,'attestation':'accepted','attestation_scope':SCOPE}]; "
        "print(pin_accepted(REJECTED_DECISION_RECORDS_SHA, REJECTED_DECISION_RECORDS_SHA), "
        "pin_accepted(EXPECTED_DECISION_RECORDS_SHA, EXPECTED_DECISION_RECORDS_SHA), "
        "resolve(prior, newer)['EFFECTIVE_B_TIMING_CLOSES_QUESTION'], "
        "resolve(prior, newer)['SUPERSESSION_RESOLUTION_STATUS'])"
    )
    results = []
    for _ in range(2):
        proc = subprocess.run(
            ["uv", "run", "--frozen", "--no-sync", "python", "-c", code],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        results.append(proc.stdout.strip())
    assert results == ["False True False PASS", "False True False PASS"]
