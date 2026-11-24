"""Event probability: URL-selected LEP routes. Client body cannot choose probe or prove a state adapter."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v015.composition import bind_source_namespace, parse_aware_datetime
from human_simulator.integrated_research_runtime_v015.future_fields import future_information_contract
from human_simulator.integrated_research_runtime_v015.hashes import p0_feature_order_sha256, sha_obj
from human_simulator.integrated_research_runtime_v015.policy import (
    LEP_MODELS,
    NS_SYN,
    SOURCE_A,
    SOURCE_B,
    SYN_HORIZON,
    SYN_SOURCE,
    VERSION,
)

SYN_ENDPOINT = "TIME_TO_NEXT_LAB_PANEL"
SYN_MODEL_ID = sha_obj({"fixture": "synthetic-lep-v014", "endpoint": SYN_ENDPOINT, "version": VERSION})
SYN_FEATURE_ORDER_SHA256 = p0_feature_order_sha256()
PROBE_MODE = "REFERENCE_FEATURE_PROBE"
STATE_MODE = "STATE_CONDITIONED"
HTTP_ROUTE_STATE = "STATE_CONDITIONED"
HTTP_ROUTE_PROBE = "REFERENCE_PROBE"
REASON_PROBE_URL = "REFERENCE_PROBE_REQUIRES_DEDICATED_URL"
REASON_ADAPTER = "LEP_STATE_ADAPTER_NOT_IMPLEMENTED"
REASON_CLIENT_VECTOR = "LEP_CLIENT_VECTOR_IS_NOT_VERIFIED_STATE_ADAPTER"


def _finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def client_requested_reference_probe(request: dict[str, Any]) -> bool:
    return request.get("REFERENCE_FEATURE_PROBE") is True or request.get("lep_input_mode") == PROBE_MODE


def _feature_order() -> list[str]:
    from human_simulator.longitudinal_event_probability_v0211.policy import FEATURE_ORDER

    return list(FEATURE_ORDER)


def client_supplied_lep_vector_kind(request: dict[str, Any]) -> str | None:
    if request.get("features") is not None:
        return "CLIENT_FEATURES_FIELD"
    try:
        order = _feature_order()
    except Exception:  # noqa: BLE001
        return None
    state = request.get("state_at_t0") or {}
    if order and all(k in state and _finite(state.get(k)) for k in order):
        return "FEATURE_ORDER_KEYS_IN_STATE_AT_T0"
    return None


def _cutoff_contract(request: dict[str, Any]) -> dict[str, Any] | None:
    blocked = future_information_contract(request)
    if blocked:
        return blocked
    cutoff = request.get("cutoff_t0")
    if not cutoff:
        return {"status": "FAIL", "reason": "CUTOFF_T0_REQUIRED", "version": VERSION}
    try:
        parse_aware_datetime(cutoff)
    except ValueError as exc:
        return {"status": "FAIL", "reason": str(exc) or "CUTOFF_T0_INVALID", "version": VERSION}
    return None


def synthetic_event_probability(request: dict[str, Any]) -> dict[str, Any]:
    blocked = _cutoff_contract(request)
    if blocked:
        return blocked
    ss = request.get("source_system")
    ns, ns_reason = bind_source_namespace(str(ss) if ss else None, request.get("namespace"))
    if ns_reason:
        return {"status": "FAIL", "reason": ns_reason, "version": VERSION}
    endpoint = request.get("endpoint")
    h = int(request.get("requested_horizon_days") or 0)
    mid = request.get("model_id")
    feat_hash = request.get("feature_order_sha256")
    if ns != NS_SYN or ss != SYN_SOURCE:
        return {"status": "FAIL", "reason": "SYNTHETIC_EVENT_ROUTE_SOURCE_MISMATCH", "version": VERSION}
    if not mid:
        return {"status": "FAIL", "reason": "MISSING_MODEL_ID", "version": VERSION}
    if not feat_hash:
        return {"status": "FAIL", "reason": "FEATURE_ORDER_HASH_REQUIRED", "version": VERSION}
    if endpoint != SYN_ENDPOINT:
        return {"status": "FAIL", "reason": "NO_SILENT_ENDPOINT_FALLBACK", "version": VERSION}
    if h != SYN_HORIZON:
        return {"status": "ABSTAIN", "reason": "UNSUPPORTED_HORIZON", "version": VERSION}
    if mid != SYN_MODEL_ID:
        return {"status": "FAIL", "reason": "MODEL_HASH_MISMATCH", "version": VERSION}
    if feat_hash != SYN_FEATURE_ORDER_SHA256:
        return {"status": "FAIL", "reason": "FEATURE_ORDER_HASH_MISMATCH", "version": VERSION}
    depth = float((request.get("state_at_t0") or {}).get("history_depth") or 1.0)
    lam = 1.0 / max(30.0, 90.0 / max(depth, 1.0))
    event_p = min(0.99, max(0.01, 1.0 - math.exp(-lam * (h / 90.0))))
    return {
        "status": "OK",
        "executed": True,
        "route": "SYNTHETIC_FIXTURE",
        "SYNTHETIC_EVENT_PROBABILITY_STATUS": "PASS",
        "FROZEN_LEP_EXECUTION_STATUS": "NOT_USED_ON_THIS_ROUTE",
        "FROZEN_LEP_REFERENCE_PROBE_STATUS": "NOT_USED_ON_THIS_ROUTE",
        "STATE_CONDITIONED_LEP_STATUS": "NOT_USED_ON_THIS_ROUTE",
        "reference_probe": False,
        "state_conditioned": False,
        "source_system": ss,
        "endpoint": endpoint,
        "requested_horizon_days": h,
        "event_probability": event_p,
        "survival_probability": 1.0 - event_p,
        "not_biological_risk": True,
        "observation_process_only": True,
        "evidence_tier": "SYNTHETIC_FIXTURE",
        "model_id": SYN_MODEL_ID,
        "feature_order_sha256": SYN_FEATURE_ORDER_SHA256,
        "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": "NOT_USED",
        "CLINICAL_USE_PROHIBITED": True,
        "version": VERSION,
    }


def _in_support_features(source_system: str, root: Path | None = None) -> tuple[list[float], dict[str, str]]:
    from human_simulator.longitudinal_event_probability_v0211.policy import FEATURE_ORDER

    src_a = 1.0 if source_system == SOURCE_A else 0.0
    src_b = 1.0 if source_system == SOURCE_B else 0.0
    values = {
        "longitudinal_age_days": 365.0,
        "days_since_last_event": 30.0,
        "n_events_before": 3.0,
        "n_obs_before": 5.0,
        "n_encounters_before": 2.0,
        "n_medications_before": 0.0,
        "n_recommendations_before": 0.0,
        "n_documents_before": 0.0,
        "n_procedures_before": 0.0,
        "source_is_a": src_a,
        "source_is_b": src_b,
        "missingness_lab": 0.0,
        "has_lab_history": 1.0,
        "has_med_history": 0.0,
        "cutoff_ordinal": 100.0,
    }
    origin = {k: "FIXED_SUPPORT_DEFAULT" for k in values}
    origin["source_is_a"] = "REQUEST_SOURCE_FLAG"
    origin["source_is_b"] = "REQUEST_SOURCE_FLAG"
    if root is not None:
        ood_path = Path(root) / LEP_MODELS / "ood-reference.json"
        if ood_path.is_file():
            import json

            det = json.loads(ood_path.read_text(encoding="utf-8"))
            label = "A" if source_system == SOURCE_A else "B"
            ranges = ((det.get("ref") or {}).get(label) or {}).get("ranges") or {}
            for k in ("n_obs_before", "longitudinal_age_days", "days_since_last_event"):
                rng = ranges.get(k) or {}
                if "lo" in rng and "hi" in rng:
                    values[k] = (float(rng["lo"]) + float(rng["hi"])) / 2.0
                    origin[k] = "OOD_RANGE_MIDPOINT"
            hist = ranges.get("history_depth") or {}
            if "lo" in hist and "hi" in hist:
                mid = (float(hist["lo"]) + float(hist["hi"])) / 2.0
                values["n_obs_before"] = max(values["n_obs_before"], mid, 1.0)
                origin["n_obs_before"] = "OOD_RANGE_MIDPOINT"
            mask = ranges.get("mask_proxy") or {}
            if "lo" in mask and "hi" in mask:
                mid_mask = (float(mask["lo"]) + float(mask["hi"])) / 2.0
                values["missingness_lab"] = min(0.99, max(0.0, 1.0 - mid_mask))
                origin["missingness_lab"] = "OOD_RANGE_MIDPOINT"
    return [float(values[k]) for k in FEATURE_ORDER], {k: origin[k] for k in FEATURE_ORDER}


def _frozen_lep_common(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    blocked = _cutoff_contract(request)
    if blocked:
        return blocked
    models = Path(root) / LEP_MODELS
    if not models.is_dir():
        return {
            "status": "ABSTAIN",
            "reason": "LEP_PROVIDER_UNAVAILABLE",
            "FROZEN_LEP_REFERENCE_PROBE_STATUS": "LEP_PROVIDER_UNAVAILABLE",
            "STATE_CONDITIONED_LEP_STATUS": "NOT_IMPLEMENTED",
            "detail": "frozen LEP model directory absent; registry presence is not execution",
            "no_synthetic_fallback": True,
            "version": VERSION,
        }
    ss = request.get("source_system")
    ns, ns_reason = bind_source_namespace(str(ss) if ss else None, request.get("namespace"))
    if ns_reason:
        return {"status": "FAIL", "reason": ns_reason, "version": VERSION}
    endpoint = request.get("endpoint")
    h = int(request.get("requested_horizon_days") or 0)
    mid = request.get("model_id")
    feat_hash = request.get("feature_order_sha256")
    if not mid:
        return {"status": "FAIL", "reason": "MISSING_MODEL_ID", "version": VERSION}
    if not feat_hash:
        return {"status": "FAIL", "reason": "FEATURE_ORDER_HASH_REQUIRED", "version": VERSION}
    if ss not in {SOURCE_A, SOURCE_B}:
        return {"status": "FAIL", "reason": "FROZEN_LEP_SOURCE_MISMATCH", "version": VERSION}
    try:
        from human_simulator.longitudinal_event_probability_v0211.engine import infer
        from human_simulator.longitudinal_event_probability_v0211.estimators import feature_order_hash
        from human_simulator.longitudinal_event_probability_v0211.policy import FEATURE_ORDER
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ABSTAIN",
            "reason": "LEP_PROVIDER_UNAVAILABLE",
            "FROZEN_LEP_REFERENCE_PROBE_STATUS": "LEP_PROVIDER_UNAVAILABLE",
            "STATE_CONDITIONED_LEP_STATUS": "NOT_IMPLEMENTED",
            "detail": type(exc).__name__,
            "no_synthetic_fallback": True,
            "version": VERSION,
        }
    expected_fo = feature_order_hash(list(FEATURE_ORDER))
    if feat_hash != expected_fo:
        return {"status": "FAIL", "reason": "FEATURE_ORDER_HASH_MISMATCH", "version": VERSION}
    return {
        "ok": True,
        "ss": ss,
        "ns": ns,
        "endpoint": endpoint,
        "h": h,
        "mid": mid,
        "feat_hash": feat_hash,
        "infer": infer,
        "FEATURE_ORDER": FEATURE_ORDER,
    }


def _run_infer(common: dict[str, Any], root: Path, request: dict[str, Any], feats: list[float]) -> dict[str, Any]:
    infer = common["infer"]
    try:
        out = infer(
            Path(root),
            source_system=str(common["ss"]),
            endpoint=str(common["endpoint"]),
            outcome_key=request.get("outcome_key"),
            requested_horizon=float(common["h"]),
            features=[float(x) for x in feats],
            feature_order_sha256=str(common["feat_hash"]),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ABSTAIN",
            "reason": "LEP_PROVIDER_UNAVAILABLE",
            "detail": type(exc).__name__,
            "no_synthetic_fallback": True,
            "version": VERSION,
        }
    if out.get("abstain") or out.get("error") == "CELL_NOT_ENGINE_ELIGIBLE":
        return {
            "status": "ABSTAIN",
            "reason": out.get("error") or out.get("reason") or "LEP_ABSTAIN",
            "executed": False,
            "not_biological_risk": True,
            "version": VERSION,
        }
    if not out.get("ok"):
        err = str(out.get("error") or "LEP_PROVIDER_UNAVAILABLE")
        if err in {"MODEL_FILE_HASH_MISMATCH", "MODEL_IDENTITY_HASH_MISMATCH", "FEATURE_ORDER_HASH_MISMATCH"}:
            return {"status": "FAIL", "reason": err, "version": VERSION}
        if err == "CELL_NOT_FOUND":
            return {"status": "ABSTAIN", "reason": "LEP_PROVIDER_UNAVAILABLE", "version": VERSION}
        return {"status": "ABSTAIN", "reason": err, "version": VERSION}
    ident = out.get("model_identity_sha256")
    if ident != common["mid"]:
        return {"status": "FAIL", "reason": "MODEL_HASH_MISMATCH", "version": VERSION}
    return {
        "status": "OK",
        "executed": True,
        "event_probability": out.get("event_probability"),
        "survival_probability": out.get("survival_probability"),
        "model_id": ident,
        "version": VERSION,
    }


def execute_frozen_lep_reference_probe(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    common = _frozen_lep_common(root, request)
    if not common.get("ok"):
        return {
            **common,
            "reference_probe": True,
            "state_conditioned": False,
            "route": "FROZEN_LEP_REFERENCE_PROBE",
        }
    feats, origin = _in_support_features(str(common["ss"]), root)
    if len(feats) != len(common["FEATURE_ORDER"]):
        return {"status": "FAIL", "reason": "FEATURE_DIM_MISMATCH_NO_PAD", "version": VERSION}
    ran = _run_infer(common, root, request, feats)
    if ran.get("status") != "OK":
        return {
            **ran,
            "route": "FROZEN_LEP_REFERENCE_PROBE",
            "reference_probe": True,
            "state_conditioned": False,
            "FROZEN_LEP_REFERENCE_PROBE_STATUS": ran.get("reason") or "FAIL",
            "STATE_CONDITIONED_LEP_STATUS": "NOT_USED_ON_THIS_ROUTE",
            "individual_interpretation_prohibited": True,
            "http_route": HTTP_ROUTE_PROBE,
        }
    return {
        **ran,
        "route": "FROZEN_LEP_REFERENCE_PROBE",
        "SYNTHETIC_EVENT_PROBABILITY_STATUS": "NOT_USED_ON_THIS_ROUTE",
        "FROZEN_LEP_EXECUTION_STATUS": "PASS_REFERENCE_PROBE_ONLY",
        "FROZEN_LEP_REFERENCE_PROBE_STATUS": "PASS",
        "STATE_CONDITIONED_LEP_STATUS": "NOT_USED_ON_THIS_ROUTE",
        "reference_probe": True,
        "state_conditioned": False,
        "source_system": common["ss"],
        "namespace": common["ns"],
        "endpoint": common["endpoint"],
        "requested_horizon_days": common["h"],
        "not_biological_risk": True,
        "observation_process_only": True,
        "evidence_tier": "FROZEN_LEP_REFERENCE_PROBE",
        "feature_order_sha256": common["feat_hash"],
        "feature_value_origin": origin,
        "individual_interpretation_prohibited": True,
        "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": "NOT_USED",
        "http_route": HTTP_ROUTE_PROBE,
        "CLINICAL_USE_PROHIBITED": True,
        "version": VERSION,
    }


def execute_state_conditioned_lep(root: Path | None, request: dict[str, Any]) -> dict[str, Any]:
    blocked = _cutoff_contract(request)
    if blocked:
        out = {
            **blocked,
            "STATE_CONDITIONED_LEP_STATUS": "NOT_IMPLEMENTED",
            "state_conditioned": False,
        }
        if blocked.get("reason") != "FUTURE_INFORMATION_LEAKAGE":
            out["TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"] = "NOT_USED"
        return out
    if client_requested_reference_probe(request):
        return {
            "status": "FAIL",
            "reason": REASON_PROBE_URL,
            "reference_probe": False,
            "state_conditioned": False,
            "STATE_CONDITIONED_LEP_STATUS": "NOT_IMPLEMENTED",
            "FROZEN_LEP_REFERENCE_PROBE_STATUS": "NOT_USED_ON_THIS_ROUTE",
            "http_route": HTTP_ROUTE_STATE,
            "version": VERSION,
        }
    ss = request.get("source_system")
    ns, ns_reason = bind_source_namespace(str(ss) if ss else None, request.get("namespace"))
    if ns_reason:
        return {"status": "FAIL", "reason": ns_reason, "version": VERSION}
    if ns == NS_SYN or ss == SYN_SOURCE:
        return {"status": "FAIL", "reason": "FROZEN_LEP_SOURCE_MISMATCH", "version": VERSION}
    kind = client_supplied_lep_vector_kind(request)
    reason = REASON_CLIENT_VECTOR if kind else REASON_ADAPTER
    return {
        "status": "ABSTAIN",
        "reason": reason,
        "client_supplied_vector_kind": kind,
        "executed": False,
        "infer_called": False,
        "reference_probe": False,
        "state_conditioned": False,
        "no_ood_support_substitution": True,
        "no_synthetic_fallback": True,
        "STATE_CONDITIONED_LEP_STATUS": "NOT_IMPLEMENTED",
        "FROZEN_LEP_REFERENCE_PROBE_STATUS": "NOT_USED_ON_THIS_ROUTE",
        "FROZEN_LEP_EXECUTION_STATUS": "NOT_USED_ON_THIS_ROUTE",
        "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": "NOT_USED",
        "http_route": HTTP_ROUTE_STATE,
        "source_system": ss,
        "namespace": ns,
        "detail": (
            "No verified source-specific adapter maps state(t0) and pre-t0 history onto LEP FEATURE_ORDER "
            "with per-feature provenance and a temporal boundary. Client features or FEATURE_ORDER keys in "
            "state_at_t0 are not that adapter."
        ),
        "version": VERSION,
    }


def execute_event_probability(
    request: dict[str, Any],
    *,
    root: Path | None = None,
    http_route: str | None = None,
) -> dict[str, Any]:
    blocked = future_information_contract(request)
    if blocked:
        return blocked
    ns = request.get("namespace")
    ss = request.get("source_system")
    route = http_route or HTTP_ROUTE_STATE
    if route == HTTP_ROUTE_PROBE:
        if ns == NS_SYN or ss == SYN_SOURCE:
            return {
                "status": "FAIL",
                "reason": "REFERENCE_PROBE_FROZEN_ONLY",
                "no_synthetic_fallback": True,
                "version": VERSION,
            }
        if root is None:
            return {
                "status": "ABSTAIN",
                "reason": "LEP_PROVIDER_UNAVAILABLE",
                "FROZEN_LEP_REFERENCE_PROBE_STATUS": "LEP_PROVIDER_UNAVAILABLE",
                "STATE_CONDITIONED_LEP_STATUS": "NOT_USED_ON_THIS_ROUTE",
                "reference_probe": True,
                "state_conditioned": False,
                "no_synthetic_fallback": True,
                "version": VERSION,
            }
        return execute_frozen_lep_reference_probe(root, request)
    if ns == NS_SYN or ss == SYN_SOURCE:
        if client_requested_reference_probe(request):
            return {
                "status": "FAIL",
                "reason": REASON_PROBE_URL,
                "STATE_CONDITIONED_LEP_STATUS": "NOT_USED_ON_THIS_ROUTE",
                "version": VERSION,
            }
        return synthetic_event_probability(request)
    return execute_state_conditioned_lep(root, request)


def frozen_lep_probe_request(root: Path) -> dict[str, Any] | None:
    try:
        from human_simulator.longitudinal_event_probability_v0211.estimators import feature_order_hash
        from human_simulator.longitudinal_event_probability_v0211.policy import FEATURE_ORDER
        from human_simulator.longitudinal_event_probability_v0211.registry import load_registry, lookup_cell

        registry = load_registry(root)
        cell = lookup_cell(registry, SOURCE_B, "TIME_TO_NEXT_LAB_PANEL", None, 90)
    except Exception:  # noqa: BLE001
        return None
    if not cell:
        return None
    return {
        "namespace": "SOURCE_B",
        "source_system": SOURCE_B,
        "endpoint": "TIME_TO_NEXT_LAB_PANEL",
        "requested_horizon_days": 90,
        "model_id": cell.get("model_identity_sha256"),
        "feature_order_sha256": cell.get("feature_order_sha256") or feature_order_hash(list(FEATURE_ORDER)),
        "cutoff_t0": "2000-01-01T00:00:00Z",
        "outcome_key": None,
        "engine_eligible": bool(cell.get("engine_eligible")),
    }


def two_state_lep_vectors(root: Path, request: dict[str, Any], state_a: dict[str, Any], state_b: dict[str, Any]) -> dict[str, Any]:
    a = execute_event_probability({**request, "state_at_t0": state_a}, root=root, http_route=HTTP_ROUTE_STATE)
    b = execute_event_probability({**request, "state_at_t0": state_b}, root=root, http_route=HTTP_ROUTE_STATE)
    infer_used = a.get("infer_called") is True or b.get("infer_called") is True
    abstained = a.get("status") == "ABSTAIN" and b.get("status") == "ABSTAIN"
    no_pass = a.get("STATE_CONDITIONED_LEP_STATUS") == "NOT_IMPLEMENTED" and b.get("STATE_CONDITIONED_LEP_STATUS") == "NOT_IMPLEMENTED"
    return {
        "a_status": a.get("status"),
        "b_status": b.get("status"),
        "a_reason": a.get("reason"),
        "b_reason": b.get("reason"),
        "both_abstain": abstained,
        "infer_called": infer_used,
        "silent_identical_support_vector": False,
        "ok": abstained and no_pass and not infer_used,
        "STATE_CONDITIONED_LEP_STATUS": "NOT_IMPLEMENTED",
    }
