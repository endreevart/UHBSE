"""Provider-neutral medication-reference snapshot adapters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_concept_v01.policy import (
    PROVIDER_SNAPSHOT_DIR,
    VERSION,
)

# Documented official RxNorm REST base (NIH) — used only if explicitly enabled
# with a local cache/snapshot; never invent undocumented endpoints.
RXNORM_DOCUMENTED_BASE = "https://rxnav.nlm.nih.gov/REST"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provider_record(
    *,
    provider_name: str,
    retrieval_status: str,
    identifier_system: str | None = None,
    source_url: str | None = None,
    snapshot_path: str | None = None,
    content_hash: str | None = None,
    retrieval_date: str | None = None,
    licensing: str | None = None,
    fields_used: list[str] | None = None,
    fields_not_trusted: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "provider_name": provider_name,
        "dataset_api_version_or_retrieval_date": retrieval_date,
        "licensing_usage_status": licensing or "NOT_CONFIGURED",
        "identifier_system": identifier_system,
        "source_url_or_local_snapshot": source_url or snapshot_path,
        "content_hash": content_hash,
        "retrieval_status": retrieval_status,
        "fields_used": fields_used or [],
        "fields_explicitly_not_trusted": fields_not_trusted
        or ["all_until_verified_snapshot"],
        "note": note,
    }


def discover_esklp_snapshot(root: Path) -> dict[str, Any]:
    """Accept only an official export / approved local snapshot under provider-snapshots.

    Does not invent API endpoints or scrape undocumented sources.
    """
    base = root / PROVIDER_SNAPSHOT_DIR / "esklp"
    manifest = base / "snapshot-manifest.json"
    if not manifest.is_file():
        return _provider_record(
            provider_name="ESKLP",
            retrieval_status="NOT_AVAILABLE",
            identifier_system="ESKLP",
            note=(
                "No approved local ESKLP/official Russian medication snapshot found at "
                f"{PROVIDER_SNAPSHOT_DIR}/esklp/. Place official export + "
                "snapshot-manifest.json to enable."
            ),
        )
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    data_rel = meta.get("data_file")
    if not data_rel:
        return _provider_record(
            provider_name="ESKLP",
            retrieval_status="NOT_AVAILABLE",
            note="snapshot-manifest.json missing data_file",
        )
    data_path = base / data_rel
    if not data_path.is_file():
        return _provider_record(
            provider_name="ESKLP",
            retrieval_status="NOT_AVAILABLE",
            note=f"declared data_file missing: {data_rel}",
        )
    h = _sha_file(data_path)
    expected = meta.get("sha256")
    if expected and expected != h:
        return _provider_record(
            provider_name="ESKLP",
            retrieval_status="HASH_MISMATCH",
            content_hash=h,
            note="snapshot sha256 does not match manifest",
        )
    return _provider_record(
        provider_name="ESKLP",
        retrieval_status="VERIFIED",
        identifier_system="ESKLP",
        source_url=meta.get("source_url"),
        snapshot_path=str(data_path.relative_to(root)),
        content_hash=h,
        retrieval_date=meta.get("retrieval_date"),
        licensing=meta.get("licensing_usage_status", "LOCAL_SNAPSHOT"),
        fields_used=list(meta.get("fields_used") or []),
        fields_not_trusted=list(meta.get("fields_explicitly_not_trusted") or []),
        note=meta.get("note"),
    )


def discover_rxnorm_snapshot(root: Path) -> dict[str, Any]:
    """Optional RxNorm/RxNav — local snapshot or documented API cache only.

    Does not purchase keys, scrape, or send patient-level data.
    """
    base = root / PROVIDER_SNAPSHOT_DIR / "rxnorm"
    manifest = base / "snapshot-manifest.json"
    if not manifest.is_file():
        return _provider_record(
            provider_name="RxNorm",
            retrieval_status="NOT_AVAILABLE",
            identifier_system="RXCUI",
            source_url=RXNORM_DOCUMENTED_BASE,
            note=(
                "Optional. No local RxNorm snapshot at "
                f"{PROVIDER_SNAPSHOT_DIR}/rxnorm/. "
                f"Documented API base: {RXNORM_DOCUMENTED_BASE}. "
                "Absence does not block Source A registry."
            ),
        )
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    data_rel = meta.get("data_file")
    data_path = base / data_rel if data_rel else None
    if data_path is None or not data_path.is_file():
        return _provider_record(
            provider_name="RxNorm",
            retrieval_status="NOT_AVAILABLE",
            identifier_system="RXCUI",
            source_url=RXNORM_DOCUMENTED_BASE,
            note="manifest present but data_file missing",
        )
    h = _sha_file(data_path)
    expected = meta.get("sha256")
    if expected and expected != h:
        return _provider_record(
            provider_name="RxNorm",
            retrieval_status="HASH_MISMATCH",
            identifier_system="RXCUI",
            content_hash=h,
        )
    return _provider_record(
        provider_name="RxNorm",
        retrieval_status="VERIFIED",
        identifier_system="RXCUI",
        source_url=meta.get("source_url") or RXNORM_DOCUMENTED_BASE,
        snapshot_path=str(data_path.relative_to(root)),
        content_hash=h,
        retrieval_date=meta.get("retrieval_date"),
        licensing=meta.get("licensing_usage_status", "LOCAL_SNAPSHOT"),
        fields_used=list(meta.get("fields_used") or ["RXCUI"]),
        fields_not_trusted=list(
            meta.get("fields_explicitly_not_trusted")
            or ["adverse_event_causality"]
        ),
    )


def build_provider_manifest(root: Path) -> dict[str, Any]:
    esklp = discover_esklp_snapshot(root)
    rxnorm = discover_rxnorm_snapshot(root)
    dailymed = _provider_record(
        provider_name="DailyMed",
        retrieval_status="DEFERRED",
        note="Downstream enrichment only after reliable concept ID/name match",
    )
    openfda = _provider_record(
        provider_name="openFDA",
        retrieval_status="DEFERRED",
        fields_not_trusted=["adverse_event_as_causal_risk"],
        note="Adverse-event reports are not proof of causal risk",
    )
    verified = [
        p
        for p in (esklp, rxnorm)
        if p.get("retrieval_status") == "VERIFIED"
    ]
    if verified:
        status = "PARTIAL" if len(verified) < 2 else "CONFIGURED"
    else:
        status = "NOT_AVAILABLE"

    return {
        "version": VERSION,
        "DRUG_REFERENCE_PROVIDER_STATUS": status,
        "providers": [esklp, rxnorm, dailymed, openfda],
        "paid_api_purchase": False,
        "api_key_created": False,
        "secret_provisioning": False,
        "undocumented_bulk_download": False,
        "commercial_drugbank": False,
        "patient_level_data_sent_externally": False,
        "llm_mappings_remain": "LLM_CANDIDATE_ONLY",
        "continues_without_provider": True,
    }
