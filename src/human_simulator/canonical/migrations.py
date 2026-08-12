"""Forward-only migration mechanism for the canonical pilot database.

Design decisions and their authority:

* Forward-only. The accepted plan defines no reverse DDL for canonical evidence:
  pipeline-plan.yaml :: rollback limits rollback to current-run staging rows and states
  that published records are never deleted, and physical-storage-plan.yaml names only a
  forward DDL role. An ``up -> down -> up`` cycle is therefore out of scope for
  Changeset 01 and is not executed.
* Idempotent. Applied versions and their checksums are recorded; re-running applies
  nothing. A checksum change on an already applied migration is a fail-closed error.
* Fail-closed schema contract. After applying, the live schema is compared to
  ``schema_contract`` and any difference is an error.

This module performs DDL only. It never reads, writes or transports clinical rows.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.canonical.constants import (
    ACCEPTED_MIGRATION_SHA256,
    CANONICAL_ROLES,
    CANONICAL_SCHEMA,
    DOWN_MIGRATIONS_SUPPORTED,
    EXPECTED_SCHEMA_OWNER,
    EXPECTED_SCHEMA_PRIVILEGES,
    EXPECTED_TABLE_OWNER,
    EXPECTED_TABLE_PRIVILEGES,
    FORBIDDEN_COLUMN_NAMES,
    FORBIDDEN_TABLE_PRIVILEGES,
    HARDENING_MIGRATION_FILENAME,
    MIGRATION_HISTORY_TABLE,
    MIGRATION_SCHEMA,
    ROLE_LOADER,
    ROLE_MIGRATOR,
    ROLE_OWNER,
    ROLE_VALIDATOR_RO,
)
from human_simulator.canonical.definition_baseline import (
    DefinitionBaselineError,
    baseline_document,
    baseline_violations,
)
from human_simulator.canonical.schema_contract import (
    EXPECTED_ENUMS,
    PILOT_TABLES,
    TABLES_BY_NAME,
    contract_fingerprint,
    load_order_violations,
)

MIGRATIONS_DIRNAME = Path("migrations") / "canonical"
MIGRATION_FILENAME_PATTERN = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

# Statements that must never appear in a canonical migration.
FORBIDDEN_MIGRATION_TOKENS: tuple[str, ...] = (
    "INSERT INTO",
    "COPY ",
    "DELETE FROM",
    "UPDATE ",
    "TRUNCATE",
    "DROP TABLE",
    "DROP SCHEMA",
    "dblink",
    "postgres_fdw",
)


class MigrationError(RuntimeError):
    """Raised on any migration or schema contract failure."""


@dataclass(frozen=True)
class MigrationFile:
    version: str
    name: str
    path: Path
    sha256: str

    @property
    def identifier(self) -> str:
        return f"{self.version}_{self.name}"


def migrations_dir(repo_root: Path) -> Path:
    return repo_root / MIGRATIONS_DIRNAME


def discover_migrations(repo_root: Path) -> list[MigrationFile]:
    directory = migrations_dir(repo_root)
    if not directory.is_dir():
        raise MigrationError(f"migration directory not found: {MIGRATIONS_DIRNAME}")

    found: list[MigrationFile] = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith("."):
            continue
        if not path.is_file():
            raise MigrationError(f"unexpected non-file entry in migrations: {path.name}")
        match = MIGRATION_FILENAME_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"migration filename does not match NNNN_name.sql: {path.name}")
        text = path.read_text(encoding="utf-8")
        found.append(
            MigrationFile(
                version=match.group(1),
                name=match.group(2),
                path=path,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )

    if not found:
        raise MigrationError("no canonical migrations found")

    versions = [item.version for item in found]
    if len(set(versions)) != len(versions):
        raise MigrationError(f"duplicate migration versions: {sorted(versions)}")
    expected = [f"{index:04d}" for index in range(1, len(found) + 1)]
    if versions != expected:
        raise MigrationError(f"migration versions must be contiguous from 0001: {versions}")
    return found


def migration_immutability(repo_root: Path) -> dict[str, Any]:
    """Compare on-disk migration bytes to the accepted SHA-256 of already published files.

    A published migration is immutable: a schema correction arrives as a new forward-only
    file, never as an edit. This is read-only and never rewrites a migration.
    """
    present = {item.path.name: item.sha256 for item in discover_migrations(repo_root)}
    violations: list[str] = []
    observed: dict[str, str] = {}
    for name, accepted in sorted(ACCEPTED_MIGRATION_SHA256.items()):
        actual = present.get(name)
        observed[name] = actual or "MISSING"
        if actual is None:
            violations.append(f"accepted migration removed: {name}")
        elif actual != accepted:
            violations.append(f"accepted migration modified: {name}")
    return {
        "status": "PASS" if not violations else "FAIL",
        "accepted_sha256": dict(sorted(ACCEPTED_MIGRATION_SHA256.items())),
        "observed_sha256": observed,
        "hardening_migration": HARDENING_MIGRATION_FILENAME,
        "hardening_migration_sha256": present.get(HARDENING_MIGRATION_FILENAME),
        "hardening_migration_present": HARDENING_MIGRATION_FILENAME in present,
        "violations": violations,
    }


def forbidden_tokens_in_migrations(repo_root: Path) -> dict[str, list[str]]:
    """Data-manipulation or cross-database tokens found in migration text, by file."""
    offenders: dict[str, list[str]] = {}
    for migration in discover_migrations(repo_root):
        text = migration.path.read_text(encoding="utf-8")
        stripped = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("--")
        )
        hits = [token for token in FORBIDDEN_MIGRATION_TOKENS if token in stripped]
        if hits:
            offenders[migration.path.name] = hits
    return offenders


# --------------------------------------------------------------------------------------
# Live database operations. All of these require an open psycopg connection.
# --------------------------------------------------------------------------------------


def _bootstrap_history(conn: Any) -> None:
    """Create the migration bookkeeping schema.

    Bookkeeping lives in its own schema so that canonical_evidence holds exactly the pilot
    entity tables. It is created by the runner rather than by a migration because the
    history table must exist before the first migration can be recorded.
    """
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {MIGRATION_SCHEMA}")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {MIGRATION_SCHEMA}.{MIGRATION_HISTORY_TABLE} (
                version      text NOT NULL PRIMARY KEY,
                name         text NOT NULL,
                sha256       text NOT NULL,
                applied_at   timestamptz NOT NULL DEFAULT now(),
                applied_by   text NOT NULL DEFAULT current_user,
                contract_fingerprint text NOT NULL
            )
            """
        )


