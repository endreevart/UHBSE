"""Timestamp helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from human_simulator.longitudinal_event_probability_v0211.policy import TS_YEAR_MAX, TS_YEAR_MIN


def parse_ts(v: Any) -> datetime | None:
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


def reliable(dt: datetime) -> bool:
    return TS_YEAR_MIN <= dt.year <= TS_YEAR_MAX
