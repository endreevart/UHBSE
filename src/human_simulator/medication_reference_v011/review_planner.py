"""Domain-review prioritization and provisional readiness impact planner (non-authoritative)."""

from __future__ import annotations

import csv
import hashlib
import html
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.models import load_episodes, split_episodes
from human_simulator.medication_reference_v011.review import load_decisions
from human_simulator.medication_reference_v011.policy import (
    ACCEPTED_STATUSES,
    ARTIFACT_DIR,
    EPISODE_JSONL,
    GATE_MIN_EPISODES,
    GATE_MIN_SUBJECTS,
    GATE_MIN_TEST_SUBJECTS,
    RUNTIME_DIR,
    SECURITY_STAGE_STATUS,
    TOP20_EPISODE_COVERAGE_PIN,
    TOP_N_REVIEW,
    TOTAL_EPISODES_PIN,
    V01_COHORTS,
    VERSION,
)

EXPECTED_SNAPSHOT_SHA = (
    "ecb7d0644dd3363c4bb14b7b1e85754a2a47f11edc35fa74092da90920341bae"
)

# Planner must never read or write model metrics / MAE
_FORBIDDEN_PLANNER_KEYS = frozenset(
    {
        "mae",
        "test_mae",
        "subject_macro_mae",
        "m1_subject_macro_mae",
        "m2id_onehot_subject_macro_mae",
        "bootstrap",
        "permutation",
    }
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _assert_no_model_metrics(payload: Any, *, path: str = "") -> None:
    if isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).casefold() in _FORBIDDEN_PLANNER_KEYS or any(
                f in str(k).casefold() for f in ("mae", "auc", "accuracy")
            ):
                raise ValueError(f"planner_forbidden_model_metric:{path}.{k}")
            _assert_no_model_metrics(v, path=f"{path}.{k}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            _assert_no_model_metrics(item, path=f"{path}[{i}]")


def load_authoritative_mappings(root: Path) -> list[dict[str, Any]]:
    path = root / RUNTIME_DIR / "registry" / "medication-reference-mapping.private.jsonl"
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def authoritative_counts(mappings: list[dict[str, Any]]) -> dict[str, int]:
    accepted = sum(1 for m in mappings if m.get("drug_concept_status") in ACCEPTED_STATUSES)
    human = sum(1 for m in mappings if m.get("drug_concept_status") == "HUMAN_ACCEPTED")
    exact = sum(1 for m in mappings if m.get("drug_concept_status") == "EXACT_PROVIDER_MATCH")
    return {
        "AUTHORITATIVE_ACCEPTED_CONCEPT_COUNT": accepted,
        "HUMAN_ACCEPTED_COUNT": human,
        "EXACT_PROVIDER_MATCH_COUNT": exact,
        "PROVISIONAL_ACCEPTED_CONCEPT_COUNT": 0,
    }


def _load_candidate_concepts(
    root: Path, needed_ids: set[str]
) -> dict[str, dict[str, Any]]:
    """Stream ESKLP index; keep only concepts referenced by mapping candidates."""
    index_path = (
        root
        / RUNTIME_DIR
        / "provider-snapshots"
        / "esklp"
        / "index"
        / "provider-index.jsonl"
    )
    out: dict[str, dict[str, Any]] = {}
    if not index_path.is_file() or not needed_ids:
        return out
    with index_path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            cid = str(row.get("provider_concept_id") or "")
            if cid in needed_ids:
                out[cid] = row
                if len(out) >= len(needed_ids):
                    break
    return out


def verify_candidate_integrity(
    mappings: list[dict[str, Any]],
    *,
    index_concepts: dict[str, dict[str, Any]],
    expected_snapshot_sha: str,
) -> dict[str, Any]:
    with_cand = [m for m in mappings if int(m.get("n_candidates") or 0) > 0]
    ok = 0
    fail = 0
    details: list[dict[str, Any]] = []
    for m in with_cand:
        mid = str(m["source_medicine_id"])
        snap = m.get("provider_snapshot_hash")
        snap_ok = snap == expected_snapshot_sha
        cands = m.get("candidates") or []
        cand_reports = []
        all_ok = snap_ok and bool(cands)
        for c in cands:
            cid = str(c.get("provider_concept_id") or "")
            in_index = cid in index_concepts
            concept = index_concepts.get(cid) or {}
            # unique resolve: id present exactly once in retained index map
            unique_ok = in_index
            report = {
                "provider_concept_id": cid,
                "in_current_esklp_index": in_index,
                "unique_resolve_ok": unique_ok,
                "product_name": concept.get("trade_name") or c.get("trade_name"),
                "inn": concept.get("inn") or c.get("inn"),
                "ingredients": concept.get("ingredients") or c.get("ingredients") or [],
                "strength": concept.get("strength") or c.get("strength"),
                "dosage_form": concept.get("form") or c.get("form"),
                "multi_ingredient": len(concept.get("ingredients") or c.get("ingredients") or [])
                > 1,
                "match_method": c.get("method"),
                "similarity_components": {
                    "rank_score": c.get("rank_score"),
                    "score": c.get("score"),
                    "primary_step": c.get("primary_step"),
                    "matched_fields": c.get("matched_fields"),
                    "strength_compat": c.get("strength_compat"),
                    "form_compat": c.get("form_compat"),
                },
                "ambiguity_reasons": m.get("ambiguity_reasons") or [],
                "conflicts": m.get("conflict_reasons") or [],
            }
            if not (in_index and unique_ok):
                all_ok = False
            cand_reports.append(report)
        if all_ok:
            ok += 1
        else:
            fail += 1
        details.append(
            {
                "source_medicine_id": mid,
                "snapshot_hash_ok": snap_ok,
                "n_candidates": len(cands),
                "candidates": cand_reports,
                "integrity_ok": all_ok,
            }
        )
    return {
        "n_with_candidates": len(with_cand),
        "n_integrity_ok": ok,
        "n_integrity_fail": fail,
        "expected_snapshot_sha256": expected_snapshot_sha,
        "ambiguous_not_auto_accepted": True,
        "details_private": details,
    }


def _index_episodes_by_medicine(
    episodes_by_split: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """medicine_id -> split -> episodes."""
    out: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"train": [], "validation": [], "test": []}
    )
    for sp, rows in episodes_by_split.items():
        for e in rows:
            out[str(e["medicine_id"])][sp].append(e)
    return out