def applied_migrations(conn: Any) -> dict[str, dict[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT version, name, sha256, contract_fingerprint, applied_at
            FROM {MIGRATION_SCHEMA}.{MIGRATION_HISTORY_TABLE}
            ORDER BY version
            """
        )
        rows = cur.fetchall()
    return {
        row[0]: {
            "name": row[1],
            "sha256": row[2],
            "contract_fingerprint": row[3],
            "applied_at": row[4].astimezone(UTC).isoformat(),
        }
        for row in rows
    }


def apply_migrations(conn: Any, repo_root: Path) -> dict[str, Any]:
    """Apply pending migrations. Returns a schema-only result with no clinical data.

    The connection must be in autocommit mode: each migration file carries its own
    BEGIN/COMMIT so that it is also runnable verbatim through psql.
    """
    if not getattr(conn, "autocommit", False):
        raise MigrationError("canonical migrations require an autocommit connection")

    migrations = discover_migrations(repo_root)
    offenders = forbidden_tokens_in_migrations(repo_root)
    if offenders:
        raise MigrationError(f"migrations contain forbidden data statements: {offenders}")

    _bootstrap_history(conn)
    already = applied_migrations(conn)
    fingerprint = contract_fingerprint()

    for version, record in already.items():
        known = next((m for m in migrations if m.version == version), None)
        if known is None:
            raise MigrationError(
                f"database records migration {version} that no longer exists in the repository"
            )
        if known.sha256 != record["sha256"]:
            raise MigrationError(
                f"checksum drift for applied migration {version}: "
                "migration files are immutable once applied"
            )

    applied_now: list[str] = []
    for migration in migrations:
        if migration.version in already:
            continue
        sql = migration.path.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                f"""
                INSERT INTO {MIGRATION_SCHEMA}.{MIGRATION_HISTORY_TABLE}
                    (version, name, sha256, contract_fingerprint)
                VALUES (%s, %s, %s, %s)
                """,
                (migration.version, migration.name, migration.sha256, fingerprint),
            )
        applied_now.append(migration.identifier)

    return {
        "declared_migrations": [m.identifier for m in migrations],
        "migration_sha256": {m.identifier: m.sha256 for m in migrations},
        "applied_in_this_run": applied_now,
        "already_applied_before_run": sorted(already),
        "down_migrations_supported": DOWN_MIGRATIONS_SUPPORTED,
        "contract_fingerprint": fingerprint,
    }


def introspect_schema(conn: Any) -> dict[str, Any]:
    """Read the live canonical schema shape. Catalog metadata only, never row values."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (CANONICAL_SCHEMA,),
        )
        tables = [row[0] for row in cur.fetchall()]

        cur.execute(
            """
            SELECT table_name, column_name, data_type, udt_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
            """,
            (CANONICAL_SCHEMA,),
        )
        columns: dict[str, list[dict[str, Any]]] = {}
        for table_name, column_name, data_type, udt_name, is_nullable in cur.fetchall():
            resolved = udt_name if data_type == "USER-DEFINED" else data_type
            columns.setdefault(table_name, []).append(
                {
                    "name": column_name,
                    "type": resolved,
                    "nullable": is_nullable == "YES",
                }
            )

        cur.execute(
            """
            SELECT c.conname, c.contype, rel.relname, c.conkey, refrel.relname, c.confkey
            FROM pg_constraint c
            JOIN pg_class rel ON rel.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = rel.relnamespace
            LEFT JOIN pg_class refrel ON refrel.oid = c.confrelid
            WHERE n.nspname = %s
            ORDER BY rel.relname, c.conname
            """,
            (CANONICAL_SCHEMA,),
        )
        raw_constraints = cur.fetchall()

        cur.execute(
            """
            SELECT rel.relname, a.attnum, a.attname
            FROM pg_attribute a
            JOIN pg_class rel ON rel.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = rel.relnamespace
            WHERE n.nspname = %s AND a.attnum > 0 AND NOT a.attisdropped
            """,
            (CANONICAL_SCHEMA,),
        )
        attribute_names: dict[tuple[str, int], str] = {
            (row[0], row[1]): row[2] for row in cur.fetchall()
        }

        cur.execute(
            """
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = %s
            ORDER BY tablename, indexname
            """,
            (CANONICAL_SCHEMA,),
        )
        indexes: dict[str, list[str]] = {}
        index_definitions: dict[str, dict[str, str]] = {}
        for table_name, index_name, index_def in cur.fetchall():
            indexes.setdefault(table_name, []).append(index_name)
            index_definitions.setdefault(table_name, {})[index_name] = index_def

        cur.execute(
            """
            SELECT t.typname, e.enumlabel
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            JOIN pg_enum e ON e.enumtypid = t.oid
            WHERE n.nspname = %s
            ORDER BY t.typname, e.enumsortorder
            """,
            (CANONICAL_SCHEMA,),
        )
        enums: dict[str, list[str]] = {}
        for type_name, label in cur.fetchall():
            enums.setdefault(type_name, []).append(label)

        # Normalized constraint text as PostgreSQL itself renders it. This is what makes a
        # renamed CHECK (TRUE) detectable: the name survives, the definition does not.
        cur.execute(
            """
            SELECT rel.relname, c.conname, pg_get_constraintdef(c.oid, true)
            FROM pg_constraint c
            JOIN pg_class rel ON rel.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = rel.relnamespace
            WHERE n.nspname = %s
            ORDER BY rel.relname, c.conname
            """,
            (CANONICAL_SCHEMA,),
        )
        constraint_definitions: dict[str, dict[str, str]] = {}
        for table_name, constraint_name, definition in cur.fetchall():
            constraint_definitions.setdefault(table_name, {})[constraint_name] = definition

        cur.execute(
            """
            SELECT rel.relname, pg_get_userbyid(rel.relowner)
            FROM pg_class rel
            JOIN pg_namespace n ON n.oid = rel.relnamespace
            WHERE n.nspname = %s AND rel.relkind = 'r'
            ORDER BY rel.relname
            """,
            (CANONICAL_SCHEMA,),
        )
        table_owners = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = %s",
            (CANONICAL_SCHEMA,),
        )
        owner_row = cur.fetchone()
        schema_owner = owner_row[0] if owner_row else None

        cur.execute(
            """
            SELECT grantee, privilege_type
            FROM information_schema.usage_privileges
            WHERE object_schema = %s AND object_type = 'SCHEMA'
            """,
            (CANONICAL_SCHEMA,),
        )
        schema_privileges: dict[str, list[str]] = {}
        for grantee, privilege in cur.fetchall():
            schema_privileges.setdefault(grantee, []).append(privilege)
        # information_schema does not expose CREATE on a schema, so ask the catalog directly
        # for every canonical role rather than inferring it from ownership.
        for role in CANONICAL_ROLES:
            for privilege in ("CREATE", "USAGE"):
                cur.execute(
                    "SELECT has_schema_privilege(%s, %s, %s)",
                    (role, CANONICAL_SCHEMA, privilege),
                )
                if cur.fetchone()[0]:
                    schema_privileges.setdefault(role, []).append(privilege)

        cur.execute(
            """
            SELECT grantee, table_name, privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = %s
            ORDER BY grantee, table_name, privilege_type
            """,
            (CANONICAL_SCHEMA,),
        )
        table_privileges: dict[str, dict[str, list[str]]] = {}
        for grantee, table_name, privilege in cur.fetchall():
            table_privileges.setdefault(grantee, {}).setdefault(table_name, []).append(privilege)

        cur.execute(
            """
            SELECT pg_get_userbyid(d.defaclrole), d.defaclobjtype,
                   array_to_string(d.defaclacl::text[], ',')
            FROM pg_default_acl d
            JOIN pg_namespace n ON n.oid = d.defaclnamespace
            WHERE n.nspname = %s
            ORDER BY 1, 2, 3
            """,
            (CANONICAL_SCHEMA,),
        )
        default_privileges = [
            f"{role}:{objtype}:{acl}" for role, objtype, acl in cur.fetchall()
        ]

    primary_keys: dict[str, list[str]] = {}
    unique_constraints: dict[str, list[dict[str, Any]]] = {}
    foreign_keys: dict[str, list[dict[str, Any]]] = {}
    check_constraints: dict[str, list[str]] = {}

    for name, contype, table_name, conkey, ref_table, confkey in raw_constraints:
        if contype == "p":
            primary_keys[table_name] = [attribute_names[(table_name, key)] for key in conkey]
        elif contype == "u":
            unique_constraints.setdefault(table_name, []).append(
                {
                    "name": name,
                    "columns": [attribute_names[(table_name, key)] for key in conkey],
                }
            )
        elif contype == "f":
            foreign_keys.setdefault(table_name, []).append(
                {
                    "name": name,
                    "columns": [attribute_names[(table_name, key)] for key in conkey],
                    "references": {
                        "table": ref_table,
                        "columns": [attribute_names[(ref_table, key)] for key in confkey or []],
                    },
                }
            )
        elif contype == "c":
            check_constraints.setdefault(table_name, []).append(name)

    return {
        "schema": CANONICAL_SCHEMA,
        "tables": tables,
        "columns": columns,
        "primary_keys": primary_keys,
        "unique_constraints": unique_constraints,
        "foreign_keys": foreign_keys,
        "check_constraints": {k: sorted(v) for k, v in check_constraints.items()},
        "indexes": indexes,
        "enums": enums,
        "constraint_definitions": constraint_definitions,
        "index_definitions": index_definitions,
        "table_owners": table_owners,
        "schema_owner": schema_owner,
        "schema_privileges": {
            grantee: sorted(set(privs)) for grantee, privs in schema_privileges.items()
        },
        "table_privileges": {
            grantee: {table: sorted(set(privs)) for table, privs in per_table.items()}
            for grantee, per_table in table_privileges.items()
        },
        "default_privileges": default_privileges,
    }


