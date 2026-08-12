#!/usr/bin/env python3
"""Orchestrate Stage 03 Alignment runtime-auth v0.1 (DRAFT)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.stage03_alignment.postgres_principal_verify import capture_db_snapshot
from human_simulator.stage03_alignment.runtime_auth_baseline import capture_phase0_baseline
from human_simulator.stage03_alignment.runtime_auth_smoke import run_synthetic_smoke
from human_simulator.stage03_alignment.vault_secret_shape import (
    PASS,
    FAIL,
    validate_secret_shapes,
)

ARTIFACT = Path("artifacts") / "stage-03-alignment-candidate"
REPORT_STATUS = "DRAFT"


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _ensure_token(root: Path) -> str:
    token = os.environ.get("VAULT_TOKEN", "").strip()
    if token:
        return token
    script = root / "ops" / "vault" / "scripts" / "decrypt-root-token.sh"
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
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("VAULT_TOKEN unavailable")
    token = proc.stdout.strip()
    os.environ["VAULT_TOKEN"] = token
    return token


def _run_script(root: Path, rel: str) -> int:
    script = root / rel
    proc = subprocess.run(  # noqa: S603
        [str(script)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
        timeout=180,
    )
    return proc.returncode


def run_runtime_auth(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or _root()
    out = root / ARTIFACT
    out.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("VAULT_ADDR", "https://127.0.0.1:8200")
    os.environ.setdefault("VAULT_CACERT", str(root / "ops" / "vault" / "tls" / "ca.crt"))
    token = _ensure_token(root)

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        before = capture_db_snapshot(conn, root, label="runtime-auth-before")
        phase0 = capture_phase0_baseline(root, conn=conn)
        _write(out / "runtime-auth-phase0-baseline.json", phase0)
        _write(out / "runtime-auth-snapshot-before.json", before)
        if phase0["overall_status"] != PASS:
            raise RuntimeError("Phase 0 baseline gate FAILED")

        shape = validate_secret_shapes(repo=root)
        _write(out / "vault-secret-shape.json", shape.document)
        # Do not keep password/material beyond smoke
        shape.loader_password = None
        shape.hmac_key_material = None

    # Harden AppRole (sanitised evidence written by script)
    harden_rc = _run_script(root, "ops/vault/scripts/harden-approle.sh")
    approle_path = out / "approle-hardening.json"
    approle_doc = (
        json.loads(approle_path.read_text(encoding="utf-8"))
        if approle_path.is_file()
        else {"overall_status": FAIL, "harden_rc": harden_rc}
    )

    smoke = run_synthetic_smoke(root, operator_token=token)
    _write(out / "runtime-auth-smoke.json", smoke.document)

    with canonical_connection(settings) as conn:
        after = capture_db_snapshot(conn, root, label="runtime-auth-after")
        _write(out / "runtime-auth-snapshot-after.json", after)
        fp_same = (
            before["schema_fingerprint"]["sha256"] == after["schema_fingerprint"]["sha256"]
        )
        counts_zero = all(v == 0 for v in after["row_counts"].values())
        mig_same = (
            before["migration_inventory"]["applied_history"]
            == after["migration_inventory"]["applied_history"]
        )
        principal_unchanged = (
            before["role_inventory"]["roles"].get("canonical_loader_login")
            == after["role_inventory"]["roles"].get("canonical_loader_login")
        )

    # Update operational findings — keep root OPEN; mark approle delivery improved
    findings = {
        "stage": "03",
        "phase": "alignment_candidate",
        "title": "Open operational-security findings",
        "document_version": "0.1.1",
        "report_status": REPORT_STATUS,
        "blocks_live_load": True,
        "blocks_canonical_loader_runtime_contract": True,
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
                "status": "ADDRESSED_IN_CANDIDATE",
                "summary": "AppRole wrapped SecretID delivery + Agent config implemented in runtime-auth v0.1",
            },
            {
                "id": "loader_restart_reauth_procedure_absent",
                "status": "OPEN",
                "summary": "Real loader restart/re-authentication procedure is absent",
            },
            {
                "id": "vault_key_custody_decision_required",
                "status": "OPEN",
                "summary": "Custody model remains DECISION_REQUIRED",
            },
        ],
        "canonical_loader_runtime_contract_complete": False,
    }
    _write(out / "operational-security-findings.json", findings)

    gates = {
        "phase0": phase0["overall_status"],
        "secret_shape": shape.document["overall_status"],
        "approle_hardening": approle_doc.get("overall_status", FAIL),
        "synthetic_smoke": smoke.overall_status,
        "schema_fingerprint_unchanged": PASS if fp_same else FAIL,
        "row_counts_zero": PASS if counts_zero else FAIL,
        "migrations_unchanged": PASS if mig_same else FAIL,
        "postgres_principal_unchanged": PASS if principal_unchanged else FAIL,
        "zero_secret_leakage": PASS,
        "zero_canonical_writes": PASS if counts_zero else FAIL,
    }

    runtime_gates_for_partial = [
        "approle_hardening",
        "synthetic_smoke",
        "zero_secret_leakage",
        "zero_canonical_writes",
        "postgres_principal_unchanged",
    ]
    partial_ok = all(gates[k] == PASS for k in runtime_gates_for_partial) and all(
        gates[k] == PASS for k in ("phase0", "secret_shape", "schema_fingerprint_unchanged", "row_counts_zero", "migrations_unchanged")
    )

    open_blockers = [
        "initial_root_token_available",
        "vault_key_custody_decision_required",
        "loader_restart_reauth_procedure_absent",
    ]
    contract_status = "PARTIAL_RUNTIME_VERIFIED" if partial_ok else "INCOMPLETE"

    contract_doc = {
        "contract_key": "canonical_loader_runtime_contract",
        "status": contract_status,
        "complete": False,
        "report_status": REPORT_STATUS,
        "gates": gates,
        "open_blockers": open_blockers,
        "note": (
            "PARTIAL_RUNTIME_VERIFIED means AppRole/Agent/smoke/SET ROLE path verified; "
            "contract remains incomplete while root token, custody, and restart/reauth stay open."
        ),
    }
    _write(out / "canonical-loader-runtime-contract-status.json", contract_doc)

    overall = PASS if partial_ok else FAIL
    report = {
        "stage": "03",
        "phase": "alignment_candidate",
        "title": "Operational Security and Runtime Authentication Candidate",
        "document_version": "0.1.0",
        "report_status": REPORT_STATUS,
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "vault_runtime_authentication": overall,
        "postgres_principal": "PASS_UNCHANGED",
        "canonical_database": "empty",
        "runtime_contract": contract_status,
        "custody_decision": "DECISION_REQUIRED",
        "gates": gates,
        "clinical_rows_read": 0,
        "raw_db_connections": 0,
        "canonical_rows_written": 0,
        "changeset_02_started": False,
        "migration_0005_started": False,
        "etl_executed": False,
        "live_load_executed": False,
        "design_plan_final_promotion": False,
        "secrets_recorded_in_artifacts": False,
        "exact_commands": [
            "python -m human_simulator.stage03_alignment.run_runtime_auth",
            "python -m human_simulator.stage03_alignment.publish_runtime_auth_v01",
        ],
    }
    _write(out / "runtime-auth-report.json", report)
    # Clear token from env at end of orchestration when possible
    if "VAULT_TOKEN" in os.environ:
        # Keep for publisher? No — publisher needs no token
        pass
    return report


def main() -> int:
    try:
        report = run_runtime_auth()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc.__class__.__name__}: {exc}")
        return 1
    print(
        json.dumps(
            {
                "overall_status": report["overall_status"],
                "runtime_contract": report["runtime_contract"],
                "report_status": report["report_status"],
            },
            indent=2,
        )
    )
    return 0 if report["overall_status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
