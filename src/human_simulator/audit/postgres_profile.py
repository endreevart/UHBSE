"""PostgreSQL source profiling for Stage 01."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from human_simulator.config.policy import ProfilingPolicy
from human_simulator.config.settings import AuditSettings
from human_simulator.db.readonly import assert_readonly


class UnsafeConfigurationError(RuntimeError):
    """Raised when PostgreSQL connection is not safe for read-only profiling."""


class ProfilePostgresError(RuntimeError):
    """Raised when profiling cannot continue safely."""


_SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema"})


def profile_postgres_source(
    settings: AuditSettings,
    engine: Engine,
    policy: ProfilingPolicy,
) -> dict[str, Any]:
    if engine.dialect.name != "postgresql":
        raise ProfilePostgresError("profile-postgres-source requires a PostgreSQL connection")

    evidence_dir = settings.repo_root / policy.evidence_dir
    query_log: list[dict[str, Any]] = []

    readonly = _validate_readonly(engine, query_log)
    if not readonly["safe"]:
        raise UnsafeConfigurationError(readonly["reason"])

    metadata = _fetch_database_metadata(engine, query_log)
    relations = _discover_relations(engine, policy, query_log)
    columns = _discover_columns(engine, policy, query_log, relations)
    constraints = _discover_constraints(engine, policy, query_log)
    indexes = _discover_indexes(engine, policy, query_log)
    row_estimates = _fetch_row_estimates(engine, policy, query_log)
    sensitive_columns = _classify_sensitive_columns(columns, policy)
    aggregates = _run_approved_aggregates(engine, relations, row_estimates, columns, policy, query_log)

    profile = _assemble_profile(
        settings=settings,
        metadata=metadata,
        readonly=readonly,
        relations=relations,
        columns=columns,
        constraints=constraints,
        indexes=indexes,
        row_estimates=row_estimates,
        sensitive_columns=sensitive_columns,
        aggregates=aggregates,
        query_log=query_log,
    )

    artifacts_dir = settings.repo_root / policy.artifacts_dir
    _write_artifacts(artifacts_dir, evidence_dir, profile, query_log)
    return profile


def _run_query(
    engine: Engine,
    query_log: list[dict[str, Any]],
    name: str,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    assert_readonly(sql)
    started = time.perf_counter()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        rows = [dict(row._mapping) for row in result.mappings()]
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    query_log.append(
        {
            "name": name,
            "query_id": _query_id(name, sql),
            "duration_ms": duration_ms,
            "row_count_returned": len(rows),
        }
    )
    return rows


def _query_id(name: str, sql: str) -> str:
    digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:12]
    slug = name.replace(" ", "-").lower()
    return f"{slug}-{digest}"


def _validate_readonly(engine: Engine, query_log: list[dict[str, Any]]) -> dict[str, Any]:
    tx_rows = _run_query(
        engine,
        query_log,
        "readonly_transaction_setting",
        "SELECT current_setting('transaction_read_only') AS transaction_read_only",
    )
    tx_read_only = tx_rows[0]["transaction_read_only"] == "on"

    role_rows = _run_query(
        engine,
        query_log,
        "current_role_privileges",
        """
        SELECT rolname, rolsuper, rolcreatedb, rolcreaterole
        FROM pg_roles
        WHERE rolname = current_user
        """,
    )
    role = role_rows[0]
    grant_rows = _run_query(
        engine,
        query_log,
        "write_privilege_grants",
        """
        SELECT privilege_type
        FROM information_schema.role_table_grants
        WHERE grantee = current_user
          AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'TRIGGER')
        LIMIT 1
        """,
    )
    has_write_grants = bool(grant_rows)
    safe = tx_read_only and not role["rolsuper"] and not has_write_grants
    reason = "ok"
    if not tx_read_only:
        reason = "transaction is not read-only"
    elif role["rolsuper"]:
        reason = "connected role is superuser"
    elif has_write_grants:
        reason = "connected role has write privileges"

    return {
        "safe": safe,
        "reason": reason,
        "transaction_read_only": tx_read_only,
        "role": {
            "name": role["rolname"],
            "superuser": bool(role["rolsuper"]),
            "create_db": bool(role["rolcreatedb"]),
            "create_role": bool(role["rolcreaterole"]),
        },
    }


def _fetch_database_metadata(engine: Engine, query_log: list[dict[str, Any]]) -> dict[str, Any]:
    version_rows = _run_query(engine, query_log, "postgres_version", "SELECT version() AS version")
    db_rows = _run_query(
        engine,
        query_log,
        "database_metadata",
        """
        SELECT
            current_database() AS database_name,
            current_user AS connected_role,
            pg_database_size(current_database()) AS database_size_bytes
        """,
    )
    return {
        "postgres_version": version_rows[0]["version"],
        **db_rows[0],
    }


def _discover_relations(
    engine: Engine,
    policy: ProfilingPolicy,
    query_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sql = """
    SELECT n.nspname AS schema_name, c.relname AS relation_name, c.relkind AS relation_kind
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND c.relkind IN ('r', 'v', 'm')
    ORDER BY 1, 2
    """
    rows = _run_query(engine, query_log, "discover_relations", sql)
    if policy.max_tables is not None:
        rows = rows[: policy.max_tables]
    kind_map = {"r": "table", "v": "view", "m": "materialized_view"}
    return [
        {
            "schema": row["schema_name"],
            "name": row["relation_name"],
            "kind": kind_map.get(row["relation_kind"], row["relation_kind"]),
        }
        for row in rows
    ]


def _discover_columns(
    engine: Engine,
    policy: ProfilingPolicy,
    query_log: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        c.table_schema AS schema_name,
        c.table_name AS relation_name,
        c.column_name,
        c.data_type,
        c.is_nullable,
        c.ordinal_position
    FROM information_schema.columns c
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY c.table_schema, c.table_name, c.ordinal_position
    """
    rows = _run_query(engine, query_log, "discover_columns", sql)
    if policy.max_tables is not None:
        allowed = {(rel["schema"], rel["name"]) for rel in relations}
        rows = [row for row in rows if (row["schema_name"], row["relation_name"]) in allowed]
    return [
        {
            "schema": row["schema_name"],
            "relation": row["relation_name"],
            "name": row["column_name"],
            "data_type": row["data_type"],
            "nullable": row["is_nullable"] == "YES",
            "ordinal_position": row["ordinal_position"],
        }
        for row in rows
    ]


