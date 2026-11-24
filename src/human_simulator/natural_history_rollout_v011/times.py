"""Timestamp and alignment helpers. Future timestamps are labels only."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from human_simulator.natural_history_rollout_v011.policy import (
    HORIZON_BIN_REL_TOL,
    PREDECLARED_ABSOLUTE_GRID_DAYS,
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


def in_target_window(days: float, horizon: int) -> bool:
    if days <= 0:
        return False
    return abs(days - horizon) / float(horizon) <= HORIZON_BIN_REL_TOL


def alignment_contract() -> dict[str, Any]:
    return {
        "label": "RECORDED_SOURCE_SPECIFIC_OUTCOME_AT_REQUESTED_HORIZON",
        "not_latent_biological_state": True,
        "window": "abs(days-H)/H <= 0.5 and days > 0",
        "tie_break": ["closest_to_H", "earliest_timestamp", "entity_id_asc"],
        "missing_target": "not_evaluable",
        "actual_post_t0_timestamp_as_model_input": False,
        "requested_horizon_from_request_not_future_gap": True,
        "predeclared_absolute_grid_days": list(PREDECLARED_ABSOLUTE_GRID_DAYS),
    }
