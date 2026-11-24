"""Read-only, aggregate-only discovery of recommendation / intake fields.

Row text is parsed inside this process only. Outputs are counts, fractions
and length quantiles. No values, identifiers or free text leave the process.
Field meanings stay UNKNOWN until a human reviews them.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from human_simulator.exposure_source_discovery_v01 import VERSION

ARTIFACT_DIR = "artifacts/exposure-source-discovery-v0.1"
MIN_KEY_SUPPORT = 50
SAFE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,47}$")

PATTERNS: dict[str, re.Pattern[str]] = {
    "dose_amount": re.compile(
        r"\d+[.,]?\d*\s*(мг|mg|мкг|mcg|µg|гр?\b|мл|ml|ме\b|iu\b|ед\b|капс|таб|капл|драже|саше|пакет|ложк)",
        re.I,
    ),
    "frequency": re.compile(
        r"(раз[а]?\s*(в|за)\s*(день|сутки|недел)|\d\s*р\s*/\s*д|\d\s*р\.?\s*в\s*д|утр|вечер|натощак|"
        r"перед\s*сн|во\s*время\s*еды|после\s*еды|до\s*еды|once|twice|daily)",
        re.I,
    ),
    "duration": re.compile(r"(\d+\s*(дн|дней|день|нед|недел|мес|месяц)|курс|week|month)", re.I),
    "supplement_term": re.compile(
        r"(бад|витамин|vitamin|омега|omega|магни|magnes|цинк|zinc|селен|selen|железо|ферр|d3|д3|b12|в12|"
        r"фолиев|folat|коэнзим|q10|пробиот|probiot|йод|кальци|calcium)",
        re.I,
    ),
    "route": re.compile(
        r"(внутрь|перорал|в/м|в/в|внутривен|внутримыш|подкож|ингаляц|наружно|сублинг|интраназ|местно)",
        re.I,
    ),
    "intake_change": re.compile(r"(отмен|прекрат|заменить|замен|снизить\s*доз|увеличить\s*доз|продолж)", re.I),
}


def _q(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    values = sorted(values)
    pick = lambda p: values[min(len(values) - 1, int(p * (len(values) - 1)))]  # noqa: E731
    return {"n": len(values), "p10": pick(0.1), "p50": pick(0.5), "p90": pick(0.9), "mean": round(statistics.fmean(values), 1)}


def _text_profile(texts: Iterable[str | None]) -> dict[str, Any]:
    total = 0
    non_empty = 0
    lengths: list[int] = []
    hits: Counter[str] = Counter()
    any_dose_and_freq = 0
    for text in texts:
        total += 1
        if text is None:
            continue
        stripped = text.strip()
        if not stripped:
            continue
        non_empty += 1
        lengths.append(len(stripped))
        found = {name for name, pattern in PATTERNS.items() if pattern.search(stripped)}
        hits.update(found)
        if {"dose_amount", "frequency"} <= found:
            any_dose_and_freq += 1
    return {
        "rows": total,
        "non_empty": non_empty,
        "non_empty_fraction": round(non_empty / total, 4) if total else None,
        "length": _q(lengths),
        "pattern_rows": {name: hits.get(name, 0) for name in PATTERNS},
        "pattern_fraction_of_non_empty": {
            name: (round(hits.get(name, 0) / non_empty, 4) if non_empty else None) for name in PATTERNS
        },
        "dose_and_frequency_rows": any_dose_and_freq,
        "semantic_status": "UNKNOWN",
    }


def _walk_keys(obj: Any, prefix: str, depth: int, out: Counter[str], seen: set[str]) -> None:
    if depth > 3:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if path not in seen:
                seen.add(path)
                out[path] += 1
            _walk_keys(value, path, depth + 1, out, seen)
    elif isinstance(obj, list):
        for item in obj[:200]:
            _walk_keys(item, f"{prefix}[]", depth + 1, out, seen)


def _flatten_strings(obj: Any, out: list[str]) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            _flatten_strings(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _flatten_strings(value, out)


def _safe_key_path(path: str) -> bool:
    return all(SAFE_KEY.match(part.replace("[]", "")) for part in path.split(".") if part.replace("[]", ""))


def _json_profile(docs: Iterable[Any], catalog: re.Pattern[str] | None) -> dict[str, Any]:
    key_docs: Counter[str] = Counter()
    n = 0
    parsed = 0
    string_texts: list[str] = []
    catalog_docs = 0
    for raw in docs:
        n += 1
        if raw is None:
            continue
        doc = raw if isinstance(raw, (dict, list)) else json.loads(raw)
        parsed += 1
        seen: set[str] = set()
        _walk_keys(doc, "", 0, key_docs, seen)
        strings: list[str] = []
        _flatten_strings(doc, strings)
        joined = "\n".join(strings)
        string_texts.append(joined)
        if catalog is not None and catalog.search(joined.lower()):
            catalog_docs += 1
    safe = {k: v for k, v in key_docs.items() if v >= MIN_KEY_SUPPORT and _safe_key_path(k)}
    suppressed = sum(1 for k, v in key_docs.items() if k not in safe)
    return {
        "rows": n,
        "parsed": parsed,
        "key_paths_supported": dict(sorted(safe.items(), key=lambda kv: (-kv[1], kv[0]))[:80]),
        "key_paths_suppressed_count": suppressed,
        "key_path_policy": f"support>={MIN_KEY_SUPPORT} and identifier-like name; others suppressed",
        "string_content": _text_profile(string_texts),
        "catalog_mention_docs": catalog_docs if catalog is not None else "NOT_RUN",
        "catalog_mention_fraction": (round(catalog_docs / parsed, 4) if catalog is not None and parsed else None),
    }


class QueryLog:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def run(self, cur: Any, name: str, source: str, sql: str, params: tuple = ()) -> list[tuple]:
        start = time.monotonic()
        cur.execute(sql, params)
        rows = cur.fetchall()
        self.entries.append({"query": name, "source": source, "duration_seconds": round(time.monotonic() - start, 3)})
        return rows

    def stream(self, conn: Any, name: str, source: str, sql: str, size: int = 5000) -> Iterable[tuple]:
        start = time.monotonic()
        with conn.cursor(name=f"c_{name}") as cur:
            cur.itersize = size
            cur.execute(sql)
            for row in cur:
                yield row
        self.entries.append({"query": name, "source": source, "duration_seconds": round(time.monotonic() - start, 3)})


def _readonly(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = 300000")
        cur.execute("SET lock_timeout = 10000")
        cur.execute("SET default_transaction_read_only = on")
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "on":
            raise RuntimeError("read-only session not established")


def _connect_a(root: Path) -> Any:
    import psycopg
    from dotenv import dotenv_values

    audit = dotenv_values(root / "db-audit.env")
    user = audit.get("MG_AUDIT_USER") or "mg_audit_ro"
    password = audit.get("MG_AUDIT_PASSWORD")
    host, port, db = audit.get("MG_HOST") or "localhost", int(audit.get("MG_PORT") or 5434), audit.get("MG_DATABASE") or "magerya_api"
    if not password:
        from human_simulator.stage01.settings import MgAuditSettings

        mg = MgAuditSettings.from_repo(root)
        user, password = mg.audit_user, mg.audit_password.get_secret_value()
        host, port, db = mg.pg_host, mg.pg_port, mg.pg_database
    conn = psycopg.connect(host=host, port=port, dbname=db, user=user, password=password, connect_timeout=10)
    conn.autocommit = False
    _readonly(conn)
    conn.commit()
    conn.read_only = True
    return conn


def _connect_b(root: Path) -> Any:
    import psycopg

    from human_simulator.stage02.settings import KgzRestoreSettings

    kgz = KgzRestoreSettings.from_repo(root)
    conn = psycopg.connect(
        host=kgz.pg_host,
        port=kgz.pg_port,
        dbname=kgz.pg_database,
        user=kgz.audit_user,
        password=kgz.audit_password.get_secret_value(),
        connect_timeout=10,
    )
    conn.autocommit = False
    _readonly(conn)
    conn.commit()
    conn.read_only = True
    return conn


def _catalog_pattern(names: list[str]) -> re.Pattern[str] | None:
    cleaned = sorted({n.strip().lower() for n in names if n and len(n.strip()) >= 5}, key=len, reverse=True)
    if not cleaned:
        return None
    return re.compile("|".join(re.escape(n) for n in cleaned))


def discover_source_a(root: Path, log: QueryLog) -> dict[str, Any]:
    conn = _connect_a(root)
    src = "magerya_api"
    out: dict[str, Any] = {"source_system": src}
    try:
        with conn.cursor() as cur:
            names = [r[0] for r in log.run(cur, "a_medicine_catalog_names", src, "SELECT name FROM magerya_api.diagnosis_medicines")]
            catalog = _catalog_pattern(names)
            out["medicine_catalog"] = {"entries": len(names), "names_used_for_matching": "IN_PROCESS_ONLY"}
            rows = log.run(
                cur,
                "a_medicine_catalog_fk_fill",
                src,
                "SELECT count(*), count(unit_of_measurement_id), count(form_id), count(reception_frequency_id), "
                "count(NULLIF(btrim(description), '')), count(NULLIF(btrim(category), '')) FROM magerya_api.diagnosis_medicines",
            )[0]
            out["medicine_catalog"]["filled"] = dict(
                zip(["rows", "unit_of_measurement_id", "form_id", "reception_frequency_id", "description", "category"], rows)
            )
            out["reception_frequency_catalog_rows"] = log.run(
                cur, "a_reception_frequency_rows", src, "SELECT count(*) FROM magerya_api.diagnosis_receptionfrequency"
            )[0][0]
            link = log.run(
                cur,
                "a_medicineappointment_to_recommendation_doc_same_day",
                src,
                """
                SELECT count(*) AS med_rows,
                       count(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM magerya_api.document_recommendation dr
                           JOIN magerya_api.appointment_appointment ap ON ap.id = dr.appointment_id
                           WHERE ap.patient_id = m.patient_id
                             AND abs(extract(epoch FROM (dr.created - m.created))) <= 86400
                       )) AS with_rec_doc_created_within_1d
                FROM magerya_api.diagnosis_medicineappointments m
                """,
            )[0]
            out["medicineappointments_linkage"] = {
                "rows": link[0],
                "with_recommendation_document_created_within_1_day_same_patient": link[1],
                "fraction": round(link[1] / link[0], 4) if link[0] else None,
                "interpretation_status": "UNKNOWN",
            }
            stat = log.run(
                cur,
                "a_recommendation_doc_versions",
                src,
                "SELECT version, count(*) FROM magerya_api.document_recommendation GROUP BY version ORDER BY 2 DESC LIMIT 20",
            )
            out["document_recommendation_versions"] = [
                {"version": v if v and SAFE_KEY.match(str(v).replace(".", "_")) else "SUPPRESSED", "rows": n} for v, n in stat
            ]
        conn.commit()
        out["document_recommendation_document"] = _json_profile(
            (r[0] for r in log.stream(conn, "a_rec_document", src, "SELECT document FROM magerya_api.document_recommendation")),
            catalog,
        )
        conn.commit()
        out["document_recommendation_schema"] = _json_profile(
            (r[0] for r in log.stream(conn, "a_rec_schema", src, "SELECT schema FROM magerya_api.document_recommendation")),
            None,
        )
        conn.commit()
        out["document_medicalreport_document"] = _json_profile(
            (r[0] for r in log.stream(conn, "a_medreport_document", src, "SELECT document FROM magerya_api.document_medicalreport")),
            catalog,
        )
        conn.commit()
        out["document_recommendationtemplate_description"] = _text_profile(
            r[0]
            for r in log.stream(
                conn, "a_rec_template_text", src, "SELECT description FROM magerya_api.document_recommendationtemplate"
            )
        )
        conn.commit()
        out["diagnosis_recommendation_description"] = _text_profile(
            r[0] for r in log.stream(conn, "a_diag_rec_text", src, "SELECT description FROM magerya_api.diagnosis_recommendation")
        )
        conn.commit()
    finally:
        conn.close()
    return out


def discover_source_b(root: Path, log: QueryLog) -> dict[str, Any]:
    conn = _connect_b(root)
    src = "kgz_raw"
    out: dict[str, Any] = {"source_system": src, "source_a_catalog_used": False}
    feedback_cols = ["drugs", "change_drugs", "decline_drugs", "vitamins", "positive_changes", "outside_doctor_medicine", "drugs_first", "complaints"]
    questionnaire_cols = ["medicines", "drugs", "drugs_first", "drugs_second", "drugs_third", "outside_doctor_medicine", "preview_treatment"]
    try:
        for col in feedback_cols:
            out[f"feedback.{col}"] = _text_profile(
                r[0] for r in log.stream(conn, f"b_feedback_{col}", src, f"SELECT {col} FROM public.feedback")
            )
            conn.commit()
        for col in questionnaire_cols:
            out[f"questionnaire.{col}"] = _text_profile(
                r[0] for r in log.stream(conn, f"b_questionnaire_{col}", src, f"SELECT {col} FROM public.questionnaire")
            )
            conn.commit()
        out["consultations.recommendations"] = _text_profile(
            r[0] for r in log.stream(conn, "b_consultations_recommendations", src, "SELECT recommendations FROM public.consultations")
        )
        conn.commit()
        out["recommendations_user.description"] = _text_profile(
            r[0] for r in log.stream(conn, "b_rec_user_description", src, "SELECT description FROM quest_digital.recommendations_user")
        )
        conn.commit()
        out["recommendations_list.title_description"] = _text_profile(
            (r[0] or "") + "\n" + (r[1] or "")
            for r in log.stream(conn, "b_rec_list_text", src, "SELECT title, description FROM quest_digital.recommendations_list")
        )
        conn.commit()
        with conn.cursor() as cur:
            cats = log.run(
                cur,
                "b_rec_user_by_category",
                src,
                """
                SELECT c.id, c.title, c.user_title, count(u.id), count(u.id) FILTER (WHERE u.is_active)
                FROM quest_digital.recommendations_category c
                LEFT JOIN quest_digital.recommendations_list l ON l.category_id = c.id
                LEFT JOIN quest_digital.recommendations_user u ON u.recommendations_id = l.id
                GROUP BY c.id, c.title, c.user_title ORDER BY c.id
                """,
            )
            out["recommendations_user_by_catalog_category"] = [
                {"category_id": cid, "catalog_title": title, "catalog_user_title": utitle, "rows": n, "active_rows": act}
                for cid, title, utitle, n, act in cats
            ]
            fb = log.run(
                cur,
                "b_feedback_consultation_linkage",
                src,
                """
                SELECT count(*), count(f.consultation_id),
                       count(*) FILTER (WHERE c.id IS NOT NULL AND f.created_at > (c.date::timestamp)),
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (f.created_at - c.date::timestamp)) / 86400.0)
                FROM public.feedback f LEFT JOIN public.consultations c ON c.id = f.consultation_id
                """,
            )[0]
            out["feedback_consultation_linkage"] = {
                "rows": fb[0],
                "with_consultation_id": fb[1],
                "created_after_consultation_date": fb[2],
                "median_days_after_consultation": round(float(fb[3]), 1) if fb[3] is not None else None,
                "interpretation_status": "UNKNOWN",
            }
            rec_link = log.run(
                cur,
                "b_feedback_to_prior_recommendation",
                src,
                """
                SELECT count(DISTINCT f.id) FROM public.feedback f
                JOIN public.consultations c ON c.id = f.consultation_id
                JOIN quest_digital.recommendations_user u ON u.consultations_id = c.id
                """,
            )[0][0]
            out["feedback_with_recommendations_on_same_consultation"] = rec_link
        conn.commit()
    finally:
        conn.close()
    return out


def discover_followup(root: Path, log: QueryLog) -> dict[str, Any]:
    out: dict[str, Any] = {}
    conn = _connect_a(root)
    try:
        codes: Counter[str] = Counter()
        items_per_section: list[int] = []
        docs_with_sections = 0
        for (doc,) in log.stream(conn, "a_rec_sections", "magerya_api", "SELECT document FROM magerya_api.document_recommendation"):
            doc = doc if isinstance(doc, dict) else json.loads(doc)
            sections = doc.get("recommendations") or []
            if sections:
                docs_with_sections += 1
            for section in sections:
                if isinstance(section, dict):
                    codes[str(section.get("code"))] += 1
                    items = section.get("items") or []
                    items_per_section.append(len(items) if isinstance(items, list) else 0)
        conn.commit()
        safe_codes = {c: n for c, n in codes.items() if n >= MIN_KEY_SUPPORT and SAFE_KEY.match(c)}
        out["source_a_recommendation_sections"] = {
            "docs_with_sections": docs_with_sections,
            "section_code_counts": dict(sorted(safe_codes.items(), key=lambda kv: -kv[1])),
            "suppressed_code_count": len(codes) - len(safe_codes),
            "items_per_section": _q(items_per_section),
            "code_semantics_status": "UNKNOWN",
        }
    finally:
        conn.close()
    conn = _connect_b(root)
    try:
        with conn.cursor() as cur:
            row = log.run(
                cur,
                "b_feedback_prior_drug_recommendation",
                "kgz_raw",
                """
                WITH drug_rec AS (
                    SELECT DISTINCT c.patient_id, c.date
                    FROM public.consultations c
                    JOIN quest_digital.recommendations_user u ON u.consultations_id = c.id
                    JOIN quest_digital.recommendations_list l ON l.id = u.recommendations_id
                    WHERE l.category_id = 3
                )
                , per_feedback AS (
                    SELECT f.id, max(d.date) AS last_rec
                    FROM public.feedback f
                    LEFT JOIN drug_rec d ON d.patient_id = f.user_id AND d.date < f.created_at::date
                    GROUP BY f.id, f.created_at
                ), gap AS (
                    SELECT p.id, p.last_rec, (f.created_at::date - p.last_rec) AS days
                    FROM per_feedback p JOIN public.feedback f ON f.id = p.id
                )
                SELECT count(*), count(last_rec),
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY days)
                FROM gap
                """,
            )[0]
            out["source_b_feedback_after_drug_recommendation"] = {
                "feedback_rows": row[0],
                "with_prior_drug_recommendation_same_subject": row[1],
                "fraction": round(row[1] / row[0], 4) if row[0] else None,
                "median_days_since_prior_drug_recommendation": float(row[2]) if row[2] is not None else None,
                "subject_key_assumption": "feedback.user_id equals consultations.patient_id — UNKNOWN, needs review",
                "interpretation_status": "UNKNOWN",
            }
        conn.commit()
    finally:
        conn.close()
    return out


def run_followup(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    log = QueryLog()
    data = discover_followup(root, log)
    doc = {"version": VERSION, "read_only_sessions": True, "row_values_exported": False, **data, "queries": log.entries}
    (art / "followup-discovery.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    from human_simulator.intervention_response_readiness_v01.privacy import scan_public

    scan = scan_public(art)
    (art / "privacy-scan.json").write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
    return {"ok": bool(scan.get("ok")), "privacy": scan.get("PUBLIC_DATA_MINIMIZATION_STATUS")}


def run(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    log = QueryLog()
    started = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    a = discover_source_a(root, log)
    b = discover_source_b(root, log)
    common = {
        "version": VERSION,
        "generated_at": started,
        "read_only_sessions": True,
        "row_values_exported": False,
        "field_semantics_status": "UNKNOWN_PENDING_HUMAN_REVIEW",
        "exposure_tier_note": "Recommendation is not administration. No field is promoted to intake evidence by this run.",
    }
    (art / "source-a-discovery.json").write_text(json.dumps({**common, **a}, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    (art / "source-b-discovery.json").write_text(json.dumps({**common, **b}, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    (art / "query-log.json").write_text(json.dumps({"version": VERSION, "queries": log.entries}, indent=2) + "\n", encoding="utf-8")
    from human_simulator.intervention_response_readiness_v01.privacy import scan_public

    scan = scan_public(art)
    (art / "privacy-scan.json").write_text(json.dumps(scan, indent=2) + "\n", encoding="utf-8")
    return {"ok": bool(scan.get("ok")), "artifact_dir": ARTIFACT_DIR, "privacy": scan.get("PUBLIC_DATA_MINIMIZATION_STATUS"), "queries": len(log.entries)}


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["followup"]:
        print(json.dumps(run_followup(Path("."))))
    else:
        print(json.dumps(run(Path("."))))
