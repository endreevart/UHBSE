"""Lifecycle helpers for medication-concept publication."""

from __future__ import annotations

from typing import Any

_FORBIDDEN_FINAL_PENDING = ("PENDING_WRITE", "PENDING_PUBLISH")


def assert_no_stale_pending(status_contract: dict[str, Any]) -> dict[str, Any]:
    errors = []
    for key, val in status_contract.items():
        if isinstance(val, str) and val in _FORBIDDEN_FINAL_PENDING:
            errors.append(f"{key}={val}")
    return {"ok": not errors, "errors": errors}


def assert_lifecycle_consistency(
    *,
    status_contract: dict[str, Any],
    attestation: dict[str, Any],
) -> dict[str, Any]:
    errors = []
    internal_pub = status_contract.get("PUBLICATION_INTEGRITY_STATUS")
    att_pub = attestation.get("PUBLICATION_INTEGRITY_STATUS")
    if internal_pub == "PASS" and att_pub == "PASS":
        errors.append("internal_and_attestation_both_PASS_forbidden")
    pending = assert_no_stale_pending(
        {
            k: v
            for k, v in status_contract.items()
            if k
            in (
                "pre_pack_manifest_status",
                "clean_staging_test_status",
                "content_verification_status",
            )
        }
    )
    if not pending["ok"]:
        errors.extend(pending["errors"])
    return {"ok": not errors, "errors": errors}
