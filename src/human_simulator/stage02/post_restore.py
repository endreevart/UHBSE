"""Post-restore verification and read-only audit user for source B."""

from __future__ import annotations

import re
import secrets
import subprocess
from pathlib import Path
from typing import Any

from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from human_simulator.stage02.schema_fingerprint import compare_source_a_fingerprint
from human_simulator.stage02.settings import KgzRestoreSettings, SourceABaseline

_APPLICATION_SCHEMAS = ("public", "quest_digital")
_POSTGIS_SCHEMAS = frozenset({"tiger", "tiger_data", "topology"})

_SENSITIVE = re.compile(
    r"(password\s*=\s*\S+|postgresql://[^\s]+|POSTGRES_PASSWORD=\S+)",
    re.IGNORECASE,
)


def sanitize_log(text: str, max_lines: int = 200) -> str:
    lines = text.splitlines()
    redacted = [_SENSITIVE.sub("[REDACTED]", line) for line in lines[:max_lines]]
    if len(lines) > max_lines:
        redacted.append(f"... truncated {len(lines) - max_lines} additional lines")
    return "\n".join(redacted)


def count_restore_messages(stderr: str, stdout: str) -> dict[str, int]:
    combined = f"{stderr}\n{stdout}".lower()
    return {
        "error_lines": sum(1 for line in combined.splitlines() if "error" in line),
        "warning_lines": sum(1 for line in combined.splitlines() if "warning" in line),
        "stderr_line_count": len(stderr.splitlines()),
        "stdout_line_count": len(stdout.splitlines()),
    }


def pg_restore_version_in_container(repo_root: Path) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "kgz-db", "pg_restore", "--version"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return "unknown"
    return proc.stdout.strip()


def collect_database_inventory(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        schemas = int(
            conn.execute(
                text(
                    """
                    SELECT count(DISTINCT nspname)
                    FROM pg_namespace
                    WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                    """
                )
            ).scalar_one()
        )
        tables = int(
            conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM information_schema.tables
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                      AND table_type = 'BASE TABLE'
                    """
                )
            ).scalar_one()
        )
        views = int(
            conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM information_schema.views
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                    """
                )
            ).scalar_one()
        )
        sequences = int(
            conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM information_schema.sequences
                    WHERE sequence_schema NOT IN ('pg_catalog', 'information_schema')
                    """
                )
            ).scalar_one()
        )
        functions = int(
            conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                    """
                )
            ).scalar_one()
        )
        extensions_rows = conn.execute(
            text("SELECT extname, extversion FROM pg_extension ORDER BY extname")
        ).fetchall()
        db_size_bytes = int(
            conn.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar_one()
        )
        server_version = str(conn.execute(text("SHOW server_version")).scalar_one())

    return {
        "schema_count": schemas,
        "table_count": tables,
        "view_count": views,
        "sequence_count": sequences,
        "function_count": functions,
        "extensions": [{"name": str(r[0]), "version": str(r[1])} for r in extensions_rows],
        "database_size_bytes": db_size_bytes,
        "server_version": server_version,
    }


def verify_source_a_unchanged(repo_root: Path) -> dict[str, Any]:
    baseline = SourceABaseline.from_repo(repo_root)
    fp_result = compare_source_a_fingerprint(repo_root)
    return {
        "expected_database": baseline.pg_database,
        "expected_port": baseline.pg_port,
        **fp_result,
    }


def _audit_password(settings: KgzRestoreSettings) -> str:
    existing = settings.audit_password.get_secret_value()
    if existing:
        return existing
    generated = secrets.token_urlsafe(24)
    env_path = settings.repo_root / "db-kgz.env"
    line = f"KGZ_AUDIT_PASSWORD={generated}\n"
    with env_path.open("a", encoding="utf-8") as f:
        f.write(line)
    return generated


def create_readonly_audit_user(settings: KgzRestoreSettings) -> dict[str, Any]:
    audit_user = settings.audit_user
    password = _audit_password(settings)
    admin_engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True, isolation_level="AUTOCOMMIT")
    schema_names: list[str] = []
    try:
        with admin_engine.connect() as conn:
            raw = conn.connection.driver_connection
            exists = conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :name"),
                {"name": audit_user},
            ).scalar_one_or_none()
            with raw.cursor() as cur:
                if not exists:
                    cur.execute(
                        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                            sql.Identifier(audit_user),
                            sql.Literal(password),
                        )
                    )
                else:
                    cur.execute(
                        sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                            sql.Identifier(audit_user),
                            sql.Literal(password),
                        )
                    )
            conn.execute(
                text(f'GRANT CONNECT ON DATABASE "{settings.pg_database}" TO "{audit_user}"')
            )
            schemas = conn.execute(
                text(
                    """
                    SELECT nspname
                    FROM pg_namespace
                    WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                    ORDER BY nspname
                    """
                )
            ).fetchall()
            schema_names = [str(s[0]) for s in schemas]
            for schema in schema_names:
                conn.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{audit_user}"'))
                conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{audit_user}"'))
                conn.execute(
                    text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{audit_user}"')
                )
                conn.execute(
                    text(f'GRANT SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{audit_user}"')
                )
                conn.execute(text(f'REVOKE CREATE ON SCHEMA "{schema}" FROM "{audit_user}"'))
            conn.execute(
                text(f'ALTER ROLE "{audit_user}" SET default_transaction_read_only = on')
            )
            conn.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
            conn.execute(text(f'REVOKE CREATE ON SCHEMA public FROM "{audit_user}"'))
    finally:
        admin_engine.dispose()

    return {
        "username": audit_user,
        "redacted_connection": (
            f"postgresql://{audit_user}:***@{settings.pg_host}:{settings.pg_port}/{settings.pg_database}"
        ),
        "default_transaction_read_only": True,
        "schemas_granted": schema_names,
    }


