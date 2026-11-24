"""Structural probes in the Magerya checkout. A matching snippet is not field semantics by itself."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from human_simulator.stage05_gate1a_evidence_recovery_v01.search import magerya_root

_PROBES = (
    ("apps/document/models/recommendation/v1_0.py", "['name', 'description']", "ITEM_NAME_AND_DESCRIPTION"),
    ("apps/document/models/recommendation/models.py", "appointment = models.OneToOneField", "ONE_DOCUMENT_PER_APPOINTMENT"),
    ("apps/document/lk_doctor/views.py", "ActiveRelatedAppointmentOrReadOnly", "EDITABLE_WHILE_APPOINTMENT_ACTIVE"),
    ("apps/document/lk_doctor/serializers.py", "instance.document = document", "WHOLE_DOCUMENT_REPLACE"),
    ("apps/appointment/services.py", "for category in RecommendationCategory.objects.all()", "ITEMS_COPIED_FROM_TEMPLATES"),
    ("apps/document/baker_recipes.py", "code='activity'", "ACTIVITY_LABEL_FIXTURE"),
    ("apps/account/back_office/serializers.py", "class CrmDoctorFeedbackSerializer", "DOCTOR_FEEDBACK_OBJECT"),
    ("apps/account/models/employee.py", "class DoctorFeedback", "DOCTOR_FEEDBACK_MODEL"),
)


def _read(root: Path, relative: str) -> tuple[str, str] | None:
    path = root / relative
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace"), hashlib.sha256(path.read_bytes()).hexdigest()


def source_a_code_evidence() -> dict[str, Any]:
    root = magerya_root()
    probes = []
    for relative, snippet, symbol in _PROBES:
        loaded = _read(root, relative)
        found = loaded is not None and snippet in loaded[0]
        line = None
        if found and loaded is not None:
            line = next(index for index, text in enumerate(loaded[0].splitlines(), start=1) if snippet in text)
        probes.append({
            "path": relative,
            "symbol": symbol,
            "found": found,
            "line": line,
            "file_sha256": loaded[1] if loaded else None,
            "production_applicable": symbol != "ACTIVITY_LABEL_FIXTURE",
            "applicability": "TEST_FIXTURE" if symbol == "ACTIVITY_LABEL_FIXTURE" else "SOURCE_A_CODE",
        })
    by_symbol = {item["symbol"]: item for item in probes}
    return {
        "code_root_available": root.is_dir(),
        "probes": probes,
        "recommendation_items": {
            "question_id": "A_RECOMMENDATION_ITEMS",
            "level": "E2" if by_symbol["ITEM_NAME_AND_DESCRIPTION"]["found"] else "NONE",
            "applicability": "STRUCTURE_ONLY",
            "object": "document_recommendation.document.recommendations[].items",
            "analysis_items_used": False,
            "database_binding": False,
            "unambiguous_production": False,
            "closes_question": False,
            "observed_contract": "name_and_description" if by_symbol["ITEM_NAME_AND_DESCRIPTION"]["found"] else None,
            "ambiguities": [
                "the doctor serializer replaces the whole document",
                "description is unconstrained text",
                "document_analysis.items is a different object and is not evidence here",
            ],
        },
        "document_lifecycle_code": {
            "one_document_field_found": by_symbol["ONE_DOCUMENT_PER_APPOINTMENT"]["found"],
            "editable_while_appointment_active": by_symbol["EDITABLE_WHILE_APPOINTMENT_ACTIVE"]["found"],
            "whole_document_replace": by_symbol["WHOLE_DOCUMENT_REPLACE"]["found"],
            "patient_delivery_path": "NOT_FOUND",
            "closes_question": False,
        },
        "doctor_feedback": {
            "object": "DoctorFeedback",
            "source_system": "magerya_api",
            "is_source_b_feedback": False,
            "applicability": "UNRELATED_FORM",
            "closes_source_b_question": False,
            "serializer_found": by_symbol["DOCTOR_FEEDBACK_OBJECT"]["found"],
            "model_found": by_symbol["DOCTOR_FEEDBACK_MODEL"]["found"],
        },
        "activity_fixture_rejected": by_symbol["ACTIVITY_LABEL_FIXTURE"]["found"],
    }
