"""Report the scope correction and the still-open Gate 1A questions."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate_1a_completion_v01.policy import VERSION


def render(status: dict[str, Any], superseding: list[dict[str, Any]], binding: dict[str, Any], temporal: dict[str, Any]) -> str:
    lines = [
        f"# Stage 05 Gate 1A completion v{VERSION}",
        "",
        "**Report status: FINAL (Gate 1A still open)**",
        "",
        "Adds superseding scope records for `B_TIMING` and `B_PERIOD`. The Gate 1A v0.1 decision records are not rewritten.",
        "No database queries and no extractor.",
        "",
        "## Status",
        "",
        f"- `GATE_1A_COMPLETION_STATUS`={status['GATE_1A_COMPLETION_STATUS']}",
        f"- `GATE_1A_STATUS`={status['GATE_1A_STATUS']}",
        f"- `GATE_1B_STATUS`={status['GATE_1B_STATUS']}",
        f"- `INTERVENTION_RESPONSE_READINESS_STATUS`={status['INTERVENTION_RESPONSE_READINESS_STATUS']}",
        f"- `INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT`={status['INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT']}",
        f"- `SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS`={status['SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS']}",
        f"- `VISIT_CLASSIFICATION_STATUS`={status['VISIT_CLASSIFICATION_STATUS']}",
        f"- `B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT`={status['B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT']}",
        "",
        "## Answer binding",
        "",
        f"v0.2.2 answer record `{binding['answer_record_path']}` sha256 `{binding['answer_record_sha256']}`.",
        f"Every Gate 1A evidence hash resolves to an answer in that file: {binding['ok']}.",
        "Per-answer recomputed hashes are in `answer-evidence-binding.json`.",
        "",
        "## Workflow scope",
        "",
        f"`{temporal['uncomparable_category']}` has {temporal['uncomparable_count']} rows in `{temporal['ledger_path']}`.",
        "Those rows, including null consultation dates, are outside `FILLED_BEFORE_CONSULTATION`.",
        "The period rule applies only after a row is classified as a first visit or a repeat visit. That classification was not performed.",
        "",
        "| Question | Scope | Visit classification required | Closes row-level question |",
        "|---|---|---|---|",
    ]
    for record in superseding:
        lines.append(
            f"| `{record['question_id']}` | `{record['attestation_scope']}` | "
            f"{record['requires_first_vs_repeat_visit_classification']} | {record['closes_question']} |"
        )
    lines += [
        "",
        "## Gate 1B",
        "",
        "Blocked by: " + ", ".join(f"`{item}`" for item in status["GATE_1B_BLOCKERS"]) + ".",
        "Deferred for an exposure-only extractor, and not a response label: "
        + ", ".join(f"`{item}`" for item in status["EXPOSURE_EXTRACTOR_DEFERRED_QUESTIONS"]) + ".",
        "Source A still open: " + ", ".join(f"`{item}`" for item in status["SOURCE_A_OPEN_QUESTIONS"]) + ".",
        "",
        "No Source B form schema for these fields was found in the Magerya application code.",
        "Magerya `DoctorFeedback` is a different object and was not used as Source B evidence.",
        "No new owner answers were recorded, so none of the blocking questions gained a superseding decision.",
        "",
    ]
    return "\n".join(lines)
