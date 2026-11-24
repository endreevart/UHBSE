"""Render the Gate 1B pilot report from the status contract."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate1b_extractor_pilot_v01.policy import VERSION


def render(status: dict[str, Any]) -> str:
    executed = status.get("GATE_1B_PILOT_STATUS") == "EXECUTED_PRECISION_RECALL_NOT_MEASURED"
    lines = [
        f"# Stage 05 Gate 1B extractor pilot v{VERSION}",
        "",
        "**Report status: FINAL (gate open, precision/recall not measured)**" if executed
        else "**Report status: FINAL (gate open, extractor not executed)**",
        "",
        "The owner opened Gate 1B on 2026-11-17.",
        "The pilot counts candidate slots in Source B feedback." if executed
        else "The candidate extractor did not read Source B. No row was counted.",
        "A candidate is not an accepted medication and not administration.",
        "Private labels were not supplied, so precision and recall stay unmeasured.",
        "Gate 2 was not started.",
        "",
        "## Status",
        "",
    ]
    for key in (
        "GATE_1B_STATUS",
        "GATE_1B_PILOT_STATUS",
        "PRECISION_RECALL_STATUS",
        "PRIVATE_LABEL_SET_STATUS",
        "GATE_2_STATUS",
        "INTERVENTION_RESPONSE_READINESS_STATUS",
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT",
        "INTERVENTION_RESPONSE_MODEL_STATUS",
        "DOMAIN_ACCEPTED_MAPPING_COUNT",
        "PUBLIC_DATA_MINIMIZATION_STATUS",
        "stream_error_class",
    ):
        lines.append(f"- `{key}`={status.get(key)}")
    lines += [
        "",
        "`drugs` and `vitamins` stay separate current-intake fields.",
        "`change_drugs` counts a replacement statement. `decline_drugs` counts discontinuation.",
        "`drugs_first` counts previously prescribed text.",
        "Short yes and no are not a regimen.",
        "`positive_changes` is not extracted.",
        "Timing and period assign 0 rows.",
        "Source A stays open.",
        "",
    ]
    return "\n".join(lines)
