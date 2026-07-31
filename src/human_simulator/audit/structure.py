"""Structural profiling (null rates, column metadata)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from human_simulator.db.readonly import assert_readonly


def _quote_table(schema: str, table: str, dialect_name: str) -> str:
    if dialect_name == "sqlite":
        return f'"{table}"'
    return f'"{schema}"."{table}"'


def profile_structure(engine: Engine, schema_discovery: dict[str, Any]) -> dict[str, Any]:
    dialect_name = engine.dialect.name
    profiles: list[dict[str, Any]] = []

    for table in schema_discovery.get("tables", []):
        schema = table["schema"]
        name = table["name"]
        quoted = _quote_table(schema, name, dialect_name)
        row_count = _estimated_or_exact_count(engine, schema, name, dialect_name)

        columns_profile: list[dict[str, Any]] = []
        for column in table["columns"]:
            col_name = column["name"]
            quoted_col = f'"{col_name}"'
            null_sql = f"SELECT COUNT(*) FROM {quoted} WHERE {quoted_col} IS NULL"
            assert_readonly(null_sql)
            with engine.connect() as conn:
                null_count = conn.execute(text(null_sql)).scalar_one()
            null_pct = 0.0 if row_count == 0 else round(100.0 * null_count / row_count, 4)
            columns_profile.append(
                {
                    "name": col_name,
                    "type": column["type"],
                    "nullable": column["nullable"],
                    "null_count": null_count,
                    "null_pct": null_pct,
                }
            )

        profiles.append(
            {
                "schema": schema,
                "name": name,
                "estimated_rows": row_count,
                "columns": columns_profile,
            }
        )

    return {"tables": profiles}


def _estimated_or_exact_count(
    engine: Engine,
    schema: str,
    table: str,
    dialect_name: str,
) -> int:
    quoted = _quote_table(schema, table, dialect_name)
    if dialect_name == "postgresql":
        sql = (
            "SELECT COALESCE(c.reltuples::bigint, 0) "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = :table AND n.nspname = :schema"
        )
        assert_readonly(sql)
        with engine.connect() as conn:
            estimate = conn.execute(text(sql), {"table": table, "schema": schema}).scalar_one()
        if estimate and estimate > 0:
            return int(estimate)

    count_sql = f"SELECT COUNT(*) FROM {quoted}"
    assert_readonly(count_sql)
    with engine.connect() as conn:
        return int(conn.execute(text(count_sql)).scalar_one())