def contract_violations(actual: dict[str, Any]) -> list[str]:
    """Every deviation between the live schema and the declared contract."""
    problems: list[str] = []

    expected_tables = sorted(TABLES_BY_NAME)
    actual_tables = sorted(actual["tables"])
    unexpected = [name for name in actual_tables if name not in TABLES_BY_NAME]
    missing = [name for name in expected_tables if name not in actual_tables]
    for name in unexpected:
        problems.append(f"table outside pilot scope present: {name}")
    for name in missing:
        problems.append(f"pilot table missing: {name}")

    for enum_name, expected_values in EXPECTED_ENUMS.items():
        actual_values = actual["enums"].get(enum_name)
        if actual_values is None:
            problems.append(f"enum type missing: {enum_name}")
        elif tuple(actual_values) != tuple(expected_values):
            problems.append(f"enum values differ for {enum_name}")
    for enum_name in actual["enums"]:
        if enum_name not in EXPECTED_ENUMS:
            problems.append(f"enum type outside contract present: {enum_name}")

    for table in PILOT_TABLES:
        if table.name not in actual_tables:
            continue
        actual_columns = {col["name"]: col for col in actual["columns"].get(table.name, [])}
        for column in table.columns:
            live = actual_columns.get(column.name)
            if live is None:
                problems.append(f"{table.name}.{column.name} missing")
                continue
            if live["type"] != column.data_type:
                problems.append(
                    f"{table.name}.{column.name} type {live['type']} != {column.data_type}"
                )
            if live["nullable"] != column.nullable:
                problems.append(
                    f"{table.name}.{column.name} nullable {live['nullable']} != {column.nullable}"
                )
        for name in actual_columns:
            if table.column(name) is None:
                problems.append(f"{table.name}.{name} is not declared in the contract")
            if name in FORBIDDEN_COLUMN_NAMES:
                problems.append(f"{table.name}.{name} is a forbidden identifier column")

        if tuple(actual["primary_keys"].get(table.name, [])) != table.primary_key:
            problems.append(f"{table.name} primary key differs from contract")

        actual_unique = {
            entry["name"]: tuple(entry["columns"])
            for entry in actual["unique_constraints"].get(table.name, [])
        }
        for name, columns in table.unique_constraints:
            if actual_unique.get(name) != columns:
                problems.append(f"{table.name} unique constraint {name} differs from contract")
        for name in actual_unique:
            if name not in {entry[0] for entry in table.unique_constraints}:
                problems.append(f"{table.name} has undeclared unique constraint {name}")

        actual_fks = {
            entry["name"]: (
                tuple(entry["columns"]),
                entry["references"]["table"],
                tuple(entry["references"]["columns"]),
            )
            for entry in actual["foreign_keys"].get(table.name, [])
        }
        for fk in table.foreign_keys:
            expected = (fk.columns, fk.referenced_table, fk.referenced_columns)
            if actual_fks.get(fk.name) != expected:
                problems.append(f"{table.name} foreign key {fk.name} differs from contract")
        for name in actual_fks:
            if name not in {fk.name for fk in table.foreign_keys}:
                problems.append(f"{table.name} has undeclared foreign key {name}")

        actual_checks = set(actual["check_constraints"].get(table.name, []))
        for name in table.check_constraints:
            if name not in actual_checks:
                problems.append(f"{table.name} check constraint {name} missing")
        for name in sorted(actual_checks - set(table.check_constraints)):
            problems.append(f"{table.name} has undeclared check constraint {name}")

        actual_indexes = set(actual["indexes"].get(table.name, []))
        # Constraint-backed indexes carry the constraint name; they are declared through the
        # primary key and unique constraint entries rather than the index list.
        constraint_backed = {f"{table.name}_pkey", *(name for name, _ in table.unique_constraints)}
        for name in table.indexes:
            if name not in actual_indexes:
                problems.append(f"{table.name} index {name} missing")
        for name in sorted(actual_indexes - set(table.indexes) - constraint_backed):
            problems.append(f"{table.name} has undeclared index {name}")

        owner = actual.get("table_owners", {}).get(table.name)
        if owner is not None and owner != EXPECTED_TABLE_OWNER:
            problems.append(
                f"{table.name} owner is {owner!r}, expected {EXPECTED_TABLE_OWNER!r}"
            )

    if actual.get("schema_owner") not in (None, EXPECTED_SCHEMA_OWNER):
        problems.append(
            f"schema owner is {actual.get('schema_owner')!r}, expected {EXPECTED_SCHEMA_OWNER!r}"
        )

    problems.extend(load_order_violations())
    return problems


