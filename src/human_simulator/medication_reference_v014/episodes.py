"""Episode reconstruction by concept — deduplicated, polypharmacy preserved."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from human_simulator.intervention_association_v01.models import load_episodes, split_episodes
from human_simulator.medication_reference_v014.policy import EPISODE_JSONL, V01_COHORTS, VERSION


def _index_episodes(
    episodes_by_split: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    out: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"train": [], "validation": [], "test": []}
    )
    for sp, rows in episodes_by_split.items():
        for e in rows:
            out[str(e["medicine_id"])][sp].append(e)
    return out


def reconstruct_cluster_coverage(
    cluster: dict[str, Any],
    *,
    by_med: dict[str, dict[str, list[dict[str, Any]]]],
    split_meta: dict[str, Any],
    medicine_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Dedup episodes by opaque episode identity when merging source medicines."""
    mids = set(medicine_ids or cluster.get("capable_source_medicine_ids") or [])
    # Fallback to all members for descriptive coverage
    if not mids:
        mids = set(cluster.get("source_medicine_ids") or [])

    # Dedup key: prefer episode_id / locator fields if present, else subject+outcome+unit+time+medicine
    seen: set[str] = set()
    by_split_out = {"train": [], "validation": [], "test": []}
    poly = 0
    concurrent_vals = []
    horizons = []
    missing = {"strength": 0, "form": 0, "route": 0}
    invalid_outcome = 0

    for mid in sorted(mids):
        for sp in ("train", "validation", "test"):
            for e in by_med.get(mid, {}).get(sp, []):
                eid = (
                    str(e.get("episode_id") or e.get("opaque_episode_key") or "")
                    or "|".join(
                        [
                            str(e.get("opaque_subject_key")),
                            str(e.get("outcome")),
                            str(e.get("unit")),
                            str(e.get("event_timestamp") or e.get("appointment_date") or ""),
                            str(mid),
                        ]
                    )
                )
                if eid in seen:
                    continue
                seen.add(eid)
                by_split_out[sp].append(e)
                if e.get("polypharmacy") or e.get("is_polypharmacy"):
                    poly += 1
                if e.get("concurrent_medication_count") is not None:
                    concurrent_vals.append(int(e["concurrent_medication_count"]))
                if e.get("horizon_days") is not None:
                    horizons.append(int(e["horizon_days"]))
                if e.get("outcome") is None or e.get("unit") is None:
                    invalid_outcome += 1

    all_eps = by_split_out["train"] + by_split_out["validation"] + by_split_out["test"]
    subjects = {e["opaque_subject_key"] for e in all_eps}
    test_subj = {e["opaque_subject_key"] for e in by_split_out["test"]}
    train_subj = {e["opaque_subject_key"] for e in by_split_out["train"]}
    val_subj = {e["opaque_subject_key"] for e in by_split_out["validation"]}

    grains = []
    for outcome, unit in V01_COHORTS:
        ge = [e for e in all_eps if e.get("outcome") == outcome and e.get("unit") == unit]
        gs = {e["opaque_subject_key"] for e in ge}
        gtest = {
            e["opaque_subject_key"]
            for e in by_split_out["test"]
            if e.get("outcome") == outcome and e.get("unit") == unit
        }
        blockers = []
        if len(gs) < 100:
            blockers.append("min_subjects")
        if len(ge) < 300:
            blockers.append("min_episodes")
        if len(gtest) < 30:
            blockers.append("min_test_subjects")
        if not split_meta.get("zero_subject_overlap"):
            blockers.append("subject_disjoint_split")
        if not (
            split_meta.get("zero_subject_overlap")
            and split_meta.get("zero_episode_overlap")
            and split_meta.get("zero_locator_overlap")
        ):
            blockers.append("overlap")
        grains.append(
            {
                "outcome": outcome,
                "unit": unit,
                "n_episodes": len(ge),
                "n_subjects": len(gs),
                "n_test_subjects": len(gtest),
                "blockers": blockers,
                "would_pass_gates": not blockers,
            }
        )

    return {
        "version": VERSION,
        "provider_neutral_concept_id": cluster.get("provider_neutral_concept_id"),
        "cluster_key": cluster.get("cluster_key"),
        "source_medicine_ids": sorted(mids),
        "n_source_medicines": len(mids),
        "n_subjects": len(subjects),
        "n_medication_events_deduped": len(all_eps),
        "n_train_subjects": len(train_subj),
        "n_validation_subjects": len(val_subj),
        "n_test_subjects": len(test_subj),
        "n_train_episodes": len(by_split_out["train"]),
        "n_validation_episodes": len(by_split_out["validation"]),
        "n_test_episodes": len(by_split_out["test"]),
        "n_polypharmacy_episodes": poly,
        "concurrent_medication_count_mean": (
            sum(concurrent_vals) / len(concurrent_vals) if concurrent_vals else None
        ),
        "horizon_days_present_n": len(horizons),
        "timestamp_hypothesis": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
        "appointment_is_not_administration": True,
        "missing_field_counts": missing,
        "invalid_outcome_values": invalid_outcome,
        "overlap_meta": {
            "zero_subject_overlap": split_meta.get("zero_subject_overlap"),
            "zero_episode_overlap": split_meta.get("zero_episode_overlap"),
            "zero_locator_overlap": split_meta.get("zero_locator_overlap"),
        },
        "outcome_grains": grains,
        "n_grains_passing_gates": sum(1 for g in grains if g["would_pass_gates"]),
        "dedup_applied": True,
    }


def load_episode_index(root) -> tuple[dict, dict]:
    from pathlib import Path

    episodes = load_episodes(Path(root) / EPISODE_JSONL)
    split = split_episodes(episodes)
    by_med = _index_episodes(split["episodes_by_split"])
    meta = {k: v for k, v in split.items() if k != "episodes_by_split"}
    return by_med, meta
