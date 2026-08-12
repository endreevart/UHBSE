#!/usr/bin/env python3
"""Synthetic child process supervised by Vault Agent (runtime-auth v0.1.1).

Reads secrets only from container-local tmpfs rendered by Agent templates.
Writes sanitised smoke result JSON — never tokens, digests, passwords, or raw ids.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

RUNTIME = Path("/run/uhbse-vault")
SECRETS = RUNTIME / "secrets"
RESULT = RUNTIME / "smoke-result.json"
SYNTHETIC_SUBJECT_ID = "synthetic-subject-runtime-smoke-001"


def _fail(msg: str, **extra: object) -> int:
    doc = {
        "status": "FAIL",
        "error": msg,
        "generated_at": datetime.now(UTC).isoformat(),
        **extra,
    }
    RESULT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return 1


def _materialise_env_secrets() -> None:
    """Vault Agent process supervisor injects secrets via env_template; write to tmpfs files."""
    SECRETS.mkdir(parents=True, exist_ok=True)
    mapping = {
        "UHBSE_HMAC_SUBJECT_KEY_JSON": SECRETS / "hmac-subject-key.json",
        "UHBSE_LOADER_CREDENTIAL_JSON": SECRETS / "loader-credential.json",
    }
    for env_name, path in mapping.items():
        raw = os.environ.get(env_name)
        if raw:
            path.write_text(raw, encoding="utf-8")
            path.chmod(0o600)
            os.environ.pop(env_name, None)


def main() -> int:
    _materialise_env_secrets()
    hmac_path = SECRETS / "hmac-subject-key.json"
    loader_path = SECRETS / "loader-credential.json"
    if not hmac_path.is_file() or not loader_path.is_file():
        return _fail("secret_templates_missing")

    # Wrapped SecretID must already have been removed by Agent.
    wrapped_still_present = (RUNTIME / "wrapped-secret-id").exists()

    hmac_doc = json.loads(hmac_path.read_text(encoding="utf-8"))
    loader_doc = json.loads(loader_path.read_text(encoding="utf-8"))

    key_version = str(hmac_doc.get("key_version"))
    algorithm = hmac_doc.get("algorithm")
    material = hmac_doc.get("key_material")
    username = loader_doc.get("username")
    password = loader_doc.get("password")

    checks: dict[str, str] = {}
    checks["wrapped_secret_id_removed"] = "FAIL" if wrapped_still_present else "PASS"
    checks["hmac_key_version_1"] = "PASS" if key_version in ("1", "1.0") else "FAIL"
    checks["hmac_algorithm"] = "PASS" if algorithm == "HMAC-SHA256" else "FAIL"
    checks["loader_username"] = (
        "PASS" if username == "canonical_loader_login" else "FAIL"
    )
    checks["loader_password_present"] = (
        "PASS" if isinstance(password, str) and len(password) >= 32 else "FAIL"
    )

    if not isinstance(material, str) or len(material) < 64:
        return _fail("hmac_material_invalid_shape", checks=checks)

    try:
        key = bytes.fromhex(material)
    except ValueError:
        return _fail("hmac_material_not_hex", checks=checks)

    d1 = hmac.new(key, SYNTHETIC_SUBJECT_ID.encode(), hashlib.sha256).digest()
    d2 = hmac.new(key, SYNTHETIC_SUBJECT_ID.encode(), hashlib.sha256).digest()
    checks["hmac_output_length_32"] = "PASS" if len(d1) == 32 else "FAIL"
    checks["hmac_deterministic"] = "PASS" if d1 == d2 else "FAIL"
    # Clear sensitive material ASAP
    material = None
    key = None
    d1 = d2 = None

    host = os.environ.get("CANONICAL_DB_HOST", "canonical-db")
    port = int(os.environ.get("CANONICAL_DB_PORT", "5432"))
    dbname = os.environ.get("CANONICAL_DB_NAME", "uhbse_canonical_dev")

    try:
        import psycopg
    except ImportError:
        return _fail("psycopg_missing", checks=checks)

    if not isinstance(password, str):
        return _fail("password_missing", checks=checks)

    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user="canonical_loader_login",
            password=password,
            connect_timeout=10,
            autocommit=True,
        )
    except Exception:  # noqa: BLE001
        password = None
        return _fail("postgres_connect_failed", checks=checks)
    finally:
        password = None

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT session_user, current_user")
            session_user, current_user = cur.fetchone()
            checks["session_user"] = (
                "PASS" if session_user == "canonical_loader_login" else "FAIL"
            )
            checks["current_user_before_set_role"] = (
                "PASS" if current_user == "canonical_loader_login" else "FAIL"
            )
            cur.execute("SET ROLE canonical_loader")
            cur.execute("SELECT current_user")
            after = cur.fetchone()[0]
            checks["current_user_after_set_role"] = (
                "PASS" if after == "canonical_loader" else "FAIL"
            )
            cur.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT'), "
                "has_table_privilege(current_user, %s, 'INSERT')",
                ("canonical_evidence.subject", "canonical_evidence.subject"),
            )
            sel, ins = cur.fetchone()
            checks["select_privilege"] = "PASS" if sel else "FAIL"
            checks["insert_privilege"] = "PASS" if ins else "FAIL"
            checks["insert_not_executed"] = "PASS"
            # Row counts while SET ROLE canonical_loader is active (login has no direct table grants).
            tables = [
                "source_system",
                "source_record",
                "subject",
                "subject_characteristic",
                "encounter",
                "observation",
                "observation_component",
            ]
            counts = {}
            for t in tables:
                cur.execute(f"SELECT count(*) FROM canonical_evidence.{t}")  # noqa: S608
                counts[t] = int(cur.fetchone()[0])
            checks["row_counts_zero"] = (
                "PASS" if all(v == 0 for v in counts.values()) else "FAIL"
            )
            cur.execute("RESET ROLE")
    except Exception as exc:  # noqa: BLE001
        conn.close()
        return _fail(
            "postgres_verification_failed",
            checks=checks,
            error_type=type(exc).__name__,
        )
    finally:
        conn.close()

    overall = "PASS" if all(v == "PASS" for v in checks.values()) else "FAIL"
    doc = {
        "status": overall,
        "generated_at": datetime.now(UTC).isoformat(),
        "auth_path": "vault_agent_process_supervisor",
        "synthetic_subject_label": "SYNTHETIC_RUNTIME_SMOKE",
        "checks": checks,
        "row_counts": counts,
        "clinical_rows_read": 0,
        "raw_db_connections": 0,
        "canonical_rows_written": 0,
        "secrets_recorded": False,
    }
    RESULT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
