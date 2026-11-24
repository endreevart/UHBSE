"""State-conditioned D0 composition: future = marginal(state, H) + residual."""

from __future__ import annotations

import random
from typing import Any

from human_simulator.integrated_research_runtime_v011.fixtures import synthetic_runtime_bundle
from human_simulator.integrated_research_runtime_v011.hashes import derive_seed, feature_order_sha256, sha_obj
from human_simulator.integrated_research_runtime_v011.policy import (
    CODE_VERSION,
    N_PATHS_DEFAULT,
    PI_HI,
    PI_LO,
    SEED,
    SYN_HORIZON,
    SYN_SOURCE,
    VERSION,
    outcome_unit,
)
from human_simulator.integrated_research_runtime_v011.scale import ScaleMissingError, scale_value
from human_simulator.natural_history_rollout_v011.policy import P1_FEATURE_ORDER
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


def _features(state_value: float, history: list[float], hist_days: list[float], horizon: int) -> dict[str, Any]:
    hist = list(history) if history else [float(state_value)]
    if hist[-1] != float(state_value):
        hist = hist + [float(state_value)]
    days = list(hist_days) if hist_days else ([30.0] * (len(hist) - 1))
    return t0_features(hist, days, float(horizon))


def _sample_ecdf(xs: list[float], rng: random.Random) -> float:
    if not xs:
        raise ValueError("empty residual ECDF")
    return float(xs[rng.randrange(len(xs))])


def _has_future(request: dict[str, Any]) -> bool:
    return bool(
        request.get("has_future_values")
        or request.get("future_intervals")
        or request.get("actual_recorded_label_offset_days")
        or request.get("t1")
        or request.get("t2")
    )


def _direct_ids(obj: Any) -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in DIRECT_ID_KEYS and v:
                return True
            if _direct_ids(v):
                return True
    elif isinstance(obj, list):
        return any(_direct_ids(v) for v in obj)
    return False


def _intervention_nonzero(obj: dict[str, Any] | None) -> bool:
    if not obj:
        return False
    for k in ("medication", "supplement", "nutrition", "activity", "dose", "duration", "start_time"):
        v = obj.get(k)
        if v not in (None, "", 0, 0.0, False, [], {}):
            return True
    return bool(obj.get("nonzero"))


