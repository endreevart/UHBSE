"""Build schema-profile.json from a PostgreSQL custom dump (schema-only, no rows)."""

from __future__ import annotations

import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CREATE_TABLE = re.compile(
    r"CREATE TABLE (?P<schema>\w+)\.(?P<relation>\w+)\s*\((?P<body>.*?)\);\s*$",
    re.MULTILINE | re.DOTALL,
)
_ALTER_FK = re.compile(
    r"ALTER TABLE ONLY (?P<schema>\w+)\.(?P<relation>\w+)\s+"
    r"ADD CONSTRAINT (?P<name>\w+) FOREIGN KEY \((?P<column>[^)]+)\)\s+"
    r"REFERENCES (?P<foreign_schema>\w+)\.(?P<foreign_table>\w+)\((?P<foreign_column>[^)]+)\)",
    re.MULTILINE,
)
_COLUMN_LINE = re.compile(
    r"^\s*(?P<name>\w+)\s+(?P<type>[\w\s\(\),]+?)(?:\s+(?P<trailer>.+))?,?\s*$"
)


def profile_schema_from_dump(
    dump_path: Path,
    *,
    database: str,
    source_id: str = "magerya_api",
) -> dict[str, Any]:
    sql_text = _extract_schema_sql(dump_path)
    relations: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []
    primary_keys: list[dict[str, Any]] = []
    foreign_keys: list[dict[str, Any]] = []

    for match in _CREATE_TABLE.finditer(sql_text):
        schema = match.group("schema")
        relation = match.group("relation")
        body = match.group("body")
        relations.append({"schema": schema, "name": relation, "kind": "table"})
        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.upper().startswith("CONSTRAINT "):
                continue
            if line.upper().startswith("PRIMARY KEY"):
                pk_cols = _parse_column_list(line)
                for col in pk_cols:
                    primary_keys.append(
                        {
                            "schema": schema,
                            "relation": relation,
                            "column_name": col,
                        }
                    )
                continue
            if " FOREIGN KEY " in line.upper():
                fk = _parse_inline_fk(schema, relation, line)
                if fk:
                    foreign_keys.append(fk)
                continue
            col_match = _COLUMN_LINE.match(line)
            if not col_match:
                continue
            name = col_match.group("name")
            data_type = col_match.group("type").strip()
            trailer = (col_match.group("trailer") or "").upper()
            columns.append(
                {
                    "schema": schema,
                    "relation": relation,
                    "name": name,
                    "data_type": data_type,
                    "nullable": "NOT NULL" not in trailer,
                }
            )

    for match in _ALTER_FK.finditer(sql_text):
        foreign_keys.append(
            {
                "schema_name": match.group("schema"),
                "relation_name": match.group("relation"),
                "column_name": match.group("column").strip(),
                "foreign_schema": match.group("foreign_schema"),
                "foreign_table": match.group("foreign_table"),
                "foreign_column": match.group("foreign_column").strip(),
            }
        )

    return {
        "profiled_at": datetime.now(UTC).isoformat(),
        "source_id": source_id,
        "database": database,
        "redacted_url": f"dump://{dump_path.name}",
        "readonly_validation": {
            "safe": True,
            "reason": "schema extracted offline from dump; no database connection",
            "transaction_read_only": True,
        },
        "database_metadata": {
            "database_name": database,
            "extraction_method": "pg_restore_schema_only",
            "dump_path": str(dump_path.name),
        },
        "relation_count": len(relations),
        "relations": relations,
        "column_count": len(columns),
        "columns": columns,
        "primary_keys": primary_keys,
        "foreign_keys": foreign_keys,
        "indexes": [],
        "row_estimates": [],
        "sensitive_columns": [],
        "aggregates": [],
    }


def _extract_schema_sql(dump_path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        proc = subprocess.run(
            [
                "pg_restore",
                "--schema-only",
                "--no-owner",
                "--no-privileges",
                "-f",
                str(temp_path),
                str(dump_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "pg_restore --schema-only failed")
        return temp_path.read_text(encoding="utf-8", errors="replace")
    finally:
        temp_path.unlink(missing_ok=True)


def _parse_column_list(line: str) -> list[str]:
    start = line.find("(")
    end = line.rfind(")")
    if start == -1 or end == -1:
        return []
    return [part.strip().strip('"') for part in line[start + 1 : end].split(",") if part.strip()]


def _parse_inline_fk(schema: str, relation: str, line: str) -> dict[str, Any] | None:
    match = re.search(
        r"FOREIGN KEY \((?P<column>[^)]+)\)\s+REFERENCES (?P<foreign_schema>\w+)\.(?P<foreign_table>\w+)\((?P<foreign_column>[^)]+)\)",
        line,
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "schema_name": schema,
        "relation_name": relation,
        "column_name": match.group("column").strip(),
        "foreign_schema": match.group("foreign_schema"),
        "foreign_table": match.group("foreign_table"),
        "foreign_column": match.group("foreign_column").strip(),
    }
