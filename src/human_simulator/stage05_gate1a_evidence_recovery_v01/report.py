"""Render the evidence-recovery report from computed status values."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import VERSION


def render(status: dict[str, Any]) -> str:
    lines = [
        f"# Stage 05 Gate 1A primary evidence recovery v{VERSION}",
        "",
        "**Report status: FINAL (Gate 1A still open)**",
        "",
        "Primary evidence was read from database catalogs and the configured Magerya checkout.",
        "No Source B application repository was available. No new question was closed.",
        "",
        "## Status",
        "",
    ]
    for key in (
        "GATE_1A_EVIDENCE_RECOVERY_STATUS",
        "GATE_1A_STATUS",
        "GATE_1A_SOURCE_B_EXPOSURE_ROUTE_STATUS",
        "GATE_1B_STATUS",
        "SOURCE_B_APPLICATION_CODE_ACCESS_STATUS",
        "SOURCE_B_FORM_SEMANTICS_STATUS",
        "SUPERSESSION_RESOLUTION_STATUS",
        "EFFECTIVE_B_TIMING_CLOSES_QUESTION",
        "EFFECTIVE_B_PERIOD_CLOSES_QUESTION",
        "B_TIMING_ROW_LEVEL_ASSIGNMENT_COUNT",
        "B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT",
        "NEW_SUPERSEDING_RECORD_COUNT",
        "INTERVENTION_RESPONSE_READINESS_STATUS",
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT",
        "INTERVENTION_RESPONSE_MODEL_STATUS",
        "PUBLIC_DATA_MINIMIZATION_STATUS",
        "NEGATIVE_CONTROL_STATUS",
    ):
        lines.append(f"- `{key}`={status.get(key)}")
    lines += [
        "",
        "Accepted decisions remain 4 and insufficient decisions remain 10.",
        "The workflow rules for timing and period are not applied to any feedback row.",
        "`B_IDENTITY` has a consultation-row foreign key and no subject-key foreign key.",
        "That is schema evidence, not identity proof.",
        "",
        "Source B blockers stay open: `B_IDENTITY`, `B_DRUGS`, `B_VITAMINS`, `B_CHANGE`, `B_DECLINE`, `B_SHORT`.",
        "`B_POSITIVE` stays deferred and is not a response label.",
        "Source A stays open: `A_RECOMMENDATION_ITEMS`, `A_MEDICATION_CODE_SET`, `A_DOCUMENT_FINAL`.",
        "",
        "Absence from the Magerya checkout is not treated as absence of a Source B form.",
        "Gate 1B was not started.",
        "",
    ]
    return "\n".join(lines)
