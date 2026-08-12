"""Idempotent provisioning of PostgreSQL LOGIN principal canonical_loader_login."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import sql

from human_simulator.canonical.constants import ROLE_LOADER
from human_simulator.stage03_alignment.vault_provider import POSTGRES_LOGIN_PRINCIPAL

LOGIN_ROLE = POSTGRES_LOGIN_PRINCIPAL
GROUP_ROLE = ROLE_LOADER

EXPECTED_ATTRIBUTES: dict[str, Any] = {
    "rolcanlogin": True,
    "rolinherit": False,  # NOINHERIT
    "rolsuper": False,
    "rolcreatedb": False,
    "rolcreaterole": False,
    "rolreplication": False,
    "rolbypassrls": False,
}

CREATE_SQL = (
    "CREATE ROLE {role} WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
    "NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {password}"
)


class PrincipalProvisionError(RuntimeError):
    """Provisioning failure. Messages must never include passwords or DSNs."""


@dataclass(frozen=True)
class RoleSnapshot:
    exists: bool
    attributes: dict[str, Any] | None
    memberships: list[str]


def fetch_role_snapshot(conn: Any, role_name: str) -> RoleSnapshot:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = %s
            """,
            (role_name,),
        )
        row = cur.fetchone()
        if row is None:
            return RoleSnapshot(exists=False, attributes=None, memberships=[])
        attributes = {
            "rolcanlogin": bool(row[0]),
            "rolinherit": bool(row[1]),
            "rolsuper": bool(row[2]),
            "rolcreatedb": bool(row[3]),
            "rolcreaterole": bool(row[4]),
            "rolreplication": bool(row[5]),
            "rolbypassrls": bool(row[6]),
        }
        cur.execute(
            """
            SELECT r.rolname
            FROM pg_auth_members am
            JOIN pg_roles m ON m.oid = am.member
            JOIN pg_roles r ON r.oid = am.roleid
            WHERE m.rolname = %s
            ORDER BY r.rolname
            """,
            (role_name,),
        )
        memberships = [r[0] for r in cur.fetchall()]
    return RoleSnapshot(exists=True, attributes=attributes, memberships=memberships)


def attributes_match(snapshot: RoleSnapshot) -> bool:
    if not snapshot.exists or snapshot.attributes is None:
        return False
    return snapshot.attributes == EXPECTED_ATTRIBUTES


def membership_match(snapshot: RoleSnapshot) -> bool:
    return snapshot.memberships == [GROUP_ROLE]


def contract_match(snapshot: RoleSnapshot) -> bool:
    return attributes_match(snapshot) and membership_match(snapshot)


def _create_login_role(conn: Any, password: str) -> None:
    if not isinstance(password, str) or not password:
        raise PrincipalProvisionError("loader password unavailable in process memory")
    stmt = sql.SQL(CREATE_SQL).format(
        role=sql.Identifier(LOGIN_ROLE),
        password=sql.Literal(password),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(stmt)
    except Exception as exc:  # noqa: BLE001
        # Never surface query text or password material.
        raise PrincipalProvisionError(
            f"CREATE ROLE failed: {exc.__class__.__name__}"
        ) from None


def _grant_group(conn: Any) -> None:
    stmt = sql.SQL("GRANT {} TO {}").format(
        sql.Identifier(GROUP_ROLE),
        sql.Identifier(LOGIN_ROLE),
    )
    try:
        with conn.cursor() as cur:
            cur.execute(stmt)
    except Exception as exc:  # noqa: BLE001
        raise PrincipalProvisionError(
            f"GRANT {GROUP_ROLE} failed: {exc.__class__.__name__}"
        ) from None


def provision_canonical_loader_login(conn: Any, *, password: str) -> dict[str, Any]:
    """Create LOGIN role idempotently. Auto-repair of unexpected roles is forbidden."""
    before = fetch_role_snapshot(conn, LOGIN_ROLE)
    if before.exists:
        if contract_match(before):
            return {
                "action": "noop",
                "status": "PASS",
                "role": LOGIN_ROLE,
                "detail": "role already matches contract",
                "auto_repair": False,
            }
        mismatches: list[str] = []
        if not attributes_match(before):
            mismatches.append("attributes")
        if not membership_match(before):
            mismatches.append("membership")
        raise PrincipalProvisionError(
            "existing role does not match contract "
            f"({', '.join(mismatches)}); automatic repair is forbidden"
        )

    _create_login_role(conn, password)
    _grant_group(conn)
    after = fetch_role_snapshot(conn, LOGIN_ROLE)
    if not contract_match(after):
        raise PrincipalProvisionError(
            "role created but post-create contract verification failed"
        )
    return {
        "action": "created",
        "status": "PASS",
        "role": LOGIN_ROLE,
        "detail": "created LOGIN + GRANT canonical_loader",
        "auto_repair": False,
    }
