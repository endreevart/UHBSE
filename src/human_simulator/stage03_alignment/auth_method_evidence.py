"""Sanitised AppRole auth-method evidence checks (no secret values)."""

from __future__ import annotations

from typing import Any

PASS = "PASS"
FAIL = "FAIL"


def approle_auth_method_evidence(lookup_data: dict[str, Any]) -> dict[str, str]:
    """Require unambiguous AppRole evidence from Vault token lookup metadata.

    token_type alone (service/batch) is NOT sufficient for PASS.
    """
    display = str(lookup_data.get("display_name") or "")
    path = str(lookup_data.get("path") or "")
    meta = lookup_data.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    meta_blob = " ".join(str(v) for v in meta.values()).lower()
    # Common Vault AppRole signals (sanitised fields only)
    signals = []
    if "approle" in display.lower():
        signals.append("display_name")
    if "approle" in path.lower():
        signals.append("path")
    if "approle" in meta_blob or any(
        "approle" in str(k).lower() for k in meta
    ):
        signals.append("meta")
    # entity aliases / auth accessor hints when present without secret material
    for key in ("role_name", "role_id", "auth_method", "mount_type"):
        val = str(meta.get(key) or lookup_data.get(key) or "").lower()
        if "approle" in val or (key == "mount_type" and val == "approle"):
            signals.append(key)

    status = PASS if signals else FAIL
    return {
        "approle_auth_method_evidence": status,
        "signal_count": str(len(signals)),
        # signal *kinds* only — never role_id values
        "signal_kinds": ",".join(sorted(set(signals))) if signals else "",
    }


def evaluate_token_policy_checks(lookup_data: dict[str, Any]) -> dict[str, str]:
    """Policy + TTL + AppRole evidence checks for Agent token lookup."""
    policies = list(lookup_data.get("policies") or [])
    ttl = lookup_data.get("ttl")
    auth = approle_auth_method_evidence(lookup_data)
    checks = {
        "policies_exact": PASS if policies == ["uhbse-canonical-loader"] else FAIL,
        "default_policy_absent": PASS if "default" not in policies else FAIL,
        "ttl_in_bounds": PASS
        if isinstance(ttl, int) and 0 < ttl <= 3600
        else FAIL,
        "approle_path_hint": auth["approle_auth_method_evidence"],
    }
    return checks