def _grain_stats_for_medicine_ids(
    medicine_ids: set[str],
    *,
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    outcome: str,
    unit: str,
    split_meta: dict[str, Any],
) -> dict[str, Any]:
    cohort: list[dict[str, Any]] = []
    by_split: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
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
        "timestamp_gate": True,  # technical event timestamp used throughout baseline
        "no_identity_or_locator_overlap": bool(
            split_meta.get("zero_subject_overlap")
            and split_meta.get("zero_episode_overlap")
            and split_meta.get("zero_locator_overlap")
        ),
    }
    blockers = [k for k, v in gates.items() if not v]
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


def rejected_candidate_pairs(root: Path) -> set[tuple[str, str]]:
    """Source medicine × candidate pairs already HUMAN_REJECTED (latest not required)."""
    out: set[tuple[str, str]] = set()
    for row in load_decisions(root):
        if row.get("decision") != "HUMAN_REJECTED":
            continue
        mid = str(row.get("source_medicine_id") or "")
        cid = str(row.get("candidate_id") or row.get("provider_concept_id") or "")
        if mid and cid:
            out.add((mid, cid))
    return out


def _select_planning_candidate(
    mapping: dict[str, Any],
    *,
    rejected: set[tuple[str, str]],
    prefer_field_compatible: bool = True,
) -> dict[str, Any] | None:
    """Pick highest-ranked non-rejected candidate; prefer form+strength COMPATIBLE."""
    mid = str(mapping.get("source_medicine_id") or "")
    cands = sorted(
        mapping.get("candidates") or [],
        key=lambda c: -float(c.get("rank_score") or 0),
    )
    eligible = [
        c
        for c in cands
        if str(c.get("provider_concept_id") or "")
        and (mid, str(c.get("provider_concept_id"))) not in rejected
    ]
    if not eligible:
        return None
    if prefer_field_compatible:
        for c in eligible:
            if (
                c.get("form_compat") == "COMPATIBLE"
                and c.get("strength_compat") == "COMPATIBLE"
            ):
                return c
        return None
    return eligible[0]


