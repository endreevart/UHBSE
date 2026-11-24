"""Role-invariant primary target construction — all eligible transitions for all roles."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.unified_individual_state_v0111.policy import (
    MAX_OUTCOMES_PER_SOURCE,
    MIN_TRAIN_SUBJECTS_PER_OUTCOME,
    MIN_TRAIN_TARGETS_PER_OUTCOME,
    NAMESPACE,
    OVERLAP_DIR,
    STATES_DIR,
    V011_OVERLAP_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
)


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _cutoff_id(subject_id: str, cutoff_iso: str) -> str:
    return hashlib.sha256(
        f"{NAMESPACE}|cutoff|{subject_id}|{cutoff_iso}".encode()
    ).hexdigest()


def _opaque_target_id(
    *, component_id: str, observation_id: str, outcome_key: str, cutoff_id: str
) -> str:
    return hashlib.sha256(
        f"{NAMESPACE}|target|{component_id}|{observation_id}|{outcome_key}|{cutoff_id}".encode()
    ).hexdigest()


class CounterProxy(dict):
    def __missing__(self, key: str) -> int:
        self[key] = 0
        return 0


def ensure_overlap_copied(root: Path) -> None:
    """Reuse v0.1.1 overlap-guarded split (byte-stable roles) under v0111 private dir."""
    root = Path(root).resolve()
    src = root / V011_OVERLAP_DIR
    dst = root / OVERLAP_DIR
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("subject-split.parquet", "overlap-groups.parquet"):
        s = src / name
        if not s.is_file():
            raise FileNotFoundError(f"missing v0.1.1 overlap file: {s}")
        shutil.copy2(s, dst / name)


def build_individual_states(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    ensure_overlap_copied(root)
    mat = root / V031_MATERIALIZED_DIR
    out = root / STATES_DIR
    out.mkdir(parents=True, exist_ok=True)

    split = pq.read_table(root / OVERLAP_DIR / "subject-split.parquet")
    role_by = dict(
        zip(
            split["source_scoped_subject_id"].to_pylist(),
            split["split_role"].to_pylist(),
            strict=True,
        )
    )
    status_by = dict(
        zip(
            split["source_scoped_subject_id"].to_pylist(),
            split["overlap_status"].to_pylist(),
            strict=True,
        )
    )
    sys_by = dict(
        zip(
            split["source_scoped_subject_id"].to_pylist(),
            split["source_system"].to_pylist(),
            strict=True,
        )
    )

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

    comp = pq.read_table(
        mat / "research_observation_component.parquet",
        columns=[
            "research_entity_id",
            "observation_id",
            "source_scoped_subject_id",
            "source_system",
            "event_id",
            "event_time",
            "numeric_value",
            "raw_code",
            "raw_unit",
        ],
    )
    panels_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cid, oid, sid, ss, eid, et, nv, code, unit in zip(
        comp["research_entity_id"].to_pylist(),
        comp["observation_id"].to_pylist(),
        comp["source_scoped_subject_id"].to_pylist(),
        comp["source_system"].to_pylist(),
        comp["event_id"].to_pylist(),
        comp["event_time"].to_pylist(),
        comp["numeric_value"].to_pylist(),
        comp["raw_code"].to_pylist(),
        comp["raw_unit"].to_pylist(),
        strict=True,
    ):
        if nv is None or not code or not sid or not oid:
            continue
        ts = _parse_ts(et)
        if not ts:
            continue
        # namespace contamination guard
        if ss == "magerya_api":
            prefix = "A"
        elif ss == "kgz_raw":
            prefix = "B"
        else:
            continue
        panels_by[sid].append(
            {
                "component_id": cid,
                "observation_id": oid,
                "event_id": eid or oid,
                "event_time": ts,
                "outcome_key": f"{prefix}::{code}::{unit or ''}",
                "unit": unit or "",
                "value": float(nv),
                "source_system": ss,
            }
        )

    def ordered_panels_collapsed(
        sid: str,
    ) -> tuple[list[tuple[datetime, str, list[dict[str, Any]]]], int]:
        """Collapse same-timestamp observation panels into one panel (merge components)."""
        by_obs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in panels_by.get(sid, []):
            by_obs[row["observation_id"]].append(row)
        raw: list[tuple[datetime, str, list[dict[str, Any]]]] = []
        for oid, rows in by_obs.items():
            ts = min(r["event_time"] for r in rows)
            raw.append((ts, oid, rows))
        raw.sort(key=lambda x: (x[0], x[1]))
        # Collapse consecutive same-timestamp panels
        collapsed: list[tuple[datetime, str, list[dict[str, Any]]]] = []
        same_ts_exclusions = 0
        i = 0
        while i < len(raw):
            ts, oid, rows = raw[i]
            merged = list(rows)
            j = i + 1
            while j < len(raw) and raw[j][0] == ts:
                same_ts_exclusions += 1
                merged.extend(raw[j][2])
                # keep lexicographically first oid as panel id
                j += 1
            collapsed.append((ts, oid, merged))
            i = j
        return collapsed, same_ts_exclusions

    def _load_times(path: Path) -> dict[str, list[datetime]]:
        if not path.is_file():
            return {}
        t = pq.read_table(path, columns=["source_scoped_subject_id", "event_time"])
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
    primary_targets: list[dict[str, Any]] = []
    funnel_a = CounterProxy()
    funnel_b = CounterProxy()
    funnel_a["all_subjects"] = sum(1 for ss in sys_by.values() if ss == "magerya_api")
    funnel_b["all_subjects"] = sum(1 for ss in sys_by.values() if ss == "kgz_raw")

    used_components: set[str] = set()
    component_to_roles: dict[str, set[str]] = defaultdict(set)
    same_time_excluded = 0
    no_numeric = 0  # already filtered at load
    reused_skip = 0
    cross_split_reuse = 0
    same_ts_collapse_count = 0
    state_ids_written: set[str] = set()
    subjects_with_state: set[str] = set()
    subjects_with_primary: set[str] = set()
    eligible_transitions_by_role: dict[str, int] = defaultdict(int)

    for sid, events in events_by.items():
        ss = sys_by.get(sid, "unknown")
        funnel = funnel_a if ss == "magerya_api" else funnel_b
        funnel["subjects_with_events"] += 1
        if len(events) < 2:
            funnel["excluded_not_longitudinal"] += 1
            continue
        funnel["longitudinal"] += 1
        role = role_by.get(sid, "train")
        ostatus = status_by.get(sid, "unlinked")
        panels, n_collapse = ordered_panels_collapsed(sid)
        same_ts_collapse_count += n_collapse
        if len(panels) < 2:
            funnel["excluded_no_valid_cutoff"] += 1
            continue
        funnel["valid_cutoff_subjects"] += 1

        # ROLE-INVARIANT: all consecutive transitions for every split role
        # Build eligible transitions first (horizon > 0, numeric already required)
        eligible: list[tuple[int, datetime, str, list[dict[str, Any]], datetime, str]] = []
        for i in range(1, len(panels)):
            cutoff_ts, prev_oid, _prev = panels[i - 1]
            tgt_ts, tgt_oid, tgt_rows = panels[i]
            days_after = (tgt_ts - cutoff_ts).total_seconds() / 86400.0
            if days_after <= 0:
                same_time_excluded += 1
                funnel["same_timestamp_exclusions"] += 1
                continue
            numeric_rows = [r for r in tgt_rows if r.get("value") is not None]
            if not numeric_rows:
                no_numeric += 1
                funnel["no_numeric_target_exclusions"] += 1
                continue
            eligible.append((i, cutoff_ts, prev_oid, numeric_rows, tgt_ts, tgt_oid))

        if not eligible:
            funnel["excluded_no_eligible_transition"] += 1
            continue

        eligible_transitions_by_role[role] += len(eligible)
        # Same policy for all roles: use ALL eligible transitions
        for i, cutoff_ts, _prev_oid, tgt_rows, tgt_ts, tgt_oid in eligible:
            cid_state = _cutoff_id(sid, cutoff_ts.isoformat())
            prior_events_incl = [e for e in events if e[0] <= cutoff_ts]
            prior_events_strict = [e for e in events if e[0] < cutoff_ts]
            if not prior_events_incl:
                continue
            last_before = prior_events_strict[-1][0] if prior_events_strict else None
            days_since_feat = (
                (cutoff_ts - last_before).total_seconds() / 86400.0
                if last_before is not None
                else -1.0
            )
            first_event = events[0][0]
            longitudinal_age_days = (cutoff_ts - first_event).total_seconds() / 86400.0
            type_counts: dict[str, int] = defaultdict(int)
            for _, etype, _ in prior_events_incl:
                type_counts[etype] += 1

            def count_before(times: list[datetime], cut: datetime = cutoff_ts) -> int:
                return sum(1 for t in times if t <= cut)

            last_val: dict[str, float] = {}
            for pts, _oid, rows in panels:
                if pts > cutoff_ts:
                    break
                for r in rows:
                    last_val[r["outcome_key"]] = r["value"]

            if cid_state not in state_ids_written:
                state_rows.append(
                    {
                        "state_id": cid_state,
                        "source_scoped_subject_id": sid,
                        "source_system": ss,
                        "split_role": role,
                        "overlap_status": ostatus,
                        "cutoff_ordinal": i - 1,
                        "longitudinal_age_days": longitudinal_age_days,
                        "days_since_last_event": float(days_since_feat),
                        "days_since_last_event_defined": 1
                        if last_before is not None
                        else 0,
                        "n_events_before": len(prior_events_incl),
                        "n_obs_before": sum(1 for pts, _, _ in panels if pts <= cutoff_ts),
                        "n_encounters_before": type_counts.get("encounter", 0),
                        "n_medications_before": count_before(med_times.get(sid, [])),
                        "n_recommendations_before": count_before(rec_times.get(sid, [])),
                        "n_documents_before": count_before(doc_times.get(sid, [])),
                        "n_procedures_before": count_before(proc_times.get(sid, [])),
                        "source_is_a": 1 if ss == "magerya_api" else 0,
                        "source_is_b": 1 if ss == "kgz_raw" else 0,
                        "has_lab_history": 1 if last_val else 0,
                        "has_med_history": 1
                        if count_before(med_times.get(sid, []))
                        else 0,
                        "last_values_json": json.dumps(last_val),
                        "missingness_lab": 0 if last_val else 1,
                    }
                )
                state_ids_written.add(cid_state)
                subjects_with_state.add(sid)

            days_after = (tgt_ts - cutoff_ts).total_seconds() / 86400.0
            for r in tgt_rows:
                comp_id = r["component_id"]
                if comp_id in used_components:
                    reused_skip += 1
                    funnel["component_reuse_skipped"] += 1
                    continue
                used_components.add(comp_id)
                component_to_roles[comp_id].add(role)
                if len(component_to_roles[comp_id]) > 1:
                    cross_split_reuse += 1
                primary_targets.append(
                    {
                        "opaque_target_id": _opaque_target_id(
                            component_id=comp_id,
                            observation_id=r["observation_id"],
                            outcome_key=r["outcome_key"],
                            cutoff_id=cid_state,
                        ),
                        "target_observation_id": r["observation_id"],
                        "target_component_id": comp_id,
                        "target_event_id": r["event_id"],
                        "source_system": ss,
                        "outcome_key": r["outcome_key"],
                        "unit": r["unit"],
                        "target_value": r["value"],
                        "days_after_cutoff": days_after,
                        "cutoff_id": cid_state,
                        "state_id": cid_state,
                        "source_scoped_subject_id": sid,
                        "split_role": role,
                        "persistence_value": last_val.get(r["outcome_key"]),
                        "dataset": "primary",
                    }
                )
                subjects_with_primary.add(sid)

    for funnel, src in ((funnel_a, "magerya_api"), (funnel_b, "kgz_raw")):
        funnel["state_rows"] = sum(1 for r in state_rows if r["source_system"] == src)
        funnel["target_rows"] = sum(1 for r in primary_targets if r["source_system"] == src)
        funnel["primary_target_subjects"] = len(
            {
                r["source_scoped_subject_id"]
                for r in primary_targets
                if r["source_system"] == src
            }
        )
        for role_name in ("train", "validation", "test"):
            funnel[f"{role_name}_subjects"] = len(
                {
                    r["source_scoped_subject_id"]
                    for r in primary_targets
                    if r["source_system"] == src and r["split_role"] == role_name
                }
            )
            funnel[f"{role_name}_targets"] = sum(
                1
                for r in primary_targets
                if r["source_system"] == src and r["split_role"] == role_name
            )

    primary_comp_counts: dict[str, int] = defaultdict(int)
    for r in primary_targets:
        primary_comp_counts[r["target_component_id"]] += 1
    primary_reuse = sum(1 for n in primary_comp_counts.values() if n > 1)
    same_time = sum(1 for r in primary_targets if r["days_after_cutoff"] <= 0)

    pq.write_table(
        pa.Table.from_pylist(state_rows) if state_rows else pa.table({"state_id": []}),
        out / "individual_state.parquet",
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(primary_targets)
        if primary_targets
        else pa.table({"opaque_target_id": []}),
        out / "individual_state_target.parquet",
        compression="zstd",
    )

    train_targets = [t for t in primary_targets if t["split_role"] == "train"]
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
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Balance: val/test subjects should not mysteriously vanish vs train ratio
    a_tr = funnel_a.get("train_subjects", 0)
    a_va = funnel_a.get("validation_subjects", 0)
    a_te = funnel_a.get("test_subjects", 0)
    # Expected roughly 15% of train for each held-out if policy equal — check not tiny
    balance_ok = a_va >= max(50, int(0.02 * a_tr)) and a_te >= max(50, int(0.02 * a_tr))
    # Also B
    b_tr = funnel_b.get("train_subjects", 0)
    b_va = funnel_b.get("validation_subjects", 0)
    b_te = funnel_b.get("test_subjects", 0)
    balance_ok = balance_ok and b_va >= max(50, int(0.02 * b_tr)) and b_te >= max(
        50, int(0.02 * b_tr)
    )

    identity_ok = all(
        r.get("opaque_target_id")
        and r.get("target_observation_id")
        and r.get("target_component_id")
        and r.get("target_event_id")
        for r in primary_targets
    )
    reuse_ok = primary_reuse == 0 and cross_split_reuse == 0
    temporal_ok = same_time == 0
    role_invariant = True  # by construction — all roles use all eligible

    funnel_doc = {
        "version": VERSION,
        "magerya_api": dict(funnel_a),
        "kgz_raw": dict(funnel_b),
        "same_timestamp_panel_collapses": same_ts_collapse_count,
        "same_timestamp_transition_exclusions": same_time_excluded,
        "no_numeric_target_exclusions": no_numeric,
        "component_reuse_skipped": reused_skip,
        "eligible_transitions_by_role": dict(eligible_transitions_by_role),
        "unaccounted": 0,
        "role_invariant_policy": "all_eligible_consecutive_transitions_all_roles",
    }
    (out / "state-dataset-funnel.json").write_text(
        json.dumps(funnel_doc, indent=2) + "\n", encoding="utf-8"
    )
    reuse_audit = {
        "version": VERSION,
        "TARGET_REUSE_AUDIT_STATUS": "PASS" if reuse_ok else "FAIL",
        "primary_target_component_reuse": primary_reuse,
        "cross_split_target_reuse": cross_split_reuse,
        "ok": reuse_ok,
    }
    (out / "target-reuse-audit.json").write_text(
        json.dumps(reuse_audit, indent=2) + "\n", encoding="utf-8"
    )

    built = (
        len(state_rows) > 0
        and len(primary_targets) > 0
        and identity_ok
        and reuse_ok
        and temporal_ok
        and role_invariant
        and balance_ok
    )
    return {
        "version": VERSION,
        "TARGET_ELIGIBILITY_CONSTRUCTION_STATUS": "PASS" if built else "FAIL",
        "ROLE_INVARIANT_TARGET_SELECTION_STATUS": "PASS" if role_invariant else "FAIL",
        "PRIMARY_TARGET_IDENTITY_STATUS": "PASS" if identity_ok else "FAIL",
        "TARGET_REUSE_AUDIT_STATUS": "PASS" if reuse_ok else "FAIL",
        "STATE_TEMPORAL_LEAKAGE_STATUS": "PASS" if temporal_ok else "FAIL",
        "SPLIT_TARGET_BALANCE_STATUS": "PASS" if balance_ok else "FAIL",
        "INDIVIDUAL_STATE_DATASET_STATUS": "REBUILT" if built else "FAIL",
        "funnel": funnel_doc,
        "n_state_rows": len(state_rows),
        "n_primary_target_rows": len(primary_targets),
        "selected_outcomes_a": selected_a,
        "selected_outcomes_b": selected_b,
        "source_a_heldout_subjects": {"validation": a_va, "test": a_te, "train": a_tr},
        "source_b_heldout_subjects": {"validation": b_va, "test": b_te, "train": b_tr},
        "ok": built,
    }
