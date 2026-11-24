"""Episode accounting funnel — explain total concept episodes → primary CV rows."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.models import load_episodes
from human_simulator.post_pilot_audit_v01.policy import (
    EPISODE_JSONL,
    PILOT_COHORTS,
    V01_OUTCOME_GRAINS,
    VERSION,
)


def _step(
    *,
    name: str,
    input_n: int,
    accepted: int,
    rejected: int = 0,
    duplicates: int = 0,
    unsupported: int = 0,
    unexplained: int = 0,
    rejection_reasons: dict[str, int] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    total_parts = accepted + rejected + duplicates + unsupported + unexplained
    bal = input_n == total_parts
    retained = (accepted / input_n) if input_n else None
    return {
        "level": name,
        "input": input_n,
        "accepted": accepted,
        "rejected": rejected,
        "duplicates": duplicates,
        "unsupported": unsupported,
        "unexplained": unexplained,
        "rejection_reasons": rejection_reasons or {},
        "invariant_ok": bal,
        "percent_retained": None if retained is None else round(100.0 * retained, 4),
        "note": note,
    }


def build_cohort_funnel(episodes: list[dict[str, Any]], cohort: dict[str, Any]) -> dict[str, Any]:
    mids = set(str(x) for x in cohort["capable_source_medicine_ids"])
    primary = cohort["primary_outcome"]
    five = set(V01_OUTCOME_GRAINS)

    # Level: medicine-filtered medication×outcome×unit×horizon rows from frozen JSONL
    # Grain definition (documented): one JSONL row = one medication event × outcome × unit
    # under horizon_days=365 and appointment_date hypothesis.
    matched = [e for e in episodes if str(e.get("medicine_id")) in mids]

    steps: list[dict[str, Any]] = []

    # 0. Start from concept-matched rows in frozen episode table
    n0 = len(matched)
    steps.append(
        _step(
            name="01_concept_medicine_x_outcome_rows_in_frozen_jsonl",
            input_n=n0,
            accepted=n0,
            note=(
                "Definition of 'total concept episode' in pilot reporting: "
                "count of frozen Level-4 medication×outcome×unit rows for capable "
                "source medicine IDs (not unique medication appointments)."
            ),
        )
    )

    # Unique medication events
    med_keys = {
        (e["opaque_subject_key"], str(e["medicine_id"]), str(e.get("event_ts")))
        for e in matched
    }
    steps.append(
        _step(
            name="02_unique_medication_events_derived",
            input_n=n0,
            accepted=len(med_keys),
            rejected=n0 - len(med_keys),
            rejection_reasons={
                "collapsed_multi_outcome_rows_per_medication_event": n0 - len(med_keys)
            },
            note=(
                "Not a filter applied by pilot CV; diagnostic collapse of multi-outcome "
                "expansion. Each medication appointment contributes many outcome grains."
            ),
        )
    )

    # Rows with event timestamp
    with_ts = [e for e in matched if e.get("event_ts")]
    steps.append(
        _step(
            name="03_candidate_technical_event_timestamp_present",
            input_n=n0,
            accepted=len(with_ts),
            rejected=n0 - len(with_ts),
            rejection_reasons={"missing_event_ts": n0 - len(with_ts)},
        )
    )

    # Pre/post present (already required to enter JSONL, but verify)
    with_pre_post = [
        e
        for e in with_ts
        if e.get("pre_value") is not None and e.get("post_value") is not None
    ]
    steps.append(
        _step(
            name="04_pre_and_post_numeric_present",
            input_n=len(with_ts),
            accepted=len(with_pre_post),
            rejected=len(with_ts) - len(with_pre_post),
            rejection_reasons={
                "missing_pre_or_post": len(with_ts) - len(with_pre_post)
            },
        )
    )

    # Same-time flag
    no_same = [e for e in with_pre_post if not e.get("same_time_measurement_seen")]
    steps.append(
        _step(
            name="05_same_time_lab_excluded",
            input_n=len(with_pre_post),
            accepted=len(no_same),
            rejected=len(with_pre_post) - len(no_same),
            rejection_reasons={
                "same_time_measurement_seen": len(with_pre_post) - len(no_same)
            },
        )
    )

    # Dedup by episode_id
    seen: set[str] = set()
    deduped = []
    dups = 0
    for e in no_same:
        eid = str(e.get("episode_id") or "")
        if eid and eid in seen:
            dups += 1
            continue
        if eid:
            seen.add(eid)
        deduped.append(e)
    steps.append(
        _step(
            name="06_unique_episode_id",
            input_n=len(no_same),
            accepted=len(deduped),
            duplicates=dups,
            rejected=0,
        )
    )

    # Five evaluated outcomes
    five_rows = [e for e in deduped if (e.get("outcome"), e.get("unit")) in five]
    steps.append(
        _step(
            name="07_match_one_of_five_v01_outcome_grains",
            input_n=len(deduped),
            accepted=len(five_rows),
            rejected=len(deduped) - len(five_rows),
            rejection_reasons={
                "outcome_unit_outside_five_v01_grains": len(deduped) - len(five_rows)
            },
            note=(
                "Pilot primary selection is max coverage among five grains only; "
                "most concept episodes are other lab components on the same panels."
            ),
        )
    )

    # Primary outcome
    primary_rows = [
        e
        for e in five_rows
        if (e.get("outcome"), e.get("unit")) == primary
    ]
    steps.append(
        _step(
            name="08_selected_primary_outcome_unit",
            input_n=len(five_rows),
            accepted=len(primary_rows),
            rejected=len(five_rows) - len(primary_rows),
            rejection_reasons={
                "other_of_five_grains_not_selected_as_primary": len(five_rows)
                - len(primary_rows)
            },
        )
    )

    # Unit already encoded in grain; temporal already in JSONL construction
    steps.append(
        _step(
            name="09_unit_and_temporal_rules_already_applied_upstream",
            input_n=len(primary_rows),
            accepted=len(primary_rows),
            note="Horizon=365d and strict pre/post windows applied when JSONL was built.",
        )
    )

    # Enter CV
    cv_subjects = {e["opaque_subject_key"] for e in primary_rows}
    steps.append(
        _step(
            name="10_rows_entering_subject_grouped_cv",
            input_n=len(primary_rows),
            accepted=len(primary_rows),
        )
    )
    steps.append(
        _step(
            name="11_unique_subjects_entering_cv",
            input_n=len(primary_rows),
            accepted=len(cv_subjects),
            rejected=len(primary_rows) - len(cv_subjects),
            rejection_reasons={
                "collapsed_to_unique_subjects": len(primary_rows) - len(cv_subjects)
            },
            note="Subject count for reporting; CV rows remain episode-level.",
        )
    )

    by_ou = Counter((e.get("outcome"), e.get("unit")) for e in deduped)
    per_event_n = []
    by_event: dict[tuple[str, str, str], set[tuple[Any, Any]]] = defaultdict(set)
    for e in matched:
        key = (e["opaque_subject_key"], str(e["medicine_id"]), str(e.get("event_ts")))
        by_event[key].add((e.get("outcome"), e.get("unit")))
    for v in by_event.values():
        per_event_n.append(len(v))

    unexplained_total = sum(int(s["unexplained"]) for s in steps)
    invariant_ok = all(s["invariant_ok"] for s in steps) and unexplained_total == 0

    return {
        "cohort_id": cohort["cohort_id"],
        "provider_neutral_concept_id": cohort["provider_neutral_concept_id"],
        "capable_source_medicine_ids": list(cohort["capable_source_medicine_ids"]),
        "total_concept_episode_definition": (
            "frozen_jsonl_rows_medication_x_outcome_x_unit_h365_for_capable_medicine_ids"
        ),
        "n_total_concept_episodes": n0,
        "n_unique_medication_events": len(med_keys),
        "n_subjects_all_outcomes": len({e["opaque_subject_key"] for e in matched}),
        "mean_outcomes_per_medication_event": (
            round(sum(per_event_n) / len(per_event_n), 4) if per_event_n else None
        ),
        "median_outcomes_per_medication_event": (
            sorted(per_event_n)[len(per_event_n) // 2] if per_event_n else None
        ),
        "max_outcomes_per_medication_event": max(per_event_n) if per_event_n else None,
        "n_outcome_unit_grains": len(by_ou),
        "n_five_grain_episodes": sum(by_ou[g] for g in five),
        "n_primary_episodes": len(primary_rows),
        "n_primary_subjects": len(cv_subjects),
        "primary_outcome": {"outcome": primary[0], "unit": primary[1]},
        "reported_total": cohort["reported_total_concept_episodes"],
        "reported_primary": cohort["reported_primary_episodes"],
        "matches_reported_total": n0 == cohort["reported_total_concept_episodes"],
        "matches_reported_primary": len(primary_rows)
        == cohort["reported_primary_episodes"],
        "reduction_ratio_total_to_primary": (
            round(len(primary_rows) / n0, 6) if n0 else None
        ),
        "primary_explanation": (
            f"{n0} medication×outcome×unit rows across {len(by_ou)} grains and "
            f"{len(med_keys)} unique medication events "
            f"(~{round(sum(per_event_n)/len(per_event_n),1) if per_event_n else '?'} "
            f"outcomes/event) → {len(five_rows)} in five V01 grains → "
            f"{len(primary_rows)} primary grain {primary[0]!r} {primary[1]!r}."
        ),
        "steps": steps,
        "invariant_all_ok": invariant_ok,
        "unexplained_total": unexplained_total,
    }


def build_all_funnels(root: Path) -> dict[str, Any]:
    episodes = load_episodes(root / EPISODE_JSONL)
    cohorts = [build_cohort_funnel(episodes, c) for c in PILOT_COHORTS]
    return {
        "version": VERSION,
        "EPISODE_ACCOUNTING_STATUS": (
            "PASS"
            if all(c["invariant_all_ok"] and c["matches_reported_total"] and c["matches_reported_primary"] for c in cohorts)
            else "FAIL"
        ),
        "source_episode_jsonl": EPISODE_JSONL,
        "n_jsonl_rows": len(episodes),
        "cohorts": cohorts,
    }
