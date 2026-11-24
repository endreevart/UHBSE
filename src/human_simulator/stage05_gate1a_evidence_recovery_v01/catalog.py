"""Read-only catalog evidence. No row values."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.db import QueryLog, connect_a, connect_b, schema_fingerprint
from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import FORM_FIELDS, NUMERIC_PHRASE

_B_TABLES = [("public", "feedback"), ("public", "consultations")]
_A_TABLES = [
    ("magerya_api", "document_recommendation"),
    ("magerya_api", "document_recommendationtemplatecategory"),
    ("magerya_api", "diagnosis_recommendationcategory"),
]

_B_CONSTRAINTS = """
SELECT c.relname, con.contype, pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relname IN ('feedback', 'consultations')
ORDER BY 1, 3
"""
_B_COLUMNS = """
SELECT table_name, column_name, data_type, is_nullable,
       col_description((table_schema || '.' || table_name)::regclass, ordinal_position)
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name IN ('feedback', 'consultations')
ORDER BY 1, ordinal_position
"""
_B_TRIGGERS = """
SELECT event_object_table, trigger_name
FROM information_schema.triggers
WHERE event_object_schema = 'public' AND event_object_table IN ('feedback', 'consultations')
ORDER BY 1, 2
"""
_B_VIEWS = """
SELECT table_schema, table_name
FROM information_schema.views
WHERE table_schema IN ('public', 'quest_digital')
  AND (position('feedback' in table_name) > 0 OR position('consult' in table_name) > 0)
