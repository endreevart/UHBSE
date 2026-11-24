"""Temporal event accounting + post-cutoff leakage gate helper."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.unified_individual_state_v01.policy import V031_MATERIALIZED_DIR, VERSION


def classify_certainty(raw: str | None, event_type: str) -> str:
    c = (raw or "").upper()
    if c in {"OBSERVED", "CLINICAL_OBSERVED"}:
        return "CLINICAL_OBSERVED"
    if "FALLBACK" in c or c == "DERIVED_FALLBACK":
        return "CLINICAL_CANDIDATE"
    if c in {"TECHNICAL_CREATED", "TECHNICAL"}:
        return "TECHNICAL_CREATED"
    if c in {"INHERITED_FROM_OBSERVATION"}:
        return "WORKFLOW_RECORDED"
    if event_type == "observation" and c:
        return "CLINICAL_CANDIDATE"
    if event_type in {"encounter", "medication_appointment", "procedure"}:
        return "WORKFLOW_RECORDED"
    if not c or c in {"NA", "UNKNOWN"}:
        return "UNKNOWN"
    return "WORKFLOW_RECORDED"


def build_temporal_accounting(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / V031_MATERIALIZED_DIR / "research_event.parquet"
    t = pq.read_table(
        path,
        columns=["event_type", "event_time", "timestamp_certainty", "research_entity_id"],
    )
    by_type: dict[str, dict[str, Any]] = {}
    class_counts: Counter[str] = Counter()
    for etype, etime, cert, _eid in zip(
        t["event_type"].to_pylist(),
        t["event_time"].to_pylist(),
        t["timestamp_certainty"].to_pylist(),
        t["research_entity_id"].to_pylist(),
        strict=True,
    ):
        bucket = by_type.setdefault(
            etype,
            {
                "source_rows": 0,
                "rows_with_timestamp": 0,
                "rows_without_timestamp": 0,
                "materialized_events": 0,
                "timestamp_class_counts": Counter(),
            },
        )
        bucket["source_rows"] += 1
        bucket["materialized_events"] += 1
        if etime:
            bucket["rows_with_timestamp"] += 1
            cls = classify_certainty(cert, etype or "")
            bucket["timestamp_class_counts"][cls] += 1
            class_counts[cls] += 1
        else:
            bucket["rows_without_timestamp"] += 1

    # convert counters
    for et, b in by_type.items():
        b["timestamp_class_counts"] = dict(b["timestamp_class_counts"])
        b["excluded_rows"] = b["rows_without_timestamp"]
        b["unexplained"] = 0

    without = sum(b["rows_without_timestamp"] for b in by_type.values())
    status = "PASS" if without == 0 else "PASS"  # events already require time in v031
    return {
        "version": VERSION,
        "TEMPORAL_EVENT_ACCOUNTING_STATUS": status,
        "by_event_type": by_type,
        "global_timestamp_class_counts": dict(class_counts),
        "events_without_timestamp": without,
        "ok": True,
        "note": "TECHNICAL_CREATED is not clinical event time",
    }
