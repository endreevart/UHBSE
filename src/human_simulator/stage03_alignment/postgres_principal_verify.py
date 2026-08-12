"""Sanitised inventories and permission / SET ROLE verification for LOGIN principal."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from human_simulator.canonical.constants import (
    CANONICAL_ROLES,
    CANONICAL_SCHEMA,
    ROLE_LOADER,
)
from human_simulator.canonical.migrations import (
    applied_migrations,
    discover_migrations,
    introspect_schema,
    migration_immutability,
    row_counts,
)
from human_simulator.canonical.settings import CanonicalConnectionSettings
from human_simulator.stage03_alignment.postgres_principal import (
    EXPECTED_ATTRIBUTES,
    GROUP_ROLE,
    LOGIN_ROLE,
    fetch_role_snapshot,
)
from human_simulator.stage03_alignment.vault_provider import POSTGRES_LOGIN_PRINCIPAL

PASS = "PASS"
FAIL = "FAIL"

TRACKED_ROLES: tuple[str, ...] = (*CANONICAL_ROLES, LOGIN_ROLE)


def schema_fingerprint(conn: Any) -> dict[str, Any]:
    schema = introspect_schema(conn)
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {
        "algorithm": "sha256",
        "sha256": digest,
        "schema": CANONICAL_SCHEMA,
        "table_count": len((schema.get("tables") or schema.get("table_names") or [])),
    }


def migration_inventory(conn: Any, repo_root: Any) -> dict[str, Any]:
    immutability = migration_immutability(repo_root)
    applied = applied_migrations(conn)
    declared = {item.path.name: item.sha256 for item in discover_migrations(repo_root)}
    return {
        "immutability_status": immutability["status"],
        "accepted_sha256": immutability.get("accepted_sha256"),
        "observed_file_sha256": immutability.get("observed_sha256"),
        "hardening_migration_sha256": immutability.get("hardening_migration_sha256"),
        "declared_file_sha256": declared,
        "applied_history": {
            version: {
                "name": meta["name"],
                "sha256": meta["sha256"],
                "applied_at": meta.get("applied_at"),
            }
            for version, meta in sorted(applied.items())
        },
        "migrations_0001_0004_present": all(
            name in declared
            for name in (
                "0001_roles_and_schema.sql",
                "0002_pilot_evidence_tables.sql",
                "0003_pilot_grants.sql",
                "0004_storage_contract_hardening.sql",
            )
        ),
    }


def sanitised_role_inventory(conn: Any) -> dict[str, Any]:
    roles: dict[str, Any] = {}
    for name in TRACKED_ROLES:
        snap = fetch_role_snapshot(conn, name)
        if not snap.exists:
            roles[name] = {"exists": False}
            continue
        roles[name] = {
            "exists": True,
            "attributes": snap.attributes,
            "memberships": snap.memberships,
        }
    return {"roles": roles, "password_material_included": False}


def grants_and_membership_inventory(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT grantee, table_name, privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = %s AND grantee = ANY(%s)
            ORDER BY grantee, table_name, privilege_type
            """,
            (CANONICAL_SCHEMA, list(TRACKED_ROLES)),
        )
        table_grants: dict[str, dict[str, list[str]]] = {}
        for grantee, table_name, privilege in cur.fetchall():
            table_grants.setdefault(grantee, {}).setdefault(table_name, []).append(privilege)

        cur.execute(
            """
            SELECT m.rolname AS member, r.rolname AS role
            FROM pg_auth_members am
            JOIN pg_roles m ON m.oid = am.member
            JOIN pg_roles r ON r.oid = am.roleid
            WHERE m.rolname = ANY(%s) OR r.rolname = ANY(%s)
            ORDER BY member, role
            """,
            (list(TRACKED_ROLES), list(TRACKED_ROLES)),
        )
        memberships = [{"member": row[0], "role": row[1]} for row in cur.fetchall()]

    return {
        "table_grants": {
            g: {t: sorted(set(p)) for t, p in tables.items()}
            for g, tables in table_grants.items()
        },
        "memberships": memberships,
    }


def capture_db_snapshot(conn: Any, repo_root: Any, *, label: str) -> dict[str, Any]:
    return {
        "label": label,
        "schema_fingerprint": schema_fingerprint(conn),
        "row_counts": row_counts(conn),
        "migration_inventory": migration_inventory(conn, repo_root),
        "role_inventory": sanitised_role_inventory(conn),
        "grants_and_membership": grants_and_membership_inventory(conn),
    }


def _connect_as_login(settings: CanonicalConnectionSettings, password: str) -> Any:
    import psycopg

    # Keyword connect only — never assemble a DSN string (keeps review zip clean).
    conn = psycopg.connect(
        host=settings.host,
        port=settings.port,
        dbname=settings.database,
        user=LOGIN_ROLE,
        password=password,
        connect_timeout=10,
        autocommit=True,
    )
    return conn


