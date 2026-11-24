"""Full multi-schema inventory — exact counts for clinical candidates; no reltuples for PASS."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_research_layer_v031.policy import (
    INFRASTRUCTURE_SCHEMAS,
    PIN_SOURCE_A_SUBJECTS,
    PIN_SOURCE_B_SUBJECTS,
    VERSION,
)

SYSTEM_SCHEMAS = frozenset(
    {
        "pg_catalog",
        "information_schema",
        "pg_toast",
    }
)


def _list_schemas(cur: Any) -> list[str]:
    cur.execute(
        """
        SELECT nspname FROM pg_namespace
        WHERE nspname NOT LIKE 'pg_temp%'
          AND nspname NOT LIKE 'pg_toast_temp%'
          AND nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        ORDER BY 1
        """
    )
    return [r[0] for r in cur.fetchall()]


def _list_relations(cur: Any, schema: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT c.relname,
               CASE c.relkind
                 WHEN 'r' THEN 'table'
                 WHEN 'p' THEN 'partitioned_table'
                 WHEN 'v' THEN 'view'
                 WHEN 'm' THEN 'materialized_view'
                 WHEN 'f' THEN 'foreign_table'
                 ELSE c.relkind::text
               END AS kind,
               COALESCE(c.reltuples, -1)::bigint AS reltuples_estimate
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
        ORDER BY 1
        """,
        (schema,),
    )
    return [
        {
            "schema": schema,
            "relation": name,
            "kind": kind,
            "reltuples_estimate_non_authoritative": int(est) if est is not None else None,
        }
        for name, kind, est in cur.fetchall()
    ]


