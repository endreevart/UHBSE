"""Hierarchical readiness with acceptance levels — gates unchanged."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.models import load_episodes, split_episodes
from human_simulator.medication_reference_v013.acceptance import (
    latest_v013_by_medicine,
    scientifically_usable_accepted,
)
from human_simulator.medication_reference_v013.policy import (
    EPISODE_JSONL,
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    RUNTIME_DIR,
    V01_COHORTS,
    VERSION,
)


def _index_by_medicine(
    episodes_by_split: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    out: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"train": [], "validation": [], "test": []}
    )
    for sp, rows in episodes_by_split.items():
        for e in rows:
            out[str(e["medicine_id"])][sp].append(e)
    return out


def _grain_stats(
    medicine_ids: set[str],
    *,
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    outcome: str,
    unit: str,
    split_meta: dict[str, Any],
) -> dict[str, Any]:
    cohort: list[dict[str, Any]] = []
    by_split = {"train": [], "validation": [], "test": []}
    for mid in medicine_ids:
        for sp in ("train", "validation", "test"):
            for e in by_med.get(mid, {}).get(sp, []):
                if e.get("outcome") == outcome and e.get("unit") == unit:
                    by_split[sp].append(e)
                    cohort.append(e)
    subjects = {e["opaque_subject_key"] for e in cohort}
    test_subjects = {e["opaque_subject_key"] for e in by_split["test"]}
    gates = {
        "min_subjects": len(subjects) >= GATE_MIN_SUBJECTS,
        "min_episodes": len(cohort) >= GATE_MIN_EPISODES,
        "min_test_subjects": len(test_subjects) >= GATE_MIN_TEST_SUBJECTS,
        "subject_disjoint_split": bool(split_meta.get("zero_subject_overlap")),
        "no_identity_or_locator_overlap": bool(
            split_meta.get("zero_subject_overlap")
            and split_meta.get("zero_episode_overlap")
            and split_meta.get("zero_locator_overlap")
        ),
    }
    blockers = [k for k, ok in gates.items() if not ok]
    return {
        "outcome": outcome,
        "unit": unit,
        "n_episodes": len(cohort),
        "n_subjects": len(subjects),
        "n_test_subjects": len(test_subjects),
        "blockers": blockers,
        "ready": not blockers,
    }


def _eval_groups(
    groups: dict[str, set[str]],
    *,
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    split_meta: dict[str, Any],
    layer: str,
    allow_ready: bool,
) -> list[dict[str, Any]]:
    out = []
    for key, mids in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        grains = []
        for outcome, unit in V01_COHORTS:
            g = _grain_stats(
                mids, by_med=by_med, outcome=outcome, unit=unit, split_meta=split_meta
            )
            grains.append(g)
        would = [g for g in grains if g["ready"]]
        out.append(
            {
                "layer": layer,
                "group_key": key,
                "source_medicine_ids": sorted(mids),
                "n_source_medicines": len(mids),
                "n_grains_passing_gates": len(would),
                "grains": [
                    {
                        "outcome": g["outcome"],
                        "unit": g["unit"],
                        "n_episodes": g["n_episodes"],
                        "n_subjects": g["n_subjects"],
                        "n_test_subjects": g["n_test_subjects"],
                        "blockers": g["blockers"],
                    }
                    for g in grains
                ],
                "READY": bool(allow_ready and would),
                "provisional_only": not allow_ready,
            }
        )
    return out


def run_acceptance_readiness(
    root: Path,
    *,
    omega3_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    episodes = load_episodes(root / EPISODE_JSONL)
    split = split_episodes(episodes)
    by_med = _index_by_medicine(split["episodes_by_split"])
    split_meta = {k: v for k, v in split.items() if k != "episodes_by_split"}

    usable = scientifically_usable_accepted(root)
    latest = latest_v013_by_medicine(root)

    # A. Product level — only PRODUCT_IDENTITY_ACCEPTED usable
    product_groups: dict[str, set[str]] = defaultdict(set)
    for item in usable.get("items") or []:
        if item.get("decision") != "PRODUCT_IDENTITY_ACCEPTED":
            continue
        key = str(item.get("candidate_id") or item.get("provider_neutral_concept_id"))
        product_groups[key].add(str(item["source_medicine_id"]))

    # B. Ingredient/form — INGREDIENT_FORM_ROUTE_ACCEPTED
    ifr_groups: dict[str, set[str]] = defaultdict(set)
    for item in usable.get("items") or []:
        if item.get("decision") != "INGREDIENT_FORM_ROUTE_ACCEPTED":
            continue
        key = str(item.get("provider_neutral_concept_id") or item.get("candidate_id"))
        ifr_groups[key].add(str(item["source_medicine_id"]))

    # C. Family sensitivity — exploratory from omega3 cards / family decisions
    family_groups: dict[str, set[str]] = defaultdict(set)
    for c in omega3_cards:
        if c.get("eligibility", {}).get("INGREDIENT_FAMILY_ONLY") or c.get(
            "provider_neutral_concept"
        ) in {
            "omega_3_fatty_acids_unspecified",
            "epa_dha_combination_form_unspecified",
        }:
            family_groups[str(c.get("provider_neutral_concept"))].add(
                str(c["source_medicine_id"])
            )
    for mid, d in latest.items():
        if d.get("decision") == "INGREDIENT_FAMILY_ONLY":
            family_groups[str(d.get("provider_neutral_concept_id") or "family")].add(mid)

    product_eval = _eval_groups(
        product_groups, by_med=by_med, split_meta=split_meta, layer="A_product", allow_ready=True
    )
    ifr_eval = _eval_groups(
        ifr_groups, by_med=by_med, split_meta=split_meta, layer="B_ingredient_form", allow_ready=True
    )
    family_eval = _eval_groups(
        family_groups,
        by_med=by_med,
        split_meta=split_meta,
        layer="C_ingredient_family_exploratory",
        allow_ready=False,  # NEVER authoritative READY
    )

    auth_ready = any(x["READY"] for x in product_eval) or any(x["READY"] for x in ifr_eval)

    # Provisional planning: ethyl-esters strength stratum eligible for IFR review
    provisional_ifr: dict[str, set[str]] = defaultdict(set)
    for c in omega3_cards:
        if c.get("eligibility", {}).get("INGREDIENT_FORM_ROUTE_ACCEPTED") or c.get(
            "eligibility", {}
        ).get("PRODUCT_IDENTITY_ACCEPTED"):
            # only if strength comparable
            if c.get("strength_comparability_vs_omacor") == "COMPATIBLE":
                provisional_ifr[c["provider_neutral_concept"]].add(str(c["source_medicine_id"]))
    provisional = _eval_groups(
        provisional_ifr,
        by_med=by_med,
        split_meta=split_meta,
        layer="provisional_ingredient_form",
        allow_ready=False,
    )

    min_decisions = None
    for row in provisional:
        if row["n_grains_passing_gates"] > 0:
            min_decisions = {
                "n_review_decisions": row["n_source_medicines"],
                "source_medicine_ids": row["source_medicine_ids"],
                "group_key": row["group_key"],
                "required_decision_type": "INGREDIENT_FORM_ROUTE_ACCEPTED_or_PRODUCT_IDENTITY",
                "n_grains_if_accepted": row["n_grains_passing_gates"],
                "note": "Human typed decisions required; not READY until accepted",
            }
            break

    if auth_ready:
        overall = "AUTHORITATIVE_INGREDIENT_FORM_COHORT_READY"
    elif any(
        c.get("eligibility", {}).get("PRODUCT_IDENTITY_ACCEPTED") for c in omega3_cards
    ):
        overall = "PRODUCT_IDENTITY_REVIEW_REQUIRED"
    elif any(
        c.get("eligibility", {}).get("INGREDIENT_FORM_ROUTE_ACCEPTED")
        or c.get("eligibility", {}).get("INGREDIENT_SET_ACCEPTED")
        for c in omega3_cards
    ):
        overall = "INGREDIENT_LEVEL_CANDIDATES_READY_FOR_REVIEW"
    elif all(
        c.get("provider_neutral_concept") == "omega_3_fatty_acids_unspecified"
        for c in omega3_cards
        if str(c["source_medicine_id"]) != "809"
    ) and not any(
        c.get("evidence_completeness", {}).get("chemical_form_specific") for c in omega3_cards
    ):
        overall = "INSUFFICIENT_OMEGA3_COMPOSITION_EVIDENCE"
    else:
        overall = "NO_AUTHORITATIVE_COHORT_READY"

    # Refine: if 809 is product-eligible, prefer PRODUCT_IDENTITY_REVIEW_REQUIRED
    # and also ingredient candidates exist for others as family
    if any(c.get("suggested_review_action") == "PRODUCT_IDENTITY_ACCEPTED" for c in omega3_cards):
        if not auth_ready:
            overall = "PRODUCT_IDENTITY_REVIEW_REQUIRED"

    result = {
        "version": VERSION,
        "gates_unchanged": {
            "min_subjects": GATE_MIN_SUBJECTS,
            "min_episodes": GATE_MIN_EPISODES,
            "min_test_subjects": GATE_MIN_TEST_SUBJECTS,
        },
        "scientifically_usable_accepted_count": usable.get(
            "SCIENTIFICALLY_USABLE_ACCEPTED_COUNT"
        ),
        "A_product_level": product_eval,
        "B_ingredient_form_level": ifr_eval,
        "C_ingredient_family_exploratory": family_eval,
        "provisional_planning": provisional,
        "authoritative_any_READY": auth_ready,
        "provisional_any_READY": False,
        "family_layer_cannot_be_authoritative_READY": True,
        "minimum_human_decisions": min_decisions,
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": (
            "READY" if auth_ready else "ZERO_READY"
        ),
        "ASSOCIATION_BASELINE_STATUS": "NOT_RUN",
        "OVERALL_STATUS": overall,
    }
    path = root / RUNTIME_DIR / "review-pack" / "hierarchical-readiness-impact.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
