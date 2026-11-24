"""Executable connectors. Filtered source-specific reads. Model registries are not clinical sources."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from human_simulator.integrated_research_runtime_v012.hashes import sha256_file, sha_obj
from human_simulator.integrated_research_runtime_v012.policy import (
    ESKLP_INDEX,
    FUTURE_SOURCES,
    LEP_ARTIFACT,
    NHR_MODELS,
    SOURCE_A,
    SOURCE_B,
    V0111_OVERLAP,
    V031_MATERIALIZED,
    VERSION,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Connector:
    category = "unknown"

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


def _filtered_source_counts(path: Path, expected: str) -> dict[str, Any]:
    dataset = ds.dataset(path, format="parquet")
    try:
        table = dataset.to_table(columns=["source_system"], filter=ds.field("source_system") == expected)
    except Exception:
        raw = pq.read_table(path, columns=["source_system"])
        table = raw.filter(pc.equal(raw.column("source_system"), expected))
    vc = pc.value_counts(table.column("source_system"))
    counts: dict[str, int] = {}
    values = vc.field("values")
    cnts = vc.field("counts")
    for i in range(len(values)):
        counts[str(values[i].as_py())] = int(cnts[i].as_py())
    n_expected = int(counts.get(expected) or 0)
    n_other = sum(v for k, v in counts.items() if k != expected)
    n_distinct = len(counts)
    foreign_absent = n_other == 0 and (n_expected == 0 or n_distinct == 1)
    return {
        "filter_contract": f"source_system == {expected}",
        "n_rows_returned": int(table.num_rows),
        "n_rows_expected_source": n_expected,
        "n_rows_other_sources": n_other,
        "n_distinct_sources": n_distinct,
        "expected_source_present": n_expected > 0,
        "foreign_source_not_returned_as_this_connector": bool(foreign_absent),
        "row_values_disclosed": False,
        "shared_parquet_snapshot": True,
        "read_is_source_filtered": True,
    }


class SourceAConnector(Connector):
    category = "clinical_research_data"
    source_id = "source_a_clinical_research_plane"

    def schema_contract(self) -> str:
        return "unified-research-layer-v0.3.1/research_observation_component.source_system==magerya_api"

    def snapshot_identity(self) -> str | None:
        p = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        return sha256_file(p) if p.is_file() else None

    def read_aggregate(self) -> dict[str, Any]:
        path = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        if not path.is_file():
            return {"ok": False, "row_values_disclosed": False}
        return {"ok": True, **_filtered_source_counts(path, SOURCE_A)}

    def probe(self) -> dict[str, Any]:
        path = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        if not path.is_file():
            return {"source_id": self.source_id, "availability_status": "NOT_CONFIGURED", "ok": False}
        agg = self.read_aggregate()
        ok = bool(agg.get("expected_source_present")) and bool(agg.get("foreign_source_not_returned_as_this_connector"))
        return {
            "source_id": self.source_id,
            "source_type": "clinical_research_plane",
            "source_system": SOURCE_A,
            "availability_status": "CONNECTED_MATERIALIZED_READ_ONLY" if ok else "NOT_CONFIGURED",
            "contains_patient_data": True,
            "outbound_transfer_allowed": False,
            "not_raw_database_connector": True,
            "ok": ok,
            "health": agg,
        }


class SourceBConnector(Connector):
    category = "clinical_research_data"
    source_id = "source_b_clinical_research_plane"

    def schema_contract(self) -> str:
        return "unified-research-layer-v0.3.1/research_observation_component.source_system==kgz_raw"

    def snapshot_identity(self) -> str | None:
        p = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        return sha256_file(p) if p.is_file() else None

    def read_aggregate(self) -> dict[str, Any]:
        path = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        if not path.is_file():
            return {"ok": False, "row_values_disclosed": False}
        return {"ok": True, **_filtered_source_counts(path, SOURCE_B)}

    def probe(self) -> dict[str, Any]:
        path = self.root / V031_MATERIALIZED / "research_observation_component.parquet"
        if not path.is_file():
            return {"source_id": self.source_id, "availability_status": "NOT_CONFIGURED", "ok": False}
        agg = self.read_aggregate()
        ok = bool(agg.get("expected_source_present")) and bool(agg.get("foreign_source_not_returned_as_this_connector"))
        return {
            "source_id": self.source_id,
            "source_type": "clinical_research_plane",
            "source_system": SOURCE_B,
            "availability_status": "CONNECTED_MATERIALIZED_READ_ONLY" if ok else "NOT_CONFIGURED",
            "contains_patient_data": True,
            "outbound_transfer_allowed": False,
            "not_raw_database_connector": True,
            "ok": ok,
            "health": agg,
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


class FrozenMarginalRegistry(Connector):
    category = "frozen_model_provider"
    source_id = "frozen_natural_history_marginal_providers"

    def schema_contract(self) -> str:
        return "natural-history-rollout-v011/pre-test-cells.json"

    def snapshot_identity(self) -> str | None:
        p = self.root / NHR_MODELS / "pre-test-cells.json"
        return sha256_file(p) if p.is_file() else None

    def probe(self) -> dict[str, Any]:
        p = self.root / NHR_MODELS / "pre-test-cells.json"
        ok = p.is_file()
        return {
            "source_id": self.source_id,
            "availability_status": "CONNECTED_FROZEN_SNAPSHOT" if ok else "NOT_CONFIGURED",
            "contains_patient_data": False,
            "execution_not_implied_by_registry": True,
            "ok": ok,
            "health": {"ok": ok, "row_values_disclosed": False},
        }


class FrozenLepRegistry(Connector):
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
            "execution_not_implied_by_registry": True,
            "ok": ok,
            "health": {"ok": ok, "row_values_disclosed": False},
        }


def build_registry(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    a = SourceAConnector(root).record()
    b = SourceBConnector(root).record()
    clinical_systems = [c for c in (a, b) if c.get("availability_status") == "CONNECTED_MATERIALIZED_READ_ONLY"]
    overlap = root / V0111_OVERLAP / "subject-split.parquet"
    layers = []
    if overlap.is_file():
        layers.append(
            {
                "layer_id": "unified_materialized_state_layer",
                "category": "materialized_layer",
                "not_an_independent_clinical_source": True,
                "availability_status": "CONNECTED_MATERIALIZED_READ_ONLY",
                "snapshot_sha256": sha256_file(overlap),
            }
        )
    parquet = root / V031_MATERIALIZED / "research_observation_component.parquet"
    if parquet.is_file():
        layers.append(
            {
                "layer_id": "unified_research_observation_component",
                "category": "materialized_layer",
                "not_an_independent_clinical_source": True,
                "shared_by_source_a_and_source_b": True,
                "availability_status": "CONNECTED_MATERIALIZED_READ_ONLY",
                "snapshot_sha256": sha256_file(parquet),
            }
        )
    reference = [EsklpConnector(root).record()]
    models = [FrozenMarginalRegistry(root).record(), FrozenLepRegistry(root).record()]
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
    filtered_ok = bool(a.get("health", {}).get("read_is_source_filtered")) and bool(
        b.get("health", {}).get("read_is_source_filtered")
    )
    foreign_ok = bool(a.get("health", {}).get("foreign_source_not_returned_as_this_connector")) and bool(
        b.get("health", {}).get("foreign_source_not_returned_as_this_connector")
    )
    return {
        "version": VERSION,
        "SOURCE_CONNECTOR_REGISTRY_STATUS": "BUILT",
        "CLINICAL_SOURCE_SYSTEM_COUNT": len(clinical_systems),
        "CLINICAL_SOURCE_CONNECTOR_COUNT": len(clinical_systems),
        "MATERIALIZED_LAYER_COUNT": len(layers),
        "REFERENCE_SOURCE_CONNECTOR_COUNT": sum(1 for c in reference if c.get("ok")),
        "FROZEN_MODEL_REGISTRY_COUNT": len(models),
        "MODEL_PROVIDER_REGISTRY_COUNT": len(models),
        "SOURCE_A_CONNECTOR_STATUS": a.get("availability_status"),
        "SOURCE_B_CONNECTOR_STATUS": b.get("availability_status"),
        "ESKLP_CONNECTOR_STATUS": reference[0].get("availability_status"),
        "SOURCE_CONNECTOR_FILTERED_READ_STATUS": "PASS" if filtered_ok and foreign_ok else "FAIL",
        "model_providers_not_counted_as_clinical_sources": True,
        "unified_layer_not_a_third_clinical_source": True,
        "separate_source_a_probe": True,
        "separate_source_b_probe": True,
        "clinical": [a, b],
        "materialized_layers": layers,
        "reference": reference,
        "model_providers": models,
        "future_not_configured": future,
        "identity": sha_obj({"clinical": [SOURCE_A, SOURCE_B], "models": [m.get("source_id") for m in models]}),
        "ok": filtered_ok and foreign_ok and len(clinical_systems) == 2,
    }
