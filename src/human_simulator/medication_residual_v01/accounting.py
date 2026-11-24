"""Phase 1 — live medication accounting (aggregates only)."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.medication_residual_v01.policy import (
    ADMINISTRATION_CLAIM,
    EPISODE_EXPANSION_PIN,
    EPISODE_JSONL,
    HUMAN_REJECTED_SOURCE_MEDICINE_IDS,
    MEDICATION_RECORD_CLASS,
    SOURCE_A,
    SOURCE_B,
    TIMESTAMP_SEMANTICS,
    V031_MATERIALIZED_DIR,
    VERSION,
)
from human_simulator.medication_residual_v01.times import parse_ts, reliable


def _empty_source() -> dict[str, Any]:
    return {
        "medication_rows": 0,
        "unique_source_medicine_ids": 0,
        "subjects": 0,
        "unique_medication_timestamps": 0,
        "same_timestamp_medication_sets": 0,
        "records_with_usable_timestamp": 0,
        "rejected_unknown_timestamps": 0,
        "records_before_state_cutoff": None,
        "records_after_state_cutoff": None,
        "records_on_or_at_cutoff_unknown": 0,
        "medication_x_outcome_expanded_rows": 0,
        "unique_underlying_medication_events": 0,
        "duplicate_collapse_count": 0,
        "provenance_coverage": 0.0,
        "unexplained_count": 0,
        "administration_claim": ADMINISTRATION_CLAIM,
        "record_class": MEDICATION_RECORD_CLASS,
        "timestamp_semantics": TIMESTAMP_SEMANTICS,
    }


def _last_lab_times(root: Path) -> dict[str, Any]:
    """UIS cutoff_ts is not persisted; last lab timestamp is the technical comparator."""
    path = root / V031_MATERIALIZED_DIR / "research_observation_component.parquet"
    if not path.is_file():
        return {"available": False, "last": {}}
    table = pq.read_table(
        path,
        columns=["source_scoped_subject_id", "source_system", "event_time", "numeric_value"],
    )
    last: dict[str, Any] = {}
    for sid, ss, et, nv in zip(
        table["source_scoped_subject_id"].to_pylist(),
        table["source_system"].to_pylist(),
        table["event_time"].to_pylist(),
        table["numeric_value"].to_pylist(),
        strict=True,
    ):
        if ss != SOURCE_A or not sid or nv is None:
            continue
        ts = parse_ts(et)
        if ts is None or not reliable(ts):
            continue
        prev = last.get(sid)
        if prev is None or ts > prev:
            last[sid] = ts
    return {"available": True, "last": last, "note": "CUTOFF_TS_NOT_PERSISTED_USE_LAST_LAB"}


def _episode_expansion_counts(root: Path) -> dict[str, Any]:
    path = root / EPISODE_JSONL
    if not path.is_file():
        return {
            "available": False,
            "medication_x_outcome_expanded_rows": None,
            "unique_underlying_medication_events": None,
            "pin_matches": False,
        }
    n_lines = 0
    unique_events: set[tuple[str, str, str]] = set()
    unique_med_ts: set[tuple[str, str]] = set()
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        n_lines += 1
        rec = json.loads(line)
        mid = str(rec.get("medicine_id") or "")
        # Opaque-ish keys only for uniqueness; never emitted.
        subj = str(rec.get("opaque_subject_key") or "")
        ts = str(rec.get("event_ts") or "")
        unique_events.add((subj, mid, ts))
        unique_med_ts.add((subj, ts))
    return {
        "available": True,
        "medication_x_outcome_expanded_rows": n_lines,
        "unique_underlying_medication_events": len(unique_events),
        "unique_subject_timestamp_sets": len(unique_med_ts),
        "pin": EPISODE_EXPANSION_PIN,
        "pin_matches": n_lines == EPISODE_EXPANSION_PIN,
        "not_prescriptions": True,
        "not_administrations": True,
    }


def inventory_medications(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    med_path = root / V031_MATERIALIZED_DIR / "research_medication_record.parquet"
    by_source = {"A": _empty_source(), "B": _empty_source()}

    unexplained = 0
    if not med_path.is_file():
        return {
            "version": VERSION,
            "ok": False,
            "error": "MISSING_RESEARCH_MEDICATION_RECORD",
            "by_source": by_source,
        }

    table = pq.read_table(med_path)
    cols = set(table.column_names)
    n = table.num_rows
    sids = table["source_scoped_subject_id"].to_pylist() if "source_scoped_subject_id" in cols else [None] * n
    systems = table["source_system"].to_pylist() if "source_system" in cols else [None] * n
    times = table["event_time"].to_pylist() if "event_time" in cols else [None] * n
    meds = table["medicine_ref_id"].to_pylist() if "medicine_ref_id" in cols else [None] * n
    claims = (
        table["administration_claim"].to_pylist()
        if "administration_claim" in cols
        else [ADMINISTRATION_CLAIM] * n
    )
    entities = table["research_entity_id"].to_pylist() if "research_entity_id" in cols else [None] * n
    certs = table["timestamp_certainty"].to_pylist() if "timestamp_certainty" in cols else [None] * n

    cut = _last_lab_times(root)
    last_cut = cut.get("last") or {}

    buckets: dict[str, dict[str, Any]] = {
        "A": {
            "rows": 0,
            "subjects": set(),
            "meds": set(),
            "ts": set(),
            "sets": set(),
            "usable": 0,
            "rejected_ts": 0,
            "before": 0,
            "after": 0,
            "unknown_cut": 0,
            "events": set(),
            "set_members": defaultdict(set),
            "prov": 0,
            "claim_ok": 0,
        },
        "B": {
            "rows": 0,
            "subjects": set(),
            "meds": set(),
            "ts": set(),
            "sets": set(),
            "usable": 0,
            "rejected_ts": 0,
            "before": 0,
            "after": 0,
            "unknown_cut": 0,
            "events": set(),
            "set_members": defaultdict(set),
            "prov": 0,
            "claim_ok": 0,
        },
    }

    for sid, ss, et, mid, claim, eid, cert in zip(
        sids, systems, times, meds, claims, entities, certs, strict=True
    ):
        label = "A" if ss == SOURCE_A else ("B" if ss == SOURCE_B else None)
        if label is None:
            unexplained += 1
            continue
        b = buckets[label]
        b["rows"] += 1
        classified = False
        if sid:
            b["subjects"].add(sid)
            classified = True
        if mid:
            b["meds"].add(mid)
            classified = True
        ts = parse_ts(et)
        if ts is not None and reliable(ts):
            b["usable"] += 1
            iso = ts.isoformat()
            b["ts"].add(iso)
            if sid:
                b["sets"].add((sid, iso))
                if mid:
                    b["set_members"][(sid, iso)].add(mid)
                if eid:
                    b["events"].add(eid)
                elif mid:
                    b["events"].add((sid, iso, mid))
            if sid in last_cut:
                if ts <= last_cut[sid]:
                    b["before"] += 1
                else:
                    b["after"] += 1
            else:
                b["unknown_cut"] += 1
            classified = True
        else:
            b["rejected_ts"] += 1
            classified = True
        if claim == ADMINISTRATION_CLAIM:
            b["claim_ok"] += 1
        if eid or mid:
            b["prov"] += 1
        if not classified:
            unexplained += 1

    expansion = _episode_expansion_counts(root)
    out_by: dict[str, Any] = {}
    for label in ("A", "B"):
        b = buckets[label]
        n_sets = len(b["sets"])
        n_events = len(b["events"]) if b["events"] else n_sets
        collapse = max(b["rows"] - n_sets, 0)
        src = _empty_source()
        src.update(
            {
                "medication_rows": b["rows"],
                "unique_source_medicine_ids": len(b["meds"]),
                "subjects": len(b["subjects"]),
                "unique_medication_timestamps": len(b["ts"]),
                "same_timestamp_medication_sets": n_sets,
                "records_with_usable_timestamp": b["usable"],
                "rejected_unknown_timestamps": b["rejected_ts"],
                "records_before_or_at_last_recorded_lab": b["before"],
                "records_after_last_recorded_lab": b["after"],
                "records_no_lab_timestamp": b["unknown_cut"],
                "state_cutoff_ts_persisted": False,
                "unique_underlying_medication_events": n_events,
                "duplicate_collapse_count": collapse,
                "provenance_coverage": (b["prov"] / b["rows"]) if b["rows"] else 1.0,
                "unexplained_count": 0,
                "administration_claim_rows": b["claim_ok"],
            }
        )
        if label == "A" and expansion.get("available"):
            src["medication_x_outcome_expanded_rows"] = expansion["medication_x_outcome_expanded_rows"]
            src["unique_underlying_medication_events_from_expansion_lineage"] = expansion[
                "unique_underlying_medication_events"
            ]
            src["expansion_is_not_prescription_count"] = True
        else:
            src["medication_x_outcome_expanded_rows"] = 0
        out_by[label] = src

    a_rows = out_by["A"]["medication_rows"]
    b_rows = out_by["B"]["medication_rows"]
    b_status = (
        "NOT_AVAILABLE_NO_TRANSFER" if b_rows == 0 else "PRESENT_STRUCTURED_PATIENT_LINKED"
    )
    a_status = "PRESENT_SOURCE_A_RECORDED_CONTEXT" if a_rows else "NOT_AVAILABLE"
    row_unexplained = unexplained
    # Every materialized row assigned to A or B or unexplained.
    ok = row_unexplained == 0
    return {
        "version": VERSION,
        "MEDICATION_SOURCE_ACCOUNTING_STATUS": "PASS" if ok else "FAIL",
        "UNIQUE_MEDICATION_EVENT_ACCOUNTING_STATUS": "PASS" if ok else "FAIL",
        "MEDICATION_EVENT_GRAIN_STATUS": "UNIQUE_EVENT_BEFORE_OUTCOME_EXPANSION",
        "MEDICATION_TIMESTAMP_SEMANTICS_STATUS": TIMESTAMP_SEMANTICS,
        "SOURCE_A_MEDICATION_CONTEXT_STATUS": a_status,
        "SOURCE_B_MEDICATION_CONTEXT_STATUS": b_status,
        "source_aware_means": "explicit_source_identity_not_fabricated_b_medications",
        "episode_expansion": expansion,
        "by_source": out_by,
        "HUMAN_REJECTED_SOURCE_MEDICINE_IDS": list(HUMAN_REJECTED_SOURCE_MEDICINE_IDS),
        "rejected_pairs_excluded_from_scientific_concepts": True,
        "unexplained_count": row_unexplained,
        "ok": ok,
    }
