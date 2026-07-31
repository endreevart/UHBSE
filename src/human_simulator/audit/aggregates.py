"""Aggregate profiling using Polars summaries."""

from __future__ import annotations

from typing import Any

import polars as pl
from sqlalchemy.engine import Engine


def profile_aggregates(
    engine: Engine,
    structure_profile: dict[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for table in structure_profile.get("tables", []):
        for column in table.get("columns", []):
            rows.append(
                {
                    "schema": table["schema"],
                    "table": table["name"],
                    "column": column["name"],
                    "type": column["type"],
                    "null_pct": column["null_pct"],
                    "estimated_rows": table["estimated_rows"],
                }
            )

    if not rows:
        summary = pl.DataFrame(
            schema={
                "schema": pl.String,
                "table": pl.String,
                "column": pl.String,
                "type": pl.String,
                "null_pct": pl.Float64,
                "estimated_rows": pl.Int64,
            }
        )
    else:
        summary = pl.DataFrame(rows)

    numeric = summary.filter(pl.col("type").str.contains("INT|NUM|REAL|FLOAT|DOUBLE", strict=False))
    aggregates: dict[str, Any] = {
        "column_count": summary.height,
        "tables_with_null_only_columns": _null_only_columns(summary),
        "numeric_column_count": numeric.height,
        "summary": summary.sort(["schema", "table", "column"]).to_dicts(),
    }
    return aggregates


def _null_only_columns(summary: pl.DataFrame) -> list[dict[str, Any]]:
    if summary.is_empty():
        return []
    grouped = (
        summary.filter(pl.col("null_pct") >= 100.0)
        .select(["schema", "table", "column"])
        .to_dicts()
    )
    return grouped
