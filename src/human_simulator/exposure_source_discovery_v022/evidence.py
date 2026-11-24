"""Source A code references and aggregate catalog evidence. Read-only; no row values leave the database."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.db import QueryLog
from human_simulator.exposure_source_discovery_v022.policy import (
    MAGERYA_CODE_FILES,
    MAGERYA_CODE_ROOT_DEFAULT,
    MAGERYA_CODE_ROOT_ENV,
)

SOURCE = "magerya_api"

_TEMPLATE_CATEGORIES_SQL = (
    "SELECT code, name, prohibit_deletion FROM magerya_api.document_recommendationtemplatecategory ORDER BY code"
)
_DIAGNOSIS_CATEGORIES_SQL = "SELECT code, name FROM magerya_api.diagnosis_recommendationcategory ORDER BY code"
_SECTION_USE_SQL = """
SELECT s->>'code' AS code, count(*) AS sections, sum(jsonb_array_length(coalesce(s->'items', '[]'::jsonb))) AS items
FROM magerya_api.document_recommendation r
CROSS JOIN LATERAL jsonb_array_elements(coalesce(r.document->'recommendations', '[]'::jsonb)) s
GROUP BY 1 ORDER BY 1
"""
_ITEM_KEYS_SQL = """
SELECT k, count(*)
FROM magerya_api.document_recommendation r
CROSS JOIN LATERAL jsonb_array_elements(coalesce(r.document->'recommendations', '[]'::jsonb)) s
CROSS JOIN LATERAL jsonb_array_elements(coalesce(s->'items', '[]'::jsonb)) i
CROSS JOIN LATERAL jsonb_object_keys(i) k
GROUP BY 1 ORDER BY 1
"""
_RECOMMENDATION_SHAPE_SQL = """
SELECT count(*), count(DISTINCT appointment_id), count(*) FILTER (WHERE appointment_id IS NULL),
       count(*) FILTER (WHERE _document IS NOT NULL)
FROM magerya_api.document_recommendation
"""
_MEDICINE_CATALOG_SQL = "SELECT category, count(*) FROM magerya_api.diagnosis_medicines GROUP BY 1 ORDER BY 1"
_MEDICINE_STATUS_SQL = "SELECT status, count(*) FROM magerya_api.diagnosis_medicineappointments GROUP BY 1 ORDER BY 1"
_MEDICINE_LINK_SQL = """
WITH ct AS (
    SELECT id FROM magerya_api.django_content_type WHERE app_label = %s AND model = %s
), links AS (
    SELECT l.appointment_id, l.object_id
    FROM magerya_api.document_appointmentanalysisresult l JOIN ct ON ct.id = l.content_type_id
)
SELECT
    (SELECT count(*) FROM links),
    (SELECT count(*) FROM links WHERE appointment_id IS NULL),
    (SELECT count(*) FROM links l JOIN magerya_api.diagnosis_medicineappointments m ON m.id::text = l.object_id),
    (SELECT count(DISTINCT appointment_id) FROM links),
    (SELECT count(DISTINCT l.appointment_id) FROM links l
        JOIN magerya_api.document_recommendation r ON r.appointment_id = l.appointment_id),
    (SELECT count(*) FROM magerya_api.diagnosis_medicineappointments),
    (SELECT count(*) FROM (SELECT object_id FROM links GROUP BY object_id HAVING count(DISTINCT appointment_id) > 1) x)
"""
_ANALYSIS_CATALOG_SQL = """
SELECT (SELECT count(*) FROM magerya_api.document_analysis), (SELECT count(*) FROM magerya_api.document_analysisitem)
"""


def code_root() -> Path:
    return Path(os.environ.get(MAGERYA_CODE_ROOT_ENV) or MAGERYA_CODE_ROOT_DEFAULT).expanduser()


def code_references(root: Path | None = None) -> dict[str, Any]:
    base = root or code_root()
    files = []
    for relative in MAGERYA_CODE_FILES:
        path = base / relative
        files.append({
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
        })
    available = all(item["sha256"] for item in files)
    return {
        "repository_label": "magerya django-develop (local working copy)",
        "SOURCE_A_CODE_EVIDENCE_STATUS": "AVAILABLE" if available else "UNAVAILABLE",
        "note": "current code may be newer than the dump; code-only facts stay LIKELY until checked against the DB",
        "files": files,
    }


def collect(conn: Any, log: QueryLog) -> dict[str, Any]:
    template = log.run(conn, "a_template_categories", SOURCE, _TEMPLATE_CATEGORIES_SQL)
    diagnosis = log.run(conn, "a_diagnosis_categories", SOURCE, _DIAGNOSIS_CATEGORIES_SQL)
    sections = log.run(conn, "a_section_use", SOURCE, _SECTION_USE_SQL)
    keys = log.run(conn, "a_item_keys", SOURCE, _ITEM_KEYS_SQL)
    [shape] = log.run(conn, "a_recommendation_shape", SOURCE, _RECOMMENDATION_SHAPE_SQL)
    medicines = log.run(conn, "a_medicine_catalog", SOURCE, _MEDICINE_CATALOG_SQL)
    statuses = log.run(conn, "a_medicine_status", SOURCE, _MEDICINE_STATUS_SQL)
    [link] = log.run(conn, "a_medicine_link", SOURCE, _MEDICINE_LINK_SQL, ("diagnosis", "medicineappointments"))
    [analysis] = log.run(conn, "a_analysis_catalog", SOURCE, _ANALYSIS_CATALOG_SQL)
    return {
        "template_categories": [{"code": c, "label": n, "prohibit_deletion": bool(p)} for c, n, p in template],
        "diagnosis_categories": [{"code": c, "label": n} for c, n in diagnosis],
        "section_use": [{"code": c, "sections": int(s), "items": int(i or 0)} for c, s, i in sections],
        "item_key_counts": {k: int(n) for k, n in keys},
        "recommendation_shape": {
            "documents": int(shape[0]),
            "distinct_appointments": int(shape[1]),
            "documents_without_appointment": int(shape[2]),
            "documents_with_backup_column": int(shape[3]),
            "one_document_per_appointment": int(shape[0]) == int(shape[1]) and int(shape[2]) == 0,
        },
        "medicine_catalog_by_category": {c: int(n) for c, n in medicines},
        "medicine_assignment_status_counts": {s: int(n) for s, n in statuses},
        "medicine_appointment_link": {
            "link_rows": int(link[0]),
            "link_rows_without_appointment": int(link[1]),
            "link_rows_resolving_to_assignment": int(link[2]),
            "distinct_appointments": int(link[3]),
            "distinct_appointments_with_recommendation_document": int(link[4]),
            "assignment_rows": int(link[5]),
            "assignments_linked_to_more_than_one_appointment": int(link[6]),
        },
        "analysis_catalog": {"analyses_and_groups": int(analysis[0]), "analysis_items": int(analysis[1])},
    }