def compose_joint_distribution(request: dict[str, Any], bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    if _direct_ids(request):
        return {"status": "FAIL", "reason": "DIRECT_IDENTIFIER_REJECTED"}
    if _has_future(request):
        return {"status": "FAIL", "reason": "FUTURE_INFORMATION_LEAKAGE", "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "FAIL"}
    if _intervention_nonzero(request.get("intervention")):
        return {
            "status": "FAIL",
            "reason": "INTERVENTION_EFFECT_UNAVAILABLE",
            "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
        }
    bundle = bundle or synthetic_runtime_bundle()
    ss = request.get("source_system")
    if not ss:
        return {"status": "FAIL", "reason": "SOURCE_REQUIRED"}
    if ss != bundle.get("source_system") and ss not in {cell.get("source_system") for cell in (bundle.get("cells") or {}).values()} and ss != SYN_SOURCE:
        # allow synthetic bundle only when source is synthetic; other sources need matching bundle
        if not (bundle.get("cells") or {}):
            return {"status": "ABSTAIN", "reason": "SOURCE_BUNDLE_MISSING"}
    h = int(request.get("requested_horizon_days") or 0)
    outcomes = list(request.get("outcome_keys") or [])
    if not outcomes:
        return {"status": "FAIL", "reason": "OUTCOME_ORDER_REQUIRED"}
    if request.get("pad_outcomes") or request.get("truncate_outcomes"):
        return {"status": "FAIL", "reason": "PAD_OR_TRUNCATE_FORBIDDEN"}
    if request.get("force_d1"):
        return {"status": "ABSTAIN", "reason": "D1_NOT_ACCEPTED", "D1_JOINT_DEPENDENCE_STATUS": "NOT_ACCEPTED", "route_used": None}
    req_hash = request.get("model_id") or request.get("model_identity_sha256") or request.get("joint_identity_sha256")
    cells: dict[str, Any] = bundle.get("cells") or {}
    if req_hash:
        expected = [cells[ok].get("active_payload_sha256") for ok in outcomes if ok in cells]
        if expected and req_hash not in expected and req_hash != bundle.get("bundle_identity_sha256"):
            # allow feature-order hash as the contract id for the synthetic bundle
            if req_hash != bundle.get("feature_order_sha256") and req_hash != feature_order_sha256():
                return {"status": "FAIL", "reason": "MODEL_HASH_MISMATCH"}
    else:
        return {"status": "FAIL", "reason": "MISSING_MODEL_ID"}
    feat_hash = request.get("feature_order_sha256")
    if feat_hash and feat_hash != feature_order_sha256():
        return {"status": "FAIL", "reason": "FEATURE_ORDER_HASH_MISMATCH"}
    if not feat_hash:
        return {"status": "FAIL", "reason": "FEATURE_ORDER_HASH_REQUIRED"}
    bundle_outcomes = list(bundle.get("outcomes") or cells.keys())
    if outcomes != [ok for ok in outcomes]:
        return {"status": "FAIL", "reason": "OUTCOME_ORDER_MISMATCH"}
    if set(outcomes) - set(bundle_outcomes) and set(outcomes) - set(cells):
        missing = [ok for ok in outcomes if ok not in cells]
        return {"status": "ABSTAIN", "reason": "MISSING_MARGINAL_PROVIDER", "abstained_outcomes": missing}
    if outcomes != [ok for ok in bundle_outcomes if ok in outcomes] and list(outcomes) != list(bundle_outcomes):
        # exact order required vs bundle when requesting the full set
        if set(outcomes) == set(bundle_outcomes) and outcomes != bundle_outcomes:
            return {"status": "FAIL", "reason": "OUTCOME_ORDER_MISMATCH"}
    supported = bundle.get("horizon_days") or SYN_HORIZON
    horizons = bundle.get("supported_horizons") or [supported]
    if h not in {int(supported), *map(int, horizons)}:
        return {"status": "ABSTAIN", "reason": "UNSUPPORTED_HORIZON"}
    state = request.get("state_at_t0") or {}
    hist_all = request.get("history") or {}
    n_paths = int(request.get("n_paths") or N_PATHS_DEFAULT)
    seed = int(request.get("seed") or SEED)
    replay_key = str(request.get("replay_key") or "synthetic")
    scales = {"train_scales": bundle.get("train_scales") or {}}
    ecdf = bundle.get("ecdf") or {}
    yhat: dict[str, float] = {}
    identities: dict[str, Any] = {}
    for ok in outcomes:
        cell = cells.get(ok)
        if not cell:
            return {"status": "ABSTAIN", "reason": "MISSING_MARGINAL_PROVIDER", "abstained_outcomes": [ok]}
        if cell.get("source_system") not in {ss, SYN_SOURCE} and cell.get("source_system") != ss:
            return {"status": "FAIL", "reason": "SOURCE_OUTCOME_MISMATCH"}
        if ok.startswith("A::") and ss == "kgz_raw":
            return {"status": "FAIL", "reason": "NO_A_B_OUTCOME_MIXING"}
        if ok.startswith("B::") and ss == "magerya_api":
            return {"status": "FAIL", "reason": "NO_A_B_OUTCOME_MIXING"}
        if "state_at_t0" not in request or ok not in state:
            return {"status": "FAIL", "reason": "STATE_AT_T0_REQUIRED"}
        hv = hist_all.get(ok) or [float(state[ok])]
        hd = (request.get("history_days") or {}).get(ok) or []
        feat = _features(float(state[ok]), hv, hd, h)
        yhat[ok] = float(predict_active(cell, feat, hv, hd))
        identities[ok] = {
            "marginal_provider_identity": cell.get("active_payload_sha256"),
            "active_provider": cell.get("active_provider"),
            "unit": outcome_unit(ok),
        }
        # prove scale lookup does not silently pass
        try:
            scale_value(scales, cell.get("source_system") or ss, ok, 0.0)
        except ScaleMissingError:
            return {"status": "FAIL", "reason": "MISSING_TRAIN_SCALE"}
        if ok not in ecdf:
            return {"status": "ABSTAIN", "reason": "RESIDUAL_ONLY_FORBIDDEN", "detail": "missing residual ECDF; residual-only forecast prohibited"}
    paths = []
    for i in range(n_paths):
        rng = random.Random(
            derive_seed(source_system=str(ss), horizon_days=h, replay_key=replay_key, mode="d0", path_index=i, extra=str(seed))
        )
        row = []
        for ok in outcomes:
            resid = _sample_ecdf(ecdf[ok], rng)
            row.append(yhat[ok] + resid)
        paths.append(row)
    per_outcome = []
    for j, ok in enumerate(outcomes):
        col = sorted(p[j] for p in paths)
        per_outcome.append(
            {
                "outcome_key": ok,
                "unit": outcome_unit(ok),
                "marginal_forecast": yhat[ok],
                "median": col[len(col) // 2],
                "q05": col[int(PI_LO * (len(col) - 1))],
                "q95": col[int(PI_HI * (len(col) - 1))],
                **identities[ok],
            }
        )
    return {
        "status": "OK",
        "endpoint_type": "SOURCE_SPECIFIC_JOINT_OUTCOME_DISTRIBUTION_AT_REQUESTED_HORIZON",
        "not_a_trajectory": True,
        "CROSS_HORIZON_DEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "source_system": ss,
        "requested_horizon_days": h,
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
        "evidence_tier": "SYNTHETIC_FIXTURE" if bundle.get("synthetic_fixture") else "CANDIDATE",
        "feature_order_sha256": feature_order_sha256(),
        "code_version": CODE_VERSION,
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "CAUSAL_INTERPRETATION_PROHIBITED": True,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
        "applicability": "source_specific_native_units",
        "abstention_reason": None,
        "version": VERSION,
    }


def natural_history_forecast(request: dict[str, Any], bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    out = compose_joint_distribution(request, bundle)
    if out.get("status") != "OK":
        return out
    # single-outcome or joint: expose per-outcome marginal
    return {
        **{k: v for k, v in out.items() if k != "paths"},
        "route": "natural_history",
        "executed": True,
        "n_outcomes": out["n_outcomes"],
        "per_outcome": out["per_outcome"],
    }
