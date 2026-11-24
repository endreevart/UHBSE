"""Source B read-only adapter — aggregate profiling only (no PII)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from human_simulator.db.readonly import assert_readonly
from human_simulator.stage02.settings import KgzRestoreSettings
from human_simulator.unified.policy import SOURCE_B_SYSTEM_ID


@contextmanager
def source_b_connection(repo_root: Path) -> Iterator[Any]:
    import psycopg

    settings = KgzRestoreSettings.from_repo(Path(repo_root))
    if not settings.audit_password.get_secret_value():
        raise RuntimeError("KGZ_AUDIT_PASSWORD missing; cannot open Source B read-only connection")
    dsn = (
        f"postgresql://{settings.audit_user}:{settings.audit_password.get_secret_value()}"
        f"@{settings.pg_host}:{settings.pg_port}/{settings.pg_database}"
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


def access_probe(conn: Any) -> dict[str, Any]:
    one = _fetch_one(conn, "SELECT current_user, current_setting('transaction_read_only')")
    return {
        "readable": one is not None,
        "db_user": one[0] if one else None,
        "transaction_read_only": one[1] if one else None,
        "raw_writes_forbidden": True,
        "source_system": SOURCE_B_SYSTEM_ID,
    }


def _safe_count(conn: Any, schema: str, table: str) -> int | None:
    """Exact count for known small/medium tables; returns None if relation missing."""
    exists = _fetch_one(
        conn,
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    if not exists:
        return None
    # Estimated count first for large tables via pg_class
    est = _fetch_one(
        conn,
        """
        SELECT c.reltuples::bigint
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
        """,
        (schema, table),
    )
    est_n = int(est[0]) if est and est[0] is not None else 0
    if est_n > 500_000:
        return est_n  # estimated; avoid full scan
    row = _fetch_one(conn, f'SELECT COUNT(*)::bigint FROM "{schema}"."{table}"')  # noqa: S608
    return int(row[0]) if row else 0


def profile_aggregates(conn: Any) -> dict[str, Any]:
    """Aggregate-only Source B profile — no patient identifiers."""
    candidates = [
        ("public", "users"),
        ("public", "persons"),
        ("public", "consultations"),
        ("quest_digital", "analyses_catalog"),
        ("quest_digital", "analyses_constructor"),
        ("quest_digital", "analyses_results"),
        ("quest_digital", "analyses_results_items"),
    ]
    relation_counts: dict[str, Any] = {}
    for schema, table in candidates:
        n = _safe_count(conn, schema, table)
        if n is not None:
            relation_counts[f"{schema}.{table}"] = n

    schemas = [
        r[0]
        for r in _fetch_all(
            conn,
            """
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name
            """,
        )
    ]
    return {
        "source_system": SOURCE_B_SYSTEM_ID,
        "schemas": schemas,
        "relation_counts": relation_counts,
        "pii_values_returned": False,
        "notes": [
            "Counts are aggregate-only; estimated for relations with reltuples > 500000.",
            "No patient-level rows returned.",
        ],
    }


def readiness_report(repo_root: Path) -> dict[str, Any]:
    """Open Source B RO connection and return aggregate readiness evidence."""
    root = Path(repo_root)
    try:
        with source_b_connection(root) as conn:
            access = access_probe(conn)
            profile = profile_aggregates(conn)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "INSUFFICIENT_DATA",
            "readable": False,
            "error_type": type(exc).__name__,
            "detail": "Source B connection or profiling failed (credentials/environment).",
            "source_system": SOURCE_B_SYSTEM_ID,
        }
    status = "PASS" if access.get("readable") else "FAIL"
    return {
        "status": status,
        "access": access,
        "profile": profile,
        "stage_02_artifacts_expected": [
            "artifacts/stage-02/identity-linkage-assessment.json",
            "artifacts/stage-02/schema-profile-kgz.json",
            "artifacts/stage-03/source-b-mapping-draft.yaml",
        ],
    }
