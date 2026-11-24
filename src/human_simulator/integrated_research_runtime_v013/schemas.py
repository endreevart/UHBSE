"""Typed request validation. Invalid bodies become deterministic 4xx JSON."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from human_simulator.integrated_research_runtime_v013.policy import N_PATHS_MAX, NS_A, NS_B, NS_SYN


class ApiContractError(Exception):
    def __init__(self, status: int, reason: str, extra: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.extra = extra or {}


def _finite_num(v: Any, *, field: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NON_FINITE_OR_NON_NUMERIC:{field}") from exc
    if not math.isfinite(x):
        raise ValueError(f"NON_FINITE_VALUE:{field}")
    return x


class CellIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_payload_sha256: str
    feature_order_sha256: str
    scaler_sha256: str
    residual_distribution_sha256: str
    unit: str
    source_system: str
    requested_horizon_days: int


class JointRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str | None = None
    source_system: str
    requested_horizon_days: int
    outcome_keys: list[str] = Field(min_length=1)
    state_at_t0: dict[str, float]
    cutoff_t0: str
    history: dict[str, list[float]] | None = None
    history_days: dict[str, list[float]] | None = None
    history_timestamps: dict[str, list[str]] | None = None
    history_is_pre_t0_summary: bool | None = None
    state_is_cutoff_state: bool | None = None
    cell_identities: dict[str, CellIdentity]
    n_paths: int = 8
    seed: int = 42
    replay_key: str = "runtime"
    include_paths: bool | None = None
    force_d1: bool | None = None
    intervention: dict[str, Any] | None = None
    pad_outcomes: bool | None = None
    truncate_outcomes: bool | None = None
    endpoint: str | None = None
    model_id: str | None = None
    feature_order_sha256: str | None = None
    t1: Any = None
    t2: Any = None
    has_future_values: Any = None
    future_intervals: Any = None
    actual_recorded_label_offset_days: Any = None
    patient_id: str | None = None
    email: str | None = None
    phone: str | None = None
    full_name: str | None = None

    @field_validator("requested_horizon_days")
    @classmethod
    def _h(cls, v: int) -> int:
        if int(v) <= 0:
            raise ValueError("HORIZON_TYPE_INVALID")
        return int(v)

    @field_validator("n_paths")
    @classmethod
    def _n(cls, v: int) -> int:
        n = int(v)
        if n < 1 or n > N_PATHS_MAX:
            raise ValueError("N_PATHS_OUT_OF_RANGE")
        return n

    @field_validator("state_at_t0")
    @classmethod
    def _state(cls, v: dict[str, float]) -> dict[str, float]:
        out = {}
        for k, val in v.items():
            if k == "history_depth":
                out[k] = _finite_num(val, field=k)
                continue
            out[k] = _finite_num(val, field=f"state_at_t0.{k}")
        return out

    @field_validator("namespace")
    @classmethod
    def _ns(cls, v: str | None) -> str | None:
        if v is None or v in {NS_SYN, NS_A, NS_B}:
            return v
        raise ValueError("UNKNOWN_NAMESPACE")

    @model_validator(mode="after")
    def _ids(self) -> "JointRequest":
        if set(self.cell_identities) != set(self.outcome_keys):
            raise ValueError("PER_OUTCOME_CELL_IDENTITIES_REQUIRED")
        return self


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str | None = None
    source_system: str
    endpoint: str
    requested_horizon_days: int
    model_id: str
    feature_order_sha256: str
    cutoff_t0: str | None = None
    state_at_t0: dict[str, Any] | None = None
    features: list[float] | None = None
    outcome_key: str | None = None
    seed: int = 42
    t1: Any = None
    has_future_values: Any = None
    REFERENCE_FEATURE_PROBE: bool | None = False
    lep_input_mode: str | None = None

    @field_validator("features")
    @classmethod
    def _feat(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return v
        return [_finite_num(x, field="features") for x in v]


class QspRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model_id: str | None = None
    medication: Any = None
    dose: Any = None
    supplement: Any = None
    nutrition: Any = None
    intervention: dict[str, Any] | None = None
    link_to_patient: Any = None
    patient_id: Any = None
    patient_linked: Any = None
    allow_synthetic_compound_x: Any = None
    synthetic_only: Any = None


class StateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str | None = None
    source_id: str | None = None
    cutoff_t0: str | None = None
    namespace: str | None = None
    patient_id: str | None = None
    email: str | None = None
    phone: str | None = None
    full_name: str | None = None


def parse_model(model: type[BaseModel], body: dict[str, Any]) -> dict[str, Any]:
    try:
        return model.model_validate(body).model_dump(exclude_none=False)
    except ValidationError as exc:
        err = exc.errors()[0] if exc.errors() else {}
        msg = str(err.get("msg") or "SCHEMA_INVALID")
        loc = err.get("loc") or ()
        loc_s = ".".join(str(x) for x in loc)
        etype = str(err.get("type") or "")
        reason = "SCHEMA_INVALID"
        if etype == "missing":
            if "cutoff_t0" in loc:
                reason = "CUTOFF_T0_REQUIRED"
            elif loc_s.endswith(".unit") or loc_s.endswith("unit") and "cell_identities" in loc_s:
                reason = "MISSING_UNIT"
            elif "cell_identities" in loc_s and loc_s.endswith("source_system"):
                reason = "MISSING_SOURCE_SYSTEM"
            elif "cell_identities" in loc_s and "requested_horizon_days" in loc_s:
                reason = "MISSING_REQUESTED_HORIZON_DAYS"
            elif loc == ("cell_identities",) or loc_s == "cell_identities":
                reason = "PER_OUTCOME_CELL_IDENTITIES_REQUIRED"
            elif "source_system" in loc:
                reason = "SOURCE_REQUIRED"
            elif "outcome_keys" in loc:
                reason = "OUTCOME_ORDER_REQUIRED"
            elif "model_id" in loc:
                reason = "MISSING_MODEL_ID"
            elif "feature_order_sha256" in loc:
                reason = "FEATURE_ORDER_HASH_REQUIRED"
            else:
                reason = "MISSING_FIELD"
        elif "NON_FINITE" in msg:
            reason = "NON_FINITE_VALUE"
        elif "N_PATHS" in msg:
            reason = "N_PATHS_OUT_OF_RANGE"
        elif "PER_OUTCOME" in msg:
            reason = "PER_OUTCOME_CELL_IDENTITIES_REQUIRED"
        elif "UNKNOWN_NAMESPACE" in msg:
            reason = "UNKNOWN_NAMESPACE"
        elif etype == "int_parsing" and "n_paths" in loc_s:
            reason = "N_PATHS_TYPE_INVALID"
        elif etype == "extra_forbidden":
            reason = "SCHEMA_INVALID"
        raise ApiContractError(400, reason, {"detail": msg, "field": loc_s}) from exc