def verify_schema(conn: Any, repo_root: Path | None = None) -> dict[str, Any]:
    """Verify the live schema against the contract and, when available, pinned definitions.

    ``repo_root`` enables definition-level verification: normalized constraint and index
    text, enum order, owners and privileges are compared to the committed baseline. Without
    it only the structural contract is checked, which is not sufficient for a release.
    """
    actual = introspect_schema(conn)
    problems = contract_violations(actual)

    definitions_checked = False
    definition_problems: list[str] = []
    if repo_root is not None:
        definitions_checked = True
        try:
            definition_problems = baseline_violations(repo_root, actual)
        except DefinitionBaselineError as error:
            definition_problems = [str(error)]
        problems = [*problems, *definition_problems]

    return {
        "status": "PASS" if not problems else "FAIL",
        "contract_fingerprint": contract_fingerprint(),
        "definitions_verified": definitions_checked,
        "definition_violations": definition_problems,
        "table_count": len(actual["tables"]),
        "tables": actual["tables"],
        "violations": problems,
    }


def assert_schema_matches_contract(conn: Any, repo_root: Path | None = None) -> dict[str, Any]:
    result = verify_schema(conn, repo_root)
    if result["status"] != "PASS":
        raise MigrationError(
            "canonical schema does not match contract: " + "; ".join(result["violations"])
        )
    return result


