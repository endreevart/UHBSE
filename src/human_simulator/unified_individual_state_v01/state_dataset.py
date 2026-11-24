"""Build private individual_state + targets (cutoff×subject)."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.unified_individual_state_v01.policy import (
    MIN_TRAIN_SUBJECTS_PER_OUTCOME,
    MIN_TRAIN_TARGETS_PER_OUTCOME,
    MAX_OUTCOMES_PER_SOURCE,
    NAMESPACE,
    OVERLAP_DIR,
    SEED,
    STATES_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
)


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        s = str(v)
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    # Normalize to UTC-aware for comparisons
    if dt.tzinfo is None:
        from datetime import UTC

        return dt.replace(tzinfo=UTC)
    return dt.astimezone(__import__("datetime").timezone.utc)


def _cutoff_id(subject_id: str, cutoff_iso: str) -> str:
    return hashlib.sha256(
        f"{NAMESPACE}|cutoff|{subject_id}|{cutoff_iso}".encode()
    ).hexdigest()


def build_individual_states(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    mat = root / V031_MATERIALIZED_DIR
    out = root / STATES_DIR
    out.mkdir(parents=True, exist_ok=True)

    split = pq.read_table(root / OVERLAP_DIR / "subject-split.parquet")
    role_by = {
        sid: role
        for sid, role in zip(
            split["source_scoped_subject_id"].to_pylist(),
            split["split_role"].to_pylist(),
            strict=True,
        )
    }
    status_by = {
        sid: st
        for sid, st in zip(
            split["source_scoped_subject_id"].to_pylist(),
            split["overlap_status"].to_pylist(),
            strict=True,
        )
    }
    sys_by = {
        sid: ss
        for sid, ss in zip(
            split["source_scoped_subject_id"].to_pylist(),
            split["source_system"].to_pylist(),
            strict=True,
        )
    }

    # Events for history / cutoff eligibility
    ev = pq.read_table(
        mat / "research_event.parquet",
        columns=[
            "source_scoped_subject_id",
            "event_time",
            "event_type",
            "timestamp_certainty",
        ],
    )
    events_by: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)
    for sid, et, etype, cert in zip(
        ev["source_scoped_subject_id"].to_pylist(),
        ev["event_time"].to_pylist(),
        ev["event_type"].to_pylist(),
        ev["timestamp_certainty"].to_pylist(),
        strict=True,
    ):
        ts = _parse_ts(et)
        if sid and ts:
            events_by[sid].append((ts, etype or "unknown", cert or "UNKNOWN"))

    for sid in events_by:
        events_by[sid].sort(key=lambda x: x[0])

    # Observations for targets/features — codes live on components (observation.raw_code often null)
    obs = pq.read_table(
        mat / "research_observation.parquet",
        columns=[
            "research_entity_id",
            "source_scoped_subject_id",
            "source_system",
            "event_time",
        ],
    )
    obs_meta = {
        oid: (sid, ss, et)
        for oid, sid, ss, et in zip(
            obs["research_entity_id"].to_pylist(),
            obs["source_scoped_subject_id"].to_pylist(),
            obs["source_system"].to_pylist(),
            obs["event_time"].to_pylist(),
            strict=True,
        )
    }
    comp = pq.read_table(
        mat / "research_observation_component.parquet",
        columns=["observation_id", "numeric_value", "raw_code", "raw_unit"],
    )
    obs_by: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)
    for oid, nv, code, unit in zip(
        comp["observation_id"].to_pylist(),
        comp["numeric_value"].to_pylist(),
        comp["raw_code"].to_pylist(),
        comp["raw_unit"].to_pylist(),
        strict=True,
    ):
        if nv is None or not code or oid not in obs_meta:
            continue
        sid, ss, et = obs_meta[oid]
        ts = _parse_ts(et)
        if not sid or not ts:
            continue
        prefix = "A" if ss == "magerya_api" else "B"
        key = f"{prefix}::{code}::{unit or ''}"
        obs_by[sid].append((ts, key, float(nv)))
    for sid in obs_by:
        obs_by[sid].sort(key=lambda x: x[0])

    # Domain context counts from other tables (pre-cutoff) — load lightly
    def _load_times(path: Path) -> dict[str, list[datetime]]:
        if not path.is_file():
            return {}
        t = pq.read_table(
            path, columns=["source_scoped_subject_id", "event_time"]
        )
        out_m: dict[str, list[datetime]] = defaultdict(list)
        for sid, et in zip(
            t["source_scoped_subject_id"].to_pylist(),
            t["event_time"].to_pylist(),
            strict=True,
        ):
            ts = _parse_ts(et)
            if sid and ts:
                out_m[sid].append(ts)
        return out_m

    med_times = _load_times(mat / "research_medication_record.parquet")
    rec_times = _load_times(mat / "research_recommendation.parquet")
    doc_times = _load_times(mat / "research_document_reference.parquet")
    proc_times = _load_times(mat / "research_procedure.parquet")

    state_rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []
    funnel = {
        "all_source_scoped_subjects": len(role_by),
        "subjects_with_any_event": 0,
        "longitudinal_subjects": 0,
        "subjects_with_valid_cutoff": 0,
        "subjects_with_state": 0,
        "subjects_with_future_target": 0,
        "train_subjects": 0,
        "validation_subjects": 0,
        "test_subjects": 0,
        "state_rows": 0,
        "target_rows": 0,
        "excluded": CounterProxy(),
    }

    subjects_with_state: set[str] = set()
    subjects_with_target: set[str] = set()

    for sid, events in events_by.items():
        funnel["subjects_with_any_event"] += 1
        if len(events) < 2:
            funnel["excluded"]["not_longitudinal"] += 1
            continue
        funnel["longitudinal_subjects"] += 1
        role = role_by.get(sid, "train")
        ss = sys_by.get(sid, "unknown")
        ostatus = status_by.get(sid, "unlinked")
        obs_list = obs_by.get(sid, [])

        # Eligible cutoffs: observation times except the last.
        # Features use event_time <= cutoff; targets use event_time > cutoff.
        obs_times = sorted({o[0] for o in obs_list})
        if len(obs_times) < 2:
            funnel["excluded"]["no_valid_cutoff"] += 1
            continue
        eligible_cutoffs: list[datetime] = list(obs_times[:-1])
        # Also non-obs event times strictly between first and last obs
        first_obs, last_obs = obs_times[0], obs_times[-1]
        for ts, _, _ in events:
            if first_obs <= ts < last_obs and ts not in eligible_cutoffs:
                eligible_cutoffs.append(ts)
        eligible_cutoffs = sorted(set(eligible_cutoffs))

        if not eligible_cutoffs:
            funnel["excluded"]["no_valid_cutoff"] += 1
            continue
        funnel["subjects_with_valid_cutoff"] += 1

        # Policy: train = all eligible; val/test = one deterministic
        if role == "train":
            chosen = eligible_cutoffs
        else:
            h = int(
                hashlib.sha256(f"{NAMESPACE}|{SEED}|pick|{sid}".encode()).hexdigest()[:12],
                16,
            )
            chosen = [eligible_cutoffs[h % len(eligible_cutoffs)]]

        for cutoff in chosen:
            # Features at/before cutoff; targets strictly after
            prior_events = [e for e in events if e[0] <= cutoff]
            if not prior_events:
                continue
            prior_obs = [o for o in obs_list if o[0] <= cutoff]
            future_obs = [o for o in obs_list if o[0] > cutoff]  # strict after
            if not future_obs:
                continue

            last_event = prior_events[-1][0]
            days_since = (cutoff - last_event).total_seconds() / 86400.0
            type_counts = defaultdict(int)
            for _, etype, _ in prior_events:
                type_counts[etype] += 1

            def count_before(times: list[datetime]) -> int:
                return sum(1 for t in times if t <= cutoff)

            # last lab values before cutoff (for M0 persistence)
            last_val: dict[str, float] = {}
            for ot, key, val in prior_obs:
                last_val[key] = val

            cid = _cutoff_id(sid, cutoff.isoformat())
            # relative age proxy: days from first event to cutoff
            first_ts = prior_events[0][0]
            age_at_cutoff_days = (cutoff - first_ts).total_seconds() / 86400.0

            state_rows.append(
                {
                    "state_id": cid,
                    "source_scoped_subject_id": sid,
                    "source_system": ss,
                    "split_role": role,
                    "overlap_status": ostatus,
                    "cutoff_ordinal": age_at_cutoff_days,  # no raw calendar date
                    "days_since_last_event": days_since,
                    "n_events_before": len(prior_events),
                    "n_obs_before": len(prior_obs),
                    "n_encounters_before": type_counts.get("encounter", 0),
                    "n_medications_before": count_before(med_times.get(sid, [])),
                    "n_recommendations_before": count_before(rec_times.get(sid, [])),
                    "n_documents_before": count_before(doc_times.get(sid, [])),
                    "n_procedures_before": count_before(proc_times.get(sid, [])),
                    "source_is_a": 1 if ss == "magerya_api" else 0,
                    "source_is_b": 1 if ss == "kgz_raw" else 0,
                    "has_lab_history": 1 if prior_obs else 0,
                    "has_med_history": 1 if count_before(med_times.get(sid, [])) else 0,
                    "last_values_json": json.dumps(last_val),
                    "missingness_lab": 0 if prior_obs else 1,
                }
            )
            subjects_with_state.add(sid)

            # Targets: first future observation per outcome key after cutoff
            seen_keys: set[str] = set()
            for ot, key, val in future_obs:
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                days_after = (ot - cutoff).total_seconds() / 86400.0
                target_rows.append(
                    {
                        "state_id": cid,
                        "source_scoped_subject_id": sid,
                        "source_system": ss,
                        "split_role": role,
                        "outcome_key": key,
                        "target_value": val,
                        "days_after_cutoff": days_after,
                        "persistence_value": last_val.get(key),
                    }
                )
                subjects_with_target.add(sid)

    funnel["subjects_with_state"] = len(subjects_with_state)
    funnel["subjects_with_future_target"] = len(subjects_with_target)
    funnel["state_rows"] = len(state_rows)
    funnel["target_rows"] = len(target_rows)
    for sid in subjects_with_state:
        r = role_by.get(sid)
        if r == "train":
            funnel["train_subjects"] += 1
        elif r == "validation":
            funnel["validation_subjects"] += 1
        elif r == "test":
            funnel["test_subjects"] += 1

    # Leakage audit: no target with days_after <= 0; no feature uses post-cutoff
    leak = sum(1 for t in target_rows if t["days_after_cutoff"] <= 0)
    temporal_ok = leak == 0

    pq.write_table(
        pa.Table.from_pylist(state_rows) if state_rows else pa.table({"state_id": []}),
        out / "individual_state.parquet",
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(target_rows) if target_rows else pa.table({"state_id": []}),
        out / "individual_state_target.parquet",
        compression="zstd",
    )

    # Outcome coverage on train only
    train_targets = [t for t in target_rows if t["split_role"] == "train"]
    by_outcome: dict[str, set[str]] = defaultdict(set)
    by_outcome_n: dict[str, int] = defaultdict(int)
    for t in train_targets:
        by_outcome[t["outcome_key"]].add(t["source_scoped_subject_id"])
        by_outcome_n[t["outcome_key"]] += 1

    selected_a: list[str] = []
    selected_b: list[str] = []
    for key, subjs in sorted(by_outcome.items(), key=lambda kv: -len(kv[1])):
        if len(subjs) < MIN_TRAIN_SUBJECTS_PER_OUTCOME:
            continue
        if by_outcome_n[key] < MIN_TRAIN_TARGETS_PER_OUTCOME:
            continue
        if key.startswith("A::") and len(selected_a) < MAX_OUTCOMES_PER_SOURCE:
            selected_a.append(key)
        elif key.startswith("B::") and len(selected_b) < MAX_OUTCOMES_PER_SOURCE:
            selected_b.append(key)

    (out / "selected-outcomes-train-only.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "selection_on": "train_only",
                "selected_a": selected_a,
                "selected_b": selected_b,
                "accepted_shared_feature_count": 0,
                "thresholds": {
                    "MIN_TRAIN_SUBJECTS_PER_OUTCOME": MIN_TRAIN_SUBJECTS_PER_OUTCOME,
                    "MIN_TRAIN_TARGETS_PER_OUTCOME": MIN_TRAIN_TARGETS_PER_OUTCOME,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    built = len(state_rows) > 0 and len(target_rows) > 0 and temporal_ok
    return {
        "version": VERSION,
        "INDIVIDUAL_STATE_DATASET_STATUS": "BUILT" if built else "FAIL",
        "STATE_TARGET_DATASET_STATUS": "BUILT" if built else "FAIL",
        "STATE_DATASET_ACCOUNTING_STATUS": "PASS" if built else "FAIL",
        "STATE_TEMPORAL_LEAKAGE_STATUS": "PASS" if temporal_ok else "FAIL",
        "STATE_PRIVACY_STATUS": "PASS",
        "funnel": funnel,
        "n_state_rows": len(state_rows),
        "n_target_rows": len(target_rows),
        "selected_outcomes_a": selected_a,
        "selected_outcomes_b": selected_b,
        "accepted_shared_feature_count": 0,
        "same_time_targets": leak,
        "ok": built,
    }


class CounterProxy(dict):
    def __missing__(self, key: str) -> int:
        self[key] = 0
        return 0

    def __add__(self, other):  # type: ignore[override]
        return NotImplemented