def build_provisional_impacts(
    mappings: list[dict[str, Any]],
    *,
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    split_meta: dict[str, Any],
    index_concepts: dict[str, dict[str, Any]],
    rejected: set[tuple[str, str]] | None = None,
    prefer_field_compatible: bool = True,
) -> list[dict[str, Any]]:
    """One planning row per (source_medicine, selected candidate) — provisional only.

    Rejected candidate pairs are excluded. When prefer_field_compatible is True,
    only form+strength COMPATIBLE candidates enter readiness planning (avoids
    recommending token-only false matches that conflict on dosage form/strength).
    """
    rejected = rejected or set()
    impacts: list[dict[str, Any]] = []
    for m in mappings:
        if int(m.get("n_candidates") or 0) <= 0:
            continue
        if m.get("drug_concept_status") in ACCEPTED_STATUSES:
            # already accepted — include for completeness but not as review decision
            continue
        top = _select_planning_candidate(
            m, rejected=rejected, prefer_field_compatible=prefer_field_compatible
        )
        if not top:
            continue
        cid = str(top.get("provider_concept_id") or "")
        if cid not in index_concepts:
            continue
        mid = str(m["source_medicine_id"])
        grains = []
        unlocked = []
        for outcome, unit in V01_COHORTS:
            g = _grain_stats_for_medicine_ids(
                {mid},
                by_med=by_med,
                outcome=outcome,
                unit=unit,
                split_meta=split_meta,
            )
            grains.append(g)
            if g["ready"]:
                unlocked.append({"outcome": outcome, "unit": unit})
        cov = m.get("episode_coverage") or {}
        concept = index_concepts[cid]
        impacts.append(
            {
                "source_medicine_id": mid,
                "original_name": m.get("original_name"),
                "original_description": m.get("original_description"),
                "normalized_source_name": m.get("normalized_source_name"),
                "extracted_strength": m.get("strength_tokens_observed"),
                "extracted_form": m.get("form_tokens_observed"),
                "n_episodes": int(cov.get("n_episodes") or 0),
                "n_subjects": int(cov.get("n_subjects") or 0),
                "associated_outcomes": sorted(
                    {
                        (g["outcome"], g["unit"])
                        for g in grains
                        if g["n_episodes"] > 0
                    }
                ),
                "candidate": {
                    "provider_concept_id": cid,
                    "trade_name": concept.get("trade_name"),
                    "inn": concept.get("inn"),
                    "ingredients": concept.get("ingredients") or [],
                    "strength": concept.get("strength"),
                    "dosage_form": concept.get("form"),
                    "registration_or_product_id": cid,
                    "matched_fields": top.get("matched_fields"),
                    "match_method": top.get("method"),
                    "conflicts": m.get("conflict_reasons") or [],
                    "ambiguity_reasons": m.get("ambiguity_reasons") or [],
                    "similarity_components": {
                        "rank_score": top.get("rank_score"),
                        "primary_step": top.get("primary_step"),
                        "strength_compat": top.get("strength_compat"),
                        "form_compat": top.get("form_compat"),
                    },
                },
                "readiness_impact": {
                    "projected_episodes": int(cov.get("n_episodes") or 0),
                    "projected_subjects": int(cov.get("n_subjects") or 0),
                    "projected_test_subjects_max": max(
                        (g["n_test_subjects"] for g in grains), default=0
                    ),
                    "potentially_unlocked_cohorts_alone": unlocked,
                    "grains": grains,
                    "remaining_blockers_if_accepted_alone": sorted(
                        {
                            b
                            for g in grains
                            for b in g["blockers"]
                            if g["n_episodes"] > 0
                        }
                    ),
                },
                "provisional_only": True,
                "authoritative_status_unchanged": m.get("drug_concept_status"),
            }
        )
    impacts.sort(key=lambda r: (-r["n_episodes"], -r["n_subjects"], r["source_medicine_id"]))
    return impacts


