"""Phase 4 — hierarchical medication concepts (provenance-preserving)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v012.policy import HIERARCHY_VERSION, RUNTIME_DIR, VERSION


def _hid(prefix: str, *parts: str) -> str:
    blob = "|".join([prefix, *parts])
    return f"{prefix}_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def build_hierarchy_for_mapping(
    profile: dict[str, Any],
    mapping: dict[str, Any],
) -> dict[str, Any]:
    mid = str(profile["source_medicine_id"])
    ings = list(profile.get("active_ingredient_tokens") or [])
    form_fam = ",".join(sorted(profile.get("dosage_form_tokens") or [])[:3]) or "unknown_form"
    route = str(profile.get("route_hint") or "unknown")
    strength = json.dumps(profile.get("strength_tokens") or [], ensure_ascii=False, sort_keys=True)
    product_key = (
        mapping.get("provider_concept_id")
        or profile.get("guessed_trade_name")
        or mid
    )

    source_rec = _hid("srcmed", mid)
    product = _hid("product", str(product_key), route, form_fam)
    ing_set = _hid("ingset", ",".join(sorted(ings)) or "none")
    ing_form_route = _hid("ingformroute", ",".join(sorted(ings)) or "none", form_fam, route)
    strength_stratum = _hid("strength", ing_form_route, strength)
    exposure = _hid("exposure", mid, "appointment_date")

    return {
        "version": VERSION,
        "hierarchy_version": HIERARCHY_VERSION,
        "source_medicine_id": mid,
        "SourceMedicationRecord": {
            "id": source_rec,
            "source_medicine_id": mid,
            "original_name": profile.get("original_name"),
            "provenance": "source_a_medication_record",
        },
        "ProductConcept": {
            "id": product,
            "provider_concept_id": mapping.get("provider_concept_id"),
            "provider": mapping.get("provider"),
            "mapping_status": mapping.get("final_mapping_status"),
        },
        "IngredientSetConcept": {
            "id": ing_set,
            "ingredients": ings,
        },
        "IngredientFormRouteConcept": {
            "id": ing_form_route,
            "ingredients": ings,
            "form_family": form_fam,
            "route": route,
        },
        "StrengthStratum": {
            "id": strength_stratum,
            "strength_tokens": profile.get("strength_tokens"),
        },
        "RecordedExposureEvent": {
            "id": exposure,
            "event_timestamp_hypothesis": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
            "appointment_is_not_administration": True,
            "recorded_medication_association_neq_confirmed_administration": True,
            "neq_intervention": True,
            "neq_treatment_response": True,
            "neq_treatment_effect": True,
        },
    }


def build_and_write_hierarchy(
    root: Path,
    profiles: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
) -> Path:
    by_mid = {str(m["source_medicine_id"]): m for m in mappings}
    out = root / RUNTIME_DIR / "hierarchy" / "hierarchical-concepts.private.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for p in profiles:
            m = by_mid.get(str(p["source_medicine_id"])) or {}
            fh.write(
                json.dumps(build_hierarchy_for_mapping(p, m), ensure_ascii=False, default=str)
                + "\n"
            )
    return out
