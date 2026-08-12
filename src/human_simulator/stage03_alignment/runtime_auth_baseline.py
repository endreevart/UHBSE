"""Frozen baseline constants and Phase 0 gate for runtime-auth v0.1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.canonical.constants import ROLE_LOADER
from human_simulator.canonical.migrations import (
    discover_migrations,
    migration_immutability,
    row_counts,
)
from human_simulator.stage03_alignment.postgres_principal import (
    EXPECTED_ATTRIBUTES,
    LOGIN_ROLE,
    fetch_role_snapshot,
)
from human_simulator.stage03_alignment.postgres_principal_verify import (
    schema_fingerprint,
)
from human_simulator.stage03_alignment.vault_provider import (
    POSTGRES_LOGIN_PRINCIPAL,
    POSTGRES_NOLOGIN_GROUP,
    VAULT_APPROLE,
)

PASS = "PASS"
FAIL = "FAIL"

ACCEPTED_VAULT_STOP_ZIP = "stage-03-alignment-vault-stop-v0.2.1-review.zip"
ACCEPTED_VAULT_STOP_SHA256 = (
    "650c81e709e14211126f06ce20e11758c78de784fcb9e2dd9ad47d1685bf0204"
)
ACCEPTED_POSTGRES_PRINCIPAL_ZIP = "stage-03-alignment-postgres-principal-v0.1-review.zip"
ACCEPTED_POSTGRES_PRINCIPAL_SHA256 = (
    "dfb6f2ce290e1e2fe3451a3d5e819b42709d7ffdcdef368bb85bd7dc943673cd"
)

REQUIRED_MIGRATIONS = (
    "0001_roles_and_schema.sql",
    "0002_pilot_evidence_tables.sql",
    "0003_pilot_grants.sql",
    "0004_storage_contract_hardening.sql",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_phase0_baseline(
    repo_root: Path,
    *,
    conn: Any | None = None,
) -> dict[str, Any]:
    external = repo_root / "artifacts" / "external-review"
    vault_zip = external / ACCEPTED_VAULT_STOP_ZIP
    pg_zip = external / ACCEPTED_POSTGRES_PRINCIPAL_ZIP

    checks: list[dict[str, str]] = []

    def add(check_id: str, status: str, detail: str = "") -> None:
        checks.append({"id": check_id, "status": status, "detail": detail})

    if vault_zip.is_file():
        digest = sha256_file(vault_zip)
        add(
            "vault_stop_zip_unchanged",
            PASS if digest == ACCEPTED_VAULT_STOP_SHA256 else FAIL,
            digest,
        )
    else:
        add("vault_stop_zip_unchanged", FAIL, "missing")

    if pg_zip.is_file():
        digest = sha256_file(pg_zip)
        add(
            "postgres_principal_zip_unchanged",
            PASS if digest == ACCEPTED_POSTGRES_PRINCIPAL_SHA256 else FAIL,
            digest,
        )
    else:
        add("postgres_principal_zip_unchanged", FAIL, "missing")

    immutability = migration_immutability(repo_root)
    add("migrations_immutability", immutability["status"])
    declared = {item.path.name: item.sha256 for item in discover_migrations(repo_root)}
    migrations_present = all(name in declared for name in REQUIRED_MIGRATIONS)
    add(
        "migrations_0001_0004_present",
        PASS if migrations_present else FAIL,
    )

    preflight_path = (
        repo_root / "artifacts" / "stage-03-alignment-candidate" / "vault-preflight.json"
    )
    preflight_status = None
    if preflight_path.is_file():
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
        preflight_status = preflight.get("overall_status")
        add(
            "vault_preflight_status",
            PASS if preflight_status == PASS else FAIL,
            str(preflight_status),
        )
    else:
        add("vault_preflight_status", FAIL, "missing")

    findings_path = (
        repo_root
        / "artifacts"
        / "stage-03-alignment-candidate"
        / "operational-security-findings.json"
    )
    findings = None
    if findings_path.is_file():
        findings = json.loads(findings_path.read_text(encoding="utf-8"))
        add("operational_security_findings_present", PASS)
    else:
        add("operational_security_findings_present", FAIL, "missing")

    fingerprint = None
    counts = None
    role_inventory = None
    if conn is not None:
        fingerprint = schema_fingerprint(conn)
        counts = row_counts(conn)
        zero = all(v == 0 for v in counts.values())
        add("canonical_row_counts_zero", PASS if zero else FAIL, str(sum(counts.values())))

        login = fetch_role_snapshot(conn, LOGIN_ROLE)
        group = fetch_role_snapshot(conn, ROLE_LOADER)
        role_ok = (
            login.exists
            and login.attributes == EXPECTED_ATTRIBUTES
            and login.memberships == [ROLE_LOADER]
            and group.exists
            and group.attributes is not None
            and group.attributes.get("rolcanlogin") is False
        )
        add("postgres_principal_contract", PASS if role_ok else FAIL)
        role_inventory = {
            POSTGRES_LOGIN_PRINCIPAL: {
                "exists": login.exists,
                "attributes": login.attributes,
                "memberships": login.memberships,
            },
            POSTGRES_NOLOGIN_GROUP: {
                "exists": group.exists,
                "attributes": group.attributes,
                "memberships": group.memberships,
            },
            "vault_approle": VAULT_APPROLE,
        }
    else:
        add("canonical_row_counts_zero", FAIL, "no_connection")
        add("postgres_principal_contract", FAIL, "no_connection")

    overall = PASS if all(c["status"] == PASS for c in checks) else FAIL
    return {
        "stage": "03",
        "phase": "alignment_candidate",
        "title": "Runtime-auth Phase 0 frozen baseline",
        "document_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "accepted_zips": {
            ACCEPTED_VAULT_STOP_ZIP: ACCEPTED_VAULT_STOP_SHA256,
            ACCEPTED_POSTGRES_PRINCIPAL_ZIP: ACCEPTED_POSTGRES_PRINCIPAL_SHA256,
        },
        "vault_preflight_status": preflight_status,
        "migration_hashes": declared,
        "schema_fingerprint": fingerprint,
        "row_counts": counts,
        "role_inventory": role_inventory,
        "operational_security_findings": findings,
        "checks": checks,
        "identities": {
            "vault_approle": VAULT_APPROLE,
            "postgres_login": POSTGRES_LOGIN_PRINCIPAL,
            "postgres_nologin": POSTGRES_NOLOGIN_GROUP,
        },
    }
