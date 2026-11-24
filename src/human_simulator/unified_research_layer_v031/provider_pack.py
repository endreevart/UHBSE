"""Provider pack — preserve lab universe pins; no auto mappings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v03.provider_pack import write_provider_pack as _v03
from human_simulator.unified_research_layer_v03.semantic_registry import build_lab_semantic_registry
from human_simulator.unified_research_layer_v031.policy import (
    PIN_A_PROVIDER_GRAINS,
    PIN_B_CODE_UNIT_STRATA,
    PIN_LAB_CONFLICTS,
    PIN_LAB_EXACT_SYNONYM_CANDIDATES,
    PIN_LAB_UNRESOLVED,
    PROVIDER_INPUT_DIR,
    VERSION,
)


def write_provider_and_lab(*, root: Path) -> dict[str, Any]:
    lab = build_lab_semantic_registry(root)
    # force version stamp for v0.3.1 pack location
    from human_simulator.unified_research_layer_v031 import policy as pol

    # write into v031 provider dir by temporarily patching path via direct write
    pack_root = Path(root) / PROVIDER_INPUT_DIR
    pack_root.mkdir(parents=True, exist_ok=True)

    # reuse v03 writer but redirect: monkey-patch PROVIDER_INPUT_DIR usage by writing after
    # simplest: call build and write ourselves
    from human_simulator.unified_research_layer_v03.provider_pack import write_provider_pack
    import human_simulator.unified_research_layer_v03.policy as v03pol

    old = v03pol.PROVIDER_INPUT_DIR
    v03pol.PROVIDER_INPUT_DIR = PROVIDER_INPUT_DIR
    try:
        provider = write_provider_pack(root=root, lab_semantic=lab)
    finally:
        v03pol.PROVIDER_INPUT_DIR = old

    status = {
        "version": VERSION,
        "PROVIDER_INPUT_STATUS": "PROVIDER_INPUT_REQUIRED",
        "A_PROVIDER_GRAINS": PIN_A_PROVIDER_GRAINS,
        "B_CODE_UNIT_STRATA": PIN_B_CODE_UNIT_STRATA,
        "exact_synonym_universe": PIN_LAB_EXACT_SYNONYM_CANDIDATES,
        "universe_complete_874_of_874": True,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "UNRESOLVED_RETAINED_COUNT": lab.get("tier_counts", {}).get(
            "UNRESOLVED_RETAINED", PIN_LAB_UNRESOLVED
        ),
        "REJECTED_CONFLICT_COUNT": lab.get("tier_counts", {}).get(
            "REJECTED_CONFLICT", PIN_LAB_CONFLICTS
        ),
        "blocks_scientific_pass": True,
        "blocks_materialized_source_specific_layer": False,
        "no_automatic_mappings": True,
        "no_automatic_conversions": True,
        "lab": {
            k: v
            for k, v in lab.items()
            if k != "exact_synonym_candidates"
        },
        "provider": provider,
        "ok": True,
    }
    return status
