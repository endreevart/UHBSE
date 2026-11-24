"""Shared future-field presence contract for NHR and LEP.

Presence is the fact that a key exists on the original request payload.
Values are not interpreted by truthiness. Explicit null/0/false/empty
are still presence. Missing keys are absence.
"""

from __future__ import annotations

from typing import Any, Iterable

from human_simulator.integrated_research_runtime_v015.policy import VERSION

DATA_BEARING_FUTURE_FIELDS: tuple[str, ...] = (
    "t1",
    "t2",
    "future_intervals",
    "actual_recorded_label_offset_days",
)
HAS_FUTURE_FIELD = "has_future_values"
REASON_LEAK = "FUTURE_INFORMATION_LEAKAGE"
REASON_SCHEMA = "SCHEMA_INVALID"

FALSEY_PRESENCE_VALUES: tuple[Any, ...] = (None, 0, 0.0, False, "", [], {})
NONEMPTY_BY_FIELD: dict[str, Any] = {
    "t1": "2020-01-02T00:00:00Z",
    "t2": "2020-01-03T00:00:00Z",
    "future_intervals": [1.0],
    "actual_recorded_label_offset_days": 90,
    "has_future_values": True,
}


def original_present_keys(payload: dict[str, Any], *, fields_set: Iterable[str] | None = None) -> frozenset[str]:
    if fields_set is not None:
        return frozenset(fields_set)
    return frozenset(payload.keys())


def _leak_fail(*, detail: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "reason": REASON_LEAK,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "FAIL",
        "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": "FAIL",
        "infer_called": False,
        "residual_sampled": False,
        "model_execution": False,
        "detail": detail,
        "version": VERSION,
    }


def _schema_fail(*, detail: str, field: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "reason": REASON_SCHEMA,
        "infer_called": False,
        "residual_sampled": False,
        "model_execution": False,
        "field": field,
        "detail": detail,
        "version": VERSION,
    }


def future_information_contract(
    payload: dict[str, Any],
    *,
    present: Iterable[str] | None = None,
) -> dict[str, Any] | None:
    """Reject data-bearing future keys by presence. has_future_values is typed separately.

    `present` must be the original key set (raw JSON keys or the source request dict).
    Do not pass keys from model_dump(exclude_none=False); that conflates missing and null.
    """
    keys = original_present_keys(payload, fields_set=present)
    for name in DATA_BEARING_FUTURE_FIELDS:
        if name in keys:
            return _leak_fail(detail=f"data-bearing future field present: {name}")
    if HAS_FUTURE_FIELD in keys:
        value = payload.get(HAS_FUTURE_FIELD)
        if value is True:
            return _leak_fail(detail="has_future_values=true")
        if value is False:
            return None
        return _schema_fail(
            field=HAS_FUTURE_FIELD,
            detail="has_future_values must be a JSON/Python boolean without coercion",
        )
    return None