def row_counts(conn: Any) -> dict[str, int]:
    """Exact counts on the pilot tables.

    Changeset 01 leaves the canonical database empty, so this is the evidence that the
    migration produced schema only. It reads counts, never column values.
    """
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in PILOT_TABLES:
            cur.execute(f"SELECT count(*) FROM {CANONICAL_SCHEMA}.{table.name}")  # noqa: S608
            counts[table.name] = int(cur.fetchone()[0])
    return counts


def role_state(conn: Any) -> dict[str, Any]:
    """Role existence, login capability and table privileges."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole
            FROM pg_roles
            WHERE rolname = ANY(%s)
            ORDER BY rolname
            """,
            (list(CANONICAL_ROLES),),
        )
        roles = {
            row[0]: {
                "can_login": row[1],
                "superuser": row[2],
                "createdb": row[3],
                "createrole": row[4],
            }
            for row in cur.fetchall()
        }

        cur.execute(
            """
            SELECT grantee, table_name, privilege_type
            FROM information_schema.role_table_grants
            WHERE table_schema = %s AND grantee = ANY(%s)
            ORDER BY grantee, table_name, privilege_type
            """,
            (CANONICAL_SCHEMA, list(CANONICAL_ROLES)),
        )
        grants: dict[str, dict[str, list[str]]] = {}
        for grantee, table_name, privilege in cur.fetchall():
            grants.setdefault(grantee, {}).setdefault(table_name, []).append(privilege)

        cur.execute(
            """
            SELECT nspname, nspowner::regrole::text
            FROM pg_namespace WHERE nspname = %s
            """,
            (CANONICAL_SCHEMA,),
        )
        owner_row = cur.fetchone()

        schema_privileges: dict[str, list[str]] = {}
        for role in CANONICAL_ROLES:
            for privilege in ("CREATE", "USAGE"):
                cur.execute(
                    "SELECT has_schema_privilege(%s, %s, %s)",
                    (role, CANONICAL_SCHEMA, privilege),
                )
                if cur.fetchone()[0]:
                    schema_privileges.setdefault(role, []).append(privilege)

        cur.execute(
            """
            SELECT rel.relname, pg_get_userbyid(rel.relowner)
            FROM pg_class rel
            JOIN pg_namespace n ON n.oid = rel.relnamespace
            WHERE n.nspname = %s AND rel.relkind = 'r'
            """,
            (CANONICAL_SCHEMA,),
        )
        table_owners = {row[0]: row[1] for row in cur.fetchall()}

    return {
        "roles": roles,
        "table_grants": {
            grantee: {table: sorted(set(privs)) for table, privs in tables.items()}
            for grantee, tables in grants.items()
        },
        "schema_owner": owner_row[1] if owner_row else None,
        "schema_privileges": {
            grantee: sorted(set(privs)) for grantee, privs in schema_privileges.items()
        },
        "table_owners": table_owners,
    }


