"""Limited operator (userpass) live verification — sanitised evidence only."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from human_simulator.stage03_alignment.vault_secret_shape import FAIL, PASS

OPERATOR_USER = "uhbse-operator-limited"
POLICY_NAME = "uhbse-operator-limited"


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _vault(
    token: str,
    args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VAULT_TOKEN"] = token
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            "VAULT_ADDR=https://127.0.0.1:8200",
            "-e",
            "VAULT_CACERT=/vault/tls/ca.crt",
            "-e",
            "VAULT_TOKEN",
            "human-simulator-vault",
            "vault",
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )


def _vault_json(token: str, args: list[str]) -> dict[str, Any]:
    proc = _vault(token, args)
    if proc.returncode != 0:
        return {"_error": True, "_rc": proc.returncode}
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return {"_error": True, "_parse": True}


def login_limited_operator(repo: Path | None = None) -> str:
    root = repo or _root()
    script = root / "ops/vault/scripts/login-limited-operator.sh"
    proc = subprocess.run(
        [str(script)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("limited operator login failed")
    return proc.stdout.strip()


def revoke_token(token: str) -> bool:
    return _vault(token, ["token", "revoke-self"]).returncode == 0


def run_permission_tests(operator_token: str) -> dict[str, Any]:
    """Positive and negative permission tests; never records secret values."""
    positive: dict[str, str] = {}
    negative: dict[str, str] = {}

    # --- Positive ---
    health = _vault(operator_token, ["status", "-format=json"])
    positive["login_token_usable"] = PASS if health.returncode == 0 else FAIL

    lookup = _vault_json(operator_token, ["token", "lookup", "-format=json"])
    data = lookup.get("data") or {}
    policies = list(data.get("policies") or [])
    meta = data.get("meta") or {}
    display = str(data.get("display_name") or "")
    positive["policies_exact"] = (
        PASS if policies == [POLICY_NAME] else FAIL
    )
    positive["default_policy_absent"] = PASS if "default" not in policies else FAIL
    # userpass tokens typically use display_name like "userpass-<username>"
    path = str(data.get("path") or "")
    positive["audit_identity_present"] = (
        PASS
        if (
            OPERATOR_USER in display
            or OPERATOR_USER in str(meta)
            or "userpass" in display.lower()
            or "userpass" in path.lower()
        )
        else FAIL
    )
    ttl = data.get("ttl")
    if isinstance(ttl, str) and ttl.isdigit():
        ttl = int(ttl)
    positive["ttl_bounded"] = (
        PASS if isinstance(ttl, int) and 0 < ttl <= 3600 else FAIL
    )
    # Retain sanitised diagnostics without secrets
    positive["_lookup_ok"] = PASS if not lookup.get("_error") else FAIL

    role = _vault(operator_token, ["read", "auth/approle/role/uhbse-canonical-loader"])
    positive["approle_metadata_read"] = PASS if role.returncode == 0 else FAIL

    wrap = _vault(
        operator_token,
        [
            "write",
            "-format=json",
            "-wrap-ttl=2m",
            "-force",
            "auth/approle/role/uhbse-canonical-loader/secret-id",
        ],
    )
    wrap_ok = False
    if wrap.returncode == 0 and wrap.stdout.strip():
        try:
            doc = json.loads(wrap.stdout)
            wrap_ok = bool((doc.get("wrap_info") or {}).get("token"))
            # discard wrap token immediately — do not return it
            doc = {}
        except json.JSONDecodeError:
            wrap_ok = False
    positive["wrapped_secret_id_issuance"] = PASS if wrap_ok else FAIL

    pol = _vault(operator_token, ["policy", "read", POLICY_NAME])
    positive["own_policy_read"] = PASS if pol.returncode == 0 else FAIL

    # --- Negative ---
    root_write = _vault(
        operator_token,
        ["write", "sys/policy/root", "policy="],
    )
    negative["root_path_denied"] = PASS if root_write.returncode != 0 else FAIL

    # sudo-ish: enable auth
    sudo_auth = _vault(operator_token, ["auth", "enable", "ldap"])
    negative["sudo_auth_enable_denied"] = PASS if sudo_auth.returncode != 0 else FAIL

    audit = _vault(operator_token, ["audit", "enable", "file", "file_path=/tmp/x"])
    negative["audit_device_change_denied"] = PASS if audit.returncode != 0 else FAIL

    storage = _vault(operator_token, ["read", "sys/storage/raft/configuration"])
    # may be path not found or permission denied — must not succeed with data
    negative["storage_change_or_read_denied"] = (
        PASS if storage.returncode != 0 else FAIL
    )

    wild = _vault(operator_token, ["kv", "get", "-mount=uhbse", "canonical/hmac-subject-key"])
    negative["wildcard_secret_read_denied"] = PASS if wild.returncode != 0 else FAIL

    unrelated = _vault(operator_token, ["kv", "get", "-mount=uhbse", "canonical/loader-credential"])
    negative["unrelated_secret_read_denied"] = PASS if unrelated.returncode != 0 else FAIL

    pol_write = _vault(
        operator_token,
        [
            "write",
            "sys/policies/acl/evil-policy",
            'policy=path "sys/health" { capabilities = ["read"] }',
        ],
    )
    negative["policy_write_denied"] = PASS if pol_write.returncode != 0 else FAIL

    auth_disable = _vault(operator_token, ["auth", "disable", "approle"])
    negative["auth_method_change_denied"] = PASS if auth_disable.returncode != 0 else FAIL

    overall = (
        PASS
        if all(v == PASS for v in positive.values())
        and all(v == PASS for v in negative.values())
        else FAIL
    )
    return {
        "kind": "LIVE",
        "operator_identity": OPERATOR_USER,
        "auth_method": "userpass",
        "policy": POLICY_NAME,
        "positive": positive,
        "negative": negative,
        "overall_status": overall,
        "secrets_recorded": False,
        "token_policies_observed_count": len(policies),
        "display_name_sanitised": display[:80] if display else None,
    }


def provision_and_verify(repo: Path | None = None) -> dict[str, Any]:
    root = repo or _root()
    provision = root / "ops/vault/scripts/provision-limited-operator.sh"
    # Ensure executable
    provision.chmod(provision.stat().st_mode | 0o111)
    (root / "ops/vault/scripts/login-limited-operator.sh").chmod(
        (root / "ops/vault/scripts/login-limited-operator.sh").stat().st_mode | 0o111
    )
    (root / "ops/vault/scripts/logout-limited-operator.sh").chmod(
        (root / "ops/vault/scripts/logout-limited-operator.sh").stat().st_mode | 0o111
    )

    from human_simulator.stage03_alignment.token_lifecycle import isolated_vault_token

    with isolated_vault_token(root) as root_token:
        env = os.environ.copy()
        env["VAULT_TOKEN"] = root_token
        env["VAULT_ADDR"] = "https://127.0.0.1:8200"
        env["VAULT_CACERT"] = str(root / "ops/vault/tls/ca.crt")
        proc = subprocess.run(
            [str(provision)],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=120,
        )
        provision_ok = proc.returncode == 0

    token = ""
    try:
        token = login_limited_operator(root)
        results = run_permission_tests(token)
    finally:
        if token:
            revoke_token(token)
            token = ""

    results["provision_exit_zero"] = provision_ok
    if not provision_ok:
        results["overall_status"] = FAIL
        results["provision_stderr_tail"] = (proc.stderr or "")[-300:]
    return results
