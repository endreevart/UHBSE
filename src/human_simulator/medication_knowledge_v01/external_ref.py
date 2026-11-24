"""Phase 2 — provider-neutral external medication-reference interface."""

from __future__ import annotations

from typing import Any

from human_simulator.medication_knowledge_v01.policy import VERSION

CANDIDATE_PROVIDERS = (
    "RxNorm/RxNav",
    "DailyMed/openFDA",
    "ATC/DDD",
    "PubChem",
    "ChEMBL",
)


def build_external_reference_status(*, configured_providers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Report external reference connectivity without purchasing or provisioning secrets."""
    configured = configured_providers or []
    connected = [p for p in configured if p.get("retrieval_status") == "VERIFIED"]
    if not connected:
        status = "NOT_CONFIGURED"
    else:
        status = "PARTIAL" if len(connected) < len(CANDIDATE_PROVIDERS) else "CONFIGURED"

    providers = []
    for name in CANDIDATE_PROVIDERS:
        match = next((p for p in configured if p.get("provider_name") == name), None)
        if match:
            providers.append(match)
        else:
            providers.append(
                {
                    "provider_name": name,
                    "dataset_api_version_or_retrieval_date": None,
                    "licensing_usage_status": "NOT_CONFIGURED",
                    "identifier_system": None,
                    "source_url_or_local_snapshot": None,
                    "content_hash": None,
                    "retrieval_status": "NOT_CONFIGURED",
                    "fields_used": [],
                    "fields_explicitly_not_trusted": ["all"],
                    "note": "Candidate only; not assumed connected",
                }
            )

    return {
        "version": VERSION,
        "EXTERNAL_MEDICATION_REFERENCE_STATUS": status,
        "candidate_providers": list(CANDIDATE_PROVIDERS),
        "providers": providers,
        "paid_api_purchase": False,
        "api_key_created": False,
        "secret_provisioning": False,
        "uncontrolled_bulk_download": False,
        "continues_with_source_derived_registry": True,
    }