def permission_violations(state: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    roles = state["roles"]
    for role in CANONICAL_ROLES:
        if role not in roles:
            problems.append(f"role missing: {role}")
            continue
        if roles[role]["superuser"]:
            problems.append(f"role {role} must not be superuser")
        if roles[role]["can_login"]:
            problems.append(
                f"role {role} must be NOLOGIN; credentials are assigned at runtime only"
            )

    if state.get("schema_owner") != ROLE_OWNER:
        problems.append(
            f"schema {CANONICAL_SCHEMA} owner is {state.get('schema_owner')!r}, expected {ROLE_OWNER!r}"
        )

    for table, owner in sorted(state.get("table_owners", {}).items()):
        if owner != EXPECTED_TABLE_OWNER:
            problems.append(f"table {table} owner is {owner!r}, expected {EXPECTED_TABLE_OWNER!r}")

    schema_privileges = state.get("schema_privileges", {})
    for role, expected in sorted(EXPECTED_SCHEMA_PRIVILEGES.items()):
        actual = tuple(schema_privileges.get(role, ()))
        if actual != expected:
            problems.append(
                f"{role} on schema {CANONICAL_SCHEMA} has {list(actual)}, expected {list(expected)}"
            )

    grants = state["table_grants"]
    pilot_tables = {table.name for table in PILOT_TABLES}

    for role, expected_privileges in sorted(EXPECTED_TABLE_PRIVILEGES.items()):
        granted = grants.get(role, {})
        for table in sorted(pilot_tables):
            privileges = tuple(sorted(set(granted.get(table, []))))
            if privileges != expected_privileges:
                problems.append(
                    f"{role} on {table} has {list(privileges)}, expected {list(expected_privileges)}"
                )

    migrator = grants.get(ROLE_MIGRATOR, {})
    for table, privileges in migrator.items():
        if privileges:
            problems.append(f"{ROLE_MIGRATOR} must hold no table privileges, found on {table}")

    # No role may hold a mutating privilege on evidence, whatever its name.
    for grantee, per_table in sorted(grants.items()):
        for table, privileges in sorted(per_table.items()):
            if table not in pilot_tables or grantee == EXPECTED_TABLE_OWNER:
                continue
            forbidden = sorted(set(privileges) & set(FORBIDDEN_TABLE_PRIVILEGES))
            if forbidden:
                problems.append(f"{grantee} holds forbidden {forbidden} on {table}")

    return problems


def verify_permissions(conn: Any) -> dict[str, Any]:
    state = role_state(conn)
    problems = permission_violations(state)
    return {
        "status": "PASS" if not problems else "FAIL",
        "roles": sorted(state["roles"]),
        "schema_owner": state.get("schema_owner"),
        "schema_privileges": state.get("schema_privileges", {}),
        "table_owners": state.get("table_owners", {}),
        "table_grants": state["table_grants"],
        "violations": problems,
    }


def capture_definition_baseline(conn: Any, repo_root: Path) -> dict[str, Any]:
    """Produce the pinned definition document from a schema built by the accepted migrations.

    Refuses to run unless every published migration matches its accepted SHA-256 and the
    structural contract already holds, so the baseline can only ever describe reviewed DDL.
    Callers are responsible for pointing this at a disposable database.
    """
    immutability = migration_immutability(repo_root)
    if immutability["status"] != "PASS":
        raise DefinitionBaselineError(
            "refusing to capture a baseline from modified migrations: "
            + "; ".join(immutability["violations"])
        )

    actual = introspect_schema(conn)
    structural = contract_violations(actual)
    if structural:
        raise DefinitionBaselineError(
            "refusing to capture a baseline from a non-conforming schema: "
            + "; ".join(structural)
        )

    declared = {item.path.name: item.sha256 for item in discover_migrations(repo_root)}
    return baseline_document(actual, migration_sha256=declared)


def migration_report(conn: Any, repo_root: Path) -> dict[str, Any]:
    """Schema-only migration result plus permission state. Contains no clinical data."""
    immutability = migration_immutability(repo_root)
    if immutability["status"] != "PASS":
        raise MigrationError(
            "published migrations were modified: " + "; ".join(immutability["violations"])
        )

    apply_result = apply_migrations(conn, repo_root)
    schema_result = verify_schema(conn, repo_root)
    permission_result = verify_permissions(conn)
    counts = row_counts(conn)
    empty = all(value == 0 for value in counts.values())

    status = "PASS"
    if (
        schema_result["status"] != "PASS"
        or permission_result["status"] != "PASS"
        or not empty
        or not schema_result["definitions_verified"]
    ):
        status = "FAIL"

    return {
        "changeset": "stage-03-implementation-changeset-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "migration_immutability": immutability,
        "migration": apply_result,
        "applied_history": applied_migrations(conn),
        "schema_verification": schema_result,
        "permission_verification": permission_result,
        "schema_only_result": {
            "row_counts": counts,
            "database_is_empty": empty,
            "clinical_rows_loaded": 0,
        },
    }
