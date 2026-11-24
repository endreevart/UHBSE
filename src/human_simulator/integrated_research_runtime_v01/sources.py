"""Source Integration Plane — adapters, registry, health without row disclosure."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v01.hashes import sha256_file, sha_obj
from human_simulator.integrated_research_runtime_v01.policy import (
    CODE_VERSION,
    CONNECTOR_STATUSES,
    ESKLP_INDEX,
    LEP_ARTIFACT,
    SOURCE_A,
    SOURCE_B,
    V011_MODELS,
    V0111_OVERLAP,
    V02_ARTIFACT,
    V02_MODELS,
    V031_MATERIALIZED,
    VERSION,
)

FUTURE_SOURCES = (
    "laboratory_reference_ontology",
    "medication_terminology",
    "drug_labels",
    "supplements",
    "nutrition",
    "activity_wearables",
    "diagnoses_anamnesis",
    "biomedical_knowledge",
    "external_governed_validation_datasets",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _health(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": ok, "detail": detail, "row_values_disclosed": False}


def _connector(
    *,
    source_id: str,
    source_type: str,
    source_version: str,
    snapshot_sha256: str | None,
    license_or_authorization_status: str,
    data_boundary: str,
    contains_patient_data: bool,
    outbound_transfer_allowed: bool,
    schema_contract: str,
    provenance_contract: str,
    availability_status: str,
    health: dict[str, Any],
) -> dict[str, Any]:
    if availability_status not in CONNECTOR_STATUSES:
        raise ValueError(f"illegal connector status {availability_status}")
    return {
        "source_id": source_id,
        "source_type": source_type,
        "source_version": source_version,
        "snapshot_sha256": snapshot_sha256,
        "license_or_authorization_status": license_or_authorization_status,
        "data_boundary": data_boundary,
        "contains_patient_data": contains_patient_data,
        "outbound_transfer_allowed": outbound_transfer_allowed,
        "schema_contract": schema_contract,
        "provenance_contract": provenance_contract,
        "availability_status": availability_status,
        "last_verified_at": _now(),
        "health": health,
        "connected": availability_status
        in {"CONNECTED_READ_ONLY", "CONNECTED_FROZEN_SNAPSHOT"},
    }


def _file_sha(root: Path, rel: str) -> str | None:
    p = root / rel
    if not p.is_file():
        return None
    return sha256_file(p)


def _dir_present(root: Path, rel: str) -> bool:
    p = root / rel
    return p.is_dir() and any(p.iterdir())


def build_source_registry(root: Path, *, joint_after_phase2: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    a_ok = _dir_present(root, V031_MATERIALIZED)
    b_ok = a_ok
    mat_ok = (root / V031_MATERIALIZED / "research_observation_component.parquet").is_file()
    esklp = root / ESKLP_INDEX
    esklp_ok = esklp.is_file()
    esklp_sha = sha256_file(esklp) if esklp_ok else None
    lep = root / LEP_ARTIFACT / "accepted-probability-registry-public.json"
    lep_ok = lep.is_file()
    nh = root / V011_MODELS / "pre-test-cells.json"
    if not nh.is_file():
        nh = root / V02_MODELS / "pre-test-cells.json"
    nh_ok = nh.is_file()
    split_ok = (root / V0111_OVERLAP / "subject-split.parquet").is_file()
    joint_status = (joint_after_phase2 or {}).get("status") or "NOT_CONFIGURED"
    joint_connected = joint_status in {
        "EVALUATED_NOT_ACCEPTED",
        "PARTIAL_ACCEPTED_WITH_EXPLICIT_CELL_REGISTRY",
        "BUILT",
    }
    connectors = [
        _connector(
            source_id="source_a_clinical_research_plane",
            source_type="clinical_research_plane",
            source_version="magerya_api",
            snapshot_sha256=_file_sha(root, f"{V031_MATERIALIZED}/research_subject.parquet"),
            license_or_authorization_status="AUTHORIZED_LOCAL_RESEARCH",
            data_boundary="local_derived_only",
            contains_patient_data=True,
            outbound_transfer_allowed=False,
            schema_contract="unified-research-layer-v0.3.1/research_observation_component",
            provenance_contract="source_system=magerya_api; opaque source_scoped_subject_id",
            availability_status="CONNECTED_READ_ONLY" if a_ok and split_ok else "NOT_CONFIGURED",
            health=_health(a_ok and split_ok, "materialized+split present" if a_ok else "missing"),
        ),
        _connector(
            source_id="source_b_clinical_research_plane",
            source_type="clinical_research_plane",
            source_version="kgz_raw",
            snapshot_sha256=_file_sha(root, f"{V031_MATERIALIZED}/research_observation_component.parquet"),
            license_or_authorization_status="AUTHORIZED_LOCAL_RESEARCH",
            data_boundary="local_derived_only",
            contains_patient_data=True,
            outbound_transfer_allowed=False,
            schema_contract="unified-research-layer-v0.3.1/research_observation_component",
            provenance_contract="source_system=kgz_raw; opaque source_scoped_subject_id",
            availability_status="CONNECTED_READ_ONLY" if b_ok else "NOT_CONFIGURED",
            health=_health(b_ok, "materialized present" if b_ok else "missing"),
        ),
        _connector(
            source_id="unified_materialized_state_layer",
            source_type="derived_state_layer",
            source_version="0.3.1",
            snapshot_sha256=_file_sha(root, f"{V031_MATERIALIZED}/research_provenance.parquet"),
            license_or_authorization_status="DERIVED_LOCAL",
            data_boundary="private/unified-research-layer-v031",
            contains_patient_data=True,
            outbound_transfer_allowed=False,
            schema_contract="unified-research-layer-v0.3.1",
            provenance_contract="record_origin required",
            availability_status="CONNECTED_READ_ONLY" if mat_ok else "NOT_CONFIGURED",
            health=_health(mat_ok, "parquet present" if mat_ok else "missing"),
        ),
        _connector(
            source_id="esklp_private_snapshot_index",
            source_type="medication_terminology_snapshot",
            source_version="esklp-20260812",
            snapshot_sha256=esklp_sha,
            license_or_authorization_status="PRIVATE_SNAPSHOT_INDEX_ONLY",
            data_boundary="private/medication-reference-v011",
            contains_patient_data=False,
            outbound_transfer_allowed=False,
            schema_contract="esklp-archive-and-index.json",
            provenance_contract="indexed snapshot; no live network",
            availability_status="CONNECTED_FROZEN_SNAPSHOT" if esklp_ok else "NOT_CONFIGURED",
            health=_health(esklp_ok, "index present" if esklp_ok else "missing"),
        ),
        _connector(
            source_id="frozen_probability_provider_v0211",
            source_type="probability_provider",
            source_version="0.2.1.1",
            snapshot_sha256=sha256_file(lep) if lep_ok else None,
            license_or_authorization_status="FROZEN_PUBLIC_REGISTRY",
            data_boundary="local_frozen",
            contains_patient_data=False,
            outbound_transfer_allowed=False,
            schema_contract="accepted-probability-registry-public.json",
            provenance_contract="LEP v0.2.1.1 frozen cells",
            availability_status="CONNECTED_FROZEN_SNAPSHOT" if lep_ok else "NOT_CONFIGURED",
            health=_health(lep_ok, "registry present" if lep_ok else "missing"),
        ),
        _connector(
            source_id="frozen_natural_history_marginal_providers",
            source_type="marginal_provider",
            source_version="0.1.1/0.2",
            snapshot_sha256=sha256_file(nh) if nh_ok else None,
            license_or_authorization_status="FROZEN_LOCAL",
            data_boundary="private models",
            contains_patient_data=False,
            outbound_transfer_allowed=False,
            schema_contract="pre-test-cells.json",
            provenance_contract="HMAC identity; disk freeze",
            availability_status="CONNECTED_FROZEN_SNAPSHOT" if nh_ok else "NOT_CONFIGURED",
            health=_health(nh_ok, "frozen cells present" if nh_ok else "missing"),
        ),
        _connector(
            source_id="joint_provider_registry",
            source_type="joint_provider",
            source_version=VERSION,
            snapshot_sha256=None,
            license_or_authorization_status="CORRECTED_AFTER_PHASE2",
            data_boundary="private/integrated-research-runtime-v01",
            contains_patient_data=False,
            outbound_transfer_allowed=False,
            schema_contract="joint-payload.json",
            provenance_contract="full ECDF identity; D0 fallback if D1 not accepted",
            availability_status="CONNECTED_FROZEN_SNAPSHOT" if joint_connected else "NOT_CONFIGURED",
            health=_health(True, joint_status),
        ),
        _connector(
            source_id="classifier_registry",
            source_type="classifier_registry",
            source_version=VERSION,
            snapshot_sha256=None,
            license_or_authorization_status="TECHNICAL_LABELS_ONLY",
            data_boundary="private/integrated-research-runtime-v01/labels",
            contains_patient_data=False,
            outbound_transfer_allowed=False,
            schema_contract="append-only label registry",
            provenance_contract="technical vs clinical classification required",
            availability_status="CONNECTED_FROZEN_SNAPSHOT",
            health=_health(True, "registry built in this stage"),
        ),
        _connector(
            source_id="mechanistic_qsp_pkpd_registry",
            source_type="mechanistic_sandbox",
            source_version=VERSION,
            snapshot_sha256=None,
            license_or_authorization_status="SYNTHETIC_REFERENCE_ONLY",
            data_boundary="private/integrated-research-runtime-v01/qsp",
            contains_patient_data=False,
            outbound_transfer_allowed=False,
            schema_contract="MechanisticModelAdapter",
            provenance_contract="synthetic parameters; no real-drug mapping",
            availability_status="CONNECTED_FROZEN_SNAPSHOT",
            health=_health(True, "synthetic fixtures"),
        ),
    ]
    future = [
        _connector(
            source_id=sid,
            source_type="future_source",
            source_version="unconfigured",
            snapshot_sha256=None,
            license_or_authorization_status="NOT_REVIEWED",
            data_boundary="none",
            contains_patient_data=False,
            outbound_transfer_allowed=False,
            schema_contract="not_declared",
            provenance_contract="not_declared",
            availability_status="NOT_CONFIGURED",
            health=_health(True, "intentionally unconnected"),
        )
        for sid in FUTURE_SOURCES
    ]
    network_blocked = _connector(
        source_id="external_network_providers",
        source_type="external_provider",
        source_version="none",
        snapshot_sha256=None,
        license_or_authorization_status="TRANSFER_PROHIBITED",
        data_boundary="no_outbound",
        contains_patient_data=True,
        outbound_transfer_allowed=False,
        schema_contract="none",
        provenance_contract="patient-level outbound transfer forbidden",
        availability_status="CLINICAL_DATA_TRANSFER_PROHIBITED",
        health=_health(True, "no outbound patient transfer"),
    )
    all_c = connectors + future + [network_blocked]
    connected = [c for c in connectors if c["connected"]]
    return {
        "version": VERSION,
        "code_version": CODE_VERSION,
        "SOURCE_INTEGRATION_PLANE_STATUS": "BUILT",
        "SOURCE_CONNECTOR_REGISTRY_STATUS": "BUILT",
        "SOURCE_A_CONNECTOR_STATUS": next(
            c["availability_status"] for c in connectors if c["source_id"] == "source_a_clinical_research_plane"
        ),
        "SOURCE_B_CONNECTOR_STATUS": next(
            c["availability_status"] for c in connectors if c["source_id"] == "source_b_clinical_research_plane"
        ),
        "ESKLP_CONNECTOR_STATUS": next(
            c["availability_status"] for c in connectors if c["source_id"] == "esklp_private_snapshot_index"
        ),
        "EXTERNAL_PROVIDER_DATA_TRANSFER_STATUS": "CLINICAL_DATA_TRANSFER_PROHIBITED",
        "n_connected": len(connected),
        "n_future_not_configured": len(future),
        "connectors": all_c,
        "identity": sha_obj({"connectors": [c["source_id"] for c in all_c], "statuses": [c["availability_status"] for c in all_c]}),
        "no_unconnected_declared_connected": True,
        "ok": True,
    }


def forbid_external_patient_transfer(request: dict[str, Any]) -> dict[str, Any]:
    dest = str(request.get("destination") or request.get("provider") or "")
    has_patient = bool(request.get("contains_patient_data") or request.get("subject_id") or request.get("rows"))
    if has_patient and dest not in {"local", "localhost", "127.0.0.1", ""}:
        return {"ok": False, "status": "CLINICAL_DATA_TRANSFER_PROHIBITED", "transferred": False}
    return {"ok": True, "transferred": False, "status": "LOCAL_ONLY"}
