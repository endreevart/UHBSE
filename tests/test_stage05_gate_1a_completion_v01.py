"""Scope records qualify B_TIMING and B_PERIOD without rewriting Gate 1A v0.1."""

from __future__ import annotations

from pathlib import Path

from human_simulator.stage05_gate_1a_completion_v01.contract import derive, validate_record, violations
from human_simulator.stage05_gate_1a_completion_v01.mutations import EXPECTED_CASES, run_negative_controls
from human_simulator.stage05_gate_1a_completion_v01.policy import SCOPE, SCIENTIFIC_CEILING
from human_simulator.stage05_gate_1a_completion_v01.prior import load_prior, temporal_scope, verify_answer_binding
from human_simulator.stage05_gate_1a_completion_v01.supersede import build_superseding

ROOT = Path(__file__).resolve().parents[1]


def test_prior_gate_stays_partial_and_answer_hashes_resolve() -> None:
    prior = load_prior(ROOT)
    binding = verify_answer_binding(ROOT, prior)
    assert prior["record_count"] == 14
    assert prior["accepted_count"] == 4
    assert prior["insufficient_count"] == 10
    assert prior["closed_count"] == 4
    assert prior["closed_insufficient"] == []
    assert prior["reviewer_digest_count"] == 1
    assert prior["role_count"] == 1
    assert prior["duplicate_question_ids"] is False
    assert binding["ok"] is True
    assert binding["answer_record_sha256"]


def test_scope_does_not_change_the_accepted_wording() -> None:
    prior = load_prior(ROOT)
    temporal = temporal_scope(ROOT)
    superseding = build_superseding(prior, temporal)
    by_id = {record["question_id"]: record for record in superseding}
    assert set(by_id) == {"B_TIMING", "B_PERIOD"}
    for question_id, record in by_id.items():
        previous = prior["scoped"][question_id]
        assert record["decision"] == previous["decision"]
        assert record["evidence_sha256"] == previous["evidence_sha256"]
        assert record["attestation_scope"] == SCOPE
        assert record["closes_question"] is False
        assert record["row_level_proof"] is False
        assert not validate_record(record)
    assert by_id["B_TIMING"]["requires_first_vs_repeat_visit_classification"] is False
    assert by_id["B_PERIOD"]["requires_first_vs_repeat_visit_classification"] is True
    recovery = {"SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS": "NOT_FOUND", "superseding_records_created_from_code": 0}
    status = derive(prior, superseding, recovery)
    assert status["GATE_1A_STATUS"] == "PARTIALLY_ATTESTED_OPEN"
    assert status["GATE_1B_STATUS"] == "BLOCKED"
    assert status["B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT"] == 0
    assert "B_POSITIVE" not in status["GATE_1B_BLOCKERS"]
    for key, value in SCIENTIFIC_CEILING.items():
        assert status[key] == value
    assert not violations(status, prior, superseding, True, recovery)


def test_negative_controls(tmp_path: Path) -> None:
    result = run_negative_controls(ROOT, tmp_path)
    assert result["baseline_accepted"] is True
    assert result["n_rejected"] == EXPECTED_CASES, [case for case in result["cases"] if not case["rejected"]]
    assert result["NEGATIVE_CONTROL_STATUS"] == "PASS"
