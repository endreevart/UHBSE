"""Administrative observation windows per source — no arbitrary +90."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v02.policy import (
    PREDECLARED_MAX_FOLLOWUP_DAYS,
    RUNTIME_DIR,
    TS_YEAR_MAX,
    TS_YEAR_MIN,
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


def _reliable(dt: datetime) -> bool:
    return TS_YEAR_MIN <= dt.year <= TS_YEAR_MAX


def build_observation_windows(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    ev = pq.read_table(
        root / V031_MATERIALIZED_DIR / "research_event.parquet",
        columns=["source_system", "event_time", "event_type"],
    )
    by: dict[str, list[datetime]] = defaultdict(list)
    rejected: dict[str, int] = defaultdict(int)
    nulls: dict[str, int] = defaultdict(int)
    type_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for ss, et, tp in zip(
        ev["source_system"].to_pylist(),
        ev["event_time"].to_pylist(),
        ev["event_type"].to_pylist(),
        strict=True,
    ):
        type_counts[ss][tp or "unknown"] += 1
        if et is None:
            nulls[ss] += 1
            continue
        dt = _parse_ts(et)
        if dt is None:
            rejected[ss] += 1
            continue
        if not _reliable(dt):
            rejected[ss] += 1
            continue
        by[ss].append(dt)

    windows: dict[str, Any] = {}
    for ss, times in by.items():
        times = sorted(times)
        admin_end = times[-1]
        admin_start = times[0]
        windows[ss] = {
            "source_system": ss,
            "n_reliable_timestamps": len(times),
            "n_null_timestamps": nulls.get(ss, 0),
            "n_rejected_out_of_bound_timestamps": rejected.get(ss, 0),
            "minimum_reliable_timestamp": admin_start.isoformat(),
            "maximum_reliable_timestamp": admin_end.isoformat(),
            "administrative_observation_end": admin_end.isoformat(),
            "timestamp_completeness": len(times)
            / max(len(times) + nulls.get(ss, 0) + rejected.get(ss, 0), 1),
            "event_type_counts": dict(type_counts[ss]),
            "left_truncation_rule": "landmarks require t0 within [min_reliable, admin_end)",
            "right_censoring_rule": (
                "followup_end = min(administrative_observation_end, t0 + "
                f"{PREDECLARED_MAX_FOLLOWUP_DAYS}d); if no event by followup_end then event=0"
            ),
            "no_arbitrary_plus_90": True,
            "year_bounds": {"min": TS_YEAR_MIN, "max": TS_YEAR_MAX},
        }

    doc = {
        "version": VERSION,
        "ADMINISTRATIVE_OBSERVATION_WINDOW_STATUS": "BUILT" if windows else "FAIL",
        "CENSORING_CONTRACT_STATUS": "PASS" if windows else "FAIL",
        "predeclared_max_followup_days": PREDECLARED_MAX_FOLLOWUP_DAYS,
        "windows": windows,
        "ok": bool(windows) and "magerya_api" in windows and "kgz_raw" in windows,
    }
    (root / RUNTIME_DIR / "administrative-observation-windows.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