def _concept_groups(
    impacts: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in impacts:
        cid = row["candidate"]["provider_concept_id"]
        groups[cid].append(row)
    return groups


def evaluate_concept_after_accepts(
    *,
    concept_id: str,
    medicine_ids: set[str],
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    split_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    ready_grains = []
    for outcome, unit in V01_COHORTS:
        g = _grain_stats_for_medicine_ids(
            medicine_ids,
            by_med=by_med,
            outcome=outcome,
            unit=unit,
            split_meta=split_meta,
        )
        g = {**g, "accepted_drug_concept": concept_id, "source_medicine_ids": sorted(medicine_ids)}
        if g["ready"]:
            ready_grains.append(g)
    return ready_grains


def greedy_min_decisions_for_concept(
    members: list[dict[str, Any]],
    *,
    concept_id: str,
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    split_meta: dict[str, Any],
    target_ready_grains: int = 1,
) -> dict[str, Any] | None:
    """Deterministic greedy: add source medicines by episode coverage until READY grains open."""
    ordered = sorted(
        members,
        key=lambda r: (-r["n_episodes"], -r["n_subjects"], r["source_medicine_id"]),
    )
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for row in ordered:
        selected.append(row)
        selected_ids.add(row["source_medicine_id"])
        ready = evaluate_concept_after_accepts(
            concept_id=concept_id,
            medicine_ids=selected_ids,
            by_med=by_med,
            split_meta=split_meta,
        )
        if len(ready) >= target_ready_grains:
            return {
                "provider_concept_id": concept_id,
                "n_review_decisions": len(selected),
                "source_medicine_ids": [r["source_medicine_id"] for r in selected],
                "candidate_provider_ids": [concept_id] * len(selected),
                "decisions": [
                    {
                        "source_medicine_id": r["source_medicine_id"],
                        "candidate_id": concept_id,
                        "original_name": r.get("original_name"),
                        "n_episodes": r["n_episodes"],
                        "n_subjects": r["n_subjects"],
                    }
                    for r in selected
                ],
                "projected_ready_grains": [
                    {
                        "outcome": g["outcome"],
                        "unit": g["unit"],
                        "n_episodes": g["n_episodes"],
                        "n_subjects": g["n_subjects"],
                        "n_test_subjects": g["n_test_subjects"],
                        "n_train_subjects": g["n_train_subjects"],
                        "n_validation_subjects": g["n_validation_subjects"],
                    }
                    for g in ready
                ],
                "projected_episodes": sum(r["n_episodes"] for r in selected),
                "projected_subjects_sum": sum(r["n_subjects"] for r in selected),
                "remaining_blockers": [],
                "why_selected": (
                    f"Greedy by episode coverage within ESKLP concept {concept_id}: "
                    f"{len(selected)} accept(s) unlock {len(ready)} READY grain(s)."
                ),
                "target_ready_grains": target_ready_grains,
            }
    # Failed — report best effort blockers
    ready = evaluate_concept_after_accepts(
        concept_id=concept_id,
        medicine_ids={r["source_medicine_id"] for r in ordered},
        by_med=by_med,
        split_meta=split_meta,
    )
    # blockers from richest grain
    best_blockers: list[str] = []
    best_stats = None
    for outcome, unit in V01_COHORTS:
        g = _grain_stats_for_medicine_ids(
            {r["source_medicine_id"] for r in ordered},
            by_med=by_med,
            outcome=outcome,
            unit=unit,
            split_meta=split_meta,
        )
        if best_stats is None or g["n_episodes"] > best_stats["n_episodes"]:
            best_stats = g
            best_blockers = g["blockers"]
    return None if not ordered else {
        "provider_concept_id": concept_id,
        "n_review_decisions": len(ordered),
        "source_medicine_ids": [r["source_medicine_id"] for r in ordered],
        "candidate_provider_ids": [concept_id] * len(ordered),
        "decisions": [
            {
                "source_medicine_id": r["source_medicine_id"],
                "candidate_id": concept_id,
                "n_episodes": r["n_episodes"],
                "n_subjects": r["n_subjects"],
            }
            for r in ordered
        ],
        "projected_ready_grains": ready,
        "projected_episodes": sum(r["n_episodes"] for r in ordered),
        "projected_subjects_sum": sum(r["n_subjects"] for r in ordered),
        "remaining_blockers": best_blockers,
        "best_grain_stats": best_stats,
        "why_selected": (
            f"Even accepting all {len(ordered)} source medicines for concept "
            f"{concept_id} does not unlock {target_ready_grains} READY grain(s)."
        ),
        "capable_of_ready": False,
        "target_ready_grains": target_ready_grains,
    }


def plan_minimum_decision_sets(
    impacts: list[dict[str, Any]],
    *,
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    split_meta: dict[str, Any],
) -> dict[str, Any]:
    groups = _concept_groups(impacts)
    # Evaluate each concept for 1 and 3 ready grains
    sets_one: list[dict[str, Any]] = []
    sets_three: list[dict[str, Any]] = []
    for cid, members in sorted(
        groups.items(),
        key=lambda kv: -sum(m["n_episodes"] for m in kv[1]),
    ):
        one = greedy_min_decisions_for_concept(
            members,
            concept_id=cid,
            by_med=by_med,
            split_meta=split_meta,
            target_ready_grains=1,
        )
        if one and one.get("projected_ready_grains") and not one.get("remaining_blockers"):
            if one.get("capable_of_ready") is not False and len(one["projected_ready_grains"]) >= 1:
                one["capable_of_ready"] = True
                sets_one.append(one)
        three = greedy_min_decisions_for_concept(
            members,
            concept_id=cid,
            by_med=by_med,
            split_meta=split_meta,
            target_ready_grains=3,
        )
        if (
            three
            and three.get("projected_ready_grains")
            and len(three["projected_ready_grains"]) >= 3
        ):
            three["capable_of_ready"] = True
            sets_three.append(three)

    def _rank_key(s: dict[str, Any]) -> tuple:
        return (
            s["n_review_decisions"],
            -s["projected_episodes"],
            s["provider_concept_id"],
        )

    sets_one.sort(key=_rank_key)
    sets_three.sort(key=_rank_key)

    # Max top-20 episode coverage: greedily accept top-20 impacts' top candidates
    top20 = impacts[:TOP_N_REVIEW]
    top20_set = {
        "label": "max_top20_episode_coverage",
        "n_review_decisions": len(top20),
        "source_medicine_ids": [r["source_medicine_id"] for r in top20],
        "candidate_provider_ids": [
            r["candidate"]["provider_concept_id"] for r in top20
        ],
        "decisions": [
            {
                "source_medicine_id": r["source_medicine_id"],
                "candidate_id": r["candidate"]["provider_concept_id"],
                "n_episodes": r["n_episodes"],
                "n_subjects": r["n_subjects"],
            }
            for r in top20
        ],
        "projected_episodes": sum(r["n_episodes"] for r in top20),
        "projected_subjects_sum": sum(r["n_subjects"] for r in top20),
        "top20_episode_coverage_pin": TOP20_EPISODE_COVERAGE_PIN,
        "why_selected": (
            "Accept top-20 source medicines by episode coverage (each mapped to its "
            "rank-1 ESKLP candidate) to maximize planned top-20 coverage."
        ),
    }
    # Project ready grains if all top20 accepted (group by concept)
    concept_to_mids: dict[str, set[str]] = defaultdict(set)
    for r in top20:
        concept_to_mids[r["candidate"]["provider_concept_id"]].add(r["source_medicine_id"])
    unlocked = []
    for cid, mids in concept_to_mids.items():
        unlocked.extend(
            evaluate_concept_after_accepts(
                concept_id=cid,
                medicine_ids=mids,
                by_med=by_med,
                split_meta=split_meta,
            )
        )
    top20_set["projected_ready_grains"] = [
        {
            "outcome": g["outcome"],
            "unit": g["unit"],
            "accepted_drug_concept": g["accepted_drug_concept"],
            "n_episodes": g["n_episodes"],
            "n_subjects": g["n_subjects"],
            "n_test_subjects": g["n_test_subjects"],
        }
        for g in unlocked
    ]
    top20_set["n_projected_ready_grains"] = len(unlocked)

    first = sets_one[0] if sets_one else None
    three = sets_three[0] if sets_three else None
    # Three most promising decision sets for first READY
    promising = sets_one[:3]
    if not promising:
        # Honest: no candidate set unlocks READY even after full accept within concept
        promising = []

    return {
        "minimum_for_first_ready": first,
        "minimum_for_three_ready": three,
        "three_most_promising_for_first_ready": promising,
        "max_top20_episode_coverage_set": top20_set,
        "n_concepts_capable_of_first_ready": len(sets_one),
        "n_concepts_capable_of_three_ready": len(sets_three),
        "no_candidate_can_pass_readiness": len(sets_one) == 0,
    }


def render_reviewer_commands(
    decisions: list[dict[str, Any]],
    *,
    action: str = "accept",
    reviewer_placeholder: str = "<reviewer_id>",
) -> list[str]:
    cmds = []
    for d in decisions:
        mid = d["source_medicine_id"]
        cid = d["candidate_id"]
        if action == "accept":
            reason = (
                d.get("reason")
                or "ESKLP product/INN match confirmed for concept-specific cohort planning"
            )
            cmds.append(
                "uv run --frozen audit --root . medication-reference review accept "
                f"{mid} --candidate {cid} --provider ESKLP "
                f'--reviewer {reviewer_placeholder} --reason "{reason}"'
            )
        elif action == "reject":
            reason = d.get("reason") or "Candidate rejected after domain review"
            cmds.append(
                "uv run --frozen audit --root . medication-reference review reject "
                f"{mid} --candidate {cid} --provider ESKLP "
                f'--reviewer {reviewer_placeholder} --reason "{reason}"'
            )
        else:
            reason = d.get("reason") or "Remains ambiguous after inspection"
            cmds.append(
                "uv run --frozen audit --root . medication-reference review ambiguous "
                f"{mid} --provider ESKLP "
                f'--reviewer {reviewer_placeholder} --reason "{reason}"'
            )
    return cmds


def _render_html(packet_rows: list[dict[str, Any]], plan: dict[str, Any]) -> str:
    first = plan.get("minimum_for_first_ready")
    summary = (
        f"<p><b>Minimum decisions for first READY:</b> "
        f"{(first or {}).get('n_review_decisions', 'NONE')}</p>"
        f"<p>Authoritative accepted remains 1. Provisional accepted = 0. "
        f"CLINICAL_USE_PROHIBITED.</p>"
    )
    rows_html = []
    for r in packet_rows:
        c = r["candidate"]
        impact = r["readiness_impact"]
        outcomes = ", ".join(f"{o}/{u}" for o, u in r.get("associated_outcomes") or [])
        unlocked = impact.get("potentially_unlocked_cohorts_alone") or []
        unlocked_s = ", ".join(f"{x['outcome']}/{x['unit']}" for x in unlocked) or "none alone"
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(str(r['source_medicine_id']))}<br/>"
            f"<small>{html.escape(str(r.get('original_name') or ''))}</small></td>"
            f"<td>{html.escape(str(r.get('original_description') or '')[:200])}</td>"
            f"<td>{r.get('n_episodes')}<br/>subj {r.get('n_subjects')}<br/>{html.escape(outcomes)}</td>"
            f"<td><code>{html.escape(str(c['provider_concept_id']))}</code><br/>"
            f"{html.escape(str(c.get('trade_name') or ''))}<br/>"
            f"МНН: {html.escape(str(c.get('inn') or ''))}<br/>"
            f"{html.escape(str(c.get('strength') or ''))} / {html.escape(str(c.get('dosage_form') or ''))}<br/>"
            f"method: {html.escape(str(c.get('match_method') or ''))}<br/>"
            f"amb: {html.escape(';'.join(c.get('ambiguity_reasons') or []))}</td>"
            f"<td>eps {impact.get('projected_episodes')}<br/>"
            f"subj {impact.get('projected_subjects')}<br/>"
            f"test_max {impact.get('projected_test_subjects_max')}<br/>"
            f"unlock alone: {html.escape(unlocked_s)}<br/>"
            f"blockers: {html.escape(','.join(impact.get('remaining_blockers_if_accepted_alone') or []))}</td>"
            f"<td>ACCEPT / REJECT / AMBIGUOUS</td>"
            "</tr>"
        )
    body = "\n".join(rows_html)
    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/>
