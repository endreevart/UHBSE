"""State-conditioned D0 composition with timezone-aware temporal proof and bound source identity."""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Any

from human_simulator.integrated_research_runtime_v013.fixtures import synthetic_runtime_bundle
from human_simulator.integrated_research_runtime_v013.hashes import derive_seed, feature_order_sha256
from human_simulator.integrated_research_runtime_v013.loader import namespace_for_source, sample_verified_residual
from human_simulator.integrated_research_runtime_v013.policy import (
    CODE_VERSION,
    IDENTITY_REQUIRED_FIELDS,
    N_PATHS_DEFAULT,
    N_PATHS_MAX,
    NS_SYN,
    PI_HI,
    PI_LO,
    SEED,
    SOURCE_A,
    SOURCE_B,
    SOURCE_NAMESPACE_PAIRS,
    SYN_SOURCE,
    VERSION,
    outcome_unit,
)
from human_simulator.natural_history_rollout_v011.providers import predict_active
from human_simulator.natural_history_rollout_v011.sequences import t0_features

DIRECT_ID_KEYS = {
    "email",
    "phone",
    "full_name",
    "patient_id",
    "user_id",
    "address",
    "passport",
    "insurance_id",
}
DAY_SECONDS = 86400.0
INTERVAL_TOLERANCE_DAYS = 1e-9


def _fail(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "FAIL", "reason": reason, "version": VERSION, **extra}


def _abstain(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "ABSTAIN", "reason": reason, "version": VERSION, **extra}


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _direct_ids(obj: Any) -> bool:
    if isinstance(obj, dict):
        return any((k in DIRECT_ID_KEYS and v) or _direct_ids(v) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_direct_ids(v) for v in obj)
    return False


def _has_future(request: dict[str, Any]) -> bool:
    return bool(
        request.get("has_future_values")
        or request.get("future_intervals")
        or request.get("actual_recorded_label_offset_days")
        or request.get("t1")
        or request.get("t2")
    )


def _intervention_nonzero(obj: dict[str, Any] | None) -> bool:
    if not obj:
        return False
    for k in ("medication", "supplement", "nutrition", "activity", "dose", "duration", "start_time"):
        v = obj.get(k)
        if v not in (None, "", 0, 0.0, False, [], {}):
            return True
    return bool(obj.get("nonzero"))


