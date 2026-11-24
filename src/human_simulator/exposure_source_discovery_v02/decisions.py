"""Human semantic decision gate. No automatic contact."""

from __future__ import annotations

QUESTIONS = [
    (1, "magerya_api", "document_recommendation.document.recommendations[].code",
     "Какие коды разделов содержат назначения препаратов и БАДов?"),
    (2, "magerya_api", "document_recommendation.document.recommendations[].items",
     "Что именно находится в recommendations[].items?"),
    (3, "magerya_api", "document_recommendation",
     "Является ли документ финальной версией, показанной или выданной пациенту?"),
    (4, "kgz_raw", "public.feedback", "Кто заполняет feedback?"),
    (5, "kgz_raw", "public.feedback.created_at", "Заполняется ли feedback перед следующей консультацией?"),
    (6, "kgz_raw", "public.feedback", "Какой период должен описывать респондент?"),
    (7, "kgz_raw", "public.feedback.user_id",
     "Указывает ли feedback.user_id на того же субъекта, что consultations.patient_id?"),
    (8, "kgz_raw", "public.feedback.drugs",
     "Что означают drugs, drugs_first и vitamins?"),
    (9, "kgz_raw", "public.feedback.change_drugs",
     "Что означают change_drugs и decline_drugs?"),
    (10, "kgz_raw", "public.feedback.change_drugs",
     "Относится ли изменение к рекомендации конкретного врача или консультации?"),
    (11, "kgz_raw", "public.feedback.positive_changes",
     "Что означает positive_changes и к какому периоду оно относится?"),
    (12, "kgz_raw", "public.feedback",
     "Являются ли короткие значения вроде «нет» и «да» штатными вариантами формы?"),
]


def questions_markdown() -> str:
    lines = [
        "# Owner questions — exposure source discovery v0.2",
        "",
        "Do not answer these inside the pipeline. Do not send mail, messages, or calendar events.",
        "Until a decision matching `semantic-decision.schema.json` is recorded, every field meaning",
        "stays `UNKNOWN_PENDING_HUMAN_REVIEW`.",
        "",
    ]
    for number, source, path, text in QUESTIONS:
        lines.append(f"{number}. `{source}` `{path}` — {text}")
    lines.append("")
    return "\n".join(lines)


def response_template() -> dict:
    return {
        "version": "0.2",
        "responses": [
            {
                "question_id": number,
                "source_system": source,
                "field_path": path,
                "reviewer_digest": None,
                "role": None,
                "decision": None,
                "basis": None,
                "decided_at": None,
                "evidence_sha256": None,
                "decision_schema_version": "0.2",
            }
            for number, source, path, _text in QUESTIONS
        ],
        "automatic_contact": False,
    }


def decision_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "uhbse/exposure-source-discovery/semantic-decision/0.2",
        "type": "object",
        "required": [
            "reviewer_digest", "role", "source_system", "field_path", "decision",
            "basis", "decided_at", "evidence_sha256", "decision_schema_version",
        ],
        "properties": {
            "reviewer_digest": {"type": "string", "minLength": 16},
            "role": {"type": "string", "minLength": 2},
            "source_system": {"enum": ["magerya_api", "kgz_raw"]},
            "field_path": {"type": "string", "minLength": 3},
            "decision": {"type": "string", "minLength": 1},
            "basis": {"type": "string", "minLength": 1},
            "decided_at": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}T.*Z$"},
            "evidence_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "decision_schema_version": {"const": "0.2"},
        },
        "additionalProperties": False,
    }


def semantics_status(responses: list[dict] | None) -> str:
    if not responses:
        return "UNKNOWN_PENDING_HUMAN_REVIEW"
    required = set(decision_schema()["required"])
    complete = all(required <= set(item) and all(item.get(key) for key in required) for item in responses)
    return "RECORDED" if complete else "UNKNOWN_PENDING_HUMAN_REVIEW"