def _discover_constraints(
    engine: Engine,
    policy: ProfilingPolicy,
    query_log: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    pk_sql = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS relation_name,
        a.attname AS column_name
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
    WHERE i.indisprimary
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY 1, 2, 3
    """
    fk_sql = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS relation_name,
        a.attname AS column_name,
        fn.nspname AS foreign_schema,
        fc.relname AS foreign_table,
        fa.attname AS foreign_column
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = con.conkey[1]
    JOIN pg_class fc ON fc.oid = con.confrelid
    JOIN pg_namespace fn ON fn.oid = fc.relnamespace
    JOIN pg_attribute fa ON fa.attrelid = fc.oid AND fa.attnum = con.confkey[1]
    WHERE con.contype = 'f'
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY 1, 2, 3
    """
    primary_keys = _run_query(engine, query_log, "discover_primary_keys", pk_sql)
    foreign_keys = _run_query(engine, query_log, "discover_foreign_keys", fk_sql)
    return {"primary_keys": primary_keys, "foreign_keys": foreign_keys}


def _discover_indexes(
    engine: Engine,
    policy: ProfilingPolicy,
    query_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sql = """
    SELECT schemaname AS schema_name, tablename AS relation_name, indexname, indexdef
    FROM pg_indexes
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
    ORDER BY 1, 2, 3
    """
    return _run_query(engine, query_log, "discover_indexes", sql)


def _fetch_row_estimates(
    engine: Engine,
    policy: ProfilingPolicy,
    query_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sql = """
    SELECT
        n.nspname AS schema_name,
        c.relname AS relation_name,
        c.relkind AS relation_kind,
        COALESCE(c.reltuples, 0)::bigint AS estimated_rows
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND c.relkind IN ('r', 'm')
    ORDER BY 1, 2
    """
    rows = _run_query(engine, query_log, "estimated_row_counts", sql)
    if policy.max_tables is not None:
        rows = rows[: policy.max_tables]
    return rows


def _classify_sensitive_columns(
    columns: list[dict[str, Any]],
    policy: ProfilingPolicy,
) -> list[dict[str, Any]]:
    text_types = {"text", "character varying", "character", "json", "jsonb", "bytea"}
    classified: list[dict[str, Any]] = []
    for column in columns:
        reasons: list[str] = []
        if policy.is_sensitive_column(column["name"]):
            reasons.append("name_pattern")
        if column["data_type"] in text_types:
            reasons.append("text_like_type")
        if reasons:
            classified.append(
                {
                    "schema": column["schema"],
                    "relation": column["relation"],
                    "column": column["name"],
                    "data_type": column["data_type"],
                    "reasons": reasons,
                }
            )
    return classified


def _run_approved_aggregates(
    engine: Engine,
    relations: list[dict[str, Any]],
    row_estimates: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    policy: ProfilingPolicy,
    query_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    estimate_map = {
        (row["schema_name"], row["relation_name"]): int(row["estimated_rows"])
        for row in row_estimates
    }
    table_relations = [rel for rel in relations if rel["kind"] in {"table", "materialized_view"}]
    aggregates: list[dict[str, Any]] = []

    for relation in table_relations:
        key = (relation["schema"], relation["name"])
        estimated_rows = estimate_map.get(key, 0)
        if estimated_rows > policy.max_rows_sample:
            aggregates.append(
                {
                    "schema": relation["schema"],
                    "relation": relation["name"],
                    "estimated_rows": estimated_rows,
                    "aggregate_status": "skipped_large_table",
                }
            )
            continue

        relation_columns = [
            col
            for col in columns
            if col["schema"] == relation["schema"]
            and col["relation"] == relation["name"]
            and not policy.is_sensitive_column(col["name"])
        ]
        if estimated_rows == 0 or not relation_columns:
            aggregates.append(
                {
                    "schema": relation["schema"],
                    "relation": relation["name"],
                    "estimated_rows": estimated_rows,
                    "aggregate_status": "skipped_empty_or_no_safe_columns",
                }
            )
            continue

        quoted = f'"{relation["schema"]}"."{relation["name"]}"'
        null_parts = [
            f'SUM(CASE WHEN "{col["name"]}" IS NULL THEN 1 ELSE 0 END) AS "{col["name"]}_nulls"'
            for col in relation_columns
        ]
        sql = f"SELECT COUNT(*) AS row_count, {', '.join(null_parts)} FROM {quoted}"
        rows = _run_query(
            engine,
            query_log,
            f"aggregate_nulls_{relation['schema']}_{relation['name']}",
            sql,
        )
        row = rows[0]
        null_rates = {
            col["name"]: round(100.0 * row[f"{col['name']}_nulls"] / row["row_count"], 4)
            for col in relation_columns
            if row["row_count"]
        }
        aggregates.append(
            {
                "schema": relation["schema"],
                "relation": relation["name"],
                "estimated_rows": estimated_rows,
                "exact_rows": int(row["row_count"]),
                "aggregate_status": "completed",
                "null_pct_by_column": null_rates,
            }
        )
    return aggregates


def _assemble_profile(
    *,
    settings: AuditSettings,
    metadata: dict[str, Any],
    readonly: dict[str, Any],
    relations: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    constraints: dict[str, list[dict[str, Any]]],
    indexes: list[dict[str, Any]],
    row_estimates: list[dict[str, Any]],
    sensitive_columns: list[dict[str, Any]],
    aggregates: list[dict[str, Any]],
    query_log: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "profiled_at": datetime.now(UTC).isoformat(),
        "source_id": "local_stage",
        "database": settings.pg_database,
        "redacted_url": settings.redacted_url,
        "readonly_validation": readonly,
        "database_metadata": metadata,
        "relation_count": len(relations),
        "relations": relations,
        "column_count": len(columns),
        "columns": columns,
        "primary_keys": constraints["primary_keys"],
        "foreign_keys": constraints["foreign_keys"],
        "indexes": [
            {
                "schema": row["schema_name"],
                "relation": row["relation_name"],
                "index_name": row["indexname"],
            }
            for row in indexes
        ],
        "row_estimates": [
            {
                "schema": row["schema_name"],
                "relation": row["relation_name"],
                "kind": row["relation_kind"],
                "estimated_rows": int(row["estimated_rows"]),
            }
            for row in row_estimates
        ],
        "sensitive_columns": sensitive_columns,
        "aggregates": aggregates,
        "query_log": query_log,
    }


def _write_artifacts(
    artifacts_dir: Path,
    evidence_dir: Path,
    profile: dict[str, Any],
    query_log: list[dict[str, Any]],
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    schema_profile = {
        key: profile[key]
        for key in (
            "profiled_at",
            "source_id",
            "database",
            "redacted_url",
            "readonly_validation",
            "database_metadata",
            "relation_count",
            "relations",
            "column_count",
            "columns",
            "primary_keys",
            "foreign_keys",
            "indexes",
            "row_estimates",
            "sensitive_columns",
            "aggregates",
        )
    }
    (artifacts_dir / "schema-profile.json").write_text(
        json.dumps(schema_profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (artifacts_dir / "profiling-query-log.json").write_text(
        json.dumps(query_log, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    evidence_index = artifacts_dir / "evidence" / "query-index.json"
    evidence_index.parent.mkdir(parents=True, exist_ok=True)
    evidence_index.write_text(
        json.dumps(query_log, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
