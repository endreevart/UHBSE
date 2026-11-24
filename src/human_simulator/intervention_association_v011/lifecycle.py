"""Publication lifecycle consistency helpers (no heavy publish imports)."""

from __future__ import annotations

from typing import Any


def assert_lifecycle_consistency(
    *,
    status_contract: dict[str, Any],
    attestation: dict[str, Any],
) -> dict[str, Any]:
    """Prevent final report contradictions between internal contract and attestation."""
    internal_pub = status_contract.get("PUBLICATION_INTEGRITY_STATUS")
    post_pack = status_contract.get("post_pack_publication_verification_status")
    att_pub = attestation.get("PUBLICATION_INTEGRITY_STATUS") or attestation.get(
        "publication_integrity_status"
    )
    errors = []
    if internal_pub == "PASS" and post_pack == "EXTERNAL_ATTESTATION_REQUIRED":
        errors.append("internal_contract_must_not_claim_post_pack_PASS")
    if att_pub == "PASS" and internal_pub == "PASS":
        errors.append("internal_and_attestation_both_PASS_forbidden_in_v011_lifecycle")
    return {"ok": not errors, "errors": errors}
