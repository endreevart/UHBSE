"""Readiness layers, minimum decision sets, ranking (no model metrics)."""

from __future__ import annotations

from typing import Any

from human_simulator.medication_reference_v014.episodes import reconstruct_cluster_coverage
from human_simulator.medication_reference_v014.policy import (
    AUTHORITATIVE_DECISIONS,
    CAPABLE_LEVELS,
    FORBIDDEN_RANK_KEYS,
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    VERSION,
)


def _assert_no_model_metrics(payload: Any, path: str = "") -> None:
    if isinstance(payload, dict):
        for k, v in payload.items():
            lk = str(k).casefold()
            if lk in FORBIDDEN_RANK_KEYS or any(x in lk for x in ("mae", "auc", "accuracy")):
                raise ValueError(f"forbidden_model_metric_in_ranking:{path}.{k}")
            _assert_no_model_metrics(v, f"{path}.{k}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            _assert_no_model_metrics(item, f"{path}[{i}]")


def ingest_typed_accepted(typed_decisions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for d in typed_decisions:
        latest[str(d["source_medicine_id"])] = d
    return {
        mid: d
        for mid, d in latest.items()
        if d.get("decision") in AUTHORITATIVE_DECISIONS
        and d.get("reviewer_identifier")
        and d.get("reason")
        and d.get("evidence_hash")
        and not d.get("llm_generated")
    }


def evaluate_readiness(
    clusters: list[dict[str, Any]],
    *,
    by_med: dict,
    split_meta: dict,
    typed_accepted: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    # Authoritative: only medicines with typed accepted decisions, grouped by cluster capable ids ∩ accepted
    auth_results = []
    for c in clusters:
        mids = [
            mid
            for mid in c.get("capable_source_medicine_ids") or []
            if mid in typed_accepted
        ]
        if not mids:
            continue
        cov = reconstruct_cluster_coverage(
            c, by_med=by_med, split_meta=split_meta, medicine_ids=mids
        )
        auth_results.append(
            {
                **{k: cov[k] for k in cov if k != "outcome_grains"},
                "READY": cov["n_grains_passing_gates"] > 0,
                "n_grains_passing_gates": cov["n_grains_passing_gates"],
                "outcome_grains": cov["outcome_grains"],
                "layer": "authoritative",
            }
        )

    # Provisional: capable clusters only; READY always false
    provisional = []
    min_sets = []
    for c in clusters:
        if c.get("family_only_cluster") or c.get("n_capable", 0) == 0:
            continue
        capable_ids = list(c["capable_source_medicine_ids"])
        # Greedy by episode coverage of members
        member_eps = {
            m["source_medicine_id"]: m["n_episodes"] for m in c["members"] if m["source_medicine_id"] in set(capable_ids)
        }
        ordered = sorted(capable_ids, key=lambda mid: (-member_eps.get(mid, 0), mid))
        selected: list[str] = []
        best = None
        for mid in ordered:
            selected.append(mid)
            cov = reconstruct_cluster_coverage(
                c, by_med=by_med, split_meta=split_meta, medicine_ids=selected
            )
            provisional.append(
                {
                    "provider_neutral_concept_id": c["provider_neutral_concept_id"],
                    "cluster_key": c["cluster_key"],
                    "n_selected": len(selected),
                    "source_medicine_ids": list(selected),
                    "n_subjects": cov["n_subjects"],
                    "n_episodes": cov["n_medication_events_deduped"],
                    "n_test_subjects": cov["n_test_subjects"],
                    "n_grains_passing_gates": cov["n_grains_passing_gates"],
                    "READY": False,
                    "provisional_only": True,
                }
            )
            if cov["n_grains_passing_gates"] > 0 and best is None:
                best = {
                    "provider_neutral_concept_id": c["provider_neutral_concept_id"],
                    "cluster_key": c["cluster_key"],
                    "n_review_decisions": len(selected),
                    "source_medicine_ids": list(selected),
                    "projected_subjects": cov["n_subjects"],
                    "projected_episodes": cov["n_medication_events_deduped"],
                    "projected_test_subjects": cov["n_test_subjects"],
                    "outcome_grains_unlocked": [
                        g for g in cov["outcome_grains"] if g["would_pass_gates"]
                    ],
                    "remaining_blockers_after_decisions": [],
                    "required_typed_levels": sorted(CAPABLE_LEVELS),
                    "why_capable": c.get("why_merge_or_not"),
                    "READY": False,
                    "note": "Human typed decisions required; provisional READY forbidden",
                }
        if best:
            min_sets.append(best)
        elif ordered:
            cov = reconstruct_cluster_coverage(
                c, by_med=by_med, split_meta=split_meta, medicine_ids=ordered
            )
            # report failed full-set blockers
            blockers = sorted(
                {
                    b
                    for g in cov["outcome_grains"]
                    for b in g["blockers"]
                }
            )
            min_sets.append(
                {
                    "provider_neutral_concept_id": c["provider_neutral_concept_id"],
                    "cluster_key": c["cluster_key"],
                    "n_review_decisions": len(ordered),
                    "source_medicine_ids": ordered,
                    "projected_subjects": cov["n_subjects"],
                    "projected_episodes": cov["n_medication_events_deduped"],
                    "projected_test_subjects": cov["n_test_subjects"],
                    "outcome_grains_unlocked": [],
                    "remaining_blockers_after_decisions": blockers,
                    "capable": False,
                    "READY": False,
                    "why_not": (
                        "Even accepting all capable members does not pass unchanged gates"
                    ),
                }
            )

    capable_min = [m for m in min_sets if m.get("outcome_grains_unlocked")]
    capable_min.sort(
        key=lambda m: (
            m["n_review_decisions"],
            -m["projected_episodes"],
            m["provider_neutral_concept_id"],
        )
    )

    auth_ready = any(r.get("READY") for r in auth_results)
    return {
        "version": VERSION,
        "gates_unchanged": {
            "min_subjects": GATE_MIN_SUBJECTS,
            "min_episodes": GATE_MIN_EPISODES,
            "min_test_subjects": GATE_MIN_TEST_SUBJECTS,
        },
        "authoritative": {
            "results": auth_results,
            "any_READY": auth_ready,
            "FIRST_INTERVENTION_COHORT_READINESS_STATUS": (
                "READY" if auth_ready else "ZERO_READY"
            ),
        },
        "provisional": {
            "planning_rows_n": len(provisional),
            "any_READY": False,
            "minimum_honest_decision_sets": capable_min if capable_min else None,
            "all_attempted_sets": min_sets[:50],
        },
        "ASSOCIATION_BASELINE_STATUS": "NOT_RUN",
    }


def rank_top_clusters(
    clusters: list[dict[str, Any]],
    coverage_by_id: dict[str, dict[str, Any]],
    *,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    scored = []
    for c in clusters:
        cov = coverage_by_id.get(c["provider_neutral_concept_id"]) or {}
        hard = any(m.get("typed_level") == "HARD_CONFLICT" for m in c.get("members") or [])
        # mean evidence score from classified members — use capable preferentially
        scored.append(
            {
                "provider_neutral_concept_id": c["provider_neutral_concept_id"],
                "cluster_key": c["cluster_key"],
                "n_capable": c["n_capable"],
                "family_only_cluster": c.get("family_only_cluster"),
                "hard_conflict": hard,
                "n_subjects": cov.get("n_subjects") or 0,
                "n_episodes": cov.get("n_medication_events_deduped") or 0,
                "n_test_subjects": cov.get("n_test_subjects") or 0,
                "n_grains_passing_gates": cov.get("n_grains_passing_gates") or 0,
                "why_merge_or_not": c.get("why_merge_or_not"),
                "source_medicine_ids": c.get("capable_source_medicine_ids")
                or c.get("source_medicine_ids"),
            }
        )
    # ranking order per spec — no model metrics
    scored.sort(
        key=lambda r: (
            0 if not r["hard_conflict"] else 1,
            0 if r["n_capable"] > 0 else 1,
            0 if not r["family_only_cluster"] else 1,
            -r["n_subjects"],
            -r["n_episodes"],
            -r["n_test_subjects"],
            -r["n_capable"],
            r["provider_neutral_concept_id"],
        )
    )
    top = scored[:top_n]
    _assert_no_model_metrics(top)
    return top
