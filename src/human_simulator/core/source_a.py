"""Source A read-only adapter (mg_audit_ro). Never mutates raw Source A."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

from human_simulator.db.readonly import assert_readonly
from human_simulator.stage01.settings import MgAuditSettings


@contextmanager
def source_a_connection(repo_root: Any) -> Iterator[Any]:
    import psycopg

    from pathlib import Path

    mg = MgAuditSettings.from_repo(Path(repo_root))
    if not mg.audit_password.get_secret_value():
        raise RuntimeError("MG_AUDIT_PASSWORD missing; cannot open Source A read-only connection")
    dsn = (
        f"postgresql://{mg.audit_user}:{mg.audit_password.get_secret_value()}"
        f"@{mg.pg_host}:{mg.pg_port}/{mg.pg_database}"
    )
    conn = psycopg.connect(dsn, connect_timeout=10, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 120000")
            cur.execute("SET lock_timeout = 10000")
            cur.execute("SET default_transaction_read_only = on")
        yield conn
    finally:
        conn.close()


def _fetch_all(conn: Any, sql: str, params: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
    assert_readonly(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def _fetch_one(conn: Any, sql: str, params: tuple[Any, ...] | None = None) -> tuple[Any, ...] | None:
    rows = _fetch_all(conn, sql, params)
    return rows[0] if rows else None


def access_probe(conn: Any) -> dict[str, Any]:
    one = _fetch_one(conn, "SELECT current_user, current_setting('transaction_read_only')")
    return {
        "readable": one is not None,
        "db_user": one[0] if one else None,
        "transaction_read_only": one[1] if one else None,
        "raw_writes_forbidden": True,
    }


def relation_counts(conn: Any) -> dict[str, int]:
    """Exact counts only for small/medium pilot relations used by the slice."""
    out: dict[str, int] = {}
    for rel in (
        "account_patient",
        "appointment_appointment",
        "document_analysisresult",
        "document_analysisresultitem",
        "diagnosis_medicineappointments",
    ):
        row = _fetch_one(conn, f"SELECT COUNT(*)::bigint FROM magerya_api.{rel}")  # noqa: S608
        out[rel] = int(row[0]) if row else 0
    return out


def cohort_eligibility_aggregates(conn: Any) -> dict[str, Any]:
    """Aggregate eligibility — no patient identifiers returned."""
    sql = """
    WITH appt AS (
      SELECT patient_id, COUNT(*)::int AS n_appt,
             MIN(created) AS first_ts, MAX(COALESCE(completed_at, created)) AS last_ts
      FROM magerya_api.appointment_appointment
      WHERE patient_id IS NOT NULL
      GROUP BY patient_id
    ),
    labs AS (
      SELECT patient_id, COUNT(*)::int AS n_lab
      FROM magerya_api.document_analysisresult
      WHERE patient_id IS NOT NULL
      GROUP BY patient_id
    ),
    joined AS (
      SELECT p.id AS patient_id,
             COALESCE(a.n_appt, 0) AS n_appt,
             COALESCE(l.n_lab, 0) AS n_lab,
             a.first_ts, a.last_ts
      FROM magerya_api.account_patient p
      LEFT JOIN appt a ON a.patient_id = p.id
      LEFT JOIN labs l ON l.patient_id = p.id
    )
    SELECT
      COUNT(*)::bigint AS subjects_total,
      COUNT(*) FILTER (WHERE n_appt >= 2)::bigint AS subjects_appt_ge2,
      COUNT(*) FILTER (WHERE n_appt >= 3)::bigint AS subjects_appt_ge3,
      COUNT(*) FILTER (WHERE n_appt >= 4)::bigint AS subjects_appt_ge4,
      COUNT(*) FILTER (WHERE n_lab >= 1)::bigint AS subjects_with_lab,
      COUNT(*) FILTER (WHERE n_appt >= 3 AND n_lab >= 1)::bigint AS subjects_appt3_and_lab,
      COUNT(*) FILTER (WHERE n_appt >= 3 AND n_lab >= 3)::bigint AS subjects_appt3_lab3
    FROM joined
    """
    row = _fetch_one(conn, sql)
    assert row
    keys = [
        "subjects_total",
        "subjects_appt_ge2",
        "subjects_appt_ge3",
        "subjects_appt_ge4",
        "subjects_with_lab",
        "subjects_appt3_and_lab",
        "subjects_appt3_lab3",
    ]
    return dict(zip(keys, (int(x) for x in row), strict=True))


def select_cohort_patient_ids(conn: Any, *, limit: int) -> list[int]:
    """Select densest longitudinal subjects; returns internal IDs for load only (not artifacts)."""
    sql = """
    WITH appt AS (
      SELECT patient_id, COUNT(*)::int AS n_appt
      FROM magerya_api.appointment_appointment
      WHERE patient_id IS NOT NULL
      GROUP BY patient_id
    ),
    labs AS (
      SELECT patient_id, COUNT(*)::int AS n_lab
      FROM magerya_api.document_analysisresult
      WHERE patient_id IS NOT NULL
      GROUP BY patient_id
    )
    SELECT p.id
    FROM magerya_api.account_patient p
    JOIN appt a ON a.patient_id = p.id
    JOIN labs l ON l.patient_id = p.id
    WHERE a.n_appt >= 3 AND l.n_lab >= 1
    ORDER BY (a.n_appt + l.n_lab) DESC, p.id
    LIMIT %s
    """
    rows = _fetch_all(conn, sql, (limit,))
    return [int(r[0]) for r in rows]


def fetch_patients(conn: Any, patient_ids: list[int]) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    sql = """
    SELECT id, created, modified, birthdate, sex
    FROM magerya_api.account_patient
    WHERE id = ANY(%s)
    """
    rows = _fetch_all(conn, sql, (patient_ids,))
    return [
        {
            "id": int(r[0]),
            "created": r[1],
            "modified": r[2],
            "birthdate": r[3],
            "sex": r[4],
        }
        for r in rows
    ]


def fetch_appointments(conn: Any, patient_ids: list[int]) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    sql = """
    SELECT id, patient_id, created, modified, completed_at, status
    FROM magerya_api.appointment_appointment
    WHERE patient_id = ANY(%s)
    ORDER BY created NULLS LAST, id
    """
    rows = _fetch_all(conn, sql, (patient_ids,))
    return [
        {
            "id": int(r[0]),
            "patient_id": int(r[1]),
            "created": r[2],
            "modified": r[3],
            "completed_at": r[4],
            "status": r[5],
        }
        for r in rows
    ]


def fetch_analysis_results(conn: Any, patient_ids: list[int], *, per_patient_limit: int = 50) -> list[dict[str, Any]]:
    """Bounded lab headers per patient for pilot load."""
    if not patient_ids:
        return []
    sql = """
    SELECT id, patient_id, sampling_date, appointment_date, created, modified, status
    FROM (
      SELECT id, patient_id, sampling_date, appointment_date, created, modified, status,
             ROW_NUMBER() OVER (PARTITION BY patient_id ORDER BY COALESCE(appointment_date, created) DESC, id DESC) AS rn
      FROM magerya_api.document_analysisresult
      WHERE patient_id = ANY(%s)
    ) t
    WHERE rn <= %s
    ORDER BY patient_id, COALESCE(appointment_date, created), id
    """
    rows = _fetch_all(conn, sql, (patient_ids, per_patient_limit))
    return [
        {
            "id": int(r[0]),
            "patient_id": int(r[1]),
            "sampling_date": r[2],
            "appointment_date": r[3],
            "created": r[4],
            "modified": r[5],
            "status": r[6],
        }
        for r in rows
    ]


def fetch_analysis_results_uncapped(conn: Any, patient_ids: list[int]) -> list[dict[str, Any]]:
    """All lab headers for cohort subjects — no per-patient ROW_NUMBER cap."""
    if not patient_ids:
        return []
    sql = """
    SELECT id, patient_id, sampling_date, appointment_date, created, modified, status
    FROM magerya_api.document_analysisresult
    WHERE patient_id = ANY(%s)
    ORDER BY patient_id, COALESCE(appointment_date, created), id
    """
    rows = _fetch_all(conn, sql, (patient_ids,))
    return [
        {
            "id": int(r[0]),
            "patient_id": int(r[1]),
            "sampling_date": r[2],
            "appointment_date": r[3],
            "created": r[4],
            "modified": r[5],
            "status": r[6],
        }
        for r in rows
    ]


def fetch_analysis_items(conn: Any, result_ids: list[int], *, per_result_limit: int = 20) -> list[dict[str, Any]]:
    if not result_ids:
        return []
    sql = """
    SELECT id, analysis_result_id, name, value, unit
    FROM (
      SELECT id, analysis_result_id, name, value, unit,
             ROW_NUMBER() OVER (PARTITION BY analysis_result_id ORDER BY id) AS rn
      FROM magerya_api.document_analysisresultitem
      WHERE analysis_result_id = ANY(%s)
    ) t
    WHERE rn <= %s
    ORDER BY analysis_result_id, id
    """
    rows = _fetch_all(conn, sql, (result_ids, per_result_limit))
    return [
        {
            "id": int(r[0]),
            "analysis_result_id": int(r[1]),
            "name": r[2],
            "value": r[3],
            "unit": r[4],
        }
        for r in rows
    ]


def fetch_analysis_items_uncapped(conn: Any, result_ids: list[int]) -> list[dict[str, Any]]:
    """All lab items for result ids — no per-result ROW_NUMBER cap."""
    if not result_ids:
        return []
    sql = """
    SELECT id, analysis_result_id, name, value, unit
    FROM magerya_api.document_analysisresultitem
    WHERE analysis_result_id = ANY(%s)
    ORDER BY analysis_result_id, id
    """
    rows = _fetch_all(conn, sql, (result_ids,))
    return [
        {
            "id": int(r[0]),
            "analysis_result_id": int(r[1]),
            "name": r[2],
            "value": r[3],
            "unit": r[4],
        }
        for r in rows
    ]


def select_all_eligible_patient_ids(conn: Any) -> list[int]:
    """All eligible subjects (appt≥3 AND lab≥1); no subject limit."""
    sql = """
    WITH appt AS (
      SELECT patient_id, COUNT(*)::int AS n_appt
      FROM magerya_api.appointment_appointment
      WHERE patient_id IS NOT NULL
      GROUP BY patient_id
    ),
    labs AS (
      SELECT patient_id, COUNT(*)::int AS n_lab
      FROM magerya_api.document_analysisresult
      WHERE patient_id IS NOT NULL
      GROUP BY patient_id
    )
    SELECT p.id
    FROM magerya_api.account_patient p
    JOIN appt a ON a.patient_id = p.id
    JOIN labs l ON l.patient_id = p.id
    WHERE a.n_appt >= 3 AND l.n_lab >= 1
    ORDER BY (a.n_appt + l.n_lab) DESC, p.id
    """
    rows = _fetch_all(conn, sql)
    return [int(r[0]) for r in rows]


def select_all_account_patient_ids(conn: Any) -> list[int]:
    """All Source A patients (canonical population ≠ scientific cohort)."""
    sql = """
    SELECT id
    FROM magerya_api.account_patient
    ORDER BY id
    """
    rows = _fetch_all(conn, sql)
    return [int(r[0]) for r in rows]


def fetch_medicine_appointments(conn: Any, patient_ids: list[int], *, limit: int = 500) -> list[dict[str, Any]]:
    if not patient_ids:
        return []
    # Column set may vary; select defensively via information_schema first
    cols = {
        r[0]
        for r in _fetch_all(
            conn,
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='magerya_api' AND table_name='diagnosis_medicineappointments'
            """,
        )
    }
    if "patient_id" not in cols or "id" not in cols:
        return []
    time_col = "created" if "created" in cols else None
    select_time = f", {time_col}" if time_col else ", NULL::timestamptz"
    sql = f"""
    SELECT id, patient_id{select_time}
    FROM magerya_api.diagnosis_medicineappointments
    WHERE patient_id = ANY(%s)
    ORDER BY id
    LIMIT %s
    """
    rows = _fetch_all(conn, sql, (patient_ids, limit))
    return [{"id": int(r[0]), "patient_id": int(r[1]), "created": r[2]} for r in rows]


