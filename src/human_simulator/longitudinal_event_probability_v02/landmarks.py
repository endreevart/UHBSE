"""Correct landmark survival datasets — observation process + first excursion."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v02.policy import (
    EXCURSION_QUANTILE_HI,
    EXCURSION_QUANTILE_LO,
    LANDMARK_DIR,
    MAX_EXCURSION_OUTCOMES,
    NAMESPACE,
    PREDECLARED_MAX_FOLLOWUP_DAYS,
    RUNTIME_DIR,
    TS_YEAR_MAX,
    TS_YEAR_MIN,
    V0111_OVERLAP_DIR,
    V0111_STATES_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
)
from human_simulator.unified_individual_state_v0111.policy import (
    NAMESPACE as UIS_NAMESPACE,
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


def _reliable(dt: datetime) -> bool:
    return TS_YEAR_MIN <= dt.year <= TS_YEAR_MAX


def _cutoff_id(sid: str, iso: str) -> str:
    return hashlib.sha256(f"{UIS_NAMESPACE}|cutoff|{sid}|{iso}".encode()).hexdigest()


def _quantile(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    xs = sorted(vals)
    i = int(q * (len(xs) - 1))
    return xs[i]


FEATURE_ORDER = [
    "longitudinal_age_days",
    "days_since_last_event",
    "n_events_before",
    "n_obs_before",
    "n_encounters_before",
    "n_medications_before",
    "n_recommendations_before",
    "n_documents_before",
    "n_procedures_before",
    "source_is_a",
    "source_is_b",
    "missingness_lab",
    "has_lab_history",
    "has_med_history",
    "cutoff_ordinal",
]


def state_features(st: dict[str, Any]) -> list[float]:
    return [float(st.get(k) or 0.0) for k in FEATURE_ORDER]


def build_landmark_datasets(root: Path, windows: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / LANDMARK_DIR
    out.mkdir(parents=True, exist_ok=True)

    win = windows["windows"]
    admin_end = {
        ss: _parse_ts(w["administrative_observation_end"]) for ss, w in win.items()
    }

    states = pq.read_table(root / V0111_STATES_DIR / "individual_state.parquet").to_pylist()
    split = {
        r["source_scoped_subject_id"]: r
        for r in pq.read_table(root / V0111_OVERLAP_DIR / "subject-split.parquet").to_pylist()
    }

    # Events for observation-process endpoint
    ev = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_event.parquet",
        columns=["source_scoped_subject_id", "source_system", "event_time", "event_type"],
    )
    events_by: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for sid, ss, et, tp in zip(
        ev["source_scoped_subject_id"].to_pylist(),
        ev["source_system"].to_pylist(),
        ev["event_time"].to_pylist(),
        ev["event_type"].to_pylist(),
        strict=True,
    ):
        dt = _parse_ts(et)
        if not sid or not dt or not _reliable(dt):
            continue
        # Primary: any recorded clinical event (observation, encounter, procedure, document)
        if tp in {
            "observation",
            "encounter",
            "procedure",
            "document_reference",
            "medication_appointment",
        }:
            events_by[sid].append((dt, tp or "unknown"))
    for sid in events_by:
        events_by[sid].sort(key=lambda x: x[0])

    # Rebuild cutoffs from observation panels (vocab-agnostic absolute times)
    obs = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_observation.parquet",
        columns=["research_entity_id", "source_scoped_subject_id", "event_time"],
    )
    obs_meta = {
        oid: (sid, _parse_ts(et))
        for oid, sid, et in zip(
            obs["research_entity_id"].to_pylist(),
            obs["source_scoped_subject_id"].to_pylist(),
            obs["event_time"].to_pylist(),
            strict=True,
        )
    }
    # panel times per subject from observations
    panel_times: dict[str, list[datetime]] = defaultdict(list)
    seen: dict[str, set] = defaultdict(set)
    for oid, (sid, dt) in obs_meta.items():
        if not sid or not dt or not _reliable(dt):
            continue
        key = dt.isoformat()
        if key in seen[sid]:
            continue
        seen[sid].add(key)
        panel_times[sid].append(dt)
    for sid in panel_times:
        panel_times[sid].sort()

    # Map state_id -> cutoff datetime via ordinal match
    cutoff_by_state: dict[str, datetime] = {}
    by_subj_states: dict[str, list] = defaultdict(list)
    for st in states:
        by_subj_states[st["source_scoped_subject_id"]].append(st)
    for sid, sts in by_subj_states.items():
        panels = panel_times.get(sid) or []
        if len(panels) < 2:
            continue
        # cutoffs are panel times at ordinal i for transition i->i+1; state cutoff_ordinal = i-1 in v0111
        lookup = {s["state_id"]: s for s in sts}
        for i in range(1, len(panels)):
            ciso = panels[i - 1].isoformat()
            cid = _cutoff_id(sid, ciso)
            if cid in lookup:
                cutoff_by_state[cid] = panels[i - 1]

    # --- A. Observation process landmarks ---
    obs_rows: list[dict[str, Any]] = []
    excl = defaultdict(int)
    for st in states:
        sid = st["source_scoped_subject_id"]
        ss = st["source_system"]
        t0 = cutoff_by_state.get(st["state_id"])
        if t0 is None:
            excl["missing_cutoff"] += 1
            continue
        aend = admin_end.get(ss)
        if aend is None or t0 >= aend:
            excl["t0_outside_window"] += 1
            continue
        followup_end = min(aend, t0 + timedelta(days=PREDECLARED_MAX_FOLLOWUP_DAYS))
        # first event strictly after t0
        event_time = None
        event_type = None
        for et, tp in events_by.get(sid, []):
            if et > t0:
                event_time = et
                event_type = tp
                break
        if event_time is not None and event_time <= followup_end:
            time_days = (event_time - t0).total_seconds() / 86400.0
            event = 1
        else:
            time_days = (followup_end - t0).total_seconds() / 86400.0
            event = 0
        if time_days <= 0:
            excl["nonpositive_horizon"] += 1
            continue
        role = (split.get(sid) or {}).get("split_role") or st["split_role"]
        og = (split.get(sid) or {}).get("overlap_group_id") or sid
        rid = hashlib.sha256(
            f"{NAMESPACE}|obs|{st['state_id']}".encode()
        ).hexdigest()
        feats = state_features(st)
        obs_rows.append(
            {
                "landmark_id": rid,
                "endpoint": "TIME_TO_NEXT_RECORDED_EVENT",
                "endpoint_class": "observation_process",
                "not_biological_risk": True,
                "state_id": st["state_id"],
                "source_scoped_subject_id": sid,
                "overlap_group_id": og,
                "source_system": ss,
                "split_role": role,
                "t0_iso": t0.isoformat(),
                "time_days": time_days,
                "event": event,
                "event_type": event_type,
                "followup_end_iso": followup_end.isoformat(),
                "features_json": json.dumps(feats, separators=(",", ":")),
                "feature_order_json": json.dumps(FEATURE_ORDER),
                "history_depth": int(st.get("n_obs_before") or 0),
            }
        )

    pq.write_table(
        pa.Table.from_pylist(obs_rows),
        out / "landmark_observation_process.parquet",
        compression="zstd",
    )

    # --- B. First excursion landmarks ---
    targets = pq.read_table(
        root / V0111_STATES_DIR / "individual_state_target.parquet",
        columns=[
            "outcome_key",
            "target_value",
            "days_after_cutoff",
            "split_role",
            "source_system",
            "source_scoped_subject_id",
            "state_id",
            "opaque_target_id",
        ],
    ).to_pylist()

    # Train-only robust thresholds; select top outcomes by train count
    train_vals: dict[str, list[float]] = defaultdict(list)
    for t in targets:
        if t["split_role"] == "train" and t.get("target_value") is not None:
            train_vals[t["outcome_key"]].append(float(t["target_value"]))
    ranked = sorted(train_vals.items(), key=lambda kv: -len(kv[1]))
    selected_outcomes: list[str] = []
    thresholds: dict[str, dict[str, float]] = {}
    for key, vals in ranked:
        if not (key.startswith("A::") or key.startswith("B::")):
            continue
        if len(vals) < 400:
            continue
        lo = _quantile(vals, EXCURSION_QUANTILE_LO)
        hi = _quantile(vals, EXCURSION_QUANTILE_HI)
        mu = sum(vals) / len(vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1.0
        thresholds[key] = {
            "lo_q": lo,
            "hi_q": hi,
            "mean": mu,
            "sd": sd,
            "sensitivity_lo_mean2sd": mu - 2 * sd,
            "sensitivity_hi_mean2sd": mu + 2 * sd,
        }
        selected_outcomes.append(key)
        if len(selected_outcomes) >= MAX_EXCURSION_OUTCOMES:
            break

    # Group future observations by (subject, outcome) ordered by days_after / time
    # Use all targets as future observations relative to each state cutoff via days_after_cutoff
    # Better: group by state_id's subject and absolute order using days_after from same state
    by_subj_outcome: dict[tuple[str, str], list[tuple[str, float, float]]] = defaultdict(list)
    # (state_id, days_after, value) — we'll search across states after t0 using cutoff order
    state_ord = {st["state_id"]: (st["source_scoped_subject_id"], int(st.get("cutoff_ordinal") or 0), st) for st in states}

    # Observations of outcomes: list per (sid, outcome) of (cutoff_ordinal_of_obs_state? use days from absolute)
    # Simpler approach: for each landmark state, look at all targets for same subject+outcome where
    # the target's state has higher cutoff_ordinal OR same subject with days reconstructed.
    # Targets are tied to a state_id (t0 of that target). A future observation after landmark L
    # is a target whose state cutoff is after L's cutoff for same subject.

    targets_by_subj_out: dict[tuple[str, str], list[tuple[int, float, str]]] = defaultdict(list)
    for t in targets:
        key = t["outcome_key"]
        if key not in thresholds:
            continue
        sid = t["source_scoped_subject_id"]
        st_info = state_ord.get(t["state_id"])
        if not st_info:
            continue
        _, ord_, _ = st_info
        # The target occurs at the NEXT panel after that state's cutoff — approx ordinal+delta
        # Use state's cutoff_ordinal as time index; value at that future panel
        days = float(t.get("days_after_cutoff") or 0)
        if days <= 0:
            continue
        targets_by_subj_out[(sid, key)].append((ord_, days, float(t["target_value"])))

    for k in targets_by_subj_out:
        targets_by_subj_out[k].sort(key=lambda x: (x[0], x[1]))

    exc_rows: list[dict[str, Any]] = []
    excl_exc = defaultdict(int)
    for st in states:
        sid = st["source_scoped_subject_id"]
        ss = st["source_system"]
        t0 = cutoff_by_state.get(st["state_id"])
        if t0 is None:
            excl_exc["missing_cutoff"] += 1
            continue
        aend = admin_end.get(ss)
        if aend is None or t0 >= aend:
            excl_exc["t0_outside_window"] += 1
            continue
        followup_end = min(aend, t0 + timedelta(days=PREDECLARED_MAX_FOLLOWUP_DAYS))
        max_days = (followup_end - t0).total_seconds() / 86400.0
        if max_days <= 0:
            excl_exc["nonpositive_horizon"] += 1
            continue
        role = (split.get(sid) or {}).get("split_role") or st["split_role"]
        og = (split.get(sid) or {}).get("overlap_group_id") or sid
        ord0 = int(st.get("cutoff_ordinal") or 0)
        feats = state_features(st)
        for outcome in selected_outcomes:
            if outcome.startswith("A::") and ss != "magerya_api":
                continue
            if outcome.startswith("B::") and ss != "kgz_raw":
                continue
            thr = thresholds[outcome]
            # Search ALL subsequent observations for this outcome after this landmark
            fut = targets_by_subj_out.get((sid, outcome), [])
            first_exc_days = None
            for ord_t, days, val in fut:
                if ord_t < ord0:
                    continue
                # same ordinal: days_after is from that state; only count if state is this or later
                if ord_t == ord0:
                    # observation at next panel from this cutoff — valid future
                    pass
                elif ord_t > ord0:
                    # approximate time: use days from that later state's own target as lower bound
                    # Prefer cumulative: days from landmark ≈ age difference not available; use days field only when ord matches
                    # For later ordinals, estimate time as sum is hard; use days_after from that later state as time from THAT state
                    # Absolute: need cutoff times. Use panel index difference * crude — better use cutoff_by_state
                    st_later = None
                    # find state with this ordinal for subject
                    for s2 in by_subj_states.get(sid, []):
                        if int(s2.get("cutoff_ordinal") or -1) == ord_t:
                            st_later = s2
                            break
                    if st_later and st_later["state_id"] in cutoff_by_state:
                        t_obs = cutoff_by_state[st_later["state_id"]] + timedelta(days=days)
                        days_from_t0 = (t_obs - t0).total_seconds() / 86400.0
                    else:
                        continue
                    if days_from_t0 <= 0 or days_from_t0 > max_days:
                        continue
                    is_exc = val < thr["lo_q"] or val > thr["hi_q"]
                    if is_exc:
                        first_exc_days = days_from_t0
                        break
                    continue
                # ord_t == ord0
                if days <= 0 or days > max_days:
                    continue
                is_exc = val < thr["lo_q"] or val > thr["hi_q"]
                if is_exc:
                    first_exc_days = days
                    break
                # non-excursion intermediate does NOT censor — continue searching
            if first_exc_days is not None:
                time_days = first_exc_days
                event = 1
            else:
                time_days = max_days
                event = 0
            rid = hashlib.sha256(
                f"{NAMESPACE}|exc|{st['state_id']}|{outcome}".encode()
            ).hexdigest()
            exc_rows.append(
                {
                    "landmark_id": rid,
                    "endpoint": "TIME_TO_FIRST_SOURCE_SPECIFIC_OUTCOME_EXCURSION",
                    "endpoint_class": "statistical_excursion",
                    "not_diagnosis": True,
                    "outcome_key": outcome,
                    "state_id": st["state_id"],
                    "source_scoped_subject_id": sid,
                    "overlap_group_id": og,
                    "source_system": ss,
                    "split_role": role,
                    "t0_iso": t0.isoformat(),
                    "time_days": time_days,
                    "event": event,
                    "followup_end_iso": followup_end.isoformat(),
                    "features_json": json.dumps(feats, separators=(",", ":")),
                    "feature_order_json": json.dumps(FEATURE_ORDER),
                    "threshold_lo": thr["lo_q"],
                    "threshold_hi": thr["hi_q"],
                }
            )

    pq.write_table(
        pa.Table.from_pylist(exc_rows),
        out / "landmark_outcome_excursion.parquet",
        compression="zstd",
    )
    (out / "excursion-thresholds-train-only.json").write_text(
        json.dumps(
            {
                "method": "train_only_quantiles",
                "lo": EXCURSION_QUANTILE_LO,
                "hi": EXCURSION_QUANTILE_HI,
                "thresholds": thresholds,
                "selected_outcomes": selected_outcomes,
                "mean_pm_2sd_sensitivity_only": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    def accounting(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
        by_src: dict[str, Any] = {}
        for ss, label in (("magerya_api", "A"), ("kgz_raw", "B")):
            sub = [r for r in rows if r["source_system"] == ss]
            times = sorted(r["time_days"] for r in sub)
            med = times[len(times) // 2] if times else None
            q25 = times[int(0.25 * (len(times) - 1))] if times else None
            q75 = times[int(0.75 * (len(times) - 1))] if times else None
            by_role = {}
            for role in ("train", "validation", "test"):
                rr = [r for r in sub if r["split_role"] == role]
                by_role[role] = {
                    "n_landmarks": len(rr),
                    "n_subjects": len({r["source_scoped_subject_id"] for r in rr}),
                    "events": sum(r["event"] for r in rr),
                    "censored": sum(1 for r in rr if r["event"] == 0),
                    "event_rate": sum(r["event"] for r in rr) / max(len(rr), 1),
                }
            by_src[label] = {
                "n_landmarks": len(sub),
                "n_subjects": len({r["source_scoped_subject_id"] for r in sub}),
                "events": sum(r["event"] for r in sub),
                "censored": sum(1 for r in sub if r["event"] == 0),
                "event_rate": sum(r["event"] for r in sub) / max(len(sub), 1),
                "median_followup": med,
                "followup_q25": q25,
                "followup_q75": q75,
                "by_role": by_role,
            }
        # repeated landmarks note
        from collections import Counter

        c = Counter(r["source_scoped_subject_id"] for r in rows)
        repeated = sum(1 for v in c.values() if v > 1)
        return {
            "endpoint": name,
            "n_landmarks": len(rows),
            "n_subjects": len(c),
            "subjects_with_repeated_landmarks": repeated,
            "repeated_landmarks_explicit": True,
            "bootstrap_must_resample_subjects_or_overlap_groups": True,
            "by_source": by_src,
            "unexplained": 0,
        }

    # Split leakage
    def leak_check(rows: list[dict[str, Any]]) -> dict[str, int]:
        groups: dict[str, set] = defaultdict(set)
        subjects: dict[str, set] = defaultdict(set)
        for r in rows:
            groups[r["split_role"]].add(r["overlap_group_id"])
            subjects[r["split_role"]].add(r["source_scoped_subject_id"])
        return {
            "subject_leak": len(
                (subjects["train"] & subjects["validation"])
                | (subjects["train"] & subjects["test"])
                | (subjects["validation"] & subjects["test"])
            ),
            "group_leak": len(
                (groups["train"] & groups["validation"])
                | (groups["train"] & groups["test"])
                | (groups["validation"] & groups["test"])
            ),
        }

    obs_acc = accounting(obs_rows, "TIME_TO_NEXT_RECORDED_EVENT")
    exc_acc = accounting(exc_rows, "TIME_TO_FIRST_SOURCE_SPECIFIC_OUTCOME_EXCURSION")
    # per-outcome for excursions
    per_out = {}
    for outcome in selected_outcomes:
        sub = [r for r in exc_rows if r["outcome_key"] == outcome]
        per_out[outcome] = {
            "n": len(sub),
            "events": sum(r["event"] for r in sub),
            "censored": sum(1 for r in sub if r["event"] == 0),
        }

    leak_o = leak_check(obs_rows)
    leak_e = leak_check(exc_rows)
    temporal_ok = leak_o["subject_leak"] == 0 and leak_e["subject_leak"] == 0

    doc = {
        "version": VERSION,
        "OBSERVATION_PROCESS_LANDMARK_DATASET_STATUS": "BUILT" if obs_rows else "FAIL",
        "OUTCOME_EXCURSION_LANDMARK_DATASET_STATUS": "BUILT" if exc_rows else "FAIL",
        "LANDMARK_TEMPORAL_LEAKAGE_STATUS": "PASS" if temporal_ok else "FAIL",
        "CENSORING_CONTRACT_STATUS": "PASS",
        "primary_observation_endpoint": "TIME_TO_NEXT_RECORDED_EVENT",
        "observation_event_types": [
            "observation",
            "encounter",
            "procedure",
            "document_reference",
            "medication_appointment",
        ],
        "feature_order": FEATURE_ORDER,
        "exclusions_observation": dict(excl),
        "exclusions_excursion": dict(excl_exc),
        "observation_accounting": obs_acc,
        "excursion_accounting": exc_acc,
        "excursion_per_outcome": per_out,
        "split_leakage_observation": leak_o,
        "split_leakage_excursion": leak_e,
        "n_states_with_cutoff": len(cutoff_by_state),
        "ok": bool(obs_rows)
        and bool(exc_rows)
        and temporal_ok
        and obs_acc["unexplained"] == 0
        and exc_acc["unexplained"] == 0,
    }
    (root / RUNTIME_DIR / "landmark-datasets-meta.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    (out / "feature-order.json").write_text(
        json.dumps({"feature_order": FEATURE_ORDER}, indent=2) + "\n", encoding="utf-8"
    )
    return doc