def verify_readonly_audit_user(settings: KgzRestoreSettings) -> dict[str, Any]:
    password = settings.audit_password.get_secret_value()
    if not password:
        password = _audit_password(settings)
    audit_url = (
        f"postgresql+psycopg://{settings.audit_user}:{password}"
        f"@{settings.pg_host}:{settings.pg_port}/{settings.pg_database}"
    )
    engine = create_engine(audit_url, pool_pre_ping=True)
    result: dict[str, Any] = {
        "username": settings.audit_user,
        "can_select": False,
        "insert_blocked": False,
        "update_blocked": False,
        "delete_blocked": False,
        "ddl_blocked": False,
        "role_flags": {},
    }
    try:
        with engine.connect() as conn:
            sample = conn.execute(
                text(
                    """
                    SELECT table_schema, table_name
                    FROM information_schema.tables
                    WHERE table_schema = ANY(:schemas)
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_schema, table_name
                    LIMIT 1
                    """
                ),
                {"schemas": list(_APPLICATION_SCHEMAS)},
            ).first()
            if sample is None:
                sample = conn.execute(
                    text(
                        """
                        SELECT table_schema, table_name
                        FROM information_schema.tables
                        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                          AND table_schema NOT LIKE 'pg\\_%' ESCAPE '\\'
                          AND table_schema <> ALL(:postgis)
                          AND table_type = 'BASE TABLE'
                        ORDER BY table_schema, table_name
                        LIMIT 1
                        """
                    ),
                    {"postgis": list(_POSTGIS_SCHEMAS)},
                ).first()
            if sample:
                schema, table = str(sample[0]), str(sample[1])
                qualified = f"{schema}.{table}"
                conn.execute(text(f'SELECT 1 FROM "{schema}"."{table}" LIMIT 1'))
                result["can_select"] = True
                result["sample_table"] = qualified
                result["sample_table_class"] = "application" if schema in _APPLICATION_SCHEMAS else "non_postgis"
                privs = conn.execute(
                    text(
                        """
                        SELECT
                          has_table_privilege(current_user, :tbl, 'SELECT') AS sel,
                          has_table_privilege(current_user, :tbl, 'INSERT') AS ins,
                          has_table_privilege(current_user, :tbl, 'UPDATE') AS upd,
                          has_table_privilege(current_user, :tbl, 'DELETE') AS del
                        """
                    ),
                    {"tbl": qualified},
                ).one()
                result["insert_blocked"] = not bool(privs[1])
                result["update_blocked"] = not bool(privs[2])
                result["delete_blocked"] = not bool(privs[3])
            flags = conn.execute(
                text(
                    """
                    SELECT rolcreatedb, rolcreaterole, rolsuper, rolcanlogin
                    FROM pg_roles WHERE rolname = :name
                    """
                ),
                {"name": settings.audit_user},
            ).one()
            result["role_flags"] = {
                "rolcreatedb": bool(flags[0]),
                "rolcreaterole": bool(flags[1]),
                "rolsuper": bool(flags[2]),
                "rolcanlogin": bool(flags[3]),
            }
            role_config = conn.execute(
                text("SELECT rolconfig FROM pg_roles WHERE rolname = :name"),
                {"name": settings.audit_user},
            ).scalar_one()
            config_items = role_config or []
            result["default_transaction_read_only"] = any(
                str(item).startswith("default_transaction_read_only=on") for item in config_items
            )
            result["ddl_blocked"] = not bool(
                conn.execute(
                    text(
                        """
                        SELECT coalesce(bool_or(
                          has_schema_privilege(current_user, nspname, 'CREATE')
                        ), false)
                        FROM pg_namespace
                        WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                        """
                    )
                ).scalar_one()
            )
            result["read_only_ok"] = all(
                [
                    result.get("can_select"),
                    result.get("insert_blocked"),
                    result.get("update_blocked"),
                    result.get("delete_blocked"),
                    result.get("ddl_blocked"),
                    result.get("default_transaction_read_only"),
                    not result["role_flags"].get("rolsuper"),
                    not result["role_flags"].get("rolcreaterole"),
                    not result["role_flags"].get("rolcreatedb"),
                ]
            )
    finally:
        engine.dispose()
    return result
