"""Source A recommendation localization and structured linkage. Aggregates only."""

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

from human_simulator.exposure_source_discovery_v02.db import _now

from human_simulator.exposure_source_discovery_v02.policy import SECTION_SUPPORT_MIN
from human_simulator.exposure_source_discovery_v02.textutil import (
    CatalogMatcher,
    add_profile,
    empty_profile,
    finish_profile,
    quantiles,
)

_CONTROL = {
    "anamnesis", "complaints", "main_diagnoses", "concomitant_diagnoses",
    "complications_diagnoses", "provisional_diagnoses", "objective_status",
    "local_status", "examination_results", "laboratory_examination_results",
    "functional_examination_results",
}


def _strings(obj: Any, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            _strings(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _strings(value, out)


def _join(obj: Any) -> str:
    found: list[str] = []
    _strings(obj, found)
    return "\n".join(found)


class _Bucket:
    def __init__(self) -> None:
        self.profile = empty_profile()
        self.exclusive: Counter[str] = Counter()
        self.method: Counter[str] = Counter()
        self.lengths: list[int] = []

    def add(self, text: str, matcher: CatalogMatcher) -> None:
        add_profile(self.profile, text)
        hit = matcher.match_text(text)
        if hit["exact"]:
            self.method["normalized_exact"] += 1
        if hit["boundary"]:
            self.method["boundary_aware"] += 1
            self.lengths.extend(len(name) for name in hit["boundary"])
        if hit["alias"]:
            self.method["alias_candidate"] += 1
        if hit["ambiguous"]:
            self.method["ambiguous"] += 1
            self.exclusive["ambiguous"] += 1
        elif hit["exact"]:
            self.exclusive["normalized_exact"] += 1
        elif hit["boundary"]:
            self.exclusive["boundary_aware"] += 1
        elif hit["alias"]:
            self.exclusive["alias_candidate"] += 1
        else:
            self.exclusive["unmatched"] += 1

    def export(self) -> dict[str, Any]:
        return {
            **finish_profile(self.profile),
            "catalog_method_hits": dict(self.method),
            "catalog_exclusive_class": dict(self.exclusive),
            "matched_term_length": quantiles(self.lengths),
            "accepted_medication_identity": False,
        }


def _load(raw: Any) -> Any:
    if isinstance(raw, (dict, list)) or raw is None:
        return raw
    return json.loads(raw)


def _section_items(section: Any) -> tuple[str, list[Any]]:
    if not isinstance(section, dict):
        return "NOT_OBJECT", []
    items = section.get("items")
    if items is None:
        return "ABSENT", []
    if isinstance(items, list):
        return "list", items
    if isinstance(items, str):
        return "str", [items]
    if isinstance(items, dict):
        return "dict", [items]
    return type(items).__name__, []


def localize(conn: Any, log: Any, matcher: CatalogMatcher) -> dict[str, Any]:
    scopes = {name: _Bucket() for name in (
        "whole_document", "recommendations_node", "recommendation_items", "outside_recommendations"
    )}
    by_code: dict[str, dict[str, Any]] = {}
    docs = 0
    sql = "SELECT document FROM magerya_api.document_recommendation"
    started, clock = _now(), time.monotonic()
    with conn.cursor(name="a_rec_loc") as cur:
        cur.itersize = 2000
        cur.execute(sql)
        for (raw,) in cur:
            docs += 1
            doc = _load(raw) or {}
            if not isinstance(doc, dict):
                continue
            scopes["whole_document"].add(_join(doc), matcher)
            rec = doc.get("recommendations")
            scopes["recommendations_node"].add(_join(rec), matcher)
            outside = {key: value for key, value in doc.items() if key != "recommendations"}
            scopes["outside_recommendations"].add(_join(outside), matcher)
            item_blob: list[str] = []
            seen_in_doc: set[str] = set()
            if isinstance(rec, list):
                for section in rec:
                    kind, items = _section_items(section)
                    code = str(section.get("code")) if isinstance(section, dict) else "NOT_OBJECT"
                    slot = by_code.setdefault(code, {
                        "documents": 0, "sections": 0, "item_types": Counter(),
                        "item_counts": [], "non_empty_items": 0, "items": 0, "bucket": _Bucket(),
                    })
                    if code not in seen_in_doc:
                        slot["documents"] += 1
                        seen_in_doc.add(code)
                    slot["sections"] += 1
                    slot["item_types"][kind] += 1
                    texts = [_join(item) for item in items]
                    slot["item_counts"].append(len(items))
                    slot["items"] += len(items)
                    slot["non_empty_items"] += sum(1 for text in texts if text.strip())
                    blob = "\n".join(texts)
                    slot["bucket"].add(blob, matcher)
                    item_blob.append(blob)
            scopes["recommendation_items"].add("\n".join(item_blob), matcher)
    conn.commit()
    log.note_stream("a_document_recommendation_stream", "magerya_api", sql, docs, started, clock)
    supported = {}
    low = 0
    for code, slot in by_code.items():
        if slot["sections"] < SECTION_SUPPORT_MIN or not code.replace("_", "").isalnum():
            low += slot["sections"]
            continue
        bucket = slot.pop("bucket")
        supported[code] = {
            "documents": slot["documents"],
            "sections": slot["sections"],
            "item_types": dict(slot["item_types"]),
            "items": slot["items"],
            "items_per_section": quantiles(slot["item_counts"]),
            "non_empty_item_fraction": round(slot["non_empty_items"] / slot["items"], 4) if slot["items"] else None,
            **bucket.export(),
            "code_semantics_status": "UNKNOWN_PENDING_HUMAN_REVIEW",
        }
        report = _medical_report(conn, log, matcher)
    return {
        "source_system": "magerya_api",
        "document_recommendation": {
            "documents": docs,
            "scope_comparison": {name: bucket.export() for name, bucket in scopes.items()},
            "by_section_code": supported,
            "low_support_or_unsafe_code_sections": low,
            "accepted_medication_identity": False,
        },
        "document_medicalreport": report,
        "catalog": matcher.fingerprint(),
    }


def _medical_report(conn: Any, log: Any, matcher: CatalogMatcher) -> dict[str, Any]:
    regions = {name: _Bucket() for name in (
        "recommendations", "recommendation_items", "drugs", "supplements", "history_and_diagnosis_control", "other_fields"
    )}
    presence = Counter()
    docs = 0
    sql = "SELECT document FROM magerya_api.document_medicalreport"
    started, clock = _now(), time.monotonic()
    with conn.cursor(name="a_report_loc") as cur:
        cur.itersize = 1000
        cur.execute(sql)
        for (raw,) in cur:
            docs += 1
            doc = _load(raw) or {}
            if not isinstance(doc, dict):
                continue
            rec = doc.get("recommendations")
            regions["recommendations"].add(_join(rec), matcher)
            items: list[Any] = []
            if isinstance(rec, list):
                for section in rec:
                    _, found = _section_items(section)
                    items.extend(found)
            elif isinstance(rec, dict):
                items.append(rec.get("items"))
            regions["recommendation_items"].add(_join(items), matcher)
            for key in ("drugs", "supplements"):
                if key in doc:
                    presence[key] += 1
                regions[key].add(_join(doc.get(key)), matcher)
            control = {key: doc.get(key) for key in _CONTROL if key in doc}
            presence["history_and_diagnosis_control"] += int(bool(control))
            regions["history_and_diagnosis_control"].add(_join(control), matcher)
            other = {key: value for key, value in doc.items() if key not in _CONTROL and key not in {"recommendations", "drugs", "supplements"}}
            regions["other_fields"].add(_join(other), matcher)
    conn.commit()
    log.note_stream("a_document_medicalreport_stream", "magerya_api", sql, docs, started, clock)
    return {
        "documents": docs,
        "field_presence_docs": dict(presence),
        "regions": {name: bucket.export() for name, bucket in regions.items()},
        "history_is_not_a_recommendation": True,
        "field_semantics_status": "UNKNOWN_PENDING_HUMAN_REVIEW",
    }


def _definition(text: str) -> dict[str, Any]:
    import hashlib
    value = text or ""
    if len(value) <= 160 and "@" not in value:
        return {"definition": value}
    return {
        "definition_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "definition_length": len(value),
    }


def structured_linkage(conn: Any, log: Any) -> dict[str, Any]:
    source = "magerya_api"
    fk = log.run(
        conn,
        "a_linkage_constraints",
        source,
        """
        SELECT c.relname, con.contype, pg_get_constraintdef(con.oid)
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'magerya_api'
          AND c.relname IN ('diagnosis_medicineappointments', 'document_recommendation', 'appointment_appointment')
          AND con.contype IN ('f', 'u')
        ORDER BY 1, 2, 3
        """,
    )
    constraints = [
        {"relation": name, "type": "FOREIGN_KEY" if kind == "f" else "UNIQUE", **_definition(definition)}
        for name, kind, definition in fk
    ]
    direct = any(
        item["relation"] == "diagnosis_medicineappointments"
        and "document_recommendation" in item.get("definition", "")
        for item in constraints
    )
    windows = {}
    for days in (0, 1, 3, 7):
        predicate = (
            "m.created::date = dr.created::date"
            if days == 0
            else f"abs(extract(epoch FROM (dr.created - m.created))) <= {days * 86400}"
        )
        row = log.run(
            conn,
            f"a_patient_window_{days}d",
            source,
            f"""
            WITH docs AS (
                SELECT dr.id, dr.created, ap.patient_id
                FROM magerya_api.document_recommendation dr
                JOIN magerya_api.appointment_appointment ap ON ap.id = dr.appointment_id
            ),
            med AS (
                SELECT m.id, count(d.id) AS n
                FROM magerya_api.diagnosis_medicineappointments m
                LEFT JOIN docs d ON d.patient_id = m.patient_id AND {predicate.replace("dr.created", "d.created")}
                GROUP BY m.id
            ),
            doc_hits AS (
                SELECT d.id, count(m.id) AS n
                FROM docs d
                LEFT JOIN magerya_api.diagnosis_medicineappointments m
                  ON m.patient_id = d.patient_id AND {predicate.replace("dr.created", "d.created")}
                GROUP BY d.id
            )
            SELECT
              (SELECT count(*) FROM med),
              (SELECT count(*) FROM med WHERE n = 0),
              (SELECT count(*) FROM med WHERE n = 1),
              (SELECT count(*) FROM med WHERE n > 1),
              (SELECT count(*) FROM doc_hits),
              (SELECT count(*) FROM doc_hits WHERE n = 0),
              (SELECT count(*) FROM doc_hits WHERE n = 1),
              (SELECT count(*) FROM doc_hits WHERE n > 1)
            """,
        )[0]
        windows[f"{days}_day"] = {
            "route": "same_patient_only",
            "strength": "WEAK_NOT_AN_EVENT_LINK",
            "clock": "created",
            "medicine_rows": row[0],
            "medicine_rows_without_candidate": row[1],
            "medicine_rows_single_candidate": row[2],
            "medicine_rows_ambiguous": row[3],
            "recommendation_documents": row[4],
            "documents_without_structured_row": row[5],
            "documents_single_candidate": row[6],
            "documents_ambiguous": row[7],
            "absence_is_not_evidence_of_no_link": True,
        }
    shared_appointment = log.run(
        conn,
        "a_shared_appointment_column",
        source,
        """
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = 'magerya_api'
          AND table_name = 'diagnosis_medicineappointments'
          AND column_name IN ('appointment_id', 'consultation_id', 'visit_id')
        """,
    )[0][0]
    return {
        "source_system": source,
        "direct_foreign_key_between_medicine_row_and_recommendation_document": direct,
        "constraints": constraints,
        "shared_visit_key_columns_on_medicine_row": shared_appointment,
        "shared_appointment_route": "NOT_AVAILABLE" if shared_appointment == 0 else "PRESENT",
        "patient_windows": windows,
        "interpretation_status": "UNKNOWN_PENDING_HUMAN_REVIEW",
        "SOURCE_A_STRUCTURED_LINKAGE_STATUS": "NO_DIRECT_VISIT_KEY",
    }
