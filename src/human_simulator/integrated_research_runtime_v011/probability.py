"""Event-probability provider execution. Frozen LEP cells or synthetic fixture."""

from __future__ import annotations

import math
from typing import Any

from human_simulator.integrated_research_runtime_v011.hashes import feature_order_sha256, sha_obj
from human_simulator.integrated_research_runtime_v011.policy import SYN_HORIZON, SYN_SOURCE, VERSION

SYN_ENDPOINT = "TIME_TO_NEXT_LAB_PANEL"
SYN_MODEL_ID = "synthetic-lep-fixture-v011"


def synthetic_event_probability(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("has_future_values") or request.get("t1"):
        return {"status": "FAIL", "reason": "FUTURE_INFORMATION_LEAKAGE"}
    ss = request.get("source_system")
    endpoint = request.get("endpoint") or SYN_ENDPOINT
    h = int(request.get("requested_horizon_days") or 0)
    mid = request.get("model_id") or request.get("model_identity_sha256")
    if not mid:
        return {"status": "FAIL", "reason": "MISSING_MODEL_ID"}
    if ss != SYN_SOURCE:
        return {"status": "ABSTAIN", "reason": "CELL_NOT_ENGINE_ELIGIBLE_OR_SOURCE_NOT_SYNTHETIC_FIXTURE"}
    if endpoint != SYN_ENDPOINT:
        return {"status": "FAIL", "reason": "NO_SILENT_ENDPOINT_FALLBACK"}
    if h != SYN_HORIZON:
        return {"status": "ABSTAIN", "reason": "UNSUPPORTED_HORIZON"}
    if mid != SYN_MODEL_ID and mid != sha_obj({"fixture": SYN_MODEL_ID}):
        return {"status": "FAIL", "reason": "MODEL_HASH_MISMATCH"}
    feat_hash = request.get("feature_order_sha256")
    if not feat_hash:
        return {"status": "FAIL", "reason": "FEATURE_ORDER_HASH_REQUIRED"}
    depth = float((request.get("state_at_t0") or {}).get("history_depth") or 1.0)
    lam = 1.0 / max(30.0, 90.0 / max(depth, 1.0))
    event_p = 1.0 - math.exp(-lam * (h / 90.0))
    event_p = min(0.99, max(0.01, event_p))
    return {
        "status": "OK",
        "executed": True,
        "source_system": ss,
        "endpoint": endpoint,
        "requested_horizon_days": h,
        "event_probability": event_p,
        "survival_probability": 1.0 - event_p,
        "not_biological_risk": True,
        "observation_process_only": True,
        "evidence_tier": "SYNTHETIC_FIXTURE",
        "model_id": SYN_MODEL_ID,
        "feature_order_sha256": feature_order_sha256(),
        "CLINICAL_USE_PROHIBITED": True,
        "version": VERSION,
    }


def execute_event_probability(request: dict[str, Any], *, lep_infer=None) -> dict[str, Any]:
    if request.get("source_system") == SYN_SOURCE or not lep_infer:
        return synthetic_event_probability(request)
    try:
        return lep_infer(request)
    except Exception:
        return {"status": "ABSTAIN", "reason": "LEP_PROVIDER_UNAVAILABLE"}
