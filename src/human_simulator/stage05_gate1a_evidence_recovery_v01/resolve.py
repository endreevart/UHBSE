"""The newer scoped record wins. Workflow intent assigns no rows."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import SCOPE, SCOPED_QUESTIONS


def resolve(prior: list[dict[str, Any]], superseding: list[dict[str, Any]]) -> dict[str, Any]:
    newer = {record["question_id"]: record for record in superseding}
    effective = []
    for record in prior:
        question_id = record["question_id"]
        chosen = newer.get(question_id, record)
        effective.append({
            "question_id": question_id,
            "source": "superseding" if question_id in newer else "original",
            "closes_question": bool(chosen["closes_question"]),
            "attestation": chosen["attestation"],
            "attestation_scope": chosen.get("attestation_scope"),
            "row_level_proof": chosen.get("row_level_proof", False),
        })
    by_id = {item["question_id"]: item for item in effective}
    scoped_ok = all(
        by_id[question_id]["source"] == "superseding"
        and by_id[question_id]["closes_question"] is False
        and by_id[question_id]["attestation_scope"] == SCOPE
        for question_id in SCOPED_QUESTIONS
    )
    return {
        "SUPERSESSION_RESOLUTION_STATUS": "PASS" if scoped_ok and len(by_id) == len(prior) else "FAIL",
        "EFFECTIVE_B_TIMING_CLOSES_QUESTION": by_id["B_TIMING"]["closes_question"],
        "EFFECTIVE_B_PERIOD_CLOSES_QUESTION": by_id["B_PERIOD"]["closes_question"],
        "questions": effective,
    }


def row_assignments(ledger: dict[str, Any]) -> dict[str, Any]:
    categories = {name: 0 for name in ledger["categories"]}
    total = int(ledger["FEEDBACK_TOTAL_COUNT"])
    return {
        "B_TIMING_ROW_LEVEL_ASSIGNMENT_COUNT": 0,
        "B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT": 0,
        "workflow_applied_row_count": 0,
        "observed_row_count": total,
        "assignment_by_temporal_category": categories,
        "workflow_and_temporal_are_separate_layers": True,
        "VISIT_CLASSIFICATION_STATUS": "NOT_PERFORMED",
    }
