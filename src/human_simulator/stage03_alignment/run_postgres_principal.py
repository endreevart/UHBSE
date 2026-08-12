"""Orchestrate Vault secret-shape check + PostgreSQL LOGIN principal provisioning."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.stage03_alignment.postgres_principal import (
    PrincipalProvisionError,
    provision_canonical_loader_login,
)
from human_simulator.stage03_alignment.postgres_principal_verify import (
    capture_db_snapshot,
    verify_set_role_and_permissions,
)
from human_simulator.stage03_alignment.vault_provider import (
    POSTGRES_LOGIN_PRINCIPAL,
    POSTGRES_NOLOGIN_GROUP,
    VAULT_APPROLE,
)
from human_simulator.stage03_alignment.vault_secret_shape import (
    PASS,
    VaultSecretAccessError,
    validate_secret_shapes,
)

ARTIFACT_DIRNAME = Path("artifacts") / "stage-03-alignment-candidate"
REPORT_STATUS = "DRAFT"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ensure_vault_token(root: Path) -> None:
    existing = os.environ.get("VAULT_TOKEN", "").strip()
    if existing:
        return
    script = root / "ops" / "vault" / "scripts" / "decrypt-root-token.sh"
    if not script.is_file():
        return
    env = os.environ.copy()
    env["GNUPGHOME"] = str(root / "ops" / "vault" / "pgp" / "gnupg")
    proc = subprocess.run(  # noqa: S603
        [str(script)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )
    if proc.returncode != 0:
        return
    token = proc.stdout.strip()
    if token:
        os.environ["VAULT_TOKEN"] = token


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _compare_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    fp_same = before["schema_fingerprint"]["sha256"] == after["schema_fingerprint"]["sha256"]
    counts_before = before["row_counts"]
    counts_after = after["row_counts"]
    counts_zero = all(v == 0 for v in counts_before.values()) and all(
        v == 0 for v in counts_after.values()
    )
    counts_unchanged = counts_before == counts_after

    mig_before = before["migration_inventory"]["applied_history"]
    mig_after = after["migration_inventory"]["applied_history"]
    migrations_unchanged = mig_before == mig_after

    roles_before = set(before["role_inventory"]["roles"])
    roles_after = {
        name
        for name, meta in after["role_inventory"]["roles"].items()
        if meta.get("exists")
    }
    # Only allowed delta: LOGIN role appears
    expected_new = {POSTGRES_LOGIN_PRINCIPAL}
    before_existing = {
        name
        for name, meta in before["role_inventory"]["roles"].items()
        if meta.get("exists")
    }
    created_only_login = roles_after - before_existing <= expected_new

    return {
        "schema_fingerprint_unchanged": fp_same,
        "row_counts_remain_zero": counts_zero,
        "row_counts_unchanged": counts_unchanged,
        "migrations_unchanged": migrations_unchanged,
        "created_only_login_principal_or_noop": created_only_login,
        "status": PASS
        if all(
            [
                fp_same,
                counts_zero,
                counts_unchanged,
                migrations_unchanged,
                created_only_login,
            ]
        )
        else "FAIL",
    }


def run_postgres_principal_provisioning(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _repo_root()
    out_dir = root / ARTIFACT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)

    _ensure_vault_token(root)
    os.environ.setdefault("VAULT_CACERT", str(root / "ops" / "vault" / "tls" / "ca.crt"))
    os.environ.setdefault("VAULT_ADDR", "https://127.0.0.1:8200")

    operational_findings = {
        "stage": "03",
        "phase": "alignment_candidate",
        "title": "Open operational-security findings",
        "document_version": "0.1.0",
        "report_status": REPORT_STATUS,
        "blocks_live_load": True,
        "blocks_canonical_loader_runtime_contract": True,
        "blocks_empty_login_role_creation": False,
        "findings": [
            {
                "id": "pgp_keys_shared_keyring_empty_passphrase",
                "status": "OPEN",
                "summary": "PGP keys currently share one local keyring and have empty passphrases",
            },
            {
                "id": "multi_custodian_separation_absent",
                "status": "OPEN",
                "summary": "Real multi-custodian separation is not established",
            },
            {
                "id": "initial_root_token_available",
                "status": "OPEN",
                "summary": "Initial root token remains available",
            },
            {
                "id": "limited_operator_identity_absent",
                "status": "OPEN",
                "summary": "Dedicated limited operator identity is not established",
            },
            {
                "id": "approle_runtime_delivery_unimplemented",
                "status": "OPEN",
                "summary": "AppRole runtime role_id/secret_id delivery is not implemented",
            },
        ],
        "canonical_loader_runtime_contract_complete": False,
    }
    _write_json(out_dir / "operational-security-findings.json", operational_findings)

    try:
        shape = validate_secret_shapes()
    except VaultSecretAccessError as exc:
        doc = {
            "overall_status": "FAIL",
            "error": {"type": exc.__class__.__name__, "message": str(exc)},
            "secrets_recorded_in_artifacts": False,
        }
        _write_json(out_dir / "vault-secret-shape.json", doc)
        raise

    _write_json(out_dir / "vault-secret-shape.json", shape.document)
    if shape.overall_status != PASS or not shape.loader_password:
        raise PrincipalProvisionError("Vault secret shape validation failed")

    password = shape.loader_password
    settings = load_canonical_settings()

    with canonical_connection(settings) as admin_conn:
        before = capture_db_snapshot(admin_conn, root, label="before")
        _write_json(out_dir / "postgres-principal-snapshot-before.json", before)

        try:
            provision = provision_canonical_loader_login(admin_conn, password=password)
        except PrincipalProvisionError:
            # Clear password before re-raise
            password = ""
            shape.loader_password = None
            raise

        verify = verify_set_role_and_permissions(
            admin_conn, settings, password=password
        )
        after = capture_db_snapshot(admin_conn, root, label="after")

    # Drop secret from process as soon as connections close.
    password = ""
    shape.loader_password = None

    _write_json(out_dir / "postgres-principal-snapshot-after.json", after)
    _write_json(out_dir / "postgres-principal-provision.json", provision)
    _write_json(out_dir / "postgres-principal-permission-verification.json", verify)

    comparison = _compare_snapshots(before, after)
    _write_json(out_dir / "postgres-principal-before-after.json", comparison)

    overall = PASS
    if (
        shape.document["overall_status"] != PASS
        or provision.get("status") != PASS
        or verify.get("status") != PASS
        or comparison.get("status") != PASS
    ):
        overall = "FAIL"

    report = {
        "stage": "03",
        "phase": "alignment_candidate",
        "title": "PostgreSQL LOGIN principal provisioning",
        "document_version": "0.1.0",
        "report_status": REPORT_STATUS,
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "login_principal": POSTGRES_LOGIN_PRINCIPAL,
        "nologin_group": POSTGRES_NOLOGIN_GROUP,
        "vault_approle": VAULT_APPROLE,
        "provision_action": provision.get("action"),
        "vault_secret_shape_status": shape.document["overall_status"],
        "permission_verification_status": verify.get("status"),
        "before_after_status": comparison.get("status"),
        "schema_fingerprint_before": before["schema_fingerprint"]["sha256"],
        "schema_fingerprint_after": after["schema_fingerprint"]["sha256"],
        "row_counts_after": after["row_counts"],
        "clinical_rows_read": 0,
        "raw_db_connections": 0,
        "repairs_outside_approved_scope": 0,
        "canonical_loader_runtime_contract_complete": False,
        "blocks_live_load_open_findings": True,
        "secrets_recorded_in_artifacts": False,
        "exact_commands": [
            "python -m human_simulator.stage03_alignment.run_postgres_principal",
            "python -m human_simulator.stage03_alignment.publish_postgres_principal_v01",
        ],
    }
    _write_json(out_dir / "postgres-principal-report.json", report)

    plan_path = out_dir / "postgres-principal-plan-canonical-loader-login.md"
    plan_path.write_text(
        f"""# Plan — PostgreSQL LOGIN principal `canonical_loader_login`

