"""Render the v0.2.2 report from computed objects only."""

from __future__ import annotations

from typing import Any

from human_simulator.exposure_source_discovery_v022.policy import VERSION


def render(status: dict[str, Any], fields: list[dict[str, Any]], evidence: dict[str, Any], validation: dict[str, Any]) -> str:
    link = evidence["medicine_appointment_link"]
    shape = evidence["recommendation_shape"]
    lines = [
        f"# Exposure source discovery v{VERSION} — owner semantic decisions",
        "",
        "**Report status: FINAL (decision ingestion only)**",
        "",
        "Not Stage 05 Gate 1. No medication extractor, mapping acceptance, cohort, model, or review ZIP.",
        "Answers come from the system architect (`role=system_architect`), relayed verbally and recorded",
        "in `owner-answer-record.json`. Each decision is bound to its answer by `evidence_sha256`.",
        "",
        "## Status",
        "",
    ]
    for key in (
        "TECHNICAL_DISCOVERY_STATUS",
        "DECISION_SCHEMA_VALIDATION_STATUS",
        "OWNER_SEMANTIC_REVIEW_STATUS",
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS",
        "SOURCE_B_SUBJECT_IDENTITY_DATA_PROOF_STATUS",
        "SOURCE_B_TIMEZONE_SEMANTICS_STATUS",
        "FEEDBACK_REPORTING_WINDOW_STATUS",
        "SOURCE_B_TEMPORAL_SEQUENCE_STATUS",
        "SOURCE_A_MEDICATION_SECTION_STATUS",
        "SOURCE_A_ACTIVITY_SECTION_STATUS",
        "SOURCE_A_V02_DOSE_SIGNAL_INTERPRETATION_STATUS",
        "SOURCE_A_MEDICINE_ASSIGNMENT_SEMANTICS",
        "CROSS_SOURCE_IDENTITY_LINKAGE_STATUS",
        "PATIENT_REPORTED_INTAKE_TIER_STATUS",
        "CONFIRMED_ADMINISTRATION_MAPPING_COUNT",
        "DOMAIN_ACCEPTED_MAPPING_COUNT",
        "INTERVENTION_RESPONSE_READINESS_STATUS",
        "PUBLIC_DATA_MINIMIZATION_STATUS",
        "NEGATIVE_CONTROL_STATUS",
    ):
        lines.append(f"- `{key}`={status.get(key)}")
    lines += [
        "",
        "## Field statuses",
        "",
        "| Source | Field | Status | Decision |",
        "|---|---|---|---|",
    ]
    for item in fields:
        lines.append(f"| {item['source_system']} | `{item['field_path']}` | {item['status']} | {item.get('decision') or '—'} |")
    lines += [
        "",
        "## Source A evidence (aggregate, query identifiers in `query-log.json`)",
        "",
        "- Recommendation section catalog (`a_template_categories`):",
    ]
    for cat in evidence["template_categories"]:
        lines.append(f"  - `{cat['code']}` = {cat['label']}")
    lines += [
        f"- Item keys (`a_item_keys`): {', '.join(f'{k}={v}' for k, v in sorted(evidence['item_key_counts'].items()))}.",
        f"- Recommendation documents (`a_recommendation_shape`): documents={shape['documents']}, "
        f"distinct_appointments={shape['distinct_appointments']}, one_per_appointment={shape['one_document_per_appointment']}.",
        f"- Medicine catalog (`a_medicine_catalog`): "
        f"{', '.join(f'{k}={v}' for k, v in sorted(evidence['medicine_catalog_by_category'].items()))}.",
        f"- Assignment statuses (`a_medicine_status`): "
        f"{', '.join(f'{k}={v}' for k, v in sorted(evidence['medicine_assignment_status_counts'].items()))}.",
        f"- Assignment→appointment links (`a_medicine_link`): link_rows={link['link_rows']}, "
        f"resolving={link['link_rows_resolving_to_assignment']}, distinct_appointments={link['distinct_appointments']}, "
        f"with_recommendation_document={link['distinct_appointments_with_recommendation_document']}, "
        f"assignments_on_several_appointments={link['assignments_linked_to_more_than_one_appointment']}.",
        "",
        "The v0.2 dose-like signal in `activity` cannot be read as medication evidence: the catalog label of",
        "`activity` is a lifestyle section. A code fixture (`baker_recipes.py`) uses a different label and is not",
        "production data.",
        "",
        "## Source B",
        "",
        f"Candidate chains from v0.2.1: {status['SOURCE_B_CANDIDATE_CHAIN_COUNT']}/{status['SOURCE_B_CANDIDATE_CHAIN_DENOMINATOR']}.",
        "The owner confirms that feedback is filled before a consultation and, for a repeat visit, covers the",
        "period since the previous visit. The subject statement is recorded with a recall caveat and is not data proof.",
        "",
        "## Unresolved",
        "",
        "- `public.feedback.drugs_first`, `positive_changes`, short «да»/«нет» values: UNKNOWN.",
        "- `public.consultations.date` null cause: UNKNOWN.",
        "- `drugs`/`vitamins` meaning and subject equality: owner recall uncertain.",
        "- Whether a Source A recommendation document reached the patient: UNKNOWN.",
        "",
        f"Decisions: {validation['decision_count']} of {validation['answer_count']} answers; "
        f"{validation['non_deciding_answer_count']} answers create no decision.",
        "",
    ]
    return "\n".join(lines)
