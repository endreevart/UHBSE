"""Phase 5 — hierarchical readiness (authoritative vs provisional, gates unchanged)."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.models import load_episodes, split_episodes
from human_simulator.medication_reference_v012.policy import (
    ACCEPTED_STATUSES,
    EPISODE_JSONL,
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    RUNTIME_DIR,
    V011_MAPPING_REGISTRY,
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
        "n_train_subjects": len({e["opaque_subject_key"] for e in by_split["train"]}),
        "n_validation_subjects": len(
            {e["opaque_subject_key"] for e in by_split["validation"]}
        ),
        "gates": gates,
        "blockers": blockers,
        "ready": not blockers,
    }


def load_v011_authoritative_accepted(root: Path) -> list[dict[str, Any]]:
    path = root / V011_MAPPING_REGISTRY
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("drug_concept_status") in ACCEPTED_STATUSES:
                rows.append(r)
    return rows


def evaluate_groups(
    groups: dict[str, set[str]],
    *,
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    split_meta: dict[str, Any],
    layer: str,
) -> list[dict[str, Any]]:
    results = []
    for key, mids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        ready_grains = []
        for outcome, unit in V01_COHORTS:
            g = _grain_stats(
                mids, by_med=by_med, outcome=outcome, unit=unit, split_meta=split_meta
            )
            if g["ready"]:
                ready_grains.append(g)
        results.append(
            {
                "layer": layer,
                "group_key": key,
                "source_medicine_ids": sorted(mids),
                "n_source_medicines": len(mids),
                "n_ready_grains": len(ready_grains),
                "ready_grains": ready_grains,
                "READY": len(ready_grains) > 0,
            }
        )
    results.sort(key=lambda r: (-r["n_ready_grains"], -r["n_source_medicines"], r["group_key"]))
    return results


def run_hierarchical_readiness(
    root: Path,
    profiles: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    hierarchy_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    episodes = load_episodes(root / EPISODE_JSONL)
    split = split_episodes(episodes)
    episodes_by_split = split["episodes_by_split"]
    split_meta = {k: v for k, v in split.items() if k != "episodes_by_split"}
    by_med = _index_by_medicine(episodes_by_split)

    # --- Authoritative: only v0.1.1 accepted mappings (unchanged gates) ---
    auth_rows = load_v011_authoritative_accepted(root)
    auth_product: dict[str, set[str]] = defaultdict(set)
    for r in auth_rows:
        cid = str(r.get("provider_concept_id") or f"accepted:{r['source_medicine_id']}")
        auth_product[cid].add(str(r["source_medicine_id"]))

    auth_product_eval = evaluate_groups(
        auth_product, by_med=by_med, split_meta=split_meta, layer="authoritative_product"
    )

    # Ingredient/form for accepted only — use profiles for those IDs
    prof_by = {str(p["source_medicine_id"]): p for p in profiles}
    auth_ing: dict[str, set[str]] = defaultdict(set)
    for r in auth_rows:
        mid = str(r["source_medicine_id"])
        p = prof_by.get(mid) or {}
        ings = ",".join(sorted(p.get("active_ingredient_tokens") or [])) or "unknown"
        route = p.get("route_hint") or "unknown"
        key = f"{ings}|{route}"
        auth_ing[key].add(mid)
    auth_ing_eval = evaluate_groups(
        auth_ing, by_med=by_med, split_meta=split_meta, layer="authoritative_ingredient_form"
    )

    auth_ready = any(x["READY"] for x in auth_product_eval) or any(
        x["READY"] for x in auth_ing_eval
    )

    # --- Provisional: candidates only, NEVER assign READY ---
    map_by = {str(m["source_medicine_id"]): m for m in mappings}
    prov_product: dict[str, set[str]] = defaultdict(set)
    prov_ing: dict[str, set[str]] = defaultdict(set)
    for p in profiles:
        mid = str(p["source_medicine_id"])
        m = map_by.get(mid) or {}
        if int(m.get("n_candidates") or 0) <= 0:
            continue
        # only field-compatible top candidate
        top = (m.get("candidates") or [None])[0]
        if not top:
            continue
        if top.get("ingredient_compatibility") != "COMPATIBLE":
            continue
        if top.get("hard_conflict"):
            continue
        cid = str(top["provider_concept_id"])
        prov_product[cid].add(mid)
        ings = ",".join(sorted(p.get("active_ingredient_tokens") or [])) or "unknown"
        route = p.get("route_hint") or "unknown"
        # do not merge oral+topical
        prov_ing[f"{ings}|{route}"].add(mid)

    def provisional_impact(groups: dict[str, set[str]], layer: str) -> list[dict[str, Any]]:
        out = []
        for key, mids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            grains = []
            for outcome, unit in V01_COHORTS:
                g = _grain_stats(
                    mids, by_med=by_med, outcome=outcome, unit=unit, split_meta=split_meta
                )
                grains.append({k: g[k] for k in g if k != "gates"})
            would_ready = [g for g in grains if not g["blockers"]]
            out.append(
                {
                    "layer": layer,
                    "group_key": key,
                    "source_medicine_ids": sorted(mids),
                    "n_source_medicines": len(mids),
                    "projected_grains": grains,
                    "n_would_pass_gates_if_accepted": len(would_ready),
                    # Explicit: provisional must not claim READY
                    "READY": False,
                    "provisional_only": True,
                }
            )
        out.sort(
            key=lambda r: (
                -r["n_would_pass_gates_if_accepted"],
                -r["n_source_medicines"],
                r["group_key"],
            )
        )
        return out

    prov_product_impact = provisional_impact(prov_product, "provisional_product")
    prov_ing_impact = provisional_impact(prov_ing, "provisional_ingredient_form")

    # Minimum real human decisions among provisional groups that would pass if accepted
    min_decisions = None
    for row in prov_product_impact:
        if row["n_would_pass_gates_if_accepted"] > 0:
            n = row["n_source_medicines"]
            if min_decisions is None or n < min_decisions["n_review_decisions"]:
                min_decisions = {
                    "n_review_decisions": n,
                    "group_key": row["group_key"],
                    "source_medicine_ids": row["source_medicine_ids"],
                    "n_would_pass_gates_if_accepted": row["n_would_pass_gates_if_accepted"],
                    "why": (
                        "Greedy product-level provisional set; human ACCEPT required; "
                        "not READY until accepted"
                    ),
                }

    if auth_ready:
        overall = "AUTHORITATIVE_HIERARCHICAL_COHORT_READY"
    elif min_decisions:
        overall = "SEMANTIC_CANDIDATES_READY_FOR_HUMAN_REVIEW"
    else:
        # check supplement gaps
        overall = "NO_HIERARCHICAL_COHORT_READY_WITH_UNCHANGED_GATES"

    result = {
        "version": VERSION,
        "gates_unchanged": {
            "min_subjects": GATE_MIN_SUBJECTS,
            "min_episodes": GATE_MIN_EPISODES,
            "min_test_subjects": GATE_MIN_TEST_SUBJECTS,
        },
        "authoritative": {
            "n_accepted_source_medicines": len(auth_rows),
            "product_level": auth_product_eval,
            "ingredient_form_level": auth_ing_eval,
            "any_READY": auth_ready,
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS": (
                "READY" if auth_ready else "ZERO_READY"
            ),
        },
        "provisional": {
            "product_level": prov_product_impact[:30],
            "ingredient_form_level": prov_ing_impact[:30],
            "any_READY": False,  # hard invariant
            "minimum_human_decisions_for_potential_ready": min_decisions,
        },
        "OVERALL_STATUS": overall,
        "planner_does_not_use_test_performance": True,
        "authoritative_and_provisional_not_mixed": True,
    }

    out = root / RUNTIME_DIR / "review-pack" / "hierarchical-readiness-impact.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return result
