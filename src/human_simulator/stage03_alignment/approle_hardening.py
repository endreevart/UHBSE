"""AppRole hardening validation — exact numeric TTLs and policy set (v0.1.1)."""

from __future__ import annotations

from typing import Any

from human_simulator.stage03_alignment.vault_provider import VAULT_APPROLE

PASS = "PASS"
FAIL = "FAIL"

APPROLE_NAME = VAULT_APPROLE
APPROLE_POLICY = "uhbse-canonical-loader"
BIND_SECRET_ID = True
SECRET_ID_TTL = "5m"
SECRET_ID_NUM_USES = 1
TOKEN_TTL = "15m"
TOKEN_MAX_TTL = "1h"
TOKEN_POLICIES = (APPROLE_POLICY,)
TOKEN_TYPE = "service"
CIDR_BINDING = None
SECRET_ID_RESPONSE_WRAPPING_PATH = (
    f"auth/approle/role/{APPROLE_NAME}/secret-id"
)
WRAPPED_SECRET_ID_TTL = "2m"

EXPECTED = {
    "bind_secret_id": True,
    "secret_id_num_uses": 1,
    "secret_id_ttl_seconds": 300,
    "token_ttl_seconds": 900,
    "token_max_ttl_seconds": 3600,
    "token_type": "service",
    "token_no_default_policy": True,
    "token_policies": ["uhbse-canonical-loader"],
}

EXPECTED_APPROLE_CONFIG = {
    "bind_secret_id": BIND_SECRET_ID,
    "secret_id_ttl": SECRET_ID_TTL,
    "secret_id_num_uses": SECRET_ID_NUM_USES,
    "token_ttl": TOKEN_TTL,
    "token_max_ttl": TOKEN_MAX_TTL,
    "token_policies": list(TOKEN_POLICIES),
    "token_type": TOKEN_TYPE,
    "cidr_binding": CIDR_BINDING,
    "secret_id_response_wrapping_path": SECRET_ID_RESPONSE_WRAPPING_PATH,
    "wrapped_secret_id_ttl": WRAPPED_SECRET_ID_TTL,
}


def _as_seconds(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text.isdigit():
            return int(text)
        if text.endswith("s") and text[:-1].isdigit():
            return int(text[:-1])
        if text.endswith("m") and text[:-1].isdigit():
            return int(text[:-1]) * 60
        if text.endswith("h") and text[:-1].isdigit():
            return int(text[:-1]) * 3600
    return None


def validate_approle_observed(observed: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, str] = {}
    checks["bind_secret_id"] = (
        PASS if observed.get("bind_secret_id") is True else FAIL
    )
    checks["secret_id_num_uses"] = (
        PASS if observed.get("secret_id_num_uses") == 1 else FAIL
    )
    checks["secret_id_ttl"] = (
        PASS if _as_seconds(observed.get("secret_id_ttl")) == 300 else FAIL
    )
    checks["token_ttl"] = (
        PASS if _as_seconds(observed.get("token_ttl")) == 900 else FAIL
    )
    checks["token_max_ttl"] = (
        PASS if _as_seconds(observed.get("token_max_ttl")) == 3600 else FAIL
    )
    checks["token_type"] = (
        PASS if observed.get("token_type") == "service" else FAIL
    )
    # token_type=default is explicitly FAIL
    if observed.get("token_type") == "default":
        checks["token_type"] = FAIL
    checks["token_no_default_policy"] = (
        PASS if observed.get("token_no_default_policy") is True else FAIL
    )
    policies = list(observed.get("token_policies") or [])
    checks["token_policies_exact"] = (
        PASS if policies == ["uhbse-canonical-loader"] else FAIL
    )
    overall = PASS if all(v == PASS for v in checks.values()) else FAIL
    return {
        "approle": APPROLE_NAME,
        "expected": EXPECTED,
        "observed_sanitised": {
            k: observed.get(k)
            for k in (
                "bind_secret_id",
                "secret_id_num_uses",
                "secret_id_ttl",
                "token_ttl",
                "token_max_ttl",
                "token_type",
                "token_no_default_policy",
                "token_policies",
            )
            if k in observed
        },
        "checks": checks,
        "overall_status": overall,
        "forbidden_in_evidence": ["role_id", "secret_id", "wrapping_token", "vault_token"],
    }