ORDER BY 1, 2
"""
_A_COLUMNS = """
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'magerya_api' AND table_name = 'document_recommendation'
ORDER BY ordinal_position
"""
_A_CONSTRAINTS = """
SELECT con.contype, pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'magerya_api' AND c.relname = 'document_recommendation'
ORDER BY 2
"""
_A_TEMPLATE_CODES = """
SELECT code, name, prohibit_deletion
FROM magerya_api.document_recommendationtemplatecategory
ORDER BY code
"""
_A_DIAGNOSIS_CODES = """
SELECT code, name
FROM magerya_api.diagnosis_recommendationcategory
ORDER BY code
"""
_KIND = {"f": "FOREIGN_KEY", "p": "PRIMARY_KEY", "u": "UNIQUE", "c": "CHECK"}


def _comment(value: Any) -> dict[str, Any]:
    if not value:
        return {"comment_present": False}
    text = str(value)
    return {
        "comment_present": True,
        "comment_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "comment_length": len(text),
    }


def _run(root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    b_conn = connect_b(root)
    try:
        b_log = QueryLog(schema_fingerprint(b_conn, _B_TABLES))
        constraints = b_log.run(b_conn, "b_constraints", "kgz_raw", _B_CONSTRAINTS)
        columns = b_log.run(b_conn, "b_columns", "kgz_raw", _B_COLUMNS)
        triggers = b_log.run(b_conn, "b_triggers", "kgz_raw", _B_TRIGGERS)
        views = b_log.run(b_conn, "b_views", "kgz_raw", _B_VIEWS)
        entries.extend(b_log.entries)
    finally:
        b_conn.close()
    a_conn = connect_a(root)
    try:
        a_log = QueryLog(schema_fingerprint(a_conn, _A_TABLES))
        document_columns = a_log.run(a_conn, "a_document_columns", "magerya_api", _A_COLUMNS)
        document_constraints = a_log.run(a_conn, "a_document_constraints", "magerya_api", _A_CONSTRAINTS)
        template_codes = a_log.run(a_conn, "a_template_codes", "magerya_api", _A_TEMPLATE_CODES)
        diagnosis_codes = a_log.run(a_conn, "a_diagnosis_codes", "magerya_api", _A_DIAGNOSIS_CODES)
        entries.extend(a_log.entries)
    finally:
        a_conn.close()
    source_b = {
        "constraints": [
            {"relation": rel, "type": _KIND.get(ctype, ctype), "definition": definition}
            for rel, ctype, definition in constraints
        ],
        "columns": [
            {
                "relation": rel,
                "column": column,
                "data_type": data_type,
                "nullable": nullable == "YES",
                **_comment(comment),
            }
            for rel, column, data_type, nullable, comment in columns
        ],
        "trigger_names": [name for _, name in triggers],
        "views": [{"schema": schema, "name": name} for schema, name in views],
    }
    source_a = {
        "document_columns": [{"column": column, "data_type": data_type} for column, data_type in document_columns],
        "document_constraints": [
            {"type": _KIND.get(ctype, ctype), "definition": definition}
            for ctype, definition in document_constraints
        ],
        "template_categories": [
            {"code": code, "label": label, "prohibit_deletion": bool(locked)}
            for code, label, locked in template_codes
        ],
        "diagnosis_categories": [{"code": code, "label": label} for code, label in diagnosis_codes],
    }
    return source_b, source_a, entries


def identity_evidence(source_b: dict[str, Any]) -> dict[str, Any]:
    definitions = [item["definition"] for item in source_b["constraints"] if item["type"] == "FOREIGN_KEY"]
    user_fk = [item for item in definitions if "user_id" in item]
    patient_fk = [item for item in definitions if "patient_id" in item]
    consultation_fk = [item for item in definitions if "consultation_id" in item]
    columns = {
        (item["relation"], item["column"]): item["data_type"]
        for item in source_b["columns"]
        if item["column"] in {"user_id", "patient_id", "consultation_id", "id"}
    }
    return {
        "question_id": "B_IDENTITY",
        "level": "E1",
        "applicability": "SCHEMA_ONLY",
        "relation_contract": "NOT_FOUND",
        "closes_question": False,
        "basis": None,
        "phrase": NUMERIC_PHRASE,
        "numeric_agreement_is_proof": False,
        "feedback_user_id_foreign_keys": user_fk,
        "consultations_patient_id_foreign_keys": patient_fk,
        "feedback_consultation_foreign_keys": consultation_fk,
        "consultation_link_is_not_subject_identity": True,
        "column_types": [
            {"relation": "feedback", "column": "user_id", "data_type": columns.get(("feedback", "user_id"))},
            {"relation": "consultations", "column": "patient_id", "data_type": columns.get(("consultations", "patient_id"))},
            {"relation": "feedback", "column": "consultation_id", "data_type": columns.get(("feedback", "consultation_id"))},
        ],
        "shared_parent_constraint": False,
        "trigger_count": len(source_b["trigger_names"]),
        "view_count": len(source_b["views"]),
        "ambiguities": [
            "INTEGER types match and do not identify a shared entity",
            "FOREIGN KEY (consultation_id) links a feedback row to a consultation row",
            "no foreign key, parent entity, or check constraint links user_id to patient_id",
        ],
    }


def form_evidence(source_b: dict[str, Any], code_access: str) -> dict[str, Any]:
    present = {item["column"] for item in source_b["columns"] if item["relation"] == "feedback"}
    fields = []
    for column in (*FORM_FIELDS, "short_yes_no"):
        physical = column if column != "short_yes_no" else None
        fields.append({
            "question_id": {
                "drugs": "B_DRUGS",
                "vitamins": "B_VITAMINS",
                "change_drugs": "B_CHANGE",
                "decline_drugs": "B_DECLINE",
                "positive_changes": "B_POSITIVE",
                "drugs_first": "B_DRUGS_FIRST",
                "short_yes_no": "B_SHORT",
            }[column],
            "column": physical,
            "column_present": physical in present if physical else False,
            "level": "E1" if physical in present else "NONE",
            "applicability": "SCHEMA_ONLY" if physical in present else "NOT_A_COLUMN",
            "label": None,
            "help_text": None,
            "answer_type": None,
            "options": None,
            "default": None,
            "required": None,
            "database_binding": False,
            "closes_question": False,
            "user_facing_form": "NOT_RECOVERED",
        })
    return {
        "SOURCE_B_APPLICATION_CODE_ACCESS_STATUS": code_access,
        "SOURCE_B_FORM_SEMANTICS_STATUS": "NOT_RECOVERED_APPLICATION_CODE_NOT_AVAILABLE",
        "absence_claim": None,
        "drugs_and_vitamins_merged": False,
        "short_yes_accepted_as_intake": False,
        "fields": fields,
    }


def section_evidence(source_a: dict[str, Any]) -> dict[str, Any]:
    codes = [item["code"] for item in source_a["template_categories"]]
    return {
        "question_id": "A_MEDICATION_CODE_SET",
        "level": "E1",
        "applicability": "CATALOG_ONLY",
        "closes_question": False,
        "medicines_already_accepted": True,
        "medicines_is_the_only_medication_section": False,
        "sole_section_from_name": False,
        "template_categories": source_a["template_categories"],
        "diagnosis_categories": source_a["diagnosis_categories"],
        "other_codes_remain_unknown": [code for code in codes if code != "medicines"],
        "dynamic_codes_possible": any(not item["prohibit_deletion"] for item in source_a["template_categories"]),
        "ambiguities": [
            "the catalog lists more than one section code",
            "a code label does not prove that the section cannot contain medication text",
        ],
    }


def document_evidence(source_a: dict[str, Any]) -> dict[str, Any]:
    columns = [item["column"] for item in source_a["document_columns"]]
    return {
        "question_id": "A_DOCUMENT_FINAL",
        "level": "E1",
        "applicability": "SCHEMA_ONLY",
        "closes_question": False,
        "basis": None,
        "issued_to_patient": None,
        "finalization_column_present": any(column in {"status", "finalized_at", "signed_at"} for column in columns),
        "document_columns": columns,
        "document_constraints": source_a["document_constraints"],
        "row_presence_is_not_delivery": True,
        "ambiguities": ["no finalization, signature, or delivery column on document_recommendation"],
    }
