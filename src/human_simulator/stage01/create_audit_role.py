"""Create read-only mg_audit_ro role for Source A profiling."""

from __future__ import annotations

import secrets
import subprocess
from pathlib import Path
from typing import Any

from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from human_simulator.stage01.settings import MG_AUDIT_USER, MgAuditSettings


def _ensure_audit_password(settings: MgAuditSettings) -> str:
    password = settings.audit_password.get_secret_value()
    if password:
        return password
    generated = secrets.token_urlsafe(24)
    env_path = settings.repo_root / "db-audit.env"
    line = f"MG_AUDIT_PASSWORD={generated}\n"
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        if "MG_AUDIT_PASSWORD=" not in content:
            with env_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    else:
        example = settings.repo_root / "db-audit.env.example"
        if example.exists():
            env_path.write_text(example.read_text(encoding="utf-8") + line, encoding="utf-8")
        else:
            env_path.write_text(f"MG_AUDIT_USER={MG_AUDIT_USER}\n{line}", encoding="utf-8")
    return generated


def _docker_psql(settings: MgAuditSettings, sql_command: str) -> None:
    compose = settings.repo_root / "docker-compose.yml"
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose),
            "exec",
            "-T",
            "mg-db",
            "psql",
            "-U",
            settings.pg_user,
            "-d",
            settings.pg_database,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql_command,
        ],
        cwd=settings.repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"docker psql failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )


def _create_role_via_docker(settings: MgAuditSettings, audit_user: str, password: str) -> list[str]:
    exists_proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(settings.repo_root / "docker-compose.yml"),
            "exec",
            "-T",
            "mg-db",
            "psql",
            "-U",
            settings.pg_user,
            "-d",
            settings.pg_database,
            "-tAc",
            f"SELECT 1 FROM pg_roles WHERE rolname='{audit_user}'",
        ],
        cwd=settings.repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    exists = exists_proc.stdout.strip() == "1"
    escaped_password = password.replace("'", "''")
    if not exists:
        _docker_psql(settings, f"CREATE ROLE {audit_user} LOGIN PASSWORD '{escaped_password}'")
    else:
        _docker_psql(settings, f"ALTER ROLE {audit_user} LOGIN PASSWORD '{escaped_password}'")

    _docker_psql(
        settings,
        f'GRANT CONNECT ON DATABASE "{settings.pg_database}" TO "{audit_user}"',
    )
    schemas_proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(settings.repo_root / "docker-compose.yml"),
            "exec",
            "-T",
            "mg-db",
            "psql",
            "-U",
            settings.pg_user,
            "-d",
            settings.pg_database,
            "-tA",
            "-F",
            "\t",
            "-c",
            """
            SELECT nspname
            FROM pg_namespace
            WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY nspname
            """,
        ],
        cwd=settings.repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if schemas_proc.returncode != 0:
        raise RuntimeError(f"failed to list schemas: {schemas_proc.stderr.strip()}")
    schema_names = [line.strip() for line in schemas_proc.stdout.splitlines() if line.strip()]
    for schema in schema_names:
        _docker_psql(settings, f'REVOKE ALL ON SCHEMA "{schema}" FROM "{audit_user}"')
        _docker_psql(settings, f'GRANT USAGE ON SCHEMA "{schema}" TO "{audit_user}"')
        _docker_psql(settings, f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{audit_user}"')
        _docker_psql(settings, f'GRANT SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{audit_user}"')
        _docker_psql(settings, f'REVOKE CREATE ON SCHEMA "{schema}" FROM "{audit_user}"')
    _docker_psql(settings, f'ALTER ROLE "{audit_user}" SET default_transaction_read_only = on')
    return schema_names


def _create_role_via_sqlalchemy(settings: MgAuditSettings, audit_user: str, password: str) -> list[str]:
    admin_engine = create_engine(
        settings.admin_sqlalchemy_url,
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )
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
            conn.execute(text(f'GRANT CONNECT ON DATABASE "{settings.pg_database}" TO "{audit_user}"'))
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
            schema_names = [str(row[0]) for row in schemas]
            for schema in schema_names:
                conn.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{audit_user}"'))
                conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{audit_user}"'))
                conn.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{audit_user}"'))
                conn.execute(text(f'GRANT SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{audit_user}"'))
                conn.execute(text(f'REVOKE CREATE ON SCHEMA "{schema}" FROM "{audit_user}"'))
            conn.execute(text(f'ALTER ROLE "{audit_user}" SET default_transaction_read_only = on'))
    finally:
        admin_engine.dispose()
    return schema_names


def create_mg_audit_role(settings: MgAuditSettings) -> dict[str, Any]:
    audit_user = settings.audit_user
    if audit_user != MG_AUDIT_USER:
        raise RuntimeError(f"expected audit user {MG_AUDIT_USER!r}, got {audit_user!r}")

    password = _ensure_audit_password(settings)
    provision_method = "sqlalchemy_admin"
    try:
        schema_names = _create_role_via_sqlalchemy(settings, audit_user, password)
    except OperationalError:
        schema_names = _create_role_via_docker(settings, audit_user, password)
        provision_method = "docker_exec_admin"

    return {
        "username": audit_user,
        "redacted_connection": settings.audit_redacted_url,
        "default_transaction_read_only": True,
        "schemas_granted": schema_names,
        "provision_method": provision_method,
    }
