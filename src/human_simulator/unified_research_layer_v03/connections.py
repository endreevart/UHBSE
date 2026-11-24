"""DB connection helpers — read-only only."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def connect_source_a(root: Path) -> Any | None:
    try:
        import psycopg
        from dotenv import dotenv_values

        audit = dotenv_values(Path(root) / "db-audit.env")
        user = audit.get("MG_AUDIT_USER") or "mg_audit_ro"
        pw = audit.get("MG_AUDIT_PASSWORD")
        if not pw:
            from human_simulator.stage01.settings import MgAuditSettings

            mg = MgAuditSettings.from_repo(Path(root))
            user, pw = mg.audit_user, mg.audit_password.get_secret_value()
            host, port, db = mg.pg_host, mg.pg_port, mg.pg_database
        else:
            host = audit.get("MG_HOST") or "localhost"
            port = int(audit.get("MG_PORT") or 5434)
            db = audit.get("MG_DATABASE") or "magerya_api"
        conn = psycopg.connect(
            f"postgresql://{user}:{pw}@{host}:{port}/{db}",
            connect_timeout=10,
            autocommit=True,
        )
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 180000")
            cur.execute("SET lock_timeout = 10000")
            cur.execute("SET default_transaction_read_only = on")
        return conn
    except Exception:
        return None


def connect_source_b(root: Path) -> Any | None:
    try:
        from sqlalchemy import create_engine
        from human_simulator.stage02.settings import KgzRestoreSettings

        kgz = KgzRestoreSettings.from_repo(Path(root))
        if not kgz.audit_password.get_secret_value():
            return None
        return create_engine(kgz.audit_sqlalchemy_url).raw_connection()
    except Exception:
        return None
