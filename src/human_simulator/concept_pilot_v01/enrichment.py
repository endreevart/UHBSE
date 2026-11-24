"""Non-blocking provider enrichment plan for high-impact gaps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.concept_pilot_v01.policy import ENRICHMENT_GAP_IDS, VERSION


def build_enrichment_plan(root: Path) -> dict[str, Any]:
    path = (
        root
        / "private/medication-reference-v014/review-pack/provider-gaps-by-episode-impact.json"
    )
    by_id: dict[str, dict[str, Any]] = {}
    if path.is_file():
        doc = json.loads(path.read_text(encoding="utf-8"))
        for item in doc.get("top_by_episode_impact") or []:
            by_id[str(item.get("source_medicine_id"))] = item

    plans = []
    for mid in ENRICHMENT_GAP_IDS:
        item = by_id.get(mid, {})
        plans.append(
            {
                "source_medicine_id": mid,
                "n_subjects": item.get("n_subjects"),
                "n_episodes": item.get("n_episodes"),
                "missing_ingredient_form_strength_evidence": list(
                    item.get("missing_fields") or []
                ),
                "necessary_provider_type": item.get("reference_needed") or "UNKNOWN",
                "potential_strict_cluster_after_enrichment": item.get("potential_if_filled")
                or "recompute_strict_cluster_after_evidence_upgrade",
                "typed_level": item.get("typed_level"),
                # deliberately omit original_name / private medication strings
            }
        )

    return {
        "version": VERSION,
        "PROVIDER_ENRICHMENT_PLAN_STATUS": "PLANNED_NON_BLOCKING",
        "blocks_technical_pilot": False,
        "no_automatic_external_fetch": True,
        "no_patient_level_data_sent": True,
        "plans": plans,
        "note": "Auxiliary artifact; absence of supplement provider does not block technical pilot.",
    }
