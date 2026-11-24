"""Negative controls. Each case changes a valid Gate 1A result and must be rejected."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.stage05_gate_1a_v01.attest import (
    build_records,
    load_answers,
    load_reviewer,
    validate_record,
    validate_records,
)
from human_simulator.stage05_gate_1a_v01.contract import derive, violations
from human_simulator.stage05_gate_1a_v01.policy import DECISION_SCHEMA

EXPECTED_CASES = 16


def _case(name: str, rejected: bool, reason: str) -> dict[str, Any]:
    return {"control": name, "rejected": bool(rejected), "reason": reason if rejected else "NOT_REJECTED"}


def _replace(records: list[dict[str, Any]], question_id: str, **changes: Any) -> list[dict[str, Any]]:
    updated = copy.deepcopy(records)
    record = next(item for item in updated if item["question_id"] == question_id)
    record.update(changes)
    return updated


def run_negative_controls(root: Path, tmp: Path) -> dict[str, Any]:
    answers = load_answers(root)
    records = build_records(answers, load_reviewer(root))
    status = derive(records)
    clean = validate_records(records, DECISION_SCHEMA)["ok"] and not violations(status, records, answers)

    missing = {key: value for key, value in records[0].items() if key != "attestation"}
    named = {**records[0], "reviewer_name": "architect"}
    items = _replace(records, "A_RECOMMENDATION_ITEMS", attestation="accepted", closes_question=True)
    identity = _replace(records, "B_IDENTITY", attestation="accepted", closes_question=True)
    forced_close = _replace(records, "B_POSITIVE", closes_question=True)
    code_set = _replace(records, "A_MEDICATION_CODE_SET", attestation="accepted", closes_question=True)
    rehashed = _replace(records, "B_AUTHOR", evidence_sha256="0" * 64)

    def broken(changed: list[dict[str, Any]], **status_changes: Any) -> bool:
        merged = {**derive(changed), **status_changes}
        return bool(violations(merged, changed, answers))

    confirmed = {**status, "SOURCE_B_FEEDBACK_SEMANTICS_STATUS": "CONFIRMED"}
    leak = tmp / "numeric-id"
    leak.mkdir(parents=True, exist_ok=True)
    (leak / "leak.json").write_text(json.dumps({"patient_id": 15}) + "\n", encoding="utf-8")

    cases = [
        _case("missing_attestation", bool(validate_record(missing, DECISION_SCHEMA)), "SCHEMA_REQUIRED"),
        _case("personal_name_added", "extra:reviewer_name" in validate_record(named, DECISION_SCHEMA), "SCHEMA_CLOSED"),
        _case("recommendation_items_accepted_from_analysis_answer", broken(items), "MISMATCHED_ANSWER_CANNOT_ACCEPT"),
        _case("recall_uncertain_identity_accepted", broken(identity), "RECALL_CANNOT_ACCEPT"),
        _case("insufficient_question_marked_closed", broken(forced_close), "INSUFFICIENT_STAYS_OPEN"),
        _case("partial_code_set_accepted_as_complete", broken(code_set), "PARTIAL_CANNOT_CLOSE"),
        _case("evidence_hash_replaced", broken(rehashed), "EVIDENCE_BOUND_TO_ANSWER"),
        _case(
            "feedback_semantics_confirmed_with_open_questions",
            bool(violations(confirmed, records, answers)),
            "CONFIRMATION_REQUIRES_EVERY_FEEDBACK_QUESTION",
        ),
        _case(
            "identity_marked_established",
            broken(records, SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS="ESTABLISHED"),
            "OWNER_STATEMENT_IS_NOT_DATA_PROOF",
        ),
        _case(
            "identity_data_proof_claimed",
            broken(records, SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS="ESTABLISHED"),
            "DATA_PROOF_NOT_AVAILABLE",
        ),
        _case(
            "intake_tier_accepted_as_administration",
            broken(records, PATIENT_REPORTED_INTAKE_TIER_STATUS="ACCEPTED"),
            "TIER_REQUIRES_EVERY_INTAKE_QUESTION",
        ),
        _case("readiness_claimed", broken(records, INTERVENTION_RESPONSE_READINESS_STATUS="READY"), "READINESS_STAYS_NOT_READY"),
        _case("eligible_cell_counted", broken(records, INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT=1), "ELIGIBLE_CELLS_STAY_ZERO"),
        _case("domain_mapping_counted", broken(records, DOMAIN_ACCEPTED_MAPPING_COUNT=1), "NO_DOMAIN_MAPPING"),
        _case("administration_counted", broken(records, CONFIRMED_ADMINISTRATION_MAPPING_COUNT=1), "NO_ADMINISTRATION"),
        _case("cross_source_identity_linked", broken(records, CROSS_SOURCE_IDENTITY_LINKAGE_STATUS="PERFORMED"), "NO_A_B_MERGE"),
    ]
    privacy_rejects = scan_public(leak)["PUBLIC_DATA_MINIMIZATION_STATUS"] == "FAIL"
    rejected = sum(1 for case in cases if case["rejected"])
    ok = clean and privacy_rejects and rejected == len(cases) == EXPECTED_CASES
    return {
        "ok": ok,
        "NEGATIVE_CONTROL_STATUS": "PASS" if ok else "FAIL",
        "baseline_accepted": clean,
        "privacy_rejects_numeric_identifier": privacy_rejects,
        "n_cases": len(cases),
        "n_rejected": rejected,
        "cases": cases,
    }
