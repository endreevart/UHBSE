"""Read-only query log. Parameters are never stored."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.policy import LOCK_TIMEOUT_MS, STATEMENT_TIMEOUT_MS


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class QueryError(RuntimeError):
    def __init__(self, error_class: str) -> None:
        super().__init__(error_class)
        self.error_class = error_class


class QueryLog:
    def __init__(self, schema_fingerprint: str) -> None:
        self.schema_fingerprint = schema_fingerprint
        self.entries: list[dict[str, Any]] = []

    def run(self, conn: Any, name: str, source: str, sql: str, params: tuple = ()) -> list[tuple]:
        started = _now()
        clock = time.monotonic()
        contract = json.dumps({"count": len(params), "types": [type(item).__name__ for item in params]}, sort_keys=True)
        entry: dict[str, Any] = {
            "query": name,
            "source_system": source,
            "sql_sha256": _sha(sql),
            "parameter_contract_sha256": _sha(contract),
            "schema_fingerprint": self.schema_fingerprint,
            "started_at": started,
            "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
            "lock_timeout_ms": LOCK_TIMEOUT_MS,
        }
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW default_transaction_read_only")
                readonly = cur.fetchone()[0] == "on"
                cur.execute(sql, params)
                rows = cur.fetchall()
            conn.commit()
            entry.update({
                "finished_at": _now(),
                "duration_seconds": round(time.monotonic() - clock, 3),
                "output_aggregate_row_count": len(rows),
                "read_only_verified": readonly,
                "success": True,
                "error_class": None,
            })
            if not readonly:
                entry["success"] = False
                entry["error_class"] = "ReadOnlyNotVerified"
                self.entries.append(entry)
                raise QueryError("ReadOnlyNotVerified")
            self.entries.append(entry)
            return rows
        except QueryError:
            raise
        except Exception as exc:
            conn.rollback()
            entry.update({
                "finished_at": _now(),
                "duration_seconds": round(time.monotonic() - clock, 3),
                "output_aggregate_row_count": 0,
                "read_only_verified": False,
                "success": False,
                "error_class": type(exc).__name__,
            })
            self.entries.append(entry)
            raise QueryError(type(exc).__name__) from None

    def note_stream(self, name: str, source: str, sql: str, rows: int, started: str, clock: float) -> None:
        contract = json.dumps({"count": 0, "types": []}, sort_keys=True)
        self.entries.append({
            "query": name,
            "source_system": source,
            "sql_sha256": _sha(sql),
            "parameter_contract_sha256": _sha(contract),
            "schema_fingerprint": self.schema_fingerprint,
            "started_at": started,
            "finished_at": _now(),
            "duration_seconds": round(time.monotonic() - clock, 3),
            "output_aggregate_row_count": rows,
            "read_only_verified": True,
            "success": True,
            "error_class": None,
            "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
            "lock_timeout_ms": LOCK_TIMEOUT_MS,
        })


def connect_a(root: Path) -> Any:
    import psycopg
    from dotenv import dotenv_values

    audit = dotenv_values(Path(root) / "db-audit.env")
    user = audit.get("MG_AUDIT_USER") or "mg_audit_ro"
    password = audit.get("MG_AUDIT_PASSWORD")
    host = audit.get("MG_HOST") or "localhost"
    port = int(audit.get("MG_PORT") or 5434)
    database = audit.get("MG_DATABASE") or "magerya_api"
    if not password:
        from human_simulator.stage01.settings import MgAuditSettings

        mg = MgAuditSettings.from_repo(Path(root))
        user, password = mg.audit_user, mg.audit_password.get_secret_value()
        host, port, database = mg.pg_host, mg.pg_port, mg.pg_database
    conn = psycopg.connect(host=host, port=port, dbname=database, user=user, password=password, connect_timeout=10)
    _prepare(conn)
    return conn


def connect_b(root: Path) -> Any:
    import psycopg

    from human_simulator.stage02.settings import KgzRestoreSettings

    kgz = KgzRestoreSettings.from_repo(Path(root))
    conn = psycopg.connect(
        host=kgz.pg_host,
        port=kgz.pg_port,
        dbname=kgz.pg_database,
        user=kgz.audit_user,
        password=kgz.audit_password.get_secret_value(),
        connect_timeout=10,
    )
    _prepare(conn)
    return conn


def _prepare(conn: Any) -> None:
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
        cur.execute(f"SET lock_timeout = {int(LOCK_TIMEOUT_MS)}")
        cur.execute("SET default_transaction_read_only = on")
        cur.execute("SHOW default_transaction_read_only")
        if cur.fetchone()[0] != "on":
            raise QueryError("ReadOnlyNotVerified")
    conn.commit()
    conn.read_only = True


def schema_fingerprint(conn: Any, tables: list[tuple[str, str]]) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name, column_name, data_type, udt_name, is_nullable
            FROM information_schema.columns
            WHERE (table_schema, table_name) IN (SELECT * FROM unnest(%s::text[], %s::text[]))
            ORDER BY 1, 2, column_name
            """,
            ([item[0] for item in tables], [item[1] for item in tables]),
        )
        rows = cur.fetchall()
    conn.commit()
    payload = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