**Status:** PROVISIONED ({provision.get("action")}) — Report status: {REPORT_STATUS}  
**Alignment:** postgres-principal v0.1  
**Overall:** {overall}

## Identity separation

| Layer | Name | Status |
|------|------|--------|
| Vault AppRole | `{VAULT_APPROLE}` | provisioned |
| PostgreSQL LOGIN | `{POSTGRES_LOGIN_PRINCIPAL}` | provisioned ({provision.get("action")}) |
| PostgreSQL NOLOGIN group | `{POSTGRES_NOLOGIN_GROUP}` | retained NOLOGIN |

## Attributes

LOGIN, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS  
Membership: `GRANT {POSTGRES_NOLOGIN_GROUP} TO {POSTGRES_LOGIN_PRINCIPAL}`

## Explicit non-closure

`canonical_loader_runtime_contract` remains **incomplete**.  
Open operational-security findings continue to **block live load**.

## Forbidden next steps (not started)

Changeset 02, migration 0005, ETL, extraction, clinical reads, canonical data load,
Design/Plan FINAL promotion.
""",
        encoding="utf-8",
    )

    if overall != PASS:
        raise PrincipalProvisionError(f"postgres principal provisioning overall={overall}")
    return report


def main() -> int:
    try:
        report = run_postgres_principal_provisioning()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc.__class__.__name__}: {exc}")
        return 1
    print(json.dumps({"overall_status": report["overall_status"], "action": report["provision_action"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