def _column_count(cur: Any, schema: str, table: str) -> int:
    cur.execute(
        """
        SELECT COUNT(*)::int FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return int(cur.fetchone()[0])


def _fk_count(cur: Any, schema: str, table: str) -> int:
    cur.execute(
        """
        SELECT COUNT(*)::int
        FROM information_schema.table_constraints
        WHERE table_schema = %s AND table_name = %s AND constraint_type = 'FOREIGN KEY'
        """,
        (schema, table),
    )
    return int(cur.fetchone()[0])


def exact_count(cur: Any, schema: str, table: str) -> int | None:
    try:
        cur.execute(f'SELECT COUNT(*)::bigint FROM "{schema}"."{table}"')
        return int(cur.fetchone()[0])
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        try:
            cur.execute("SET default_transaction_read_only = on")
        except Exception:
            pass
        return None


# Clinical candidate relations requiring exact counts (authoritative accounting)
CLINICAL_EXACT_A = {
    ("magerya_api", "account_patient"),
    ("magerya_api", "appointment_appointment"),
    ("magerya_api", "document_analysisresult"),
    ("magerya_api", "document_analysisresultitem"),
    ("magerya_api", "diagnosis_diagnosis"),
    ("magerya_api", "diagnosis_medicines"),
    ("magerya_api", "diagnosis_medicineappointments"),
    ("magerya_api", "document_recommendation"),
    ("magerya_api", "diagnosis_proceduresresult"),
    ("magerya_api", "diagnosis_manipulationsresult"),
    ("magerya_api", "document_procedurelist"),
    ("magerya_api", "document_document"),
}

CLINICAL_EXACT_B = {
    ("public", "users"),
    ("public", "consultations"),
    ("public", "documents"),
    ("quest_digital", "analyses_pool"),
    ("quest_digital", "analyses_constructor"),
    ("quest_digital", "analyses_catalog"),
    ("quest_digital", "recommendations_user"),
    ("quest_digital", "recommendations_list"),
    ("quest_digital", "recommendations_category"),
    ("quest_digital", "link_analyses"),
    ("quest_digital", "analyses_weight"),
    ("quest_digital", "catalog_weights"),
}


def inventory_source(
    *,
    conn: Any | None,
    source_system: str,
    pin_subjects: int,
    clinical_exact: set[tuple[str, str]],
    subject_schema_table: tuple[str, str] | None,
) -> dict[str, Any]:
    if conn is None:
        return {
            "version": VERSION,
            "source_system": source_system,
            "connection": "UNAVAILABLE",
            "ok": False,
        }
    cur = conn.cursor()
    try:
        cur.execute("SET default_transaction_read_only = on")
        cur.execute("SET statement_timeout = 600000")
        schemas = _list_schemas(cur)
        app_schemas = [s for s in schemas if s not in INFRASTRUCTURE_SCHEMAS]
        infra_schemas = [s for s in schemas if s in INFRASTRUCTURE_SCHEMAS]
        relations: list[dict[str, Any]] = []
        n_tables = n_views = n_partitions = 0
        n_columns = 0
        n_fks = 0
        exact_rows: dict[str, int] = {}

        for schema in schemas:
            rels = _list_relations(cur, schema)
            for r in rels:
                kind = r["kind"]
                if kind == "table":
                    n_tables += 1
                elif kind == "view":
                    n_views += 1
                elif kind == "partitioned_table":
                    n_partitions += 1
                cols = _column_count(cur, schema, r["relation"])
                fks = _fk_count(cur, schema, r["relation"]) if kind in {"table", "partitioned_table"} else 0
                n_columns += cols
                n_fks += fks
                entry = {
                    **r,
                    "n_columns": cols,
                    "n_foreign_keys": fks,
                    "schema_class": (
                        "infrastructure"
                        if schema in INFRASTRUCTURE_SCHEMAS
                        else "application"
                    ),
                }
                key = (schema, r["relation"])
                if key in clinical_exact and kind in {"table", "partitioned_table"}:
                    n = exact_count(cur, schema, r["relation"])
                    entry["exact_row_count"] = n
                    entry["count_method"] = "COUNT(*)" if n is not None else "FAILED"
                    if n is not None:
                        exact_rows[f"{schema}.{r['relation']}"] = n
                else:
                    entry["exact_row_count"] = None
                    entry["count_method"] = (
                        "NOT_REQUIRED_INFRASTRUCTURE"
                        if schema in INFRASTRUCTURE_SCHEMAS
                        else "DEFERRED_NON_CLINICAL_CANDIDATE"
                    )
                relations.append(entry)

        subject_count = None
        if subject_schema_table:
            subject_count = exact_rows.get(
                f"{subject_schema_table[0]}.{subject_schema_table[1]}"
            )
            if subject_count is None:
                subject_count = exact_count(
                    cur, subject_schema_table[0], subject_schema_table[1]
                )

        return {
            "version": VERSION,
            "source_system": source_system,
            "connection": "OK",
            "schemas_all": schemas,
            "application_schemas": app_schemas,
            "infrastructure_schemas": infra_schemas,
            "n_schemas": len(schemas),
            "n_tables": n_tables,
            "n_views": n_views,
            "n_partitions": n_partitions,
            "n_relations": len(relations),
            "n_columns_sum": n_columns,
            "n_foreign_keys_sum": n_fks,
            "subject_count_exact": subject_count,
            "subject_count_matches_pin": subject_count == pin_subjects,
            "pin_subjects": pin_subjects,
            "exact_clinical_counts": exact_rows,
            "reltuples_used_for_authoritative_accounting": False,
            "relations": relations,
            "ok": True,
        }
    finally:
        cur.close()


def inventory_canonical(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SET search_path TO canonical_evidence, public")
        cur.execute("SET default_transaction_read_only = on")
        cur.execute(
            """
            SELECT source_system_id, COUNT(*)::bigint
            FROM subject GROUP BY 1
            """
        )
        by_sys = {r[0]: int(r[1]) for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*)::bigint FROM subject")
        n_subj = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*)::bigint FROM encounter")
        n_enc = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*)::bigint FROM observation")
        n_obs = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*)::bigint FROM observation_component")
        n_comp = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*)::bigint FROM source_record")
        n_sr = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT s.source_system_id, COUNT(*)::bigint
            FROM encounter e JOIN subject s ON s.subject_id = e.subject_id
            GROUP BY 1
            """
        )
        enc_by = {r[0]: int(r[1]) for r in cur.fetchall()}
        cur.execute(
            """
            SELECT s.source_system_id, COUNT(*)::bigint
            FROM observation o JOIN subject s ON s.subject_id = o.subject_id
            GROUP BY 1
            """
        )
        obs_by = {r[0]: int(r[1]) for r in cur.fetchall()}
    return {
        "version": VERSION,
        "n_subjects": n_subj,
        "source_a_subjects": by_sys.get("magerya_api"),
        "source_b_subjects": by_sys.get("kgz_raw"),
        "n_encounters": n_enc,
        "encounters_by_source": enc_by,
        "n_observations": n_obs,
        "observations_by_source": obs_by,
        "n_observation_components": n_comp,
        "n_source_records": n_sr,
        "pins_match": by_sys.get("magerya_api") == PIN_SOURCE_A_SUBJECTS
        and by_sys.get("kgz_raw") == PIN_SOURCE_B_SUBJECTS,
        "count_method": "COUNT(*)",
        "ok": True,
    }


def inventory_source_a(conn: Any | None) -> dict[str, Any]:
    return inventory_source(
        conn=conn,
        source_system="magerya_api",
        pin_subjects=PIN_SOURCE_A_SUBJECTS,
        clinical_exact=CLINICAL_EXACT_A,
        subject_schema_table=("magerya_api", "account_patient"),
    )


def inventory_source_b(conn: Any | None) -> dict[str, Any]:
    inv = inventory_source(
        conn=conn,
        source_system="kgz_raw",
        pin_subjects=PIN_SOURCE_B_SUBJECTS,
        clinical_exact=CLINICAL_EXACT_B,
        subject_schema_table=("public", "users"),
    )
    # B subject pin is canonical patient-role users, not all public.users rows
    if inv.get("connection") == "OK":
        inv["raw_users_count"] = (inv.get("exact_clinical_counts") or {}).get(
            "public.users"
        )
        inv["subject_count_note"] = (
            "PIN_SOURCE_B_SUBJECTS refers to canonical patient-role subjects "
            "(kgz_raw), not raw public.users cardinality"
        )
        # subject pin validated via canonical separately
        inv["subject_count_matches_pin"] = None
    return inv
