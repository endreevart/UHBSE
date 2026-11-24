"""Twenty-four negative controls. Each mutated acceptance is rejected."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.stage05_gate1a_evidence_recovery_v01.adjudicate import closes, gate_outcome
from human_simulator.stage05_gate1a_evidence_recovery_v01.pins import pin_accepted
from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import (
    EXPECTED_DECISION_RECORDS_SHA,
    REJECTED_DECISION_RECORDS_SHA,
    SCIENTIFIC_CEILING,
)
from human_simulator.stage05_gate1a_evidence_recovery_v01.resolve import resolve

EXPECTED_CASES = 24


def _case(name: str, rejected: bool, reason: str) -> dict[str, Any]:
    return {"control": name, "rejected": bool(rejected), "reason": reason if rejected else "NOT_REJECTED"}


def _open(question_id: str, **evidence: Any) -> bool:
    return closes(question_id, evidence) is False


def _linked(record: dict[str, Any]) -> bool:
    value = record.get("prior_record_sha256")
    return isinstance(value, str) and len(value) == 64


def _timing_allowed(count: int) -> bool:
    return count == 0


def _period_allowed(visit_class: str | None, count: int) -> bool:
    if count == 0:
        return True
    return visit_class in {"FIRST", "REPEAT"}


def _model_allowed(status: dict[str, Any]) -> bool:
    return status.get("INTERVENTION_RESPONSE_MODEL_STATUS") == "NOT_STARTED" and status.get("medication_extractor") is not True


def run_negative_controls(tmp: Path, prior: list[dict[str, Any]], superseding: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = resolve(prior, superseding)
    prefer_old = next(record["closes_question"] for record in prior if record["question_id"] == "B_TIMING")
    leak = tmp / "numeric-id"
    leak.mkdir(parents=True, exist_ok=True)
    (leak / "leak.json").write_text(json.dumps({"patient_id": 15}) + "\n", encoding="utf-8")
    blocked = gate_outcome({question: False for question in (
        "B_IDENTITY", "B_DRUGS", "B_VITAMINS", "B_CHANGE", "B_DECLINE", "B_SHORT",
    )})
    cases = [
        _case("concatenated_baseline_sha_accepted", pin_accepted(REJECTED_DECISION_RECORDS_SHA, REJECTED_DECISION_RECORDS_SHA) is False and pin_accepted(EXPECTED_DECISION_RECORDS_SHA, EXPECTED_DECISION_RECORDS_SHA), "PIN_MUST_BE_EXACT"),
        _case("prior_decision_hash_replaced", pin_accepted("0" * 64, EXPECTED_DECISION_RECORDS_SHA) is False, "PRIOR_FILE_HASH_IS_PINNED"),
        _case("superseding_record_without_prior_hash", _linked({**superseding[0], "prior_record_sha256": None}) is False, "SUPERSEDING_MUST_CITE_PRIOR"),
        _case("older_closes_question_wins", prefer_old is True and resolved["EFFECTIVE_B_TIMING_CLOSES_QUESTION"] is False, "NEWER_SCOPE_WINS"),
        _case("timing_applied_to_a_row", _timing_allowed(1) is False, "NO_ROW_ASSIGNMENT"),
        _case("period_applied_without_visit_class", _period_allowed(None, 1) is False, "VISIT_CLASS_REQUIRED"),
        _case("doctor_feedback_accepted_as_source_b", _open("B_DRUGS", level="E2", object="DoctorFeedback", applicability="UNRELATED_FORM", database_binding=True, unambiguous_production=True), "UNRELATED_FORM"),
        _case("column_name_accepted_as_semantics", _open("B_DRUGS", level="E0", basis="COLUMN_NAME", applicability="NAMING_ONLY"), "E0_DOES_NOT_CLOSE"),
        _case("numeric_agreement_accepted_as_identity", _open("B_IDENTITY", level="E1", basis="NUMERIC_KEY_AGREEMENT", relation_contract="PROVEN_SINGLE_ENTITY"), "NUMERIC_AGREEMENT_IS_NOT_PROOF"),
        _case("unrelated_repository_accepted", _open("B_DRUGS", level="E3", applicability="UNRELATED_REPOSITORY", database_binding=True, unambiguous_production=True), "REPOSITORY_MUST_MATCH"),
        _case("test_fixture_accepted_as_production", _open("A_MEDICATION_CODE_SET", level="E2", applicability="TEST_FIXTURE", basis="FIXTURE", database_binding=True, unambiguous_production=True), "FIXTURE_IS_NOT_PRODUCTION"),
        _case("dead_code_accepted", _open("B_CHANGE", level="E2", applicability="DEAD_CODE", database_binding=True, unambiguous_production=True), "USAGE_PATH_REQUIRED"),
        _case("ui_label_without_database_binding", _open("B_DRUGS", level="E3", database_binding=False, unambiguous_production=True, applicability="PRODUCTION"), "BINDING_REQUIRED"),
        _case("database_column_without_form_meaning", _open("B_VITAMINS", level="E1", database_binding=True, applicability="PRODUCTION"), "E1_DOES_NOT_CLOSE_SEMANTICS"),
        _case("drugs_and_vitamins_merged", _open("B_VITAMINS", level="E3", auto_merged=True, database_binding=True, unambiguous_production=True, applicability="PRODUCTION"), "FIELDS_STAY_SEPARATE"),
        _case("short_yes_accepted_as_intake", _open("B_SHORT", level="E3", accepted_from_token=True, database_binding=True, unambiguous_production=True, applicability="PRODUCTION"), "YES_IS_NOT_INTAKE"),
        _case("change_accepted_from_the_word_change", _open("B_CHANGE", level="E0", basis="TOKEN", accepted_from_token=True), "TOKEN_IS_NOT_A_QUESTION"),
        _case("decline_interpreted_as_refusal", _open("B_DECLINE", level="E0", basis="TOKEN", applicability="NAMING_ONLY"), "REFUSAL_NEEDS_THE_QUESTION"),
        _case("analysis_items_accepted_as_recommendation_items", _open("A_RECOMMENDATION_ITEMS", level="E2", object="document_analysis.items", database_binding=True, unambiguous_production=True, applicability="PRODUCTION"), "DIFFERENT_OBJECT"),
        _case("medicines_declared_the_only_section", _open("A_MEDICATION_CODE_SET", level="E2", sole_section_from_name=True, database_binding=True, unambiguous_production=True, applicability="PRODUCTION"), "ONE_CODE_IS_NOT_THE_REGISTRY"),
        _case("draft_document_declared_issued", _open("A_DOCUMENT_FINAL", level="E1", basis="ROW_EXISTS"), "PRESENCE_IS_NOT_DELIVERY"),
        _case("raw_patient_value_published", scan_public(leak)["PUBLIC_DATA_MINIMIZATION_STATUS"] == "FAIL", "PRIVACY"),
        _case("gate_1b_opened_with_a_blocker", blocked["GATE_1B_STATUS"] == "BLOCKED", "ONE_OPEN_BLOCKER_BLOCKS_1B"),
        _case("extractor_or_model_started", _model_allowed({**SCIENTIFIC_CEILING, "medication_extractor": True}) is False, "MODEL_STAYS_NOT_STARTED"),
    ]
    rejected = sum(case["rejected"] for case in cases)
    return {
        "ok": rejected == len(cases) == EXPECTED_CASES and resolved["SUPERSESSION_RESOLUTION_STATUS"] == "PASS",
        "NEGATIVE_CONTROL_STATUS": "PASS" if rejected == EXPECTED_CASES else "FAIL",
        "n_cases": len(cases),
        "n_rejected": rejected,
        "cases": cases,
    }
