"""Optional NIH DSLD adapter — candidates only; never auto-accept; offline-safe."""

from __future__ import annotations

from typing import Any


def dsld_adapter_status(*, configured: bool = False, network_enabled: bool = False) -> dict[str, Any]:
    return {
        "provider": "NIH_DSLD",
        "role": "dietary_supplement_candidate_generation_only",
        "configured": configured,
        "network_enabled": network_enabled,
        "us_product_is_not_identity_proof_for_ru_product": True,
        "auto_human_accepted_forbidden": True,
        "patient_level_data_forbidden": True,
        "mass_external_search_forbidden_unless_configured": True,
        "status": (
            "NOT_CONFIGURED_OFFLINE"
            if not configured
            else ("READY_FOR_CANDIDATE_GENERATION" if network_enabled else "CONFIGURED_OFFLINE")
        ),
    }


def generate_dsld_candidates(
    profile: dict[str, Any],
    *,
    configured: bool = False,
    network_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Stub: no network calls. Returns empty unless explicitly configured later."""
    _ = profile
    if not configured or not network_enabled:
        return []
    return []
