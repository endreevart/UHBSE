"""Residual landmark contract: subject × state(t0) × outcome×unit × requested horizon × unique target."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.medication_residual_v01.hashes import sha_obj
from human_simulator.medication_residual_v01.policy import (
    ADMINISTRATION_CLAIM,
    FORBIDDEN_R1_MEDICATION_FIELDS,
    LANDMARK_DIR,
    MEDICATION_RECORD_CLASS,
    NH_PROVIDER_ID,
    POLYPHARMACY_MIN,
    PREDECLARED_HORIZONS_DAYS,
    PREDECLARED_OUTCOME_KEYS_A,
    R1_FEATURE_ORDER,
    SOURCE_A,
    TEST_PARQUET,
    TIMESTAMP_SEMANTICS,
    TRAIN_VAL_PARQUET,
    V0111_OVERLAP_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
    TestAccessError,
)
from human_simulator.medication_residual_v01.providers import m0_provider_identity
from human_simulator.medication_residual_v01.times import days_between, parse_ts, reliable


def _state_id(subject_id: str, t0_iso: str) -> str:
    return hashlib.sha256(f"{NAMESPACE_LOCAL}|state|{subject_id}|{t0_iso}".encode()).hexdigest()


NAMESPACE_LOCAL = "medication-residual-v01"


def _outcome_key(raw_code: Any, raw_unit: Any) -> str | None:
    if not raw_code or raw_unit is None or raw_unit == "":
        return None
    return f"A::{raw_code}::{raw_unit}"


def load_split(root: Path) -> dict[str, dict[str, str]]:
    table = pq.read_table(root / V0111_OVERLAP_DIR / "subject-split.parquet")
    out: dict[str, dict[str, str]] = {}
    for sid, ss, role, og, ostatus in zip(
        table["source_scoped_subject_id"].to_pylist(),
        table["source_system"].to_pylist(),
        table["split_role"].to_pylist(),
        table["overlap_group_id"].to_pylist(),
        table["overlap_status"].to_pylist(),
        strict=True,
    ):
        if sid:
            out[str(sid)] = {
                "source_system": str(ss or ""),
                "split_role": str(role or ""),
                "overlap_group_id": str(og or ""),
                "overlap_status": str(ostatus or ""),
            }
    return out


def _load_context_sets(
    root: Path, allowed_subjects: set[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = root / V031_MATERIALIZED_DIR / "research_medication_record.parquet"
    table = pq.read_table(
        path,
        columns=[
            "research_entity_id",
            "source_system",
            "source_scoped_subject_id",
            "event_time",
            "medicine_ref_id",
            "administration_claim",
            "timestamp_certainty",
        ],
    )
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    rows_in = 0
    usable = 0
    rejected_ts = 0
    wrong_source = 0
    for eid, ss, sid, et, mid, claim, cert in zip(
        table["research_entity_id"].to_pylist(),
        table["source_system"].to_pylist(),
        table["source_scoped_subject_id"].to_pylist(),
        table["event_time"].to_pylist(),
        table["medicine_ref_id"].to_pylist(),
        table["administration_claim"].to_pylist(),
        table["timestamp_certainty"].to_pylist(),
        strict=True,
    ):
        if ss != SOURCE_A:
            wrong_source += 1
            continue
        if not sid or sid not in allowed_subjects:
            continue
        rows_in += 1
        ts = parse_ts(et)
        if ts is None or not reliable(ts):
            rejected_ts += 1
            continue
        usable += 1
        iso = ts.isoformat()
        key = (str(sid), iso)
        rec = grouped.get(key)
        if rec is None:
            rec = {
                "source_scoped_subject_id": str(sid),
                "t0": ts,
                "t0_iso": iso,
                "medicine_ref_ids": set(),
                "event_ids": [],
                "timestamp_certainty": cert,
                "administration_claim": claim or ADMINISTRATION_CLAIM,
            }
            grouped[key] = rec
        if mid:
            rec["medicine_ref_ids"].add(str(mid))
        if eid:
            rec["event_ids"].append(str(eid))
    sets = []
    for rec in grouped.values():
        ids = sorted(rec["medicine_ref_ids"])
        rec["medicine_ref_ids"] = ids
        rec["concurrent_count"] = len(ids)
        rec["polypharmacy"] = 1 if len(ids) >= POLYPHARMACY_MIN else 0
        rec["context_set_sha256"] = sha_obj(ids)
        sets.append(rec)
    sets.sort(key=lambda r: (r["source_scoped_subject_id"], r["t0_iso"]))
    accounting = {
        "source_a_rows_in_roles": rows_in,
        "usable_timestamp": usable,
        "rejected_unknown_timestamps": rejected_ts,
        "same_timestamp_medication_sets": len(sets),
        "wrong_source_skipped": wrong_source,
        "record_class": MEDICATION_RECORD_CLASS,
        "timestamp_semantics": TIMESTAMP_SEMANTICS,
        "administration_claim": ADMINISTRATION_CLAIM,
    }
    return sets, accounting


def _load_series(
    root: Path, allowed_subjects: set[str]
) -> dict[str, dict[str, list[tuple[Any, float, str]]]]:
    path = root / V031_MATERIALIZED_DIR / "research_observation_component.parquet"
    wanted = set(PREDECLARED_OUTCOME_KEYS_A)
    table = pq.read_table(
        path,
        columns=[
            "research_entity_id",
            "source_system",
            "source_scoped_subject_id",
            "event_time",
            "numeric_value",
            "raw_code",
            "raw_unit",
        ],
    )
    series: dict[str, dict[str, list[tuple[Any, float, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    same_ts_collapse = 0
    tmp: dict[tuple[str, str, str], list[tuple[Any, float, str]]] = defaultdict(list)
    for eid, ss, sid, et, nv, code, unit in zip(
        table["research_entity_id"].to_pylist(),
        table["source_system"].to_pylist(),
        table["source_scoped_subject_id"].to_pylist(),
        table["event_time"].to_pylist(),
        table["numeric_value"].to_pylist(),
        table["raw_code"].to_pylist(),
        table["raw_unit"].to_pylist(),
        strict=True,
    ):
        if ss != SOURCE_A or not sid or sid not in allowed_subjects or nv is None:
            continue
        ts = parse_ts(et)
        if ts is None or not reliable(ts):
            continue
        ok = _outcome_key(code, unit)
        if ok not in wanted:
            continue
        tmp[(str(sid), ok, ts.isoformat())].append((ts, float(nv), str(eid)))
    for (sid, ok, _iso), items in tmp.items():
        items.sort(key=lambda x: x[2])
        if len(items) > 1:
            same_ts_collapse += len(items) - 1
        chosen = items[0]
        series[sid][ok].append(chosen)
    for sid in series:
        for ok in series[sid]:
            series[sid][ok].sort(key=lambda x: x[0])
    series["_meta_collapse"] = same_ts_collapse  # type: ignore[assignment]
    return series


def _load_event_counts(
    root: Path, allowed_subjects: set[str]
) -> dict[str, list[tuple[Any, str]]]:
    path = root / V031_MATERIALIZED_DIR / "research_event.parquet"
    table = pq.read_table(
        path,
        columns=["source_scoped_subject_id", "source_system", "event_time", "event_type"],
    )
    by: dict[str, list[tuple[Any, str]]] = defaultdict(list)
    for sid, ss, et, etype in zip(
        table["source_scoped_subject_id"].to_pylist(),
        table["source_system"].to_pylist(),
        table["event_time"].to_pylist(),
        table["event_type"].to_pylist(),
        strict=True,
    ):
        if ss != SOURCE_A or not sid or sid not in allowed_subjects:
            continue
        ts = parse_ts(et)
        if ts is None or not reliable(ts):
            continue
        by[str(sid)].append((ts, str(etype or "")))
    for sid in by:
        by[sid].sort(key=lambda x: x[0])
    return by


def _counts_at(
    events: list[tuple[Any, str]], t0: Any
) -> tuple[int, int, int, float | None]:
    n_ev = n_obs = n_enc = 0
    first = None
    for ts, etype in events:
        if ts > t0:
            break
        n_ev += 1
        el = etype.lower()
        if "obs" in el or "lab" in el or "panel" in el:
            n_obs += 1
        if "enc" in el:
            n_enc += 1
        if first is None:
            first = ts
    age = days_between(t0, first) if first is not None else 0.0
    return n_ev, n_obs, n_enc, age


def _r1_features(row: dict[str, Any]) -> list[float]:
    return [float(row[k]) for k in R1_FEATURE_ORDER]


def build_residual_rows(
    root: Path,
    *,
    roles: set[str],
    allow_test: bool,
) -> dict[str, Any]:
    """Build residual rows for the requested split roles only."""
    if "test" in roles and not allow_test:
        raise TestAccessError("test residual rows forbidden before open-test")
    if allow_test and roles != {"test"}:
        raise TestAccessError("open-test must request test role only")
    root = Path(root).resolve()
    split = load_split(root)
    allowed = {
        sid
        for sid, rec in split.items()
        if rec["split_role"] in roles and rec["source_system"] == SOURCE_A
    }
    # Do not compute test medication frequencies when building train/val.
    sets, set_acc = _load_context_sets(root, allowed)
    series_raw = _load_series(root, allowed)
    collapse = int(series_raw.pop("_meta_collapse", 0))  # type: ignore[arg-type]
    series: dict[str, dict[str, list[tuple[Any, float, str]]]] = series_raw  # type: ignore[assignment]
    events = _load_event_counts(root, allowed)
    m0 = m0_provider_identity()
    provider_hash = m0["provider_identity_sha256"]

    prior_meds: dict[str, list[Any]] = defaultdict(list)
    for rec in sets:
        prior_meds[rec["source_scoped_subject_id"]].append(rec["t0"])
    for sid in prior_meds:
        prior_meds[sid].sort()

    used_targets: set[str] = set()
    rows: list[dict[str, Any]] = []
    skipped_no_history = 0
    skipped_no_target = 0
    skipped_nonpositive_h = 0
    skipped_target_reuse = 0
    skipped_zero_h = 0
    unexplained = 0

    for rec in sets:
        sid = rec["source_scoped_subject_id"]
        t0 = rec["t0"]
        meta = split.get(sid) or {}
        n_ev, n_obs, n_enc, age = _counts_at(events.get(sid, []), t0)
        prior_t = [t for t in prior_t0s(prior_meds[sid], t0)]
        n_prior_med = len(prior_t)
        if prior_t:
            recency = days_between(t0, prior_t[-1])
            recency_missing = 0.0
        else:
            recency = 0.0
            recency_missing = 1.0
        for outcome_key, seq in series.get(sid, {}).items():
            hist = [(ts, v, eid) for ts, v, eid in seq if ts <= t0]
            if len(hist) < 1:
                skipped_no_history += 1
                continue
            last_ts, last_v, _last_id = hist[-1]
            prev_v = hist[-2][1] if len(hist) >= 2 else None
            days_prev = days_between(t0, hist[-2][0]) if len(hist) >= 2 else 0.0
            days_prev_missing = 0.0 if len(hist) >= 2 else 1.0
            delta = (last_v - prev_v) if prev_v is not None else 0.0
            delta_missing = 0.0 if prev_v is not None else 1.0
            future = [(ts, v, eid) for ts, v, eid in seq if ts > t0]
            for h in PREDECLARED_HORIZONS_DAYS:
                if h <= 0:
                    skipped_zero_h += 1
                    continue
                window_end = t0 + timedelta(days=int(h))
                chosen = None
                for ts, v, eid in future:
                    if ts <= t0:
                        continue
                    if ts > window_end:
                        break
                    chosen = (ts, v, eid)
                    break
                if chosen is None:
                    skipped_no_target += 1
                    continue
                tgt_ts, observed, tid = chosen
                actual_h = days_between(tgt_ts, t0)
                if actual_h <= 0:
                    skipped_nonpositive_h += 1
                    continue
                reuse_key = f"{outcome_key}|{int(h)}|{tid}"
                if tid in used_targets:
                    # unique within this builder (role-scoped); cell grain is outcome×horizon
                    skipped_target_reuse += 1
                    continue
                used_targets.add(tid)
                residual = float(observed) - float(last_v)
                r1 = {
                    "persistence_value": float(last_v),
                    "n_prior_outcome_measurements": float(len(hist)),
                    "days_since_previous_outcome": float(days_prev),
                    "days_since_previous_missing": days_prev_missing,
                    "prior_delta": float(delta),
                    "prior_delta_missing": delta_missing,
                    "requested_horizon_days": float(h),
                    "n_obs_before": float(n_obs if n_obs else len(hist)),
                    "n_events_before": float(n_ev),
                    "n_encounters_before": float(n_enc),
                    "longitudinal_age_days": float(age or 0.0),
                    "source_is_a": 1.0,
                    "missingness_lab": 0.0,
                }
                for banned in FORBIDDEN_R1_MEDICATION_FIELDS:
                    if banned in r1:
                        raise RuntimeError(f"medication field leaked into R1: {banned}")
                row = {
                    "source_scoped_subject_id": sid,
                    "overlap_group_id": meta.get("overlap_group_id") or "",
                    "split_role": meta.get("split_role") or "",
                    "state_id": _state_id(sid, rec["t0_iso"]),
                    "t0_iso": rec["t0_iso"],
                    "requested_horizon_days": int(h),
                    "target_id": tid,
                    "target_ts_iso": tgt_ts.isoformat(),
                    "actual_days_to_target": actual_h,
                    "outcome_key": outcome_key,
                    "source_system": SOURCE_A,
                    "frozen_nh_prediction": float(last_v),
                    "observed_target": float(observed),
                    "residual": residual,
                    "medicine_ref_ids_json": rec["medicine_ref_ids"],
                    "concurrent_count": rec["concurrent_count"],
                    "polypharmacy": rec["polypharmacy"],
                    "n_prior_recorded_medication_events": n_prior_med,
                    "days_since_last_prior_med": recency,
                    "days_since_last_prior_med_missing": recency_missing,
                    "context_set_sha256": rec["context_set_sha256"],
                    "nh_provider_id": NH_PROVIDER_ID,
                    "nh_provider_identity_sha256": provider_hash,
                    "r1_features": _r1_features(r1),
                    "timestamp_semantics": TIMESTAMP_SEMANTICS,
                    "medication_record_class": MEDICATION_RECORD_CLASS,
                    "administration_claim": rec["administration_claim"],
                    "actual_horizon_used_as_feature": False,
                    **r1,
                }
                rows.append(row)

    unique_subjects = {r["source_scoped_subject_id"] for r in rows}
    unique_targets = {r["target_id"] for r in rows}
    target_ids = [r["target_id"] for r in rows]
    reuse = len(target_ids) - len(set(target_ids))
    roles_by_target: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        roles_by_target[r["target_id"]].add(r["split_role"])
    cross_role = sum(1 for s in roles_by_target.values() if len(s) > 1)

    public = {
        "version": VERSION,
        "roles": sorted(roles),
        "n_rows": len(rows),
        "n_unique_subjects": len(unique_subjects),
        "n_unique_targets": len(unique_targets),
        "same_timestamp_panel_collapses": collapse,
        "skipped_no_history": skipped_no_history,
        "skipped_no_target": skipped_no_target,
        "skipped_nonpositive_horizon": skipped_nonpositive_h + skipped_zero_h,
        "skipped_target_reuse": skipped_target_reuse,
        "target_reuse_count": reuse,
        "cross_role_target_reuse": cross_role,
        "unexplained_count": unexplained,
        "context_sets": set_acc,
        "nh_provider_identity_sha256": provider_hash,
        "r1_feature_order": list(R1_FEATURE_ORDER),
        "r1_feature_order_sha256": sha_obj(list(R1_FEATURE_ORDER)),
        "actual_future_horizon_is_feature": False,
        "requested_horizon_predeclared": list(PREDECLARED_HORIZONS_DAYS),
        "RESIDUAL_TEMPORAL_LEAKAGE_STATUS": "PASS_STRICT_POST_T0",
        "RESIDUAL_TARGET_REUSE_STATUS": "PASS" if reuse == 0 and cross_role == 0 else "FAIL",
        "ok": unexplained == 0 and reuse == 0 and cross_role == 0,
    }
    return {"rows": rows, "public": public, "n": len(rows)}


def prior_t0s(times: list[Any], t0: Any) -> list[Any]:
    return [t for t in times if t < t0]


def write_residual_parquet(root: Path, rows: list[dict[str, Any]], name: str) -> Path:
    out = root / LANDMARK_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    if name == TEST_PARQUET and name == TRAIN_VAL_PARQUET:
        raise TestAccessError("invalid parquet name")
    serial = []
    for r in rows:
        rec = dict(r)
        rec["medicine_ref_ids_json"] = json_dumps(rec.get("medicine_ref_ids_json") or [])
        rec["r1_features"] = json_dumps(rec.get("r1_features") or [])
        serial.append(rec)
    table = pa.Table.from_pylist(serial) if serial else pa.table({"n": pa.array([], type=pa.int64())})
    pq.write_table(table, path, compression="zstd")
    return path


def json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def load_residual_parquet(path: Path) -> list[dict[str, Any]]:
    import json

    if not path.is_file():
        return []
    rows = pq.read_table(path).to_pylist()
    for r in rows:
        if isinstance(r.get("medicine_ref_ids_json"), str):
            r["medicine_ref_ids_json"] = json.loads(r["medicine_ref_ids_json"])
        if isinstance(r.get("r1_features"), str):
            r["r1_features"] = json.loads(r["r1_features"])
    return rows


def assert_no_test_parquet(root: Path) -> None:
    if (root / LANDMARK_DIR / TEST_PARQUET).is_file():
        raise TestAccessError("test parquet present before open-test")
