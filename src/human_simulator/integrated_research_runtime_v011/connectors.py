"""Executable connector contracts. Clinical / reference / model registries separated."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.compute as pc
import pyarrow.parquet as pq

from human_simulator.integrated_research_runtime_v011.hashes import sha256_file, sha_obj
from human_simulator.integrated_research_runtime_v011.policy import (
    ESKLP_INDEX,
    LEP_ARTIFACT,
    SOURCE_A,
    SOURCE_B,
    V0111_OVERLAP,
    V02_MODELS,
    V031_MATERIALIZED,
    VERSION,
)

FUTURE_SOURCES = (
    "laboratory_reference_ontology",
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


def _agg_source_counts(path: Path, expected: str) -> dict[str, Any]:
    table = pq.read_table(path, columns=["source_system"])
    vc = pc.value_counts(table.column("source_system"))
    counts: dict[str, int] = {}
    values = vc.field("values")
    cnts = vc.field("counts")
    for i in range(len(values)):
        counts[str(values[i].as_py())] = int(cnts[i].as_py())
    n_expected = int(counts.get(expected) or 0)
    n_other = sum(v for k, v in counts.items() if k != expected)
    return {
        "n_rows_expected_source": n_expected,
        "n_rows_other_sources": n_other,
        "n_distinct_sources": len(counts),
        "expected_source_present": n_expected > 0,
        "foreign_source_not_returned_as_this_connector": True,
        "row_values_disclosed": False,
    }


class Connector:
    category: str = "unknown"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def probe(self) -> dict[str, Any]:
        raise NotImplementedError

    def schema_contract(self) -> str:
        raise NotImplementedError

    def snapshot_identity(self) -> str | None:
        return None

    def health_check(self) -> dict[str, Any]:
        return self.probe()

    def read_aggregate(self) -> dict[str, Any]:
        return {"ok": True, "row_values_disclosed": False}

    def provenance(self) -> dict[str, Any]:
        return {"category": self.category}

    def close(self) -> None:
        return None

    def record(self) -> dict[str, Any]:
        p = self.probe()
        return {
            **p,
            "schema_contract": self.schema_contract(),
            "snapshot_sha256": self.snapshot_identity(),
            "provenance": self.provenance(),
            "last_verified_at": _now(),
            "category": self.category,
        }


class SourceAConnector(Connector):
    category = "clinical_research_data"
    source_id = "source_a_clinical_research_plane"

    def schema_contract(self) -> str:
        return "unified-research-layer-v0.3.1/research_observation_component.source_system"

    def snapshot_identity(self) -> str | None:
        p = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        return sha256_file(p) if p.is_file() else None

    def probe(self) -> dict[str, Any]:
        path = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        if not path.is_file():
            return {
                "source_id": self.source_id,
                "availability_status": "NOT_CONFIGURED",
                "ok": False,
            }
        agg = _agg_source_counts(path, SOURCE_A)
        ok = bool(agg["expected_source_present"])
        return {
            "source_id": self.source_id,
            "source_type": "clinical_research_plane",
            "availability_status": "CONNECTED_MATERIALIZED_READ_ONLY" if ok else "NOT_CONFIGURED",
            "contains_patient_data": True,
            "outbound_transfer_allowed": False,
            "not_raw_database_connector": True,
            "ok": ok,
            "health": {"ok": ok, "row_values_disclosed": False, **agg},
        }


class SourceBConnector(Connector):
    category = "clinical_research_data"
    source_id = "source_b_clinical_research_plane"

    def schema_contract(self) -> str:
        return "unified-research-layer-v0.3.1/research_observation_component.source_system"

    def snapshot_identity(self) -> str | None:
        p = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        return sha256_file(p) if p.is_file() else None

    def probe(self) -> dict[str, Any]:
        path = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        if not path.is_file():
            return {"source_id": self.source_id, "availability_status": "NOT_CONFIGURED", "ok": False}
        agg = _agg_source_counts(path, SOURCE_B)
        ok = bool(agg["expected_source_present"])
        return {
            "source_id": self.source_id,
            "source_type": "clinical_research_plane",
            "availability_status": "CONNECTED_MATERIALIZED_READ_ONLY" if ok else "NOT_CONFIGURED",
            "contains_patient_data": True,
            "outbound_transfer_allowed": False,
            "not_raw_database_connector": True,
            "ok": ok,
            "health": {"ok": ok, "row_values_disclosed": False, **agg},
        }


class EsklpConnector(Connector):
    category = "reference_knowledge"
    source_id = "esklp_private_snapshot_index"

    def schema_contract(self) -> str:
        return "esklp-archive-and-index.json"

    def snapshot_identity(self) -> str | None:
        p = self.root / ESKLP_INDEX
        return sha256_file(p) if p.is_file() else None

    def probe(self) -> dict[str, Any]:
        p = self.root / ESKLP_INDEX
        ok = p.is_file()
        return {
            "source_id": self.source_id,
            "availability_status": "CONNECTED_FROZEN_SNAPSHOT" if ok else "NOT_CONFIGURED",
            "contains_patient_data": False,
            "scientifically_usable_medication_mapping": False,
            "ok": ok,
            "health": {"ok": ok, "row_values_disclosed": False, "index_present": ok},
        }


class FrozenMarginalProvider(Connector):
    category = "frozen_model_provider"
    source_id = "frozen_natural_history_marginal_providers"

    def schema_contract(self) -> str:
        return "pre-test-cells.json / synthetic P0 fixture"

    def snapshot_identity(self) -> str | None:
        p = self.root / V02_MODELS / "pre-test-cells.json"
        return sha256_file(p) if p.is_file() else None

    def probe(self) -> dict[str, Any]:
        p = self.root / V02_MODELS / "pre-test-cells.json"
        ok = p.is_file()
        return {
            "source_id": self.source_id,
            "availability_status": "CONNECTED_FROZEN_SNAPSHOT" if ok else "NOT_CONFIGURED",
            "contains_patient_data": False,
            "ok": ok,
            "health": {"ok": ok, "row_values_disclosed": False},
        }


class FrozenProbabilityProvider(Connector):
    category = "frozen_model_provider"
    source_id = "frozen_probability_provider_v0211"

    def schema_contract(self) -> str:
        return "accepted-probability-registry-public.json"

    def snapshot_identity(self) -> str | None:
        p = self.root / LEP_ARTIFACT / "accepted-probability-registry-public.json"
        return sha256_file(p) if p.is_file() else None

    def probe(self) -> dict[str, Any]:
        p = self.root / LEP_ARTIFACT / "accepted-probability-registry-public.json"
        ok = p.is_file()
        return {
            "source_id": self.source_id,
            "availability_status": "CONNECTED_FROZEN_SNAPSHOT" if ok else "NOT_CONFIGURED",
            "ok": ok,
            "health": {"ok": ok, "row_values_disclosed": False},
        }


def build_registry(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    clinical = [SourceAConnector(root).record(), SourceBConnector(root).record()]
    overlap = root / V0111_OVERLAP / "subject-split.parquet"
    if overlap.is_file():
        clinical.append(
            {
                "source_id": "unified_materialized_state_layer",
                "category": "clinical_research_data",
                "availability_status": "CONNECTED_MATERIALIZED_READ_ONLY",
                "contains_patient_data": True,
                "outbound_transfer_allowed": False,
                "ok": True,
                "schema_contract": "unified-research-layer-v0.3.1",
                "snapshot_sha256": sha256_file(overlap),
            }
        )
    reference = [EsklpConnector(root).record()]
    models = [FrozenMarginalProvider(root).record(), FrozenProbabilityProvider(root).record()]
    future = [
        {
            "source_id": sid,
            "category": "reference_knowledge",
            "availability_status": "NOT_CONFIGURED",
            "connected": False,
            "ok": True,
            "health": {"ok": True, "detail": "intentionally unconnected"},
        }
        for sid in FUTURE_SOURCES
    ]
    n_clinical_connected = sum(
        1
        for c in clinical
        if c.get("availability_status") in {"CONNECTED_MATERIALIZED_READ_ONLY", "CONNECTED_READ_ONLY", "CONNECTED_FROZEN_SNAPSHOT"}
    )
    return {
        "version": VERSION,
        "SOURCE_CONNECTOR_REGISTRY_STATUS": "BUILT",
        "CLINICAL_SOURCE_CONNECTOR_COUNT": n_clinical_connected,
        "REFERENCE_SOURCE_CONNECTOR_COUNT": sum(1 for c in reference if c.get("ok")),
        "MODEL_PROVIDER_REGISTRY_COUNT": len(models),
        "SOURCE_A_CONNECTOR_STATUS": clinical[0].get("availability_status"),
        "SOURCE_B_CONNECTOR_STATUS": clinical[1].get("availability_status"),
        "ESKLP_CONNECTOR_STATUS": reference[0].get("availability_status"),
        "model_providers_not_counted_as_clinical_sources": True,
        "separate_source_a_probe": True,
        "separate_source_b_probe": True,
        "clinical": clinical,
        "reference": reference,
        "model_providers": models,
        "future_not_configured": future,
        "identity": sha_obj({"clinical": [c.get("source_id") for c in clinical], "models": [m.get("source_id") for m in models]}),
        "ok": True,
    }
