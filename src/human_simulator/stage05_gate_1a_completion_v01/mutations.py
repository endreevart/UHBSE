"""Negative controls for the scope records. Prior Gate 1A records are only read."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.stage05_gate_1a_completion_v01.contract import derive, violations
from human_simulator.stage05_gate_1a_completion_v01.policy import UNCOMPARABLE
from human_simulator.stage05_gate_1a_completion_v01.prior import load_prior, temporal_scope, verify_answer_binding
from human_simulator.stage05_gate_1a_completion_v01.recovery import search_form_schema
from human_simulator.stage05_gate_1a_completion_v01.supersede import (
    build_superseding,
    period_applies_to_visit,
    timing_applies_to_category,
)

EXPECTED_CASES = 12


def _case(name: str, rejected: bool, reason: str) -> dict[str, Any]:
    return {"control": name, "rejected": bool(rejected), "reason": reason if rejected else "NOT_REJECTED"}


def run_negative_controls(root: Path, tmp: Path) -> dict[str, Any]:
    prior = load_prior(root)
    temporal = temporal_scope(root)
    answers = verify_answer_binding(root, prior)
    recovery = {"SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS": "NOT_FOUND", "superseding_records_created_from_code": 0}
    superseding = build_superseding(prior, temporal)
    status = derive(prior, superseding, recovery)
    clean = answers["ok"] and not violations(status, prior, superseding, True, recovery)

    changed_decision = copy.deepcopy(superseding)
    changed_decision[0]["decision"] = "FILLED_ON_EVERY_ROW"
    opened = {**status, "GATE_1B_STATUS": "OPEN"}
    ready = {**status, "INTERVENTION_RESPONSE_READINESS_STATUS": "READY"}
    cells = {**status, "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 1}
    assigned = {**status, "B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT": 10}
    closed = copy.deepcopy(superseding)
    closed[0]["closes_question"] = True
    closed[0]["row_level_proof"] = True
    period = copy.deepcopy(superseding)
    period[1]["requires_first_vs_repeat_visit_classification"] = False
    invented = copy.deepcopy(superseding)
    invented.append({**superseding[0], "question_id": "B_DRUGS", "decision": "ACCEPTED_FROM_CODE"})
    from_code = {**recovery, "superseding_records_created_from_code": 1}

    def broken(records: list[dict[str, Any]], current: dict[str, Any], found: dict[str, Any] | None = None) -> bool:
        return bool(violations(current, prior, records, True, found or recovery))

    leak = tmp / "numeric-id"
    leak.mkdir(parents=True, exist_ok=True)
    (leak / "leak.json").write_text(json.dumps({"patient_id": 15}) + "\n", encoding="utf-8")
    absent = search_form_schema(tmp / "missing-code")

    cases = [
        _case("workflow_decision_text_changed", broken(changed_decision, status), "PRIOR_DECISION_STAYS"),
        _case("workflow_scope_closed_as_row_proof", broken(closed, status), "SCOPE_IS_NOT_ROW_PROOF"),
        _case("period_without_visit_classification", broken(period, status), "PERIOD_NEEDS_VISIT_CLASS"),
        _case("timing_applied_to_uncomparable_rows", timing_applies_to_category(UNCOMPARABLE, temporal) is False, "UNCOMPARABLE_ROWS_EXCLUDED"),
        _case("period_applied_without_visit_class", period_applies_to_visit(None) is False, "VISIT_CLASS_REQUIRED"),
        _case("gate_1b_opened_with_open_blockers", broken(superseding, opened), "GATE_1B_STAYS_BLOCKED"),
        _case("readiness_claimed", broken(superseding, ready), "READINESS_STAYS_NOT_READY"),
        _case("eligible_cell_counted", broken(superseding, cells), "ELIGIBLE_CELLS_STAY_ZERO"),
        _case("period_rows_assigned_without_classification", broken(superseding, assigned), "NO_ROW_ASSIGNMENT"),
        _case("blocker_accepted_without_new_evidence", broken(invented, status), "NO_INVENTED_ACCEPTANCE"),
        _case("code_search_creates_a_decision", broken(superseding, status, from_code), "CODE_MISS_CREATES_NOTHING"),
        _case("missing_code_root_creates_nothing", absent["superseding_records_created_from_code"] == 0, "NO_CODE_NO_DECISION"),
    ]
    privacy_rejects = scan_public(leak)["PUBLIC_DATA_MINIMIZATION_STATUS"] == "FAIL"
    rejected = sum(case["rejected"] for case in cases)
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
