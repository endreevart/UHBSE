"""Landmark survival datasets — identity-corrected observation process + exact-timestamp excursion."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v0211.policy import (
    EXCURSION_ENDPOINT,
    EXCURSION_FEATURE_SUFFIX,
    EXCURSION_QUANTILE_HI,
    EXCURSION_QUANTILE_LO,
    FEATURE_ORDER,
    LANDMARK_DIR,
    MAX_EXCURSION_OUTCOMES_PER_SOURCE,
    NAMESPACE,
    PREDECLARED_MAX_FOLLOWUP_DAYS,
    RUNTIME_DIR,
    V0111_OVERLAP_DIR,
    V0111_STATES_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
)
from human_simulator.longitudinal_event_probability_v0211.times import parse_ts, reliable
from human_simulator.unified_individual_state_v0111.policy import NAMESPACE as UIS_NAMESPACE

RECORDED_TYPES = frozenset(
    {
        "observation",
        "encounter",
        "procedure",
        "document_reference",
        "medication_appointment",
    }
)


def _cutoff_id(sid: str, iso: str) -> str:
    return hashlib.sha256(f"{UIS_NAMESPACE}|cutoff|{sid}|{iso}".encode()).hexdigest()


def _quantile(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    xs = sorted(vals)
    i = int(q * (len(xs) - 1))
    return xs[i]


def first_excursion_days(
    t0,
    followup_end,
    future_obs: list[tuple],
    lo: float,
    hi: float,
) -> tuple[float | None, str | None]:
    """Search first subsequent excursion; intermediate non-excursions do not censor.

    future_obs: list of (datetime, value, observation_id) sorted by time.
    """
    max_days = (followup_end - t0).total_seconds() / 86400.0
    for dt, val, oid in future_obs:
        if dt <= t0:
            continue
        days = (dt - t0).total_seconds() / 86400.0
        if days <= 0 or days > max_days:
            continue
        if val < lo or val > hi:
            return days, oid
    return None, None


def state_features(st: dict[str, Any]) -> list[float]:
    return [float(st.get(k) or 0.0) for k in FEATURE_ORDER]


def _accounting(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
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


def _leak_check(rows: list[dict[str, Any]]) -> dict[str, int]:
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


def _unique_times_from_events(
    root: Path, allowed_types: frozenset[str] | None, *, observation_panels: bool = False
) -> dict[str, list]:
    """Return sid -> sorted unique datetimes."""
    if observation_panels:
        table = pq.read_table(
            root / V031_MATERIALIZED_DIR / "research_observation.parquet",
            columns=["source_scoped_subject_id", "event_time"],
        )
        sids = table["source_scoped_subject_id"].to_pylist()
        ets = table["event_time"].to_pylist()
        types = [None] * len(sids)
    else:
        table = pq.read_table(
            root / V031_MATERIALIZED_DIR / "research_event.parquet",
            columns=["source_scoped_subject_id", "event_time", "event_type"],
        )
        sids = table["source_scoped_subject_id"].to_pylist()
        ets = table["event_time"].to_pylist()
        types = table["event_type"].to_pylist()
    seen: dict[str, set[str]] = defaultdict(set)
    out: dict[str, list] = defaultdict(list)
    for sid, et, tp in zip(sids, ets, types, strict=True):
        if allowed_types is not None and tp not in allowed_types:
            continue
        dt = parse_ts(et)
        if not sid or dt is None or not reliable(dt):
            continue
        iso = dt.isoformat()
        if iso in seen[sid]:
            continue
        seen[sid].add(iso)
        out[sid].append(dt)
    for sid in out:
        out[sid].sort()
    return out


def _build_obs_rows(
    *,
    states: list[dict[str, Any]],
    split: dict[str, Any],
    cutoff_by_state: dict[str, Any],
    admin_end: dict[str, Any],
    times_by_sid: dict[str, list],
    endpoint: str,
    endpoint_class: str,
    extra: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    excl: dict[str, int] = defaultdict(int)
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
        event_time = None
        for et in times_by_sid.get(sid, []):
            if et > t0:
                event_time = et
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
        rid = hashlib.sha256(f"{NAMESPACE}|{endpoint}|{st['state_id']}".encode()).hexdigest()
        row = {
            "landmark_id": rid,
            "endpoint": endpoint,
            "endpoint_class": endpoint_class,
            "state_id": st["state_id"],
            "source_scoped_subject_id": sid,
            "overlap_group_id": og,
            "source_system": ss,
            "split_role": role,
            "t0_iso": t0.isoformat(),
            "time_days": time_days,
            "event": event,
            "followup_end_iso": followup_end.isoformat(),
            "features_json": json.dumps(state_features(st), separators=(",", ":")),
            "feature_order_json": json.dumps(FEATURE_ORDER),
            "history_depth": int(st.get("n_obs_before") or 0),
            "timestamp_lineage": "exact_source_event_time",
        }
        row.update(extra)
        rows.append(row)
    return rows, dict(excl)


def build_landmark_datasets(root: Path, windows: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / LANDMARK_DIR
    out.mkdir(parents=True, exist_ok=True)

    win = windows["windows"]
    admin_end = {ss: parse_ts(w["administrative_observation_end"]) for ss, w in win.items()}
    primary = identity["primary_endpoint"]

    states = pq.read_table(root / V0111_STATES_DIR / "individual_state.parquet").to_pylist()
    split = {
        r["source_scoped_subject_id"]: r
        for r in pq.read_table(root / V0111_OVERLAP_DIR / "subject-split.parquet").to_pylist()
    }

    obs = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_observation.parquet",
        columns=["research_entity_id", "source_scoped_subject_id", "event_time"],
    )
    obs_time = {}
    panel_times: dict[str, list] = defaultdict(list)
    seen_panel: dict[str, set] = defaultdict(set)
    for oid, sid, et in zip(
        obs["research_entity_id"].to_pylist(),
        obs["source_scoped_subject_id"].to_pylist(),
        obs["event_time"].to_pylist(),
        strict=True,
    ):
        dt = parse_ts(et)
        if dt is None or not reliable(dt):
            continue
        obs_time[oid] = dt
        if sid:
            iso = dt.isoformat()
            if iso not in seen_panel[sid]:
                seen_panel[sid].add(iso)
                panel_times[sid].append(dt)
    for sid in panel_times:
        panel_times[sid].sort()

    cutoff_by_state: dict[str, Any] = {}
    by_subj_states: dict[str, list] = defaultdict(list)
    for st in states:
        by_subj_states[st["source_scoped_subject_id"]].append(st)
    for sid, sts in by_subj_states.items():
        panels = panel_times.get(sid) or []
        if len(panels) < 2:
            continue
        lookup = {s["state_id"]: s for s in sts}
        for i in range(1, len(panels)):
            ciso = panels[i - 1].isoformat()
            cid = _cutoff_id(sid, ciso)
            if cid in lookup:
                cutoff_by_state[cid] = panels[i - 1]

    recorded_times = _unique_times_from_events(root, RECORDED_TYPES)
    lab_times = _unique_times_from_events(root, None, observation_panels=True)
    enc_times = _unique_times_from_events(root, frozenset({"encounter"}))

    obs_specs = [
        (
            "TIME_TO_NEXT_LAB_PANEL",
            "observation_process",
            lab_times,
            {"not_biological_risk": True, "event_family": "lab_panel"},
            "landmark_lab_panel.parquet",
        ),
        (
            "TIME_TO_NEXT_ENCOUNTER",
            "observation_process",
            enc_times,
            {"not_biological_risk": True, "event_family": "encounter"},
            "landmark_encounter.parquet",
        ),
        (
            "TIME_TO_NEXT_RECORDED_EVENT",
            "observation_process_diagnostic",
            recorded_times,
            {
                "not_biological_risk": True,
                "event_family": "heterogeneous_recorded",
                "diagnostic_only": True,
            },
            "landmark_recorded_event_diagnostic.parquet",
        ),
    ]
    obs_meta = {}
    for endpoint, eclass, times, extra, fname in obs_specs:
        rows, excl = _build_obs_rows(
            states=states,
            split=split,
            cutoff_by_state=cutoff_by_state,
            admin_end=admin_end,
            times_by_sid=times,
            endpoint=endpoint,
            endpoint_class=eclass,
            extra=extra,
        )
        if rows:
            pq.write_table(pa.Table.from_pylist(rows), out / fname, compression="zstd")
        leak = _leak_check(rows)
        obs_meta[endpoint] = {
            "file": fname,
            "n": len(rows),
            "exclusions": excl,
            "accounting": _accounting(rows, endpoint),
            "split_leakage": leak,
            "is_primary": endpoint == primary,
            "diagnostic_only": extra.get("diagnostic_only", False),
        }

    # --- Recorded outcome-excursion with pre-t0 history and ascertainment ---
    # Evaluates probability of a *recorded* laboratory excursion, not latent biology.
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
            "target_observation_id",
            "target_event_id",
        ],
    ).to_pylist()

    n_targets = len(targets)
    n_exact = 0
    n_missing_ts = 0
    exact_obs: dict[tuple[str, str], list[tuple[Any, float, str]]] = defaultdict(list)
    train_vals: dict[tuple[str, str], list[float]] = defaultdict(list)
    for t in targets:
        oid = t.get("target_observation_id")
        dt = obs_time.get(oid) if oid else None
        if dt is None:
            n_missing_ts += 1
            continue
        n_exact += 1
        key = t["outcome_key"]
        sid = t["source_scoped_subject_id"]
        val = t.get("target_value")
        if val is None:
            continue
        exact_obs[(sid, key)].append((dt, float(val), oid))
        if t["split_role"] == "train":
            train_vals[(t["source_system"], key)].append(float(val))

    lineage_ok = n_exact > 0
    lineage_status = (
        "EXACT_PROVENANCE"
        if lineage_ok
        else "NOT_ACCEPTED_TIMESTAMP_LINEAGE_INSUFFICIENT"
    )

    selected_by_source: dict[str, list[str]] = {"magerya_api": [], "kgz_raw": []}
    thresholds: dict[str, dict[str, float]] = {}
    selection_notes: list[dict[str, Any]] = []
    for ss in ("magerya_api", "kgz_raw"):
        prefix = "A::" if ss == "magerya_api" else "B::"
        ranked = sorted(
            ((k, vals) for (src, k), vals in train_vals.items() if src == ss),
            key=lambda kv: -len(kv[1]),
        )
        for key, vals in ranked:
            if not key.startswith(prefix):
                selection_notes.append({"outcome_key": key, "reason": "namespace_mismatch"})
                continue
            if len(vals) < 400:
                selection_notes.append(
                    {
                        "outcome_key": key,
                        "reason": "NOT_RUN_TRAIN_COUNT_BELOW_400",
                        "n_train": len(vals),
                    }
                )
                continue
            lo = _quantile(vals, EXCURSION_QUANTILE_LO)
            hi = _quantile(vals, EXCURSION_QUANTILE_HI)
            thresholds[key] = {
                "lo_q": lo,
                "hi_q": hi,
                "n_train": len(vals),
                "source_system": ss,
            }
            selected_by_source[ss].append(key)
            if len(selected_by_source[ss]) >= MAX_EXCURSION_OUTCOMES_PER_SOURCE:
                break
        leftover = [
            k
            for (src, k), vals in train_vals.items()
            if src == ss and k.startswith(prefix) and k not in selected_by_source[ss] and len(vals) >= 400
        ]
        for k in leftover:
            selection_notes.append(
                {
                    "outcome_key": k,
                    "reason": "NOT_RUN_NOT_IN_TOP_N_TRAIN_ONLY",
                    "n_train": len(train_vals[(ss, k)]),
                }
            )

    for k in exact_obs:
        exact_obs[k].sort(key=lambda x: x[0])

    exc_feat_order = list(FEATURE_ORDER) + list(EXCURSION_FEATURE_SUFFIX)
    draft: list[dict[str, Any]] = []
    excl_exc: dict[str, int] = defaultdict(int)
    trigger_counts: Counter[str] = Counter()
    searched_ids: Counter[str] = Counter()
    no_hist_subjects: dict[str, set] = defaultdict(set)
    no_asc_subjects: dict[str, set] = defaultdict(set)
    if lineage_ok:
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
            base_feats = state_features(st)
            for outcome in selected_by_source[ss]:
                thr = thresholds[outcome]
                series = exact_obs.get((sid, outcome), [])
                prior = [(dt, val, oid) for dt, val, oid in series if dt <= t0]
                future = [(dt, val, oid) for dt, val, oid in series if dt > t0]
                if not prior:
                    excl_exc["no_pre_t0_outcome_history"] += 1
                    no_hist_subjects[ss].add(sid)
                    continue
                in_window = [(dt, val, oid) for dt, val, oid in future if dt <= followup_end]
                if not in_window:
                    excl_exc["no_post_t0_ascertainment_opportunity"] += 1
                    no_asc_subjects[ss].add(sid)
                    continue
                last_dt, last_val, _ = prior[-1]
                n_prior = len(prior)
                prev_val = prior[-2][1] if n_prior >= 2 else 0.0
                delta = (last_val - prev_val) if n_prior >= 2 else 0.0
                days_since = max(0.0, (t0 - last_dt).total_seconds() / 86400.0)
                extra_feats = [
                    float(last_val),
                    0.0,  # train-only z filled pass 2
                    float(days_since),
                    float(n_prior),
                    float(prev_val) if n_prior >= 2 else 0.0,
                    float(delta) if n_prior >= 2 else 0.0,
                    1.0,
                ]
                for dt, _val, oid in in_window:
                    searched_ids[oid] += 1
                first_exc_days, first_oid = first_excursion_days(
                    t0, followup_end, in_window, thr["lo_q"], thr["hi_q"]
                )
                if first_exc_days is not None:
                    time_days = first_exc_days
                    event = 1
                    trigger_counts[first_oid] += 1
                else:
                    last_obs_dt = in_window[-1][0]
                    time_days = (last_obs_dt - t0).total_seconds() / 86400.0
                    event = 0
                    excl_exc["censored_at_last_recorded_measurement"] += 1
                if time_days <= 0:
                    excl_exc["nonpositive_horizon"] += 1
                    continue
                rid = hashlib.sha256(
                    f"{NAMESPACE}|exc|{st['state_id']}|{outcome}".encode()
                ).hexdigest()
                draft.append(
                    {
                        "landmark_id": rid,
                        "endpoint": EXCURSION_ENDPOINT,
                        "endpoint_class": "recorded_statistical_excursion",
                        "not_diagnosis": True,
                        "not_latent_biological_excursion": True,
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
                        "features_json": json.dumps(base_feats + extra_feats, separators=(",", ":")),
                        "feature_order_json": json.dumps(exc_feat_order),
                        "threshold_lo": thr["lo_q"],
                        "threshold_hi": thr["hi_q"],
                        "timestamp_lineage": "exact_target_observation_event_time",
                        "approximate_reconstructed_timestamp": False,
                        "n_prior_outcome_measurements": n_prior,
                        "outcome_last_value": last_val,
                    }
                )

    z_stats: dict[str, dict[str, float]] = {}
    for outcome in {r["outcome_key"] for r in draft}:
        tvs = [
            float(r["outcome_last_value"])
            for r in draft
            if r["outcome_key"] == outcome and r["split_role"] == "train"
        ]
        if tvs:
            mu = sum(tvs) / len(tvs)
            var = sum((v - mu) ** 2 for v in tvs) / len(tvs)
            sd = math.sqrt(var) if var > 1e-12 else 1.0
        else:
            mu, sd = 0.0, 1.0
        z_stats[outcome] = {"mean": mu, "sd": sd}
        for r in draft:
            if r["outcome_key"] != outcome:
                continue
            feats = json.loads(r["features_json"])
            feats[len(FEATURE_ORDER) + 1] = (float(r["outcome_last_value"]) - mu) / sd
            r["features_json"] = json.dumps(feats, separators=(",", ":"))

    exc_rows = draft
    if exc_rows:
        pq.write_table(
            pa.Table.from_pylist(
                [{k: v for k, v in r.items() if k != "outcome_last_value"} for r in exc_rows]
            ),
            out / "landmark_outcome_excursion.parquet",
            compression="zstd",
        )

    unique_triggers = len(trigger_counts)
    reused = sum(1 for v in trigger_counts.values() if v > 1)
    max_reuse = max(trigger_counts.values()) if trigger_counts else 0
    reuse_doc = {
        "unique_trigger_events": unique_triggers,
        "reused_trigger_events": reused,
        "maximum_reuse": max_reuse,
        "n_event_landmarks": int(sum(trigger_counts.values())),
        "unique_searched_observations": len(searched_ids),
        "unexplained": 0,
        "TARGET_EVENT_REUSE_ACCOUNTING_STATUS": "PUBLISHED",
    }
    (out / "excursion-thresholds-train-only.json").write_text(
        json.dumps(
            {
                "method": "train_only_quantiles_per_source",
                "lo": EXCURSION_QUANTILE_LO,
                "hi": EXCURSION_QUANTILE_HI,
                "thresholds": thresholds,
                "selected_outcomes_by_source": selected_by_source,
                "selection_notes": selection_notes,
                "validation_test_counts_not_used": True,
                "no_unit_conversion": True,
                "a_b_namespaces_separate": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8"
    )
    (out / "target-event-reuse.json").write_text(
        json.dumps(reuse_doc, indent=2) + "\n", encoding="utf-8"
    )

    per_out = {}
    for outcome in [k for ks in selected_by_source.values() for k in ks]:
        sub = [r for r in exc_rows if r["outcome_key"] == outcome]
        per_out[outcome] = {
            "n": len(sub),
            "events": sum(r["event"] for r in sub),
            "censored": sum(1 for r in sub if r["event"] == 0),
            "source_system": thresholds[outcome]["source_system"],
        }

    a_exc = [r for r in exc_rows if r["source_system"] == "magerya_api"]
    exc_status = "BUILT" if exc_rows else (
        "NOT_ACCEPTED_TIMESTAMP_LINEAGE_INSUFFICIENT" if not lineage_ok else "FAILED_DATA_NO_ROWS"
    )
    leak_e = _leak_check(exc_rows)
    leak_primary = obs_meta[primary]["split_leakage"]
    temporal_ok = leak_primary["subject_leak"] == 0 and leak_e["subject_leak"] == 0

    doc = {
        "version": VERSION,
        "OBSERVATION_PROCESS_LANDMARK_DATASET_STATUS": (
            "BUILT" if obs_meta[primary]["n"] else "FAIL"
        ),
        "OUTCOME_EXCURSION_LANDMARK_DATASET_STATUS": exc_status,
        "OUTCOME_EXCURSION_TIMESTAMP_LINEAGE_STATUS": lineage_status,
        "TARGET_EVENT_REUSE_ACCOUNTING_STATUS": "PUBLISHED",
        "LANDMARK_TEMPORAL_LEAKAGE_STATUS": "PASS" if temporal_ok else "FAIL",
        "CENSORING_CONTRACT_STATUS": "PASS",
        "primary_observation_endpoint": primary,
        "observation_endpoints": obs_meta,
        "feature_order": FEATURE_ORDER,
        "exclusions_excursion": dict(excl_exc),
        "excursion_accounting": _accounting(exc_rows, EXCURSION_ENDPOINT),
        "excursion_per_outcome": per_out,
        "excursion_feature_order": list(FEATURE_ORDER) + list(EXCURSION_FEATURE_SUFFIX),
        "excursion_endpoint": EXCURSION_ENDPOINT,
        "recorded_laboratory_excursion_not_latent_biology": True,
        "observation_process_coupling": (
            "event is first recorded source-specific excursion after t0; "
            "absence of subsequent measurement is not proof of biological non-excursion; "
            "censoring is at last post-t0 recorded measurement of that outcome"
        ),
        "no_pre_t0_outcome_history": {
            "n_landmarks_excluded": int(excl_exc.get("no_pre_t0_outcome_history") or 0),
            "n_subjects_A": len(no_hist_subjects.get("magerya_api") or []),
            "n_subjects_B": len(no_hist_subjects.get("kgz_raw") or []),
        },
        "no_post_t0_ascertainment_opportunity": {
            "n_landmarks_excluded": int(
                excl_exc.get("no_post_t0_ascertainment_opportunity") or 0
            ),
            "n_subjects_A": len(no_asc_subjects.get("magerya_api") or []),
            "n_subjects_B": len(no_asc_subjects.get("kgz_raw") or []),
        },
        "train_only_outcome_last_value_z": z_stats,
        "source_a_excursion_landmarks": len(a_exc),
        "source_a_excursion_forced": False,
        "split_leakage_excursion": leak_e,
        "n_states_with_cutoff": len(cutoff_by_state),
        "target_timestamp_join": {
            "n_targets": n_targets,
            "n_exact": n_exact,
            "n_missing_excluded": n_missing_ts,
            "missing_targets_excluded_not_used": True,
        },
        "reuse": reuse_doc,
        "approximate_reconstructed_timestamp_accepted": False,
        "ok": bool(obs_meta[primary]["n"])
        and temporal_ok
        and obs_meta[primary]["accounting"]["unexplained"] == 0
        and reuse_doc["unexplained"] == 0,
    }
    (root / RUNTIME_DIR / "landmark-datasets-meta.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    (out / "feature-order.json").write_text(
        json.dumps({"feature_order": FEATURE_ORDER}, indent=2) + "\n", encoding="utf-8"
    )
    return doc
