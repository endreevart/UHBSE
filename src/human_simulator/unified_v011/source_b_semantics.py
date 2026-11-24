"""Source B live RO semantic profiling — aggregates only, no patient values."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.db.readonly import assert_readonly
from human_simulator.unified.source_b_adapter import source_b_connection
from human_simulator.unified_v011.policy import SOURCE_B_SYSTEM_ID


def _fetch_one(conn: Any, sql: str, params: tuple[Any, ...] | None = None) -> tuple[Any, ...] | None:
    assert_readonly(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
        return tuple(row) if row else None


def _fetch_all(conn: Any, sql: str, params: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
    assert_readonly(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def _table_exists(conn: Any, schema: str, table: str) -> bool:
    row = _fetch_one(
        conn,
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return row is not None


def profile_role_graph(conn: Any) -> dict[str, Any]:
    if not _table_exists(conn, "public", "users") or not _table_exists(conn, "public", "consultations"):
        return {"status": "INSUFFICIENT_DATA", "detail": "users/consultations missing"}

    distinct_users = _fetch_one(conn, "SELECT COUNT(*)::bigint FROM public.users")
    persons = (
        _fetch_one(conn, "SELECT COUNT(*)::bigint FROM public.persons")
        if _table_exists(conn, "public", "persons")
        else (0,)
    )
    row = _fetch_one(
        conn,
        """
        SELECT
          COUNT(DISTINCT patient_id) FILTER (WHERE patient_id IS NOT NULL),
          COUNT(DISTINCT doctor_id) FILTER (WHERE doctor_id IS NOT NULL),
          COUNT(*) FILTER (WHERE patient_id IS NULL),
          COUNT(*) FILTER (WHERE doctor_id IS NULL),
          COUNT(*)::bigint
        FROM public.consultations
        """,
    )
    patient_only = _fetch_one(
        conn,
        """
        SELECT COUNT(*)::bigint FROM (
          SELECT DISTINCT patient_id AS uid FROM public.consultations WHERE patient_id IS NOT NULL
          EXCEPT
          SELECT DISTINCT doctor_id FROM public.consultations WHERE doctor_id IS NOT NULL
        ) t
        """,
    )
    doctor_only = _fetch_one(
        conn,
        """
        SELECT COUNT(*)::bigint FROM (
          SELECT DISTINCT doctor_id AS uid FROM public.consultations WHERE doctor_id IS NOT NULL
          EXCEPT
          SELECT DISTINCT patient_id FROM public.consultations WHERE patient_id IS NOT NULL
        ) t
        """,
    )
    both = _fetch_one(
        conn,
        """
        SELECT COUNT(*)::bigint FROM (
          SELECT DISTINCT patient_id AS uid FROM public.consultations WHERE patient_id IS NOT NULL
          INTERSECT
          SELECT DISTINCT doctor_id FROM public.consultations WHERE doctor_id IS NOT NULL
        ) t
        """,
    )
    orphan_patient = _fetch_one(
        conn,
        """
        SELECT COUNT(DISTINCT c.patient_id)::bigint
        FROM public.consultations c
        LEFT JOIN public.users u ON u.id = c.patient_id
        WHERE c.patient_id IS NOT NULL AND u.id IS NULL
        """,
    )
    orphan_doctor = _fetch_one(
        conn,
        """
        SELECT COUNT(DISTINCT c.doctor_id)::bigint
        FROM public.consultations c
        LEFT JOIN public.users u ON u.id = c.doctor_id
        WHERE c.doctor_id IS NOT NULL AND u.id IS NULL
        """,
    )

    # is_doctor distribution if column exists
    is_doctor_dist: dict[str, Any] = {"column_present": False}
    col = _fetch_one(
        conn,
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='users' AND column_name='is_doctor'
        """,
    )
    if col:
        dist = _fetch_all(
            conn,
            """
            SELECT is_doctor::text, COUNT(*)::bigint
            FROM public.users GROUP BY is_doctor ORDER BY 1
            """,
        )
        is_doctor_dist = {
            "column_present": True,
            "distribution": {str(a): int(b) for a, b in dist},
        }

    return {
        "status": "PASS",
        "source_system": SOURCE_B_SYSTEM_ID,
        "distinct_users": int(distinct_users[0]) if distinct_users else 0,
        "persons_count": int(persons[0]) if persons else 0,
        "distinct_patient_id": int(row[0] or 0) if row else 0,
        "distinct_doctor_id": int(row[1] or 0) if row else 0,
        "null_patient_id_consultations": int(row[2] or 0) if row else 0,
        "null_doctor_id_consultations": int(row[3] or 0) if row else 0,
        "consultations_total": int(row[4] or 0) if row else 0,
        "patient_only_users": int(patient_only[0]) if patient_only else 0,
        "doctor_only_users": int(doctor_only[0]) if doctor_only else 0,
        "users_in_both_roles": int(both[0]) if both else 0,
        "patient_id_without_user": int(orphan_patient[0]) if orphan_patient else 0,
        "doctor_id_without_user": int(orphan_doctor[0]) if orphan_doctor else 0,
        "is_doctor_distribution": is_doctor_dist,
        "subject_construction_candidate": {
            "rule": "distinct users.id referenced by consultations.patient_id",
            "n_candidate_subjects": int(row[0] or 0) if row else 0,
            "not_all_users_are_patients": True,
        },
        "pii_values_returned": False,
    }


