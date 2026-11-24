"""Render the owner-attestation report from the status contract."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate1a_owner_attestation_v01.policy import VERSION


def render(status: dict[str, Any]) -> str:
    lines = [
        f"# Stage 05 Gate 1A owner attestation v{VERSION}",
        "",
        "**Report status: FINAL (Source B route accepted, Source A open)**",
        "",
        "The system architect answered the six Source B blockers on 2026-11-17.",
        "The answers are recorded without widening them.",
        "Gate 1B was not started.",
        "",
        "## Status",
        "",
    ]
    for key in (
        "GATE_1A_OWNER_ATTESTATION_STATUS",
        "GATE_1A_STATUS",
        "GATE_1A_SOURCE_B_EXPOSURE_ROUTE_STATUS",
        "GATE_1B_STATUS",
        "INTERVENTION_RESPONSE_READINESS_STATUS",
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT",
        "INTERVENTION_RESPONSE_MODEL_STATUS",
        "B_POSITIVE",
    ):
        lines.append(f"- `{key}`={status.get(key)}")
    lines += [
        "",
        "`drugs` and `vitamins` are current intake and stay separate.",
        "`change_drugs` is replacement. `decline_drugs` is discontinuation.",
        "`drugs_first` is previously prescribed.",
        "`feedback.user_id` and `consultations.patient_id` are the same `users.id`. There is still no database foreign key.",
        "Short yes and no are free text. Yes is not confirmed intake.",
        "`B_POSITIVE` stays deferred and is not a response label.",
        "Timing and period still assign 0 rows.",
        "",
    ]
    return "\n".join(lines)
