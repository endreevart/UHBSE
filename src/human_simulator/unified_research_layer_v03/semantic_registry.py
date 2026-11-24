"""Semantic tier registries across domains — no automatic HUMAN_ACCEPTED."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v03.policy import (
    PIN_A_PROVIDER_GRAINS,
    PIN_B_CODE_UNIT_STRATA,
    PIN_LAB_EXACT_SYNONYM_CANDIDATES,
    VERSION,
)


def build_lab_semantic_registry(root: Path) -> dict[str, Any]:
    """Use published v0.2.1.1 public graph aggregates + private summary if present."""
    art = (
        Path(root)
        / "artifacts"
        / "stage-03-cross-source-laboratory-metadata-privacy-closure-v0.2.1.1"
    )
    graph_path = art / "cross-source-candidate-graph-public.json"
    rebuild = art / "candidate-graph-rebuild.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8")) if graph_path.is_file() else {}
    reb = json.loads(rebuild.read_text(encoding="utf-8")) if rebuild.is_file() else {}
    after = reb.get("after_v0211") or {}
    records = graph.get("records_public") or []

    tiers = Counter()
    for r in records:
        if r.get("hard_conflict"):
            tiers["REJECTED_CONFLICT"] += 1
        elif r.get("identity_level") in {
            "EXACT_ANALYTE_IDENTITY",
            "APPROVED_ANALYTE_SYNONYM",
        }:
            # candidates until domain evidence — not CROSS_SOURCE_ACCEPTED
            tiers["UNRESOLVED_RETAINED"] += 1
        elif r.get("candidate_class") == "NO_CANDIDATE_AFTER_EXHAUSTIVE_SEARCH":
            tiers["SOURCE_SPECIFIC_SUPPORTED"] += 1  # A grain retained source-specific
        else:
            tiers["UNRESOLVED_RETAINED"] += 1

    exact = [
        r
        for r in records
        if r.get("identity_level")
        in {"EXACT_ANALYTE_IDENTITY", "APPROVED_ANALYTE_SYNONYM"}
        and r.get("b_raw_code")
    ]
    return {
        "version": VERSION,
        "CROSS_SOURCE_LAB_MAPPING_STATUS": "PARTIAL_NO_ACCEPTED",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "CROSS_SOURCE_ACCEPTED_COUNT": 0,
        "n_exact_synonym_candidates": len(exact),
        "exact_synonym_universe_complete": len(exact)
        == PIN_LAB_EXACT_SYNONYM_CANDIDATES
        or after.get("n_exact_or_synonym_candidates") == PIN_LAB_EXACT_SYNONYM_CANDIDATES,
        "pin_exact_synonym": PIN_LAB_EXACT_SYNONYM_CANDIDATES,
        "graph_exact_synonym": after.get("n_exact_or_synonym_candidates") or len(exact),
        "A_PROVIDER_GRAINS": PIN_A_PROVIDER_GRAINS,
        "B_CODE_UNIT_STRATA": PIN_B_CODE_UNIT_STRATA,
        "tier_counts": dict(tiers),
        "specimen_assay_gaps_do_not_block_source_specific_retention": True,
        "scientific_comparability_separate_from_retention": True,
        "HUMAN_ACCEPTED_created": False,
        "ok": True,
        "exact_synonym_candidates": [
            {
                "mapping_id": r.get("mapping_id"),
                "a_outcome": r.get("a_outcome"),
                "a_unit": r.get("a_unit"),
                "b_raw_code": r.get("b_raw_code"),
                "b_unit": r.get("b_unit"),
                "identity_level": r.get("identity_level"),
                "candidate_class": r.get("candidate_class"),
                "semantic_tier": "UNRESOLVED_RETAINED",
            }
            for r in exact
        ],
    }


def build_domain_mapping_stub(domain: str, *, a_rels: list[str], b_rels: list[str]) -> dict[str, Any]:
    return {
        "domain": domain,
        "status": "SOURCE_SPECIFIC_REGISTRY_ONLY",
        "CROSS_SOURCE_ACCEPTED_COUNT": 0,
        "SOURCE_SPECIFIC_SUPPORTED_COUNT": len(a_rels) + len(b_rels),
        "UNRESOLVED_RETAINED_COUNT": 0,
        "REJECTED_CONFLICT_COUNT": 0,
        "a_relations": a_rels,
        "b_relations": b_rels,
        "HUMAN_ACCEPTED_created": False,
        "registry_entries": [
            {
                "source": "A" if r.startswith("magerya") or "magerya" in r else "B",
                "relation": r,
                "identity_status": "exact_source_identity",
                "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
            }
            for r in sorted(set(a_rels + b_rels))
        ],
    }


def build_semantic_layers(
    *, root: Path, a_inv: dict[str, Any], b_inv: dict[str, Any]
) -> dict[str, Any]:
    lab = build_lab_semantic_registry(root)

    def rels(inv: dict[str, Any], domain: str) -> list[str]:
        return list((inv.get("domains") or {}).get(domain, {}).get("source_relations") or [])

    diagnosis = build_domain_mapping_stub(
        "diagnoses",
        a_rels=rels(a_inv, "diagnoses"),
        b_rels=rels(b_inv, "diagnoses"),
    )
    medication = build_domain_mapping_stub(
        "medications",
        a_rels=rels(a_inv, "medications")
        + rels(a_inv, "prescriptions_recorded_medication_events"),
        b_rels=rels(b_inv, "medications")
        + rels(b_inv, "prescriptions_recorded_medication_events"),
    )
    procedure = build_domain_mapping_stub(
        "procedures_interventions",
        a_rels=rels(a_inv, "procedures_interventions"),
        b_rels=rels(b_inv, "procedures_interventions"),
    )
    recommendations = build_domain_mapping_stub(
        "recommendations",
        a_rels=rels(a_inv, "recommendations"),
        b_rels=rels(b_inv, "recommendations"),
    )

    totals = Counter()
    totals["CROSS_SOURCE_ACCEPTED"] = 0
    totals["SOURCE_SPECIFIC_SUPPORTED"] = (
        sum(
            int((a_inv.get("domains") or {}).get(d, {}).get("supported_rows") or 0)
            for d in (a_inv.get("domains") or {})
        )
        + sum(
            int((b_inv.get("domains") or {}).get(d, {}).get("supported_rows") or 0)
            for d in (b_inv.get("domains") or {})
        )
    )
    totals["UNRESOLVED_RETAINED"] = int(
        (lab.get("tier_counts") or {}).get("UNRESOLVED_RETAINED") or 0
    )
    totals["REJECTED_CONFLICT"] = int(
        (lab.get("tier_counts") or {}).get("REJECTED_CONFLICT") or 0
    )

    return {
        "version": VERSION,
        "CROSS_SOURCE_SEMANTIC_STATUS": "PARTIAL",
        "CROSS_SOURCE_LAB_MAPPING_STATUS": lab["CROSS_SOURCE_LAB_MAPPING_STATUS"],
        "CROSS_SOURCE_DIAGNOSIS_MAPPING_STATUS": "SOURCE_SPECIFIC_ONLY",
        "CROSS_SOURCE_MEDICATION_MAPPING_STATUS": "SOURCE_SPECIFIC_ONLY",
        "CROSS_SOURCE_PROCEDURE_MAPPING_STATUS": "SOURCE_SPECIFIC_ONLY",
        "lab": lab,
        "diagnosis": diagnosis,
        "medication": medication,
        "procedure": procedure,
        "recommendations": recommendations,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "SOURCE_SPECIFIC_SUPPORTED_COUNT": totals["SOURCE_SPECIFIC_SUPPORTED"],
        "UNRESOLVED_RETAINED_COUNT": totals["UNRESOLVED_RETAINED"],
        "REJECTED_CONFLICT_COUNT": totals["REJECTED_CONFLICT"],
        "HUMAN_ACCEPTED_created": False,
        "ok": lab.get("ok") is True,
    }
