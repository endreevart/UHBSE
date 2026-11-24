"""Lifecycle helpers."""

from __future__ import annotations

from typing import Any

_FORBIDDEN = ("PENDING_WRITE", "PENDING_PUBLISH")


def assert_lifecycle_consistency(
    *, status_contract: dict[str, Any], attestation: dict[str, Any]
) -> dict[str, Any]:
    errors = []
    if (
        status_contract.get("PUBLICATION_INTEGRITY_STATUS") == "PASS"
        and attestation.get("PUBLICATION_INTEGRITY_STATUS") == "PASS"
    ):
        errors.append("internal_and_attestation_both_PASS_forbidden")
    for k, v in status_contract.items():
        if k in (
            "pre_pack_manifest_status",
            "clean_staging_test_status",
            "content_verification_status",
        ) and isinstance(v, str) and v in _FORBIDDEN:
            errors.append(f"{k}={v}")
    return {"ok": not errors, "errors": errors}
