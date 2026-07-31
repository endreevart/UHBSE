"""Schema discovery via SQLAlchemy inspector."""

from __future__ import annotations

from typing import Any

import polars as pl
from sqlalchemy import inspect
from sqlalchemy.engine import Engine


def discover_schema(engine: Engine) -> dict[str, Any]:
    inspector = inspect(engine)
    tables: list[dict[str, Any]] = []

    for schema in sorted(inspector.get_schema_names()):
        if schema.startswith("pg_") or schema in {"information_schema"}:
            continue
        for table_name in sorted(inspector.get_table_names(schema=schema)):
            columns = inspector.get_columns(table_name, schema=schema)
            fks = inspector.get_foreign_keys(table_name, schema=schema)
            pk = inspector.get_pk_constraint(table_name, schema=schema)
            tables.append(
                {
                    "schema": schema,
                    "name": table_name,
                    "columns": [
                        {
                            "name": col["name"],
                            "type": str(col["type"]),
                            "nullable": col.get("nullable", True),
                        }
                        for col in columns
                    ],
                    "primary_key": pk.get("constrained_columns") or [],
                    "foreign_keys": [
                        {
                            "columns": fk.get("constrained_columns") or [],
                            "referred_table": fk.get("referred_table"),
                            "referred_columns": fk.get("referred_columns") or [],
                        }
                        for fk in fks
                    ],
                }
            )

    frame = pl.DataFrame(
        [
            {
                "schema": t["schema"],
                "table": t["name"],
                "column_count": len(t["columns"]),
            }
            for t in tables
        ]
    )
    return {"table_count": len(tables), "tables": tables, "summary": frame.to_dicts()}
