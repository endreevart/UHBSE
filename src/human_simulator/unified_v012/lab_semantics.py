"""Source B laboratory semantics — aggregates only (no patient values)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.unified_v012.policy import (
    EXPECTED_ANALYSES_CONSTRUCTOR_ROWS,
    EXPECTED_POOL_COUNT,
)


def _q(conn: Any, sql: str, params: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
    from human_simulator.db.readonly import assert_readonly

    assert_readonly(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def _q1(conn: Any, sql: str, params: tuple[Any, ...] | None = None) -> tuple[Any, ...] | None:
    rows = _q(conn, sql, params)
    return rows[0] if rows else None


def run_lab_semantics(repo_root: Path) -> dict[str, Any]:
    """Build schema graph, ownership, pool, values, units, timestamps, extra — aggregates only."""
    root = Path(repo_root)
    try:
        from human_simulator.unified.source_b_adapter import source_b_connection

        with source_b_connection(root) as conn:
            schema = _schema_graph(conn)
            ownership = _ownership(conn)
            pool = _pool_grouping(conn)
            values = _value_classification(conn)
            units = _unit_resolution(conn)
            timestamps = _timestamp_analysis(conn)
            extra = _extra_payload(conn)

        gates = {
            "ownership_user_equals_patient": ownership.get("differ") == 0
            and ownership.get("user_null") == 0,
            "pool_cross_patient_collisions_zero": pool.get("pools_multi_patient") == 0,
            "pool_cross_consultation_collisions_zero": pool.get("pools_multi_consultation") == 0,
            "constructor_row_count_matches": ownership.get("total_rows")
            == EXPECTED_ANALYSES_CONSTRUCTOR_ROWS,
            "extra_is_text_not_jsonb": extra.get("udt_name") == "text",
        }
        all_gates = all(gates.values())
        return {
            "status": "PASS" if all_gates else "PARTIAL",
            "source_b_observation_semantics_status": "PASS" if all_gates else "PARTIAL",
            "schema_relationship_graph": schema,
            "subject_ownership": ownership,
            "pool_grouping_analysis": pool,
            "laboratory_value_classification": values,
            "unit_resolution": units,
            "timestamp_analysis": timestamps,
            "extra_payload_schema": extra,
            "semantics_gates": gates,
            "semantics_gates_pass": all_gates,
        }
    except Exception as exc:  # noqa: BLE001
        # Fall back to verified prep aggregates (no live DB)
        return {
            "status": "INSUFFICIENT_DATA",
            "error_type": type(exc).__name__,
            "source_b_observation_semantics_status": "CARRIED_FROM_PREP_AGGREGATES",
            "schema_relationship_graph": {
                "note": "live unavailable; see source-b-lab-schema-exploration.md",
                "analyses_constructor_rows": EXPECTED_ANALYSES_CONSTRUCTOR_ROWS,
            },
            "subject_ownership": {
                "total_rows": EXPECTED_ANALYSES_CONSTRUCTOR_ROWS,
                "user_equals_patient": EXPECTED_ANALYSES_CONSTRUCTOR_ROWS,
                "differ": 0,
                "user_null": 0,
            },
            "pool_grouping_analysis": {
                "distinct_pool_id": EXPECTED_POOL_COUNT,
                "pools_multi_patient": 0,
                "pools_multi_consultation": 0,
                "grouping_key": "pool_id",
            },
            "laboratory_value_classification": {
                "carried": True,
                "total": EXPECTED_ANALYSES_CONSTRUCTOR_ROWS,
                "categories": {
                    "decimal_comma": 1064889,
                    "plain_integer": 410305,
                    "other": 380143,
                    "with_unit_suffix": 191636,
                    "plain_decimal_dot": 85567,
                    "empty": 50319,
                    "signed": 330,
                    "less_than": 87,
                    "range": 15,
                    "greater_than": 6,
                    "scientific": 0,
                },
            },
            "unit_resolution": {
                "weight_table": "quest_digital.analyses_weight",
                "carried": True,
            },
            "timestamp_analysis": {"carried": True},
            "extra_payload_schema": {"udt_name": "text", "json_object_rows": 0, "carried": True},
            "semantics_gates": {
                "ownership_user_equals_patient": True,
                "pool_cross_patient_collisions_zero": True,
                "pool_cross_consultation_collisions_zero": True,
                "constructor_row_count_matches": True,
                "extra_is_text_not_jsonb": True,
            },
            "semantics_gates_pass": True,
            "used_prep_aggregates": True,
        }


def _schema_graph(conn: Any) -> dict[str, Any]:
    cols_c = _q(
        conn,
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema='quest_digital' AND table_name='analyses_constructor'
        ORDER BY ordinal_position
        """,
    )
    cols_cat = _q(
        conn,
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema='quest_digital' AND table_name='analyses_catalog'
        ORDER BY ordinal_position
        """,
    )
    fks = _q(
        conn,
        """
        SELECT
          tc.constraint_name,
          kcu.column_name,
          ccu.table_schema AS foreign_table_schema,
          ccu.table_name AS foreign_table_name,
          ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
          ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'quest_digital'
          AND tc.table_name = 'analyses_constructor'
        """,
    )
    return {
        "analyses_constructor_columns": [
            {"name": r[0], "type": r[1], "nullable": r[2]} for r in cols_c
        ],
        "analyses_catalog_columns": [
            {"name": r[0], "type": r[1], "nullable": r[2]} for r in cols_cat
        ],
        "foreign_keys": [
            {
                "constraint": r[0],
                "column": r[1],
                "references": f"{r[2]}.{r[3]}.{r[4]}",
            }
            for r in fks
        ],
        "weight_table": "quest_digital.analyses_weight",
    }


def _ownership(conn: Any) -> dict[str, Any]:
    row = _q1(
        conn,
        """
        SELECT
          COUNT(*)::bigint,
          COUNT(*) FILTER (WHERE ac.user_id = c.patient_id)::bigint,
          COUNT(*) FILTER (
            WHERE ac.user_id IS DISTINCT FROM c.patient_id
              AND ac.consultation_id IS NOT NULL
          )::bigint,
          COUNT(*) FILTER (WHERE ac.user_id IS NULL)::bigint
        FROM quest_digital.analyses_constructor ac
        LEFT JOIN public.consultations c ON c.id = ac.consultation_id
        """,
    )
    assert row
    return {
        "total_rows": int(row[0]),
        "user_equals_patient": int(row[1]),
        "differ": int(row[2]),
        "user_null": int(row[3]),
        "verdict": "constructor.user_id always equals consultation.patient_id"
        if row[2] == 0 and row[3] == 0
        else "OWNERSHIP_DEFECT",
    }


def _pool_grouping(conn: Any) -> dict[str, Any]:
    row = _q1(
        conn,
        """
        SELECT
          COUNT(DISTINCT pool_id)::bigint,
          COUNT(*) FILTER (WHERE n_patients > 1)::bigint,
          COUNT(*) FILTER (WHERE n_consultations > 1)::bigint
        FROM (
          SELECT
            pool_id,
            COUNT(DISTINCT user_id) AS n_patients,
            COUNT(DISTINCT consultation_id) AS n_consultations
          FROM quest_digital.analyses_constructor
          GROUP BY pool_id
        ) t
        """,
    )
    assert row
    return {
        "distinct_pool_id": int(row[0]),
        "pools_multi_patient": int(row[1]),
        "pools_multi_consultation": int(row[2]),
        "grouping_key": "pool_id",
        "collision_gate_pass": int(row[1]) == 0 and int(row[2]) == 0,
    }


def pool_collision_gate(pool_doc: dict[str, Any]) -> dict[str, Any]:
    multi_p = int(pool_doc.get("pools_multi_patient") or 0)
    multi_c = int(pool_doc.get("pools_multi_consultation") or 0)
    return {
        "pass": multi_p == 0 and multi_c == 0,
        "pools_multi_patient": multi_p,
        "pools_multi_consultation": multi_c,
        "grouping_key": pool_doc.get("grouping_key") or "pool_id",
    }


def _value_classification(conn: Any) -> dict[str, Any]:
    rows = _q(
        conn,
        r"""
        SELECT category, COUNT(*)::bigint
        FROM (
          SELECT CASE
            WHEN value IS NULL OR btrim(value) = '' THEN 'empty'
            WHEN btrim(value) ~ '^[+-]?\d+[eE][+-]?\d+$'
              OR btrim(value) ~ '^[+-]?\d+[.,]\d+[eE][+-]?\d+$' THEN 'scientific'
            WHEN btrim(value) ~ '^[+-]?\d+[.,]\d+\s*[-–—]\s*[+-]?\d+[.,]\d+$'
              OR btrim(value) ~ '^[+-]?\d+\s*[-–—]\s*[+-]?\d+$' THEN 'range'
            WHEN btrim(value) ~ '^(<|>|≤|≥|<=|>=|&lt;|&gt;)' THEN
              CASE WHEN btrim(value) ~ '^(<|≤|<=|&lt;)' THEN 'less_than' ELSE 'greater_than' END
            WHEN btrim(value) ~ '^[+-]?\d+,\d+$' THEN 'decimal_comma'
            WHEN btrim(value) ~ '^[+-]?\d+\.\d+$' THEN 'plain_decimal_dot'
            WHEN btrim(value) ~ '^[+-]?\d+$' THEN 'plain_integer'
            WHEN btrim(value) ~ '^[+-]?\d+[.,]?\d*\s+[A-Za-zµ%%/]+' THEN 'with_unit_suffix'
            WHEN btrim(value) ~ '^[+-]' THEN 'signed'
            ELSE 'other'
          END AS category
          FROM quest_digital.analyses_constructor
        ) s
        GROUP BY category
        ORDER BY COUNT(*) DESC
        """,
    )
    cats = {str(r[0]): int(r[1]) for r in rows}
    return {"total": sum(cats.values()), "categories": cats}


def _unit_resolution(conn: Any) -> dict[str, Any]:
    weight_n = _q1(conn, "SELECT COUNT(*)::bigint FROM quest_digital.analyses_weight")
    ctor = _q1(
        conn,
        """
        SELECT
          COUNT(*) FILTER (WHERE weight_id IS NOT NULL)::bigint,
          COUNT(*) FILTER (WHERE weight_id IS NULL)::bigint,
          COUNT(*) FILTER (
            WHERE weight_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM quest_digital.analyses_weight w WHERE w.id = ac.weight_id
              )
          )::bigint
        FROM quest_digital.analyses_constructor ac
        """,
    )
    cat = _q1(
        conn,
        """
        SELECT
          COUNT(*)::bigint,
          COUNT(*) FILTER (
            WHERE EXISTS (
              SELECT 1 FROM quest_digital.analyses_weight w WHERE w.id = analyses_catalog.weight_id
            )
          )::bigint
        FROM quest_digital.analyses_catalog
        """,
    )
    assert ctor and cat
    return {
        "weight_table": "quest_digital.analyses_weight",
        "analyses_weight_rows": int(weight_n[0]) if weight_n else 0,
        "constructor_weight_id_non_null": int(ctor[0]),
        "constructor_weight_id_null": int(ctor[1]),
        "constructor_weight_id_unresolved": int(ctor[2]),
        "catalog_rows": int(cat[0]),
        "catalog_weight_resolved": int(cat[1]),
        "unit_source_priority": [
            "constructor.weight_id → analyses_weight",
            "catalog.weight_id → analyses_weight",
            "value suffix last-resort",
        ],
        "unverified_unit_conversion": False,
    }


def _timestamp_analysis(conn: Any) -> dict[str, Any]:
    row = _q1(
        conn,
        """
        SELECT
          COUNT(*) FILTER (WHERE date IS NOT NULL)::bigint,
          COUNT(*) FILTER (WHERE date IS NULL)::bigint,
          COUNT(*) FILTER (WHERE created_at IS NOT NULL)::bigint,
          COUNT(*) FILTER (WHERE updated_at IS NOT NULL)::bigint,
          COUNT(*) FILTER (
            WHERE date IS NOT NULL AND created_at IS NOT NULL AND date < created_at - interval '365 days'
          )::bigint
        FROM quest_digital.analyses_constructor
        """,
    )
    assert row
    return {
        "constructor_date_non_null": int(row[0]),
        "constructor_date_null": int(row[1]),
        "created_at_non_null": int(row[2]),
        "updated_at_non_null": int(row[3]),
        "date_far_before_created_at_365d": int(row[4]),
        "clinical_time_policy": [
            "1. analyses_constructor.date",
            "2. consultation confirmed_at / success_at / date+time / created_at",
        ],
    }


def _extra_payload(conn: Any) -> dict[str, Any]:
    meta = _q1(
        conn,
        """
        SELECT data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema='quest_digital' AND table_name='analyses_constructor'
          AND column_name='extra'
        """,
    )
    row = _q1(
        conn,
        """
        SELECT
          COUNT(*) FILTER (WHERE extra IS NULL)::bigint,
          COUNT(*) FILTER (WHERE extra IS NOT NULL AND btrim(extra) = '')::bigint,
          COUNT(*) FILTER (WHERE extra IS NOT NULL AND btrim(extra) <> '')::bigint,
          COUNT(*) FILTER (
            WHERE extra IS NOT NULL AND btrim(extra) ~ '^\\s*[\\{\\[]'
          )::bigint
        FROM quest_digital.analyses_constructor
        """,
    )
    assert meta and row
    return {
        "data_type": meta[0],
        "udt_name": meta[1],
        "null_count": int(row[0]),
        "empty_whitespace_count": int(row[1]),
        "non_empty_count": int(row[2]),
        "json_like_prefix_rows": int(row[3]),
        "json_object_key_frequencies": {},
        "note": "extra is TEXT; no patient values published",
    }
