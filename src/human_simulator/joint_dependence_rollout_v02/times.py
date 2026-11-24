"""Alignment helpers. Actual offsets are labels only; closest-horizon unique assignment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from human_simulator.joint_dependence_rollout_v02.policy import (
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


def assign_horizon(days: float) -> int | None:
    """Assign a recorded offset to at most one predeclared horizon (closest, then smaller H)."""
    cands = []
    for h in PREDECLARED_ABSOLUTE_GRID_DAYS:
        if in_target_window(days, h):
            cands.append((abs(days - h), h))
    if not cands:
        return None
    cands.sort()
    return cands[0][1]


def alignment_contract() -> dict[str, Any]:
    return {
        "TARGET_ALIGNMENT_CONTRACT_STATUS": "WINDOW_ALIGNED_RECORDED_SOURCE_SPECIFIC_OUTCOME",
        "REQUESTED_HORIZON_RUNTIME_STATUS": "PASS_REQUEST_PARAMETER_T0_PLUS_H",
        "not_latent_biological_state": True,
        "window": "abs(days-H)/H <= 0.5 and days > 0",
        "unique_horizon_rule": "closest_then_smaller_H",
        "tie_break": ["closest_to_H", "smaller_horizon", "earliest_timestamp", "entity_id_asc"],
        "actual_recorded_label_offset_in_runtime_features": False,
        "requested_prediction_offset_days": "request_parameter",
        "predeclared_absolute_grid_days": list(PREDECLARED_ABSOLUTE_GRID_DAYS),
    }
