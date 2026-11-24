"""Reject claims the pilot is not allowed to make."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate1b_extractor_pilot_v01.extract import parse_field


def _case(name: str, rejected: bool, reason: str) -> dict[str, str | bool]:
    return {"control": name, "rejected": rejected, "reason": reason if rejected else "NOT_REJECTED"}


def run_controls(status: dict[str, Any]) -> list[dict[str, str | bool]]:
    yes = parse_field("да", "CURRENT_INTAKE")
    no = parse_field("нет", "REPLACEMENT")
    dose = parse_field("400 мг", "CURRENT_INTAKE")
    policy = status["policy"]
    cases = [
        _case("yes_is_not_intake", not yes["yes_is_confirmed_intake"] and not yes["name_candidate"], "YES_TREATED_AS_INTAKE"),
        _case("no_is_not_a_replacement", not no["event_stated"] and not no["name_candidate"], "NO_TREATED_AS_REPLACEMENT"),
        _case("dose_without_name", dose["dose"] and not dose["name_candidate"], "DOSE_BECAME_A_NAME"),
        _case("decline_has_no_early_stop", not parse_field("отменила препарат", "DISCONTINUATION")["earlier_than_recommended"], "EARLY_STOP_ADDED"),
        _case("administration_stays_zero", parse_field("препарат 1 раз в день", "CURRENT_INTAKE")["accepted_administration"] is False, "ADMINISTRATION_CLAIMED"),
        _case("precision_without_labels", status["PRECISION_RECALL_STATUS"] == "NOT_MEASURED" and status["PRIVATE_LABEL_SET_STATUS"] == "ABSENT", "PRECISION_WITHOUT_PRIVATE_LABELS"),
        _case("synthetic_labels", policy["synthetic_labels_created"] is False, "SYNTHETIC_LABELS"),
        _case("model_training", status["INTERVENTION_RESPONSE_MODEL_STATUS"] == "NOT_STARTED" and policy["model_training"] is False, "MODEL_STARTED"),
        _case("eligible_cells", status["INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0, "CELLS_RECOMPUTED"),
        _case("domain_accepted", status["DOMAIN_ACCEPTED_MAPPING_COUNT"] == 0, "MAPPING_ACCEPTED"),
        _case("gate_2", status["GATE_2_STATUS"] == "CLOSED" and policy["gate_2_started"] is False, "GATE_2_OPENED"),
        _case("positive_changes", status["B_POSITIVE"] == "DEFERRED_NOT_EXTRACTED" and policy["response_label"] is False, "POSITIVE_CHANGES_EXTRACTED"),
    ]
    return cases


def controls_pass(cases: list[dict[str, Any]]) -> bool:
    return len(cases) == 12 and all(item["rejected"] is True for item in cases)