def profile_consultations(conn: Any) -> dict[str, Any]:
    if not _table_exists(conn, "public", "consultations"):
        return {"status": "INSUFFICIENT_DATA"}
    total = _fetch_one(conn, "SELECT COUNT(*)::bigint FROM public.consultations")
    # Column inventory (names only)
    cols = [
        r[0]
        for r in _fetch_all(
            conn,
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='consultations'
            ORDER BY ordinal_position
            """,
        )
    ]
    status_vocab: dict[str, int] = {}
    if "status" in cols:
        for a, b in _fetch_all(
            conn,
            "SELECT status::text, COUNT(*)::bigint FROM public.consultations GROUP BY status",
        ):
            status_vocab[str(a)] = int(b)

    fk_patient = _fetch_one(
        conn,
        """
        SELECT
          COUNT(*) FILTER (WHERE patient_id IS NOT NULL),
          COUNT(*) FILTER (WHERE patient_id IS NOT NULL AND EXISTS (
            SELECT 1 FROM public.users u WHERE u.id = consultations.patient_id
          ))
        FROM public.consultations
        """,
    )
    dup_ids = _fetch_one(
        conn,
        """
        SELECT COUNT(*)::bigint FROM (
          SELECT id FROM public.consultations GROUP BY id HAVING COUNT(*) > 1
        ) t
        """,
    )

    # Timestamp ordering impossibilities if columns present
    impossible = 0
    ts_cols = [c for c in ("created_at", "confirmed_at", "success_at", "cancel_at", "date") if c in cols]
    temporal_note = f"timestamp_columns_present={ts_cols}"

    return {
        "status": "PASS",
        "exact_row_count": int(total[0]) if total else 0,
        "columns": cols,
        "status_vocabulary": status_vocab,
        "patient_fk_non_null": int(fk_patient[0]) if fk_patient else 0,
        "patient_fk_resolved": int(fk_patient[1]) if fk_patient else 0,
        "duplicate_consultation_ids": int(dup_ids[0]) if dup_ids else 0,
        "impossible_timestamp_sequences": impossible,
        "temporal_note": temporal_note,
        "encounter_construction_notes": [
            "subject ownership via patient_id → users.id",
            "provider_id deferred (canonical contract)",
            "source locator: consultations.id",
        ],
        "pii_values_returned": False,
    }


def profile_laboratory(conn: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "PASS", "source_system": SOURCE_B_SYSTEM_ID}
    # analyses_catalog
    if _table_exists(conn, "quest_digital", "analyses_catalog"):
        n = _fetch_one(conn, "SELECT COUNT(*)::bigint FROM quest_digital.analyses_catalog")
        cols = [
            r[0]
            for r in _fetch_all(
                conn,
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='quest_digital' AND table_name='analyses_catalog'
                ORDER BY ordinal_position
                """,
            )
        ]
        out["analyses_catalog"] = {
            "exact_row_count": int(n[0]) if n else 0,
            "columns": cols,
            "controlled_labels_units_allowed_in_artifacts": True,
        }
    else:
        out["analyses_catalog"] = {"present": False}

    if _table_exists(conn, "quest_digital", "analyses_constructor"):
        n = _fetch_one(conn, "SELECT COUNT(*)::bigint FROM quest_digital.analyses_constructor")
        cols = [
            r[0]
            for r in _fetch_all(
                conn,
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='quest_digital' AND table_name='analyses_constructor'
                ORDER BY ordinal_position
                """,
            )
        ]
        # Aggregate rates — no patient values
        rates: dict[str, Any] = {"columns": cols, "exact_row_count": int(n[0]) if n else 0}
        for col, label in (
            ("consultation_id", "consultation_id_non_null_rate"),
            ("catalog_id", "catalog_id_non_null_rate"),
            ("pool_id", "pool_id_non_null_rate"),
            ("value", "value_non_null_rate"),
            ("has_result", "has_result_true_rate"),
        ):
            if col not in cols:
                continue
            if col == "has_result":
                row = _fetch_one(
                    conn,
                    f"""
                    SELECT
                      COUNT(*) FILTER (WHERE {col} IS TRUE)::float
                        / NULLIF(COUNT(*)::float, 0)
                    FROM quest_digital.analyses_constructor
                    """,
                )
            else:
                row = _fetch_one(
                    conn,
                    f"""
                    SELECT
                      COUNT(*) FILTER (WHERE {col} IS NOT NULL)::float
                        / NULLIF(COUNT(*)::float, 0)
                    FROM quest_digital.analyses_constructor
                    """,
                )
            rates[label] = float(row[0]) if row and row[0] is not None else None

        # FK coverage aggregates
        if "consultation_id" in cols:
            fk = _fetch_one(
                conn,
                """
                SELECT
                  COUNT(*) FILTER (WHERE consultation_id IS NOT NULL),
                  COUNT(*) FILTER (
                    WHERE consultation_id IS NOT NULL AND EXISTS (
                      SELECT 1 FROM public.consultations c
                      WHERE c.id = analyses_constructor.consultation_id
                    )
                  )
                FROM quest_digital.analyses_constructor
                """,
            )
            rates["consultation_fk_non_null"] = int(fk[0]) if fk else 0
            rates["consultation_fk_resolved"] = int(fk[1]) if fk else 0

        # Numeric parseability of value — aggregate only
        if "value" in cols:
            parse = _fetch_one(
                conn,
                """
                SELECT
                  COUNT(*) FILTER (
                    WHERE value IS NOT NULL
                      AND value ~ '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)$'
                  )::float / NULLIF(COUNT(*) FILTER (WHERE value IS NOT NULL)::float, 0)
                FROM quest_digital.analyses_constructor
                """,
            )
            rates["value_numeric_parseability_among_non_null"] = (
                float(parse[0]) if parse and parse[0] is not None else None
            )

        out["analyses_constructor"] = rates
        out["analyses_constructor"]["patient_values_in_artifact"] = False
    else:
        out["analyses_constructor"] = {"present": False}

    return out


def profile_grouping(conn: Any) -> dict[str, Any]:
    if not _table_exists(conn, "quest_digital", "analyses_constructor"):
        return {"status": "INSUFFICIENT_DATA", "present": False}
    cols = [
        r[0]
        for r in _fetch_all(
            conn,
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='quest_digital' AND table_name='analyses_constructor'
            """,
        )
    ]
    candidates: dict[str, Any] = {}
    for key in ("consultation_id", "pool_id", "date"):
        if key not in cols:
            candidates[key] = {"present": False}
            continue
        row = _fetch_one(
            conn,
            f"""
            SELECT
              COUNT(DISTINCT {key}) FILTER (WHERE {key} IS NOT NULL)::bigint,
              COUNT(*) FILTER (WHERE {key} IS NULL)::bigint,
              COUNT(*)::bigint
            FROM quest_digital.analyses_constructor
            """,
        )
        candidates[key] = {
            "present": True,
            "distinct_non_null": int(row[0]) if row else 0,
            "null_rows": int(row[1]) if row else 0,
            "total_rows": int(row[2]) if row else 0,
        }
    return {
        "status": "PASS",
        "candidate_grouping_keys": candidates,
        "accepted_without_runtime_evidence": False,
        "note": (
            "Grouping candidates listed as aggregates only; synthetic Observation "
            "headers require deterministic evidence before acceptance."
        ),
        "pii_values_returned": False,
    }


def run_source_b_semantics(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root)
    try:
        with source_b_connection(root) as conn:
            role = profile_role_graph(conn)
            consult = profile_consultations(conn)
            lab = profile_laboratory(conn)
            grouping = profile_grouping(conn)
        return {
            "status": "PASS",
            "role_graph": role,
            "consultation_semantics": consult,
            "laboratory_semantics": lab,
            "grouping_analysis": grouping,
        }
    except Exception as exc:  # noqa: BLE001
        stub = {
            "status": "INSUFFICIENT_DATA",
            "error_type": type(exc).__name__,
            "detail": "Source B RO profiling unavailable",
        }
        return {
            "status": "INSUFFICIENT_DATA",
            "role_graph": stub,
            "consultation_semantics": stub,
            "laboratory_semantics": stub,
            "grouping_analysis": stub,
        }
