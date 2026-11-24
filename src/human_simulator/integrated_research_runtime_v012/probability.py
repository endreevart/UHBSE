"""Event probability: synthetic fixture vs frozen LEP. Registry presence is not execution."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v012.hashes import p0_feature_order_sha256, sha_obj
from human_simulator.integrated_research_runtime_v012.policy import (
    LEP_MODELS,
    NS_SYN,
    SOURCE_A,
    SOURCE_B,
    SYN_HORIZON,
    SYN_SOURCE,
    VERSION,
)

SYN_ENDPOINT = "TIME_TO_NEXT_LAB_PANEL"
SYN_MODEL_ID = sha_obj({"fixture": "synthetic-lep-v012", "endpoint": SYN_ENDPOINT, "version": VERSION})
SYN_FEATURE_ORDER_SHA256 = p0_feature_order_sha256()


def synthetic_event_probability(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("has_future_values") or request.get("t1"):
        return {"status": "FAIL", "reason": "FUTURE_INFORMATION_LEAKAGE", "version": VERSION}
    ss = request.get("source_system")
    ns = request.get("namespace") or NS_SYN
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
        "CLINICAL_USE_PROHIBITED": True,
        "version": VERSION,
    }


def _in_support_features(source_system: str, root: Path | None = None) -> list[float]:
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
            hist = ranges.get("history_depth") or {}
            if "lo" in hist and "hi" in hist:
                mid = (float(hist["lo"]) + float(hist["hi"])) / 2.0
                values["n_obs_before"] = max(values["n_obs_before"], mid, 1.0)
            mask = ranges.get("mask_proxy") or {}
            if "lo" in mask and "hi" in mask:
                mid_mask = (float(mask["lo"]) + float(mask["hi"])) / 2.0
                values["missingness_lab"] = min(0.99, max(0.0, 1.0 - mid_mask))
    return [float(values[k]) for k in FEATURE_ORDER]


def execute_frozen_lep(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    if request.get("has_future_values") or request.get("t1"):
        return {"status": "FAIL", "reason": "FUTURE_INFORMATION_LEAKAGE", "version": VERSION}
    models = Path(root) / LEP_MODELS
    if not models.is_dir():
        return {
            "status": "ABSTAIN",
            "reason": "LEP_PROVIDER_UNAVAILABLE",
            "FROZEN_LEP_EXECUTION_STATUS": "LEP_PROVIDER_UNAVAILABLE",
            "detail": "frozen LEP model directory absent; registry presence is not execution",
            "version": VERSION,
        }
    ss = request.get("source_system")
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
        from human_simulator.longitudinal_event_probability_v0211.policy import FEATURE_ORDER
        from human_simulator.longitudinal_event_probability_v0211.estimators import feature_order_hash
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ABSTAIN",
            "reason": "LEP_PROVIDER_UNAVAILABLE",
            "FROZEN_LEP_EXECUTION_STATUS": "LEP_PROVIDER_UNAVAILABLE",
            "detail": type(exc).__name__,
            "version": VERSION,
        }
    expected_fo = feature_order_hash(list(FEATURE_ORDER))
    if feat_hash != expected_fo:
        return {"status": "FAIL", "reason": "FEATURE_ORDER_HASH_MISMATCH", "version": VERSION}
    feats = request.get("features")
    if feats is None:
        feats = _in_support_features(str(ss), root)
    if len(feats) != len(FEATURE_ORDER):
        return {"status": "FAIL", "reason": "FEATURE_DIM_MISMATCH_NO_PAD", "version": VERSION}
    try:
        out = infer(
            Path(root),
            source_system=str(ss),
            endpoint=str(endpoint),
            outcome_key=request.get("outcome_key"),
            requested_horizon=float(h),
            features=[float(x) for x in feats],
            feature_order_sha256=str(feat_hash),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ABSTAIN",
            "reason": "LEP_PROVIDER_UNAVAILABLE",
            "FROZEN_LEP_EXECUTION_STATUS": "LEP_PROVIDER_UNAVAILABLE",
            "detail": type(exc).__name__,
            "version": VERSION,
        }
    if out.get("abstain") or out.get("error") == "CELL_NOT_ENGINE_ELIGIBLE":
        return {
            "status": "ABSTAIN",
            "reason": out.get("error") or out.get("reason") or "LEP_ABSTAIN",
            "FROZEN_LEP_EXECUTION_STATUS": "ABSTAIN",
            "executed": False,
            "not_biological_risk": True,
            "version": VERSION,
        }
    if not out.get("ok"):
        err = str(out.get("error") or "LEP_PROVIDER_UNAVAILABLE")
        if err in {"MODEL_FILE_HASH_MISMATCH", "MODEL_IDENTITY_HASH_MISMATCH", "FEATURE_ORDER_HASH_MISMATCH"}:
            return {"status": "FAIL", "reason": err, "version": VERSION}
        if err == "CELL_NOT_FOUND":
            return {"status": "ABSTAIN", "reason": "LEP_PROVIDER_UNAVAILABLE", "FROZEN_LEP_EXECUTION_STATUS": "LEP_PROVIDER_UNAVAILABLE", "version": VERSION}
        return {"status": "ABSTAIN", "reason": err, "FROZEN_LEP_EXECUTION_STATUS": "ABSTAIN", "version": VERSION}
    ident = out.get("model_identity_sha256")
    if ident != mid:
        return {"status": "FAIL", "reason": "MODEL_HASH_MISMATCH", "version": VERSION}
    return {
        "status": "OK",
        "executed": True,
        "route": "FROZEN_LEP_V0211",
        "SYNTHETIC_EVENT_PROBABILITY_STATUS": "NOT_USED_ON_THIS_ROUTE",
        "FROZEN_LEP_EXECUTION_STATUS": "PASS",
        "source_system": ss,
        "endpoint": endpoint,
        "requested_horizon_days": h,
        "event_probability": out.get("event_probability"),
        "survival_probability": out.get("survival_probability"),
        "not_biological_risk": True,
        "observation_process_only": True,
        "evidence_tier": "FROZEN_LEP_ENGINE_ELIGIBLE",
        "model_id": ident,
        "feature_order_sha256": feat_hash,
        "validation_heldout_tier": "engine_eligible_cell",
        "CLINICAL_USE_PROHIBITED": True,
        "version": VERSION,
    }


def execute_event_probability(request: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    ns = request.get("namespace")
    ss = request.get("source_system")
    if ns == NS_SYN or ss == SYN_SOURCE:
        return synthetic_event_probability(request)
    if root is None:
        return {
            "status": "ABSTAIN",
            "reason": "LEP_PROVIDER_UNAVAILABLE",
            "FROZEN_LEP_EXECUTION_STATUS": "LEP_PROVIDER_UNAVAILABLE",
            "detail": "frozen LEP route requires a repository root; registry presence is not execution",
            "version": VERSION,
        }
    return execute_frozen_lep(root, request)


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
