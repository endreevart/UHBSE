"""Render the Gate 1A report from decision records and derived statuses."""

from __future__ import annotations

from typing import Any

from human_simulator.stage05_gate_1a_v01.policy import QUESTIONS, VERSION


def render(
    status: dict[str, Any],
    records: list[dict[str, Any]],
    outside: list[dict[str, str]],
    validation: dict[str, Any],
) -> str:
    by_id = {record["question_id"]: record for record in records}
    lines = [
        f"# Stage 05 Gate 1A v{VERSION} — source-owner semantic confirmation",
        "",
        "**Report status: FINAL (attestation incomplete)**" if status["GATE_1A_ATTESTATION_STATUS"] == "INCOMPLETE"
        else f"**Report status: FINAL ({status['GATE_1A_ATTESTATION_STATUS']})**",
        "",
        "Human evidence gate over the frozen v0.2.2 answer record. No database queries, no extractor,",
        "no cohort, no model, no review ZIP.",
        "",
        "## Status",
        "",
    ]
    for key in (
        "GATE_1A_EXECUTION_STATUS",
        "GATE_1A_ATTESTATION_STATUS",
        "DECISION_SCHEMA_VALIDATION_STATUS",
        "SOURCE_A_RECOMMENDATION_SEMANTICS_STATUS",
        "SOURCE_B_FEEDBACK_SEMANTICS_STATUS",
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS",
        "SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS",
        "PATIENT_REPORTED_INTAKE_TIER_STATUS",
        "CONFIRMED_ADMINISTRATION_MAPPING_COUNT",
        "DOMAIN_ACCEPTED_MAPPING_COUNT",
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT",
        "INTERVENTION_RESPONSE_READINESS_STATUS",
        "INTERVENTION_RESPONSE_MODEL_STATUS",
        "PUBLIC_DATA_MINIMIZATION_STATUS",
        "NEGATIVE_CONTROL_STATUS",
    ):
        lines.append(f"- `{key}`={status.get(key)}")
    lines += [
        "",
        "A question is `accepted` only when the system architect stated an answer that addresses that question.",
        "Recall-uncertain, deferred, and unanswered items stay `insufficient`. `rejected` was not used.",
        "",
        "## Checklist",
        "",
        "| Question | Attestation | Closes | Decision |",
        "|---|---|---|---|",
    ]
    for spec in QUESTIONS:
        record = by_id[spec["question_id"]]
        lines.append(
            f"| `{record['question_id']}` | {record['attestation']} | {record['closes_question']} | `{record['decision']}` |"
        )
    accepted = sum(1 for record in records if record["attestation"] == "accepted")
    lines += [
        "",
        f"Accepted {accepted} of {len(records)}. Schema validation {validation['DECISION_SCHEMA_VALIDATION_STATUS']}.",
        "",
        "`medicines` is attested as a drug and supplement section. The complete set of such section codes is not",
        "attested, so the v0.2 dose-like signal in other sections stays unusable as medication evidence.",
        "The answer about items describes analysis components, not `recommendations[].items`.",
        "Whether the recommendation document is the final one given to the patient is not attested.",
        "",
        "Feedback author, timing, and reporting period are attested. Drug and vitamin meanings, change and decline",
        "meanings, positive changes, and short yes/no answers are not. Subject equality was stated with a recall",
        "caveat and is not accepted; it is not data proof.",
        "",
        "## Answers outside this gate",
        "",
    ]
    for item in outside:
        lines.append(f"- `{item['answer_key']}` {item['field_path']} ({item['certainty']})")
    lines += [
        "",
        "Gate 1B, Gate 2, and Gate 3 are not started.",
        "",
    ]
    return "\n".join(lines)