def to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def truncation_accounting(
    conn: Any,
    patient_ids: list[int],
    *,
    per_patient_limit: int,
    per_result_limit: int,
) -> dict[str, Any]:
    """Aggregate available vs selected vs truncated — no patient IDs returned."""
    if not patient_ids:
        return {
            "per_patient_limit": per_patient_limit,
            "per_result_limit": per_result_limit,
            "relations": {},
        }

    def _cov(selected: int, available: int) -> float:
        return round(100.0 * selected / available, 4) if available else 100.0

    appt = _fetch_one(
        conn,
        "SELECT COUNT(*)::bigint FROM magerya_api.appointment_appointment WHERE patient_id = ANY(%s)",
        (patient_ids,),
    )
    appt_n = int(appt[0]) if appt else 0

    labs_available = _fetch_one(
        conn,
        """
        SELECT COUNT(*)::bigint FROM magerya_api.document_analysisresult
        WHERE patient_id = ANY(%s)
        """,
        (patient_ids,),
    )
    labs_available_n = int(labs_available[0]) if labs_available else 0

    # Uncapped full-population loads: no window ranking; truncated_rows must be 0.
    if per_patient_limit >= 10**9 and per_result_limit >= 10**9:
        items_available = _fetch_one(
            conn,
            """
            SELECT COUNT(*)::bigint
            FROM magerya_api.document_analysisresultitem i
            JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
            WHERE ar.patient_id = ANY(%s)
            """,
            (patient_ids,),
        )
        items_available_n = int(items_available[0]) if items_available else 0
        return {
            "per_patient_limit": per_patient_limit,
            "per_result_limit": per_result_limit,
            "cohort_subject_count": len(patient_ids),
            "uncapped_short_circuit": True,
            "relations": {
                "appointment_appointment": {
                    "available_rows": appt_n,
                    "selected_rows": appt_n,
                    "truncated_rows": 0,
                    "coverage_percentage": 100.0,
                    "note": "all appointments for cohort subjects loaded (no per-patient encounter cap)",
                },
                "document_analysisresult": {
                    "available_rows": labs_available_n,
                    "selected_rows": labs_available_n,
                    "truncated_rows": 0,
                    "coverage_percentage": 100.0,
                },
                "document_analysisresultitem": {
                    "available_rows": items_available_n,
                    "selected_rows": items_available_n,
                    "truncated_rows": 0,
                    "coverage_percentage": 100.0,
                    "note": "uncapped load — all items for patients considered",
                },
            },
        }

    labs_selected_row = _fetch_one(
        conn,
        """
        SELECT COUNT(*)::bigint FROM (
          SELECT id,
                 ROW_NUMBER() OVER (
                   PARTITION BY patient_id
                   ORDER BY COALESCE(appointment_date, created) DESC, id DESC
                 ) AS rn
          FROM magerya_api.document_analysisresult
          WHERE patient_id = ANY(%s)
        ) t WHERE rn <= %s
        """,
        (patient_ids, per_patient_limit),
    )
    labs_selected_n = int(labs_selected_row[0]) if labs_selected_row else 0

    # Items available for selected labs only (denominator for item truncation)
    selected_lab_ids = [
        int(r[0])
        for r in _fetch_all(
            conn,
            """
            SELECT id FROM (
              SELECT id,
                     ROW_NUMBER() OVER (
                       PARTITION BY patient_id
                       ORDER BY COALESCE(appointment_date, created) DESC, id DESC
                     ) AS rn
              FROM magerya_api.document_analysisresult
              WHERE patient_id = ANY(%s)
            ) t WHERE rn <= %s
            """,
            (patient_ids, per_patient_limit),
        )
    ]
    items_available_n = 0
    items_selected_n = 0
    if selected_lab_ids:
        av = _fetch_one(
            conn,
            """
            SELECT COUNT(*)::bigint FROM magerya_api.document_analysisresultitem
            WHERE analysis_result_id = ANY(%s)
            """,
            (selected_lab_ids,),
        )
        sel = _fetch_one(
            conn,
            """
            SELECT COUNT(*)::bigint FROM (
              SELECT id,
                     ROW_NUMBER() OVER (PARTITION BY analysis_result_id ORDER BY id) AS rn
              FROM magerya_api.document_analysisresultitem
              WHERE analysis_result_id = ANY(%s)
            ) t WHERE rn <= %s
            """,
            (selected_lab_ids, per_result_limit),
        )
        items_available_n = int(av[0]) if av else 0
        items_selected_n = int(sel[0]) if sel else 0

    return {
        "per_patient_limit": per_patient_limit,
        "per_result_limit": per_result_limit,
        "cohort_subject_count": len(patient_ids),
        "relations": {
            "appointment_appointment": {
                "available_rows": appt_n,
                "selected_rows": appt_n,
                "truncated_rows": 0,
                "coverage_percentage": 100.0,
                "note": "all appointments for cohort subjects loaded (no per-patient encounter cap)",
            },
            "document_analysisresult": {
                "available_rows": labs_available_n,
                "selected_rows": labs_selected_n,
                "truncated_rows": max(0, labs_available_n - labs_selected_n),
                "coverage_percentage": _cov(labs_selected_n, labs_available_n),
            },
            "document_analysisresultitem": {
                "available_rows": items_available_n,
                "selected_rows": items_selected_n,
                "truncated_rows": max(0, items_available_n - items_selected_n),
                "coverage_percentage": _cov(items_selected_n, items_available_n),
                "note": "available_rows counted only for selected analysisresult parents",
            },
        },
    }