def parse_aware_datetime(value: Any) -> datetime:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("TIMESTAMP_EMPTY")
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError("TIMESTAMP_UNPARSEABLE") from exc
    if dt.tzinfo is None:
        raise ValueError("TIMESTAMP_NAIVE_TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def bind_source_namespace(source_system: str | None, requested_namespace: str | None) -> tuple[str | None, str | None]:
    if not source_system:
        return None, "SOURCE_REQUIRED"
    derived = SOURCE_NAMESPACE_PAIRS.get(str(source_system)) or namespace_for_source(str(source_system))
    if derived is None:
        return None, "UNKNOWN_NAMESPACE"
    if requested_namespace not in (None, "", derived):
        return None, "SOURCE_NAMESPACE_MISMATCH"
    return derived, None


def _days_between(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / DAY_SECONDS


def verify_temporal_contract(request: dict[str, Any], outcomes: list[str]) -> dict[str, Any]:
    if not request.get("cutoff_t0"):
        return {"ok": False, "status": "FAIL", "reason": "CUTOFF_T0_REQUIRED", "leak": "FAIL", "tier": "UNPROVEN"}
    try:
        cutoff = parse_aware_datetime(request.get("cutoff_t0"))
    except ValueError as exc:
        return {"ok": False, "status": "FAIL", "reason": str(exc) or "CUTOFF_T0_INVALID", "leak": "FAIL", "tier": "UNPROVEN"}
    stamps_map = request.get("history_timestamps")
    history = request.get("history") or {}
    hist_days = request.get("history_days") or {}
    state = request.get("state_at_t0") or {}
    has_stamp_key = stamps_map is not None
    nonempty_stamps = bool(has_stamp_key and any(bool(v) for v in (stamps_map or {}).values()))
    if has_stamp_key:
        for ok in outcomes:
            hv = list(history.get(ok) or [])
            ts = list((stamps_map or {}).get(ok) or [])
            if hv and not ts:
                return {
                    "ok": False,
                    "status": "FAIL",
                    "reason": "HISTORY_TIMESTAMPS_EMPTY_FOR_NONEMPTY_HISTORY",
                    "leak": "FAIL",
                    "tier": "UNPROVEN",
                    "outcome_key": ok,
                }
            if ts and not hv:
                return {
                    "ok": False,
                    "status": "FAIL",
                    "reason": "HISTORY_TIMESTAMPS_WITHOUT_HISTORY",
                    "leak": "FAIL",
                    "tier": "UNPROVEN",
                    "outcome_key": ok,
                }
            extra_keys = set(stamps_map or {}) - set(outcomes)
            if extra_keys:
                return {
                    "ok": False,
                    "status": "FAIL",
                    "reason": "HISTORY_TIMESTAMP_OUTCOME_MISMATCH",
                    "leak": "FAIL",
                    "tier": "UNPROVEN",
                }
        if nonempty_stamps:
            computed_days: dict[str, list[float]] = {}
            for ok in outcomes:
                hv = list(history.get(ok) or [])
                ts_raw = list((stamps_map or {}).get(ok) or [])
                if len(hv) != len(ts_raw):
                    return {
                        "ok": False,
                        "status": "FAIL",
                        "reason": "HISTORY_TIMESTAMP_LENGTH_MISMATCH",
                        "leak": "FAIL",
                        "tier": "UNPROVEN",
                        "outcome_key": ok,
                    }
                parsed: list[datetime] = []
                for t in ts_raw:
                    try:
                        parsed.append(parse_aware_datetime(t))
                    except ValueError as exc:
                        return {
                            "ok": False,
                            "status": "FAIL",
                            "reason": str(exc),
                            "leak": "FAIL",
                            "tier": "UNPROVEN",
                            "outcome_key": ok,
                        }
                for i in range(1, len(parsed)):
                    if parsed[i] < parsed[i - 1]:
                        return {
                            "ok": False,
                            "status": "FAIL",
                            "reason": "HISTORY_TIMESTAMP_ORDER_INVALID",
                            "leak": "FAIL",
                            "tier": "UNPROVEN",
                            "outcome_key": ok,
                        }
                if parsed and parsed[-1] > cutoff:
                    return {
                        "ok": False,
                        "status": "FAIL",
                        "reason": "HISTORY_TIMESTAMP_AFTER_CUTOFF_T0",
                        "leak": "FAIL",
                        "tier": "UNPROVEN",
                        "outcome_key": ok,
                    }
                if ok not in state or not _finite(state[ok]):
                    return {
                        "ok": False,
                        "status": "FAIL",
                        "reason": "STATE_AT_T0_NON_FINITE_OR_MISSING",
                        "leak": "FAIL",
                        "tier": "UNPROVEN",
                        "outcome_key": ok,
                    }
                if hv and abs(float(hv[-1]) - float(state[ok])) > 1e-12 and request.get("state_is_cutoff_state") is not True:
                    return {
                        "ok": False,
                        "status": "FAIL",
                        "reason": "STATE_AT_T0_NOT_LAST_PRE_T0_OBSERVATION",
                        "leak": "FAIL",
                        "tier": "UNPROVEN",
                        "outcome_key": ok,
                    }
                intervals = [_days_between(parsed[i], parsed[i + 1]) for i in range(len(parsed) - 1)]
                provided = list(hist_days.get(ok) or [])
                if provided:
                    if len(provided) != len(intervals):
                        return {
                            "ok": False,
                            "status": "FAIL",
                            "reason": "HISTORY_INTERVAL_LENGTH_MISMATCH",
                            "leak": "FAIL",
                            "tier": "UNPROVEN",
                            "outcome_key": ok,
                        }
                    if any(abs(float(a) - float(b)) > INTERVAL_TOLERANCE_DAYS for a, b in zip(provided, intervals, strict=True)):
                        return {
                            "ok": False,
                            "status": "FAIL",
                            "reason": "HISTORY_INTERVALS_INCONSISTENT_WITH_TIMESTAMPS",
                            "leak": "FAIL",
                            "tier": "UNPROVEN",
                            "outcome_key": ok,
                        }
                computed_days[ok] = [float(x) for x in (provided if provided else intervals)]
            return {
                "ok": True,
                "status": "OK",
                "reason": None,
                "leak": "PASS_NO_T1_T2_READ",
                "tier": "TIMESTAMP_VERIFIED",
                "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": "PASS",
                "DECLARED_PRE_T0_SUMMARY_STATUS": "NOT_USED",
                "history_days": computed_days,
            }
        return {
            "ok": False,
            "status": "FAIL",
            "reason": "HISTORY_TIMESTAMPS_EMPTY_FOR_NONEMPTY_HISTORY"
            if any(history.get(ok) for ok in outcomes)
            else "HISTORY_TIMESTAMPS_UNPROVEN",
            "leak": "FAIL",
            "tier": "UNPROVEN",
        }
    if request.get("history_is_pre_t0_summary") is True:
        return {
            "ok": True,
            "status": "OK",
            "reason": None,
            "leak": "PASS_DECLARED_PRE_T0_SUMMARY_NO_T1_T2_FIELDS",
            "tier": "DECLARED_PRE_T0_SUMMARY",
            "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": "NOT_USED",
            "DECLARED_PRE_T0_SUMMARY_STATUS": "PASS",
            "history_days": None,
        }
    return {
        "ok": False,
        "status": "FAIL",
        "reason": "PRE_T0_HISTORY_CONTRACT_UNPROVEN",
        "leak": "UNPROVEN_PRE_T0_CONTRACT",
        "tier": "UNPROVEN",
    }


def _predict(cell: dict[str, Any], state_value: float, history: list[float], hist_days: list[float], horizon: int) -> float:
    hist = list(history) if history else [float(state_value)]
    if not hist or abs(float(hist[-1]) - float(state_value)) > 1e-12:
        hist = hist + [float(state_value)]
    days = list(hist_days) if hist_days else ([30.0] * max(0, len(hist) - 1))
    feat = t0_features(hist, days, float(horizon))
    order = list(cell.get("feature_order") or [])
    if not order:
        raise ValueError("FEATURE_ORDER_MISSING")
    missing = [k for k in order if k not in feat]
    if missing:
        raise ValueError("FEATURE_PAD_OR_TRUNCATE_FORBIDDEN")
    provider = cell.get("active_provider")
    if provider == "P1":
        if not cell.get("p1_payload"):
            raise ValueError("P1_PAYLOAD_MISSING")
        runtime = {"active_provider": "P1", "p1_payload": cell["p1_payload"], "horizon_days": horizon}
        return float(predict_active(runtime, feat, hist, days))
    if provider == "P0":
        runtime = {"active_provider": "P0", "horizon_days": horizon}
        return float(predict_active(runtime, feat, hist, days))
    raise ValueError("UNKNOWN_PROVIDER_NO_P0_FALLBACK")


def compose_joint_distribution(request: dict[str, Any], bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    if _direct_ids(request):
        return _fail("DIRECT_IDENTIFIER_REJECTED")
    if _has_future(request):
        return _fail("FUTURE_INFORMATION_LEAKAGE", ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS="FAIL")
    if _intervention_nonzero(request.get("intervention")):
        return _fail("INTERVENTION_EFFECT_UNAVAILABLE", INTERVENTION_EFFECT_STATUS="UNAVAILABLE")
    if request.get("force_d1"):
        return _abstain("D1_NOT_ACCEPTED", D1_JOINT_DEPENDENCE_STATUS="NOT_ACCEPTED", route_used=None)
    if request.get("pad_outcomes") or request.get("truncate_outcomes"):
        return _fail("PAD_OR_TRUNCATE_FORBIDDEN")
    ss = request.get("source_system")
    ns, ns_reason = bind_source_namespace(str(ss) if ss else None, request.get("namespace"))
    if ns_reason:
        return _fail(ns_reason)
    if ns == NS_SYN and ss != SYN_SOURCE:
        return _fail("SYNTHETIC_PROVIDER_FORBIDDEN_FOR_CLINICAL_SOURCE")
    if ns != NS_SYN and ss == SYN_SOURCE:
        return _fail("SYNTHETIC_SOURCE_FORBIDDEN_IN_FROZEN_NAMESPACE")
    if bundle is None:
        if ns != NS_SYN:
            return _abstain("FROZEN_BUNDLE_REQUIRED")
        bundle = synthetic_runtime_bundle()
    if bundle.get("synthetic_fixture") and ss in {SOURCE_A, SOURCE_B}:
        return _fail("SYNTHETIC_PROVIDER_FORBIDDEN_FOR_CLINICAL_SOURCE")
    if bundle.get("source_system") and bundle.get("source_system") != ss:
        return _fail("SOURCE_BUNDLE_MISMATCH")
    if bundle.get("namespace") and bundle.get("namespace") != ns:
        return _fail("SOURCE_NAMESPACE_MISMATCH")
    try:
        h = int(request.get("requested_horizon_days"))
    except (TypeError, ValueError):
        return _fail("HORIZON_TYPE_INVALID")
    outcomes = list(request.get("outcome_keys") or [])
    if not outcomes:
        return _fail("OUTCOME_ORDER_REQUIRED")
    prefixes = {ok.split("::")[0] for ok in outcomes}
    if prefixes & {"A"} and prefixes & {"B"}:
        return _fail("NO_A_B_OUTCOME_MIXING")
    if ss == SOURCE_A and any(ok.startswith("B::") for ok in outcomes):
        return _fail("NO_A_B_OUTCOME_MIXING")
    if ss == SOURCE_B and any(ok.startswith("A::") for ok in outcomes):
        return _fail("NO_A_B_OUTCOME_MIXING")
    if ss == SOURCE_A and any(not ok.startswith("A::") and not ok.startswith("SYN::") for ok in outcomes):
        return _fail("OUTCOME_PREFIX_SOURCE_MISMATCH")
    if ss == SOURCE_B and any(not ok.startswith("B::") and not ok.startswith("SYN::") for ok in outcomes):
        return _fail("OUTCOME_PREFIX_SOURCE_MISMATCH")
    temporal = verify_temporal_contract(request, outcomes)
    if not temporal.get("ok"):
        return _fail(
            str(temporal.get("reason") or "PRE_T0_HISTORY_CONTRACT_UNPROVEN"),
            ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS=temporal.get("leak"),
            TEMPORAL_EVIDENCE_TIER=temporal.get("tier"),
            TEMPORAL_TIMESTAMP_VERIFICATION_STATUS=temporal.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") or "FAIL",
            DECLARED_PRE_T0_SUMMARY_STATUS=temporal.get("DECLARED_PRE_T0_SUMMARY_STATUS") or "NOT_USED",
        )
    leak_status = str(temporal.get("leak"))
    n_paths = request.get("n_paths", N_PATHS_DEFAULT)
    try:
        n_paths = int(n_paths)
    except (TypeError, ValueError):
        return _fail("N_PATHS_TYPE_INVALID")
    if n_paths < 1 or n_paths > N_PATHS_MAX:
        return _fail("N_PATHS_OUT_OF_RANGE", n_paths_max=N_PATHS_MAX)
    seed = int(request.get("seed") or SEED)
    replay_key = str(request.get("replay_key") or "runtime")
    cells: dict[str, Any] = bundle.get("cells") or {}
    bundle_outcomes = list(bundle.get("outcomes") or cells.keys())
    if set(outcomes) == set(bundle_outcomes) and outcomes != bundle_outcomes:
        return _fail("OUTCOME_ORDER_MISMATCH")
    identities = request.get("cell_identities")
    if not isinstance(identities, dict) or set(identities) != set(outcomes):
        return _fail("PER_OUTCOME_CELL_IDENTITIES_REQUIRED")
    state = request.get("state_at_t0") or {}
    hist_all = request.get("history") or {}
    hist_days_all = temporal.get("history_days") if temporal.get("history_days") is not None else (request.get("history_days") or {})
    yhat: dict[str, float] = {}
    per_meta: dict[str, Any] = {}
    for ok in outcomes:
        cell = cells.get(ok)
        if not cell:
            return _abstain("MISSING_MARGINAL_PROVIDER", abstained_outcomes=[ok])
        if cell.get("synthetic_fixture") and ss in {SOURCE_A, SOURCE_B}:
            return _fail("SYNTHETIC_PROVIDER_FORBIDDEN_FOR_CLINICAL_SOURCE")
        if cell.get("source_system") not in {ss}:
            return _fail("SOURCE_OUTCOME_MISMATCH")
        unit = outcome_unit(ok)
        ident = identities.get(ok) or {}
        for field in IDENTITY_REQUIRED_FIELDS:
            if ident.get(field) in (None, ""):
                return _fail("MISSING_" + field.upper(), outcome_key=ok, PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS="FAIL")
        need = (
            ("active_payload_sha256", cell.get("active_payload_sha256"), "MODEL_HASH_MISMATCH"),
            ("feature_order_sha256", cell.get("feature_order_sha256"), "FEATURE_ORDER_HASH_MISMATCH"),
            ("scaler_sha256", cell.get("scaler_sha256"), "SCALER_HASH_MISMATCH"),
            ("residual_distribution_sha256", cell.get("residual_distribution_sha256"), "RESIDUAL_HASH_MISMATCH"),
            ("unit", unit, "UNIT_MISMATCH"),
            ("source_system", ss, "IDENTITY_SOURCE_MISMATCH"),
        )
        for key, expected, reason in need:
            got = ident.get(key)
            if str(got) != str(expected):
                return _fail(reason, outcome_key=ok, field=key)
        try:
            ident_h = int(ident.get("requested_horizon_days"))
        except (TypeError, ValueError):
            return _fail("IDENTITY_HORIZON_TYPE_INVALID", outcome_key=ok)
        if ident_h != h:
            return _fail("IDENTITY_HORIZON_MISMATCH", outcome_key=ok)
        if int(cell.get("horizon_days") or 0) != h and h not in set(cell.get("supported_horizons") or []):
            supported = bundle.get("supported_horizons") or [bundle.get("horizon_days"), cell.get("horizon_days")]
            if h not in {int(x) for x in supported if x is not None}:
                return _abstain("UNSUPPORTED_HORIZON")
        if ok not in state or not _finite(state[ok]):
            return _fail("STATE_AT_T0_NON_FINITE_OR_MISSING", outcome_key=ok)
        provider = cell.get("active_provider")
        if provider not in {"P0", "P1"}:
            return _fail("UNKNOWN_PROVIDER_NO_P0_FALLBACK", active_provider=provider)
        if provider == "P1" and not cell.get("p1_payload"):
            return _fail("P1_PAYLOAD_MISSING", outcome_key=ok)
        hv = hist_all.get(ok) or [float(state[ok])]
        hd = hist_days_all.get(ok) or []
        if any(not _finite(x) for x in list(hv) + list(hd)):
            return _fail("HISTORY_NON_FINITE", outcome_key=ok)
        try:
            yhat[ok] = _predict(cell, float(state[ok]), list(hv), list(hd), h)
        except ValueError as exc:
            return _fail(str(exc) or "MARGINAL_INFERENCE_FAIL", outcome_key=ok)
        if not _finite(yhat[ok]):
            return _fail("NON_FINITE_MARGINAL_FORECAST", outcome_key=ok)
        if not cell.get("residual_blocks") and not cell.get("ecdf"):
            return _abstain("RESIDUAL_ONLY_FORBIDDEN", detail="missing verified residual payload")
        per_meta[ok] = {
            "outcome_key": ok,
            "unit": unit,
            "source_system": ss,
            "requested_horizon_days": h,
            "marginal_provider_identity": cell.get("active_payload_sha256"),
            "active_provider": provider,
            "feature_order_sha256": cell.get("feature_order_sha256"),
            "scaler_sha256": cell.get("scaler_sha256"),
            "residual_provider_identity": cell.get("residual_distribution_sha256"),
            "scale_contract": cell.get("scale_contract") or "NATIVE_UNIT_NO_TRANSFORM",
        }
    paths: list[list[float]] = []
    for i in range(n_paths):
        rng = random.Random(
            derive_seed(source_system=str(ss), horizon_days=h, replay_key=replay_key, mode="d0", path_index=i, extra=str(seed))
        )
        row = []
        for ok in outcomes:
            cell = cells[ok]
            if cell.get("residual_blocks"):
                resid = sample_verified_residual(cell, rng)
            else:
                xs = cell.get("ecdf") or []
                if not xs:
                    return _abstain("RESIDUAL_ONLY_FORBIDDEN")
                resid = float(xs[rng.randrange(len(xs))])
            sample = yhat[ok] + resid
            if not _finite(sample):
                return _fail("NON_FINITE_SAMPLE")
            row.append(sample)
        paths.append(row)
    per_outcome = []
    for j, ok in enumerate(outcomes):
        col = sorted(p[j] for p in paths)
        per_outcome.append(
            {
                **per_meta[ok],
                "marginal_forecast": yhat[ok],
                "median": col[len(col) // 2],
                "q05": col[int(PI_LO * (len(col) - 1))],
                "q95": col[int(PI_HI * (len(col) - 1))],
            }
        )
    return {
        "status": "OK",
        "endpoint_type": "SOURCE_SPECIFIC_JOINT_OUTCOME_DISTRIBUTION_AT_REQUESTED_HORIZON",
        "not_a_trajectory": True,
        "CROSS_HORIZON_DEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "namespace": ns,
        "source_system": ss,
        "requested_horizon_days": h,
        "cutoff_t0": request.get("cutoff_t0"),
        "outcome_keys": outcomes,
        "route_used": "D0",
        "D0_explicit": True,
        "D1_JOINT_DEPENDENCE_STATUS": "NOT_ACCEPTED",
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": 0,
        "n_paths": n_paths,
        "n_outcomes": len(outcomes),
        "paths": paths,
        "per_outcome": per_outcome,
        "marginal_forecasts": yhat,
        "residual_added_to_marginal": True,
        "evidence_tier": "SYNTHETIC_FIXTURE" if bundle.get("synthetic_fixture") else "FROZEN_NHR_V011",
        "TEMPORAL_EVIDENCE_TIER": temporal.get("tier"),
        "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": temporal.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"),
        "DECLARED_PRE_T0_SUMMARY_STATUS": temporal.get("DECLARED_PRE_T0_SUMMARY_STATUS"),
        "SOURCE_NAMESPACE_BINDING_STATUS": "PASS",
        "PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS": "PASS",
        "feature_order_sha256": feature_order_sha256(list((next(iter(cells.values())) or {}).get("feature_order") or [])),
        "code_version": CODE_VERSION,
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "CAUSAL_INTERPRETATION_PROHIBITED": True,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": leak_status,
        "applicability": "source_specific_native_units",
        "abstention_reason": None,
        "version": VERSION,
    }


def natural_history_forecast(request: dict[str, Any], bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    out = compose_joint_distribution(request, bundle)
    if out.get("status") != "OK":
        return out
    return {**{k: v for k, v in out.items() if k != "paths"}, "route": "natural_history", "executed": True}
