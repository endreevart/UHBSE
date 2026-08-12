"""Connection helpers for the isolated canonical database.

DDL and catalog access only. Nothing here reads clinical rows, and the isolation guard
refuses any target that is a raw source database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from human_simulator.canonical.settings import (
    CanonicalConnectionSettings,
    assert_canonical_target_allowed,
    load_canonical_settings,
)

CONNECT_TIMEOUT_SECONDS = 10
STATEMENT_TIMEOUT_MS = 60_000
LOCK_TIMEOUT_MS = 10_000


@contextmanager
def canonical_connection(
    settings: CanonicalConnectionSettings | None = None,
    *,
    database_override: str | None = None,
) -> Iterator[Any]:
    """Open an autocommit connection to the canonical database."""
    import psycopg

    resolved = settings or load_canonical_settings(database_override=database_override)
    assert_canonical_target_allowed(resolved.database, resolved.port)

    conn = psycopg.connect(resolved.dsn(), connect_timeout=CONNECT_TIMEOUT_SECONDS, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            cur.execute(f"SET lock_timeout = {LOCK_TIMEOUT_MS}")
        yield conn
    finally:
        conn.close()


def canonical_endpoint_reachable(settings: CanonicalConnectionSettings | None = None) -> bool:
    try:
        with canonical_connection(settings) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception:  # noqa: BLE001 - reachability probe only
        return False
    return True


def postgres_major_version(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute("SHOW server_version_num")
        return int(cur.fetchone()[0]) // 10_000
