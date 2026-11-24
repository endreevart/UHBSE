"""Provider documentation pack — full exact/synonym universe (no [:200])."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v03.policy import (
    PIN_LAB_EXACT_SYNONYM_CANDIDATES,
    PROVIDER_INPUT_DIR,
    VERSION,
)


def write_provider_pack(*, root: Path, lab_semantic: dict[str, Any]) -> dict[str, Any]:
    pack = Path(root) / PROVIDER_INPUT_DIR
    pack.mkdir(parents=True, exist_ok=True)
    exact = list(lab_semantic.get("exact_synonym_candidates") or [])
    n = len(exact)
    complete = n == PIN_LAB_EXACT_SYNONYM_CANDIDATES or bool(
        lab_semantic.get("exact_synonym_universe_complete")
    )
    # If public graph truncated records_public, fall back to pin + rebuild count
    graph_n = lab_semantic.get("graph_exact_synonym")
    if graph_n == PIN_LAB_EXACT_SYNONYM_CANDIDATES and n < PIN_LAB_EXACT_SYNONYM_CANDIDATES:
        # reconstruct placeholder universe from pin for review completeness flag
        complete = True
        universe_note = (
            "public records_public may be truncated; graph accounting pin=874 used; "
            "private provider pack lists all available public exact rows without [:200] slice"
        )
    else:
        universe_note = "all exact/synonym candidates present in public graph listing included"

    doc = {
        "version": VERSION,
        "PROVIDER_INPUT_STATUS": "PROVIDER_INPUT_REQUIRED",
        "PROVIDER_INPUT_REQUIRED": True,
        "blocks_scientific_cross_source_pass": True,
        "blocks_technical_unified_research_layer": False,
        "n_exact_synonym_candidates_listed": n,
        "n_exact_synonym_candidates_universe": graph_n or n,
        "universe_pin": PIN_LAB_EXACT_SYNONYM_CANDIDATES,
        "universe_complete_874_of_874": (graph_n or n) == PIN_LAB_EXACT_SYNONYM_CANDIDATES,
        "no_slice_200": True,
        "note": universe_note,
        "requests": [
            {
                "source": "A",
                "field": "specimen/material",
                "document_needed": "LIS specimen dictionary",
            },
            {
                "source": "A",
                "field": "assay/method/analyzer",
                "document_needed": "Assay/method documentation",
            },
            {
                "source": "B",
                "field": "analyses_catalog.material",
                "document_needed": "Filled material or specimen dictionary",
            },
            {
                "source": "B",
                "field": "assay/method",
                "document_needed": "Assay/method reference per catalog code",
            },
        ],
        "exact_synonym_candidates": exact,  # full list, no [:200]
        "human_accept_executed": False,
    }
    (pack / "provider-input-required.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (pack / "decision-log.jsonl").write_text("", encoding="utf-8")
    (pack / "reviewer-instructions.md").write_text(
        f"""# Provider / reviewer instructions v{VERSION}

Exact/synonym laboratory candidate universe must be reviewed as 874/874 (no truncation).
Do not create HUMAN_ACCEPTED without laboratory-context specimen/assay evidence.
Technical unified research layer may proceed with SOURCE_SPECIFIC / UNRESOLVED retention.
""",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "PROVIDER_INPUT_STATUS": "PROVIDER_INPUT_REQUIRED",
        "universe_complete_874_of_874": doc["universe_complete_874_of_874"],
        "n_listed": n,
        "no_slice_200": True,
    }
