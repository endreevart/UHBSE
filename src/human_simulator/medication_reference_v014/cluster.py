"""Strict provider-neutral concept clustering."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from human_simulator.medication_reference_v014.policy import (
    CAPABLE_LEVELS,
    REGRESSION_REJECTS,
    VERSION,
)


def cluster_key(row: dict[str, Any]) -> str:
    ings = ",".join(row.get("active_ingredient_set") or [])
    return "|".join(
        [
            ings or "no_ing",
            str(row.get("chemical_form") or "unknown_chem"),
            str(row.get("route") or "unknown_route"),
            str(row.get("dosage_form_family") or "unknown_form"),
            str(row.get("strength_stratum") or "unknown_strength"),
        ]
    )


def concept_id_for_key(key: str) -> str:
    return "pnconc_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:28]


def build_strict_clusters(
    classified: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rejected_mids = {a for a, _ in REGRESSION_REJECTS}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in classified:
        # still include in clusters for transparency, mark excluded if rejected medicine
        key = cluster_key(row)
        groups[key].append(row)

    clusters = []
    for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        levels = {m["typed_level"] for m in members}
        capable_members = [
            m
            for m in members
            if m["typed_level"] in CAPABLE_LEVELS
            and m["source_medicine_id"] not in rejected_mids
            and not m.get("hard_conflict")
            and m.get("strength_stratum") not in {"unknown_strength", "strength_conflict"}
            and m.get("typed_level") != "INGREDIENT_FAMILY_ONLY"
        ]
        # IFR without strength: only cluster together if all share unknown_strength
        # — those are NOT capable for authoritative gates requiring strength stratum
        family_only = all(m["typed_level"] == "INGREDIENT_FAMILY_ONLY" for m in members)
        cid = concept_id_for_key(key)
        parts = key.split("|")
        clusters.append(
            {
                "version": VERSION,
                "provider_neutral_concept_id": cid,
                "cluster_key": key,
                "ingredient_set": parts[0].split(",") if parts[0] != "no_ing" else [],
                "chemical_form": parts[1],
                "route": parts[2],
                "dosage_form_family": parts[3],
                "strength_stratum": parts[4],
                "n_source_medicines": len(members),
                "source_medicine_ids": [m["source_medicine_id"] for m in members],
                "typed_levels_present": sorted(levels),
                "capable_source_medicine_ids": [m["source_medicine_id"] for m in capable_members],
                "n_capable": len(capable_members),
                "family_only_cluster": family_only,
                "members": [
                    {
                        "source_medicine_id": m["source_medicine_id"],
                        "original_name": m.get("original_name"),
                        "typed_level": m["typed_level"],
                        "provider_concept_id": m.get("provider_concept_id"),
                        "provider_trade_name": m.get("provider_trade_name"),
                        "evidence_hash": m.get("evidence_hash"),
                        "n_episodes": int((m.get("episode_coverage") or {}).get("n_episodes") or 0),
                        "n_subjects": int((m.get("episode_coverage") or {}).get("n_subjects") or 0),
                    }
                    for m in members
                ],
                "why_merge_or_not": _explain(members, capable_members, family_only),
            }
        )
    clusters.sort(
        key=lambda c: (
            -c["n_capable"],
            -sum(m["n_episodes"] for m in c["members"]),
            c["provider_neutral_concept_id"],
        )
    )
    return clusters


def _explain(
    members: list[dict[str, Any]],
    capable: list[dict[str, Any]],
    family_only: bool,
) -> str:
    if family_only:
        return (
            "Family-only cluster — cannot form authoritative intervention concept; "
            "brands/supplements share only a broad nutrient/mineral/vitamin family."
        )
    if not capable:
        levels = sorted({m["typed_level"] for m in members})
        return (
            f"No capable members for decision set (levels={levels}); "
            "missing form/route/strength evidence or family-only / hard conflict."
        )
    trades = sorted({(m.get("provider_trade_name") or "") for m in capable})
    return (
        f"{len(capable)} capable source medicine(s) share ingredient×chem×route×form×strength; "
        f"provider trades={trades[:5]}; product identity not required for IFR cohort, "
        "but each source keeps provenance and original product id."
    )


def clusters_to_jsonable(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "n_clusters": len(clusters),
        "n_capable_clusters": sum(1 for c in clusters if c["n_capable"] > 0),
        "clusters": clusters,
        "rules": {
            "key": "ingredient_set × chemical_form × route × dosage_form_family × strength_stratum",
            "separate_chemical_forms": True,
            "separate_oral_topical": True,
            "separate_mono_combination": True,
            "unknown_strength_not_mixed_with_known": True,
            "fish_oil_neq_ethyl_esters": True,
            "family_only_not_authoritative": True,
        },
    }
