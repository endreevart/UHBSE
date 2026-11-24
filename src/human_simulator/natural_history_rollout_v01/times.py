"""Timestamp helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from human_simulator.natural_history_rollout_v01.policy import (
    HORIZON_BIN_REL_TOL,
    PREDECLARED_HORIZONS_DAYS,
    TS_YEAR_MAX,
    TS_YEAR_MIN,
)


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


def days_between(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 86400.0


def bin_horizon(days: float) -> int | None:
    if days <= 0:
        return None
    best = min(PREDECLARED_HORIZONS_DAYS, key=lambda h: abs(days - h))
    if abs(days - best) / float(best) <= HORIZON_BIN_REL_TOL:
        return int(best)
    return None
