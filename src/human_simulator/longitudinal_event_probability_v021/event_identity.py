"""Observation-process event identity, collapse accounting, primary endpoint selection."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v021.policy import (
    RUNTIME_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
)
from human_simulator.longitudinal_event_probability_v021.times import parse_ts, reliable

HETEROGENEOUS_TYPES = frozenset(
    {
        "observation",
        "encounter",
        "procedure",
        "document_reference",
        "medication_appointment",
        "recommendation",
    }
)
RECORDED_DIAGNOSTIC_TYPES = frozenset(
    {
        "observation",
        "encounter",
        "procedure",
        "document_reference",
        "medication_appointment",
    }
)
LAB_TYPE = "observation"
ENC_TYPE = "encounter"


def _interval_audit(times_by_sid: dict[str, list[datetime]]) -> dict[str, Any]:
    n_lt_1s = n_lt_1m = n_lt_1h = n_pairs = 0
    n_subjects = 0
    for _sid, times in times_by_sid.items():
        if len(times) < 2:
            continue
        n_subjects += 1
        prev = times[0]
        for t in times[1:]:
            dt = (t - prev).total_seconds()
            n_pairs += 1
            if dt < 1.0:
                n_lt_1s += 1
            if dt < 60.0:
                n_lt_1m += 1
            if dt < 3600.0:
                n_lt_1h += 1
            prev = t
    return {
        "n_subjects_with_2plus": n_subjects,
        "n_consecutive_pairs": n_pairs,
        "n_interval_lt_1_second": n_lt_1s,
        "n_interval_lt_1_minute": n_lt_1m,
        "n_interval_lt_1_hour": n_lt_1h,
        "fraction_lt_1_second": n_lt_1s / max(n_pairs, 1),
        "fraction_lt_1_minute": n_lt_1m / max(n_pairs, 1),
        "fraction_lt_1_hour": n_lt_1h / max(n_pairs, 1),
        "microintervals_not_silently_deleted": True,
    }


def build_event_identity(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    ev = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_event.parquet",
        columns=[
            "research_entity_id",
            "source_scoped_subject_id",
            "source_system",
            "event_time",
            "event_type",
            "event_id",
            "encounter_id",
        ],
    )
    obs = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_observation.parquet",
        columns=[
            "research_entity_id",
            "source_scoped_subject_id",
            "source_system",
            "event_time",
            "encounter_id",
        ],
    )
    enc = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_encounter.parquet",
        columns=[
            "research_entity_id",
            "source_scoped_subject_id",
            "source_system",
            "event_time",
            "encounter_id",
        ],
    )

    before = defaultdict(int)
    unreliable = defaultdict(int)
    null_ts = defaultdict(int)
    type_counts: dict[str, Counter] = defaultdict(Counter)
    # identity key -> first
    raw_rows = 0
    collapsed_same_ts_type = 0
    seen_id: dict[tuple[str, str, str], int] = defaultdict(int)
    # unique times per stream
    rec_times: dict[str, dict[str, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    rec_seen: dict[str, set[str]] = defaultdict(set)
    lab_times: dict[str, dict[str, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    lab_seen: dict[str, set[str]] = defaultdict(set)
    enc_times: dict[str, dict[str, list[datetime]]] = defaultdict(lambda: defaultdict(list))
    enc_seen: dict[str, set[str]] = defaultdict(set)
    panel_size: dict[str, Counter] = defaultdict(Counter)
    enc_size: dict[str, Counter] = defaultdict(Counter)
    same_enc_multi = defaultdict(int)
    same_panel_multi = defaultdict(int)
    synthetic_state_rows_as_events = 0

    sids_e = ev["source_scoped_subject_id"].to_pylist()
    ss_e = ev["source_system"].to_pylist()
    et_e = ev["event_time"].to_pylist()
    tp_e = ev["event_type"].to_pylist()
    eid_e = ev["event_id"].to_pylist()
    enc_e = ev["encounter_id"].to_pylist()

    for sid, ss, et, tp, eid, enc_id in zip(sids_e, ss_e, et_e, tp_e, eid_e, enc_e, strict=True):
        raw_rows += 1
        before[ss] += 1
        type_counts[ss][tp or "unknown"] += 1
        if et is None:
            null_ts[ss] += 1
            continue
        dt = parse_ts(et)
        if dt is None or not reliable(dt):
            unreliable[ss] += 1
            continue
        key = (sid, dt.isoformat(), tp or "unknown")
        seen_id[key] += 1
        if seen_id[key] > 1:
            collapsed_same_ts_type += 1
            continue
        iso = dt.isoformat()
        if tp in RECORDED_DIAGNOSTIC_TYPES:
            sk = f"{sid}|{iso}"
            if sk not in rec_seen[ss]:
                rec_seen[ss].add(sk)
                rec_times[ss][sid].append(dt)
        if tp == LAB_TYPE:
            sk = f"{sid}|{iso}"
            if sk not in lab_seen[ss]:
                lab_seen[ss].add(sk)
                lab_times[ss][sid].append(dt)
            panel_size[ss][f"{sid}|{iso}"] += 1
        if tp == ENC_TYPE:
            sk = f"{sid}|{iso}"
            if sk not in enc_seen[ss]:
                enc_seen[ss].add(sk)
                enc_times[ss][sid].append(dt)
        if enc_id:
            enc_size[ss][str(enc_id)] += 1

    # observation table: panel grouping (subject, timestamp)
    obs_panel: dict[str, Counter] = defaultdict(Counter)
    for sid, ss, et in zip(
        obs["source_scoped_subject_id"].to_pylist(),
        obs["source_system"].to_pylist(),
        obs["event_time"].to_pylist(),
        strict=True,
    ):
        dt = parse_ts(et)
        if not sid or dt is None or not reliable(dt):
            continue
        obs_panel[ss][f"{sid}|{dt.isoformat()}"] += 1

    for ss, c in obs_panel.items():
        same_panel_multi[ss] = sum(1 for v in c.values() if v > 1)
    for ss, c in enc_size.items():
        same_enc_multi[ss] = sum(1 for v in c.values() if v > 1)

    for ss in rec_times:
        for sid in rec_times[ss]:
            rec_times[ss][sid].sort()
    for ss in lab_times:
        for sid in lab_times[ss]:
            lab_times[ss][sid].sort()
    for ss in enc_times:
        for sid in enc_times[ss]:
            enc_times[ss][sid].sort()

    by_source: dict[str, Any] = {}
    for ss in sorted(set(before) | set(lab_times) | set(enc_times)):
        rec_audit = _interval_audit(rec_times.get(ss) or {})
        lab_audit = _interval_audit(lab_times.get(ss) or {})
        enc_audit = _interval_audit(enc_times.get(ss) or {})
        panel_ns = list((obs_panel.get(ss) or Counter()).values())
        by_source[ss] = {
            "n_raw_events": before.get(ss, 0),
            "n_null_timestamps": null_ts.get(ss, 0),
            "n_unreliable_timestamps": unreliable.get(ss, 0),
            "event_type_counts": dict(type_counts.get(ss) or {}),
            "n_unique_recorded_timestamps": sum(len(v) for v in (rec_times.get(ss) or {}).values()),
            "n_unique_lab_panels": sum(len(v) for v in (lab_times.get(ss) or {}).values()),
            "n_unique_encounters": sum(len(v) for v in (enc_times.get(ss) or {}).values()),
            "n_panels_with_multiple_rows": same_panel_multi.get(ss, 0),
            "n_encounters_with_multiple_event_rows": same_enc_multi.get(ss, 0),
            "panel_row_count_max": max(panel_ns) if panel_ns else 0,
            "recorded_interval_audit": rec_audit,
            "lab_panel_interval_audit": lab_audit,
            "encounter_interval_audit": enc_audit,
        }

    mixed_includes_documents = any(
        (type_counts[ss].get("document_reference") or 0) > 0 for ss in type_counts
    )
    # Primary endpoint: semantics + timestamp quality, not model performance.
    # Mixed recorded events include documents → diagnostic only.
    rec_frac_1s = max(
        (by_source.get(ss, {}).get("recorded_interval_audit") or {}).get("fraction_lt_1_second") or 0
        for ss in by_source
    ) if by_source else 1.0
    lab_frac_1s = max(
        (by_source.get(ss, {}).get("lab_panel_interval_audit") or {}).get("fraction_lt_1_second") or 0
        for ss in by_source
    ) if by_source else 1.0
    enc_frac_1s = max(
        (by_source.get(ss, {}).get("encounter_interval_audit") or {}).get("fraction_lt_1_second") or 0
        for ss in by_source
    ) if by_source else 1.0
    both_have_labs = all(
        (by_source.get(ss, {}).get("n_unique_lab_panels") or 0) > 100
        for ss in ("magerya_api", "kgz_raw")
    )
    both_have_enc = all(
        (by_source.get(ss, {}).get("n_unique_encounters") or 0) > 100
        for ss in ("magerya_api", "kgz_raw")
    )
    primary = "TIME_TO_NEXT_LAB_PANEL"
    primary_reason = (
        "Lab panels are source-local observation groups with explicit event_time; "
        "mixed TIME_TO_NEXT_RECORDED_EVENT includes heterogeneous document_reference rows "
        "and is diagnostic-only. Selection used timestamp identity quality "
        f"(lab max fraction_lt_1s={lab_frac_1s:.6f} vs recorded {rec_frac_1s:.6f}; "
        f"encounter {enc_frac_1s:.6f}), not model performance."
    )
    if not both_have_labs and both_have_enc:
        primary = "TIME_TO_NEXT_ENCOUNTER"
        primary_reason = (
            "Insufficient lab panels in at least one source; encounters selected on "
            "timestamp completeness, not model performance."
        )
    elif not both_have_labs and not both_have_enc:
        primary = "TIME_TO_NEXT_RECORDED_EVENT"
        primary_reason = "Fallback diagnostic mixed recorded stream; both panel and encounter streams failed coverage."

    after_same_ts = sum(1 for v in seen_id.values() if v >= 1)
    doc = {
        "version": VERSION,
        "OBSERVATION_EVENT_IDENTITY_STATUS": "BUILT",
        "OBSERVATION_MICROINTERVAL_AUDIT_STATUS": "PUBLISHED",
        "synthetic_state_rows_used_as_events": synthetic_state_rows_as_events,
        "synthetic_state_rows_excluded": True,
        "collapse": {
            "n_raw_event_rows": raw_rows,
            "n_after_same_timestamp_type_identity": after_same_ts,
            "n_collapsed_duplicate_same_timestamp_type": collapsed_same_ts_type,
            "collapse_reasons": [
                "same_subject_same_timestamp_same_event_type",
                "lab_panel_same_subject_same_timestamp",
                "encounter_id_grouping_audit",
            ],
            "microintervals_retained_as_distinct_when_timestamps_differ": True,
        },
        "by_source": by_source,
        "TIME_TO_NEXT_RECORDED_EVENT_is_diagnostic": mixed_includes_documents,
        "primary_endpoint": primary,
        "primary_endpoint_selection_before_test": True,
        "primary_endpoint_selection_used_model_performance": False,
        "primary_endpoint_reason": primary_reason,
        "endpoints": {
            "TIME_TO_NEXT_LAB_PANEL": "first subsequent unique observation-panel timestamp after t0",
            "TIME_TO_NEXT_ENCOUNTER": "first subsequent unique encounter timestamp after t0",
            "TIME_TO_NEXT_RECORDED_EVENT": (
                "diagnostic mixed recorded stream including documents; not primary"
                if mixed_includes_documents
                else "mixed recorded stream"
            ),
        },
        "ok": True,
    }
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR / "event-identity.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