def verify_set_role_and_permissions(
    admin_conn: Any,
    settings: CanonicalConnectionSettings,
    *,
    password: str,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    group = fetch_role_snapshot(admin_conn, GROUP_ROLE)
    checks.append(
        {
            "id": "canonical_loader_remains_nologin",
            "status": PASS
            if group.exists and group.attributes and group.attributes.get("rolcanlogin") is False
            else FAIL,
        }
    )

    login = fetch_role_snapshot(admin_conn, LOGIN_ROLE)
    attrs = login.attributes or {}
    for key, expected in EXPECTED_ATTRIBUTES.items():
        checks.append(
            {
                "id": f"login_attr_{key}",
                "status": PASS if attrs.get(key) is expected else FAIL,
            }
        )
    foreign = [m for m in (login.memberships or []) if m != GROUP_ROLE]
    checks.append(
        {
            "id": "no_foreign_memberships",
            "status": PASS if not foreign and login.memberships == [GROUP_ROLE] else FAIL,
        }
    )

    try:
        login_conn = _connect_as_login(settings, password)
    except Exception:  # noqa: BLE001
        checks.append({"id": "login_connect", "status": FAIL})
        return {"status": FAIL, "checks": checks, "detail": "login connect failed"}

    try:
        with login_conn.cursor() as cur:
            cur.execute("SELECT session_user, current_user")
            session_user, current_user = cur.fetchone()
            checks.append(
                {
                    "id": "session_user_is_login",
                    "status": PASS if session_user == LOGIN_ROLE else FAIL,
                }
            )
            checks.append(
                {
                    "id": "current_user_before_set_role",
                    "status": PASS if current_user == LOGIN_ROLE else FAIL,
                }
            )

            # NOINHERIT: without SET ROLE, evidence privileges must not apply.
            # has_table_privilege may raise if the login lacks schema USAGE — treat as denied.
            insert_without = False
            try:
                cur.execute(
                    "SELECT has_table_privilege(current_user, %s, 'INSERT')",
                    (f"{CANONICAL_SCHEMA}.source_system",),
                )
                insert_without = bool(cur.fetchone()[0])
            except Exception:  # noqa: BLE001
                insert_without = False
            checks.append(
                {
                    "id": "noinherit_blocks_without_set_role",
                    "status": PASS if not insert_without else FAIL,
                }
            )

            cur.execute(f"SET ROLE {GROUP_ROLE}")
            cur.execute("SELECT current_user")
            after_set = cur.fetchone()[0]
            checks.append(
                {
                    "id": "current_user_after_set_role",
                    "status": PASS if after_set == GROUP_ROLE else FAIL,
                }
            )

            # Allowed under loader role: SELECT + INSERT.
            try:
                cur.execute(
                    "SELECT has_table_privilege(current_user, %s, 'SELECT'), "
                    "has_table_privilege(current_user, %s, 'INSERT')",
                    (
                        f"{CANONICAL_SCHEMA}.subject",
                        f"{CANONICAL_SCHEMA}.subject",
                    ),
                )
                select_ok, insert_ok = cur.fetchone()
            except Exception:  # noqa: BLE001
                select_ok, insert_ok = False, False
            checks.append(
                {"id": "loader_select_allowed", "status": PASS if select_ok else FAIL}
            )
            checks.append(
                {"id": "loader_insert_allowed", "status": PASS if insert_ok else FAIL}
            )

            # Forbidden under loader grants: UPDATE / DELETE / TRUNCATE / DDL.
            for check_id, priv in (
                ("update_blocked", "UPDATE"),
                ("delete_blocked", "DELETE"),
                ("truncate_blocked", "TRUNCATE"),
            ):
                allowed = True
                try:
                    cur.execute(
                        "SELECT has_table_privilege(current_user, %s, %s)",
                        (f"{CANONICAL_SCHEMA}.source_system", priv),
                    )
                    allowed = bool(cur.fetchone()[0])
                except Exception:  # noqa: BLE001
                    allowed = False
                checks.append({"id": check_id, "status": PASS if not allowed else FAIL})

            ddl_denied = False
            try:
                cur.execute(f"CREATE TABLE {CANONICAL_SCHEMA}.__forbidden_probe (id int)")
            except Exception:  # noqa: BLE001
                ddl_denied = True
            checks.append({"id": "ddl_blocked", "status": PASS if ddl_denied else FAIL})

            cur.execute("RESET ROLE")
            cur.execute("SELECT current_user")
            after_reset = cur.fetchone()[0]
            checks.append(
                {
                    "id": "reset_role_restores_current_user",
                    "status": PASS if after_reset == LOGIN_ROLE else FAIL,
                }
            )
            cur.execute("SELECT session_user")
            checks.append(
                {
                    "id": "session_user_stable_after_reset",
                    "status": PASS if cur.fetchone()[0] == LOGIN_ROLE else FAIL,
                }
            )
    finally:
        login_conn.close()

    # Login principal itself must not hold table grants; only via SET ROLE group.
    grants = grants_and_membership_inventory(admin_conn)["table_grants"]
    login_grants = grants.get(LOGIN_ROLE) or {}
    checks.append(
        {
            "id": "login_has_no_direct_table_grants",
            "status": PASS if not login_grants else FAIL,
        }
    )
    loader_grants = grants.get(ROLE_LOADER) or {}
    expected_privs = {"SELECT", "INSERT"}
    loader_ok = bool(loader_grants) and all(
        set(privs) == expected_privs for privs in loader_grants.values()
    )
    checks.append(
        {
            "id": "only_canonical_loader_table_grants",
            "status": PASS if loader_ok else FAIL,
        }
    )

    status = PASS if all(c["status"] == PASS for c in checks) else FAIL
    return {
        "status": status,
        "login_principal": POSTGRES_LOGIN_PRINCIPAL,
        "group_role": GROUP_ROLE,
        "checks": checks,
    }