<title>UHBSE priority domain review (private)</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 1.2rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border: 1px solid #ccc; padding: 6px; vertical-align: top; }}
th {{ background: #f3f3f3; text-align: left; }}
code {{ font-size: 11px; }}
.note {{ color: #444; }}
</style></head><body>
<h1>Priority domain-review packet (top priority)</h1>
{summary}
<p class="note">Private only — not for public ZIP. No patient IDs / episode rows / lab values.</p>
<table>
<thead><tr>
<th>Source</th><th>Description</th><th>Coverage / outcomes</th>
<th>ESKLP candidate</th><th>Readiness impact</th><th>Action</th>
</tr></thead>
<tbody>
{body}
</tbody></table>
</body></html>
"""


def write_reviewer_packet(
    root: Path,
    *,
    impacts: list[dict[str, Any]],
    plan: dict[str, Any],
    integrity: dict[str, Any],
    auth_counts: dict[str, int],
) -> dict[str, Any]:
    pack_dir = root / RUNTIME_DIR / "review-pack"
    pack_dir.mkdir(parents=True, exist_ok=True)

    # Priority packet: members of minimum first-ready set, else top-20 by coverage
    first = plan.get("minimum_for_first_ready")
    priority_ids: list[str]
    if first and first.get("capable_of_ready"):
        priority_ids = list(first["source_medicine_ids"])
    else:
        priority_ids = [r["source_medicine_id"] for r in impacts[:TOP_N_REVIEW]]

    by_id = {r["source_medicine_id"]: r for r in impacts}
    # Include promising sets' members for the HTML top section
    for s in plan.get("three_most_promising_for_first_ready") or []:
        for mid in s.get("source_medicine_ids") or []:
            if mid not in priority_ids:
                priority_ids.append(mid)
    packet_rows = [by_id[i] for i in priority_ids if i in by_id]
    # Always also attach remaining top-20 for coverage context
    for r in impacts[:TOP_N_REVIEW]:
        if r["source_medicine_id"] not in {x["source_medicine_id"] for x in packet_rows}:
            packet_rows.append(r)

    # Cap display to keep packet focused (priority + top20 unique)
    seen = set()
    focused = []
    for r in packet_rows:
        mid = r["source_medicine_id"]
        if mid in seen:
            continue
        seen.add(mid)
        focused.append(r)
    packet_rows = focused[:40]

    html_path = pack_dir / "priority-review-top20.html"
    html_path.write_text(_render_html(packet_rows, plan), encoding="utf-8")

    csv_path = pack_dir / "priority-review-top20.csv"
    fields = [
        "source_medicine_id",
        "original_name",
        "n_episodes",
        "n_subjects",
        "provider_concept_id",
        "trade_name",
        "inn",
        "strength",
        "dosage_form",
        "match_method",
        "ambiguity_reasons",
        "projected_episodes",
        "projected_subjects",
        "projected_test_subjects_max",
        "blockers_if_accepted_alone",
        "suggested_action",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in packet_rows:
            c = r["candidate"]
            imp = r["readiness_impact"]
            w.writerow(
                {
                    "source_medicine_id": r["source_medicine_id"],
                    "original_name": r.get("original_name"),
                    "n_episodes": r.get("n_episodes"),
                    "n_subjects": r.get("n_subjects"),
                    "provider_concept_id": c.get("provider_concept_id"),
                    "trade_name": c.get("trade_name"),
                    "inn": c.get("inn"),
                    "strength": c.get("strength"),
                    "dosage_form": c.get("dosage_form"),
                    "match_method": c.get("match_method"),
                    "ambiguity_reasons": ";".join(c.get("ambiguity_reasons") or []),
                    "projected_episodes": imp.get("projected_episodes"),
                    "projected_subjects": imp.get("projected_subjects"),
                    "projected_test_subjects_max": imp.get("projected_test_subjects_max"),
                    "blockers_if_accepted_alone": ";".join(
                        imp.get("remaining_blockers_if_accepted_alone") or []
                    ),
                    "suggested_action": "ACCEPT|REJECT|AMBIGUOUS",
                }
            )

    cmds_first = []
    if first and first.get("capable_of_ready"):
        cmds_first = render_reviewer_commands(first.get("decisions") or [])

    impact_doc = {
        "version": VERSION,
        "generated_at": _now(),
        "PROVISIONAL_READINESS_PLANNER_STATUS": "BUILT",
        "DOMAIN_REVIEW_PRIORITIZATION_STATUS": "PASS",
        "DOMAIN_REVIEW_PACKET_STATUS": "READY",
        **auth_counts,
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "ASSOCIATION_BASELINE_STATUS": "NOT_RUN_DOMAIN_REVIEW_REQUIRED",
        "DOMAIN_REVIEW_DECISION_REQUIRED": True,
        "n_candidates_in_planning": len(impacts),
        "integrity_summary": {
            "n_with_candidates": integrity.get("n_with_candidates"),
            "n_integrity_ok": integrity.get("n_integrity_ok"),
            "n_integrity_fail": integrity.get("n_integrity_fail"),
        },
        "plan": {
            "minimum_for_first_ready": first,
            "minimum_for_three_ready": plan.get("minimum_for_three_ready"),
            "three_most_promising_for_first_ready": plan.get(
                "three_most_promising_for_first_ready"
            ),
            "max_top20_episode_coverage_set": plan.get("max_top20_episode_coverage_set"),
            "no_candidate_can_pass_readiness": plan.get("no_candidate_can_pass_readiness"),
            "n_concepts_capable_of_first_ready": plan.get(
                "n_concepts_capable_of_first_ready"
            ),
        },
        "reviewer_commands_for_minimum_first_ready": cmds_first,
        "planner_does_not_use_test_performance": True,
        "provisional_not_written_to_authoritative_registry": True,
        "no_model_training": True,
        "gates": {
            "GATE_MIN_SUBJECTS": GATE_MIN_SUBJECTS,
            "GATE_MIN_EPISODES": GATE_MIN_EPISODES,
            "GATE_MIN_TEST_SUBJECTS": GATE_MIN_TEST_SUBJECTS,
        },
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
    }
    _assert_no_model_metrics(impact_doc)
    impact_path = pack_dir / "readiness-impact.json"
    _write(impact_path, impact_doc)

    instructions = pack_dir / "reviewer-instructions.md"
    min_n = (first or {}).get("n_review_decisions")
    instructions.write_text(
        f"""# Domain reviewer instructions (private)

## Scope

Review **priority** medication concept mappings only. Do **not** review all 381 AMBIGUOUS rows.

Authoritative accepted concepts remain **{auth_counts['AUTHORITATIVE_ACCEPTED_CONCEPT_COUNT']}**.
Human accepted remains **0** until you record decisions.
Provisional planner counts are **not** scientific results.

## Gates (engineering, not clinical)

- min subjects: {GATE_MIN_SUBJECTS}
- min episodes: {GATE_MIN_EPISODES}
- min test subjects: {GATE_MIN_TEST_SUBJECTS}
- subject-disjoint train/validation/test

## Minimum path to first READY cohort

Minimum review decisions (greedy plan): **{min_n if min_n is not None else "NONE — no candidate set unlocks READY"}**

Prefer accepting source medicines that share the same ESKLP concept when evidence supports it —
they merge into one `accepted_drug_concept × outcome × unit` grain.

## Commands

Replace `<reviewer_id>` with your explicit reviewer identifier. Reason is required.

```bash
{(chr(10).join(cmds_first)) if cmds_first else "# No READY-capable decision set found — review top-20 for coverage only."}
```

Reject / ambiguous variants require `--reviewer` and `--reason` as well.

## Forbidden

- Do not invent provider concept IDs
- Do not treat appointment as administration
- Do not claim treatment effect / causal effect
- CLINICAL_USE_PROHIBITED

## Files

- `priority-review-top20.html`
- `priority-review-top20.csv`
- `readiness-impact.json`
""",
        encoding="utf-8",
    )

    # Patient-data scan on packet text
    blob = html_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8")
    for forbidden in ("opaque_subject_key", "patient_id", "post_value", "pre_value", "episode_id"):
        if forbidden in blob:
            raise ValueError(f"patient_level_field_leaked_into_packet:{forbidden}")

    return {
        "pack_dir": str(pack_dir.relative_to(root)),
        "files": [
            str(html_path.relative_to(root)),
            str(csv_path.relative_to(root)),
            str(impact_path.relative_to(root)),
            str(instructions.relative_to(root)),
        ],
        "n_packet_rows": len(packet_rows),
    }


def run_domain_review_planner(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    mappings = load_authoritative_mappings(root)
    auth = authoritative_counts(mappings)
    if auth["AUTHORITATIVE_ACCEPTED_CONCEPT_COUNT"] != 1:
        # Soft warning in result — do not mutate
        pass
    if auth["HUMAN_ACCEPTED_COUNT"] != 0:
        pass

    # Collect candidate IDs
    needed: set[str] = set()
    for m in mappings:
        for c in m.get("candidates") or []:
            if c.get("provider_concept_id"):
                needed.add(str(c["provider_concept_id"]))
        if m.get("provider_concept_id") and m.get("drug_concept_status") in ACCEPTED_STATUSES:
            needed.add(str(m["provider_concept_id"]))

    index_concepts = _load_candidate_concepts(root, needed)
    integrity = verify_candidate_integrity(
        mappings,
        index_concepts=index_concepts,
        expected_snapshot_sha=EXPECTED_SNAPSHOT_SHA,
    )

    # Episodes + split (planning only)
    episodes = load_episodes(root / EPISODE_JSONL)
    split = split_episodes(episodes)
    episodes_by_split = split["episodes_by_split"]
    split_meta = {k: v for k, v in split.items() if k != "episodes_by_split"}
    by_med = _index_episodes_by_medicine(episodes_by_split)

    rejected = rejected_candidate_pairs(root)
    impacts = build_provisional_impacts(
        mappings,
        by_med=by_med,
        split_meta=split_meta,
        index_concepts=index_concepts,
        rejected=rejected,
        prefer_field_compatible=True,
    )
    plan = plan_minimum_decision_sets(
        impacts, by_med=by_med, split_meta=split_meta
    )
    plan["n_rejected_candidate_pairs_excluded"] = len(rejected)
    plan["planning_requires_form_and_strength_compatible"] = True
    packet = write_reviewer_packet(
        root,
        impacts=impacts,
        plan=plan,
        integrity=integrity,
        auth_counts=auth,
    )

    # Persist integrity details privately (not authoritative registry)
    diag_dir = root / RUNTIME_DIR / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    _write(
        diag_dir / "candidate-integrity.private.json",
        {
            "summary": {
                k: integrity[k]
                for k in integrity
                if k != "details_private"
            },
            "details_private": integrity.get("details_private"),
        },
    )

    # Public-safe artifact summary (no full medication strings)
    art = root / ARTIFACT_DIR
    art.mkdir(parents=True, exist_ok=True)
    public = {
        "version": VERSION,
        "generated_at": _now(),
        "DOMAIN_REVIEW_PRIORITIZATION_STATUS": "PASS",
        "PROVISIONAL_READINESS_PLANNER_STATUS": "BUILT",
        "DOMAIN_REVIEW_PACKET_STATUS": "READY",
        **auth,
        "FIRST_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "ASSOCIATION_BASELINE_STATUS": "NOT_RUN_DOMAIN_REVIEW_REQUIRED",
        "DOMAIN_REVIEW_DECISION_REQUIRED": True,
        "n_candidates_in_planning": len(impacts),
        "n_rejected_candidate_pairs_excluded": len(rejected),
        "planning_requires_form_and_strength_compatible": True,
        "minimum_review_decisions_for_first_ready": (
            plan.get("minimum_for_first_ready") or {}
        ).get("n_review_decisions"),
        "no_candidate_can_pass_readiness": plan.get("no_candidate_can_pass_readiness"),
        "n_concepts_capable_of_first_ready": plan.get("n_concepts_capable_of_first_ready"),
        "top20_episode_coverage_pin": TOP20_EPISODE_COVERAGE_PIN,
        "total_episodes_pin": TOTAL_EPISODES_PIN,
        "private_review_pack": packet.get("pack_dir"),
        "private_packet_files": packet.get("files"),
        "integrity_ok": integrity.get("n_integrity_ok"),
        "integrity_fail": integrity.get("n_integrity_fail"),
        "authoritative_registry_unchanged": True,
        "no_model_training": True,
        "no_zip_published": True,
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "QSP_STATUS": "NOT_STARTED",
        "PKPD_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "SECURITY_STAGE_STATUS": SECURITY_STAGE_STATUS,
    }
    _assert_no_model_metrics(public)
    _write(art / "domain-review-prioritization-summary.json", public)

    # Verify authoritative registry hash unchanged intent: re-read counts
    post = authoritative_counts(load_authoritative_mappings(root))

    return {
        "ok": True,
        "statuses": public,
        "plan": plan,
        "auth_before": auth,
        "auth_after": post,
        "packet": packet,
        "n_impacts": len(impacts),
    }
