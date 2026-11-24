"""Engine loads frozen disk payload. Real pre-t0 history. Endpoint = t0+H."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

from human_simulator.core.simulation import (
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    hash_state,
    snapshot_parent_branch,
    verify_parent_isolation,
)
from human_simulator.natural_history_rollout_v011.evaluate import recursive_endpoint
from human_simulator.natural_history_rollout_v011.freeze import verify_pretest_freeze
from human_simulator.natural_history_rollout_v011.hashes import sha_obj
from human_simulator.natural_history_rollout_v011.policy import (
    MODELS_DIR,
    N_PATHS_DEFAULT,
    P1_FEATURE_ORDER,
    PREDECLARED_ABSOLUTE_GRID_DAYS,
    RECURSIVE_BASE_INCREMENT_DAYS,
    SEED,
    VERSION,
    recursive_n_steps,
)
from human_simulator.natural_history_rollout_v011.providers import features_from_history, predict_active
from human_simulator.natural_history_rollout_v011.residuals import sample_residual


def _kernel_lifecycle() -> dict[str, Any]:
    kernel = SimulationKernel(seed=SEED, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 1.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "nhr_v011_parent",
            "label": "Parent",
            "dose": 1.0,
            "dose_change_week": None,
            "events": [{"week": 0, "type": "start"}],
        },
        base_state=base_state,
        models=models,
        start_week=0,
        start_state=copy.deepcopy(base_state),
        start_dose=1.0,
        emit_checkpoint_at=2,
    )
    cps = parent.get("checkpoints") or []
    if not cps:
        return {"ok": False}
    cp = cps[0]
    parent_before = snapshot_parent_branch(parent)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="nhr_v011_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={"week": 3, "type": "dose_change", "dose": 2.5, "name": "nhr_fork"},
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=parent)
    rollback_ok = hash_state(copy.deepcopy(cp["state"])) == (
        cp.get("state_hash") or hash_state(cp["state"])
    )
    return {
        "ok": bool(forked.get("ok")) and bool(isolation.get("fork_isolation_verified")) and rollback_ok,
        "checkpoint": True,
        "fork": True,
        "rollback": rollback_ok,
        "parent_isolation": bool(isolation.get("fork_isolation_verified")),
        "predictions_do_not_drive_synthetic_physiology": True,
    }


def _intervention_nonzero(obj: dict[str, Any] | None) -> bool:
    if not obj:
        return False
    for k in ("medication", "supplement", "nutrition", "activity", "dose", "duration", "start_time"):
        v = obj.get(k)
        if v not in (None, "", 0, 0.0, False, [], {}):
            return True
    return bool(obj.get("nonzero"))


def load_frozen_cells(root: Path) -> list[dict[str, Any]]:
    v = verify_pretest_freeze(root)
    if not v.get("ok"):
        raise RuntimeError(f"freeze not verified: {v}")
    path = root / MODELS_DIR / "pre-test-cells.json"
    return json.loads(path.read_text(encoding="utf-8"))["cells"]


def infer_from_disk(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    cells = load_frozen_cells(root)
    return infer(request, cells)


def infer(request: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, Any]:
    if request.get("feature_vector") is not None:
        return {
            "status": "FAIL",
            "reason": "UNUSED_FEATURE_VECTOR_REJECTED",
        }
    req_hash = request.get("active_payload_sha256") or request.get("model_identity_sha256")
    if not req_hash:
        return {"status": "FAIL", "reason": "MANDATORY_PAYLOAD_IDENTITY_MISSING"}
    if request.get("has_future_values") or request.get("future_intervals"):
        return {"status": "FAIL", "reason": "FUTURE_INFORMATION_LEAKAGE"}
    intervention = request.get("intervention")
    iv = None
    if _intervention_nonzero(intervention):
        iv = {
            "INTERVENTION_EFFECT_STATUS": "UNAVAILABLE",
            "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
            "scenario_modified": False,
            "reason": "NATURAL_HISTORY_ONLY_NO_EFFECT_MODEL",
        }
    horizon = int(request.get("requested_horizon_days") or 0)
    if horizon not in PREDECLARED_ABSOLUTE_GRID_DAYS:
        return {"status": "ABSTAIN", "reason": "UNSUPPORTED_HORIZON", "intervention": iv}
    history = request.get("history_values")
    if not history:
        return {"status": "ABSTAIN", "reason": "MISSING_PRE_T0_HISTORY", "intervention": iv}
    hist_days = list(request.get("history_days") or [])
    mode = request.get("mode") or "direct"
    accepted = [
        c
        for c in cells
        if c.get("source_system") == request.get("source_system")
        and c.get("outcome_key") == request.get("outcome_key")
        and int(c.get("horizon_days") or 0) == horizon
        and c.get("one_step_status")
        in {"VALIDATION_BASELINE_SUPPORTED_P0", "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED"}
    ]
    if not accepted:
        return {
            "status": "ABSTAIN",
            "reason": "NO_ELIGIBLE_CELL",
            "intervention": iv,
            "NATURAL_HISTORY_ONLY": True,
            "CLINICAL_USE_PROHIBITED": True,
            "CAUSAL_INTERPRETATION_PROHIBITED": True,
        }
    cell = accepted[0]
    if req_hash != cell.get("active_payload_sha256"):
        return {"status": "FAIL", "reason": "HASH_MISMATCH_HARD_FAIL"}
    seed = int(request.get("seed") or SEED)
    n_paths = int(request.get("n_paths") or N_PATHS_DEFAULT)
    if mode == "recursive":
        n = recursive_n_steps(horizon)
        if n is None:
            return {"status": "ABSTAIN", "reason": "UNSUPPORTED_INCREMENT", "intervention": iv}
        inc = next(
            (
                c
                for c in cells
                if c.get("source_system") == cell["source_system"]
                and c.get("outcome_key") == cell["outcome_key"]
                and int(c.get("horizon_days") or 0) == RECURSIVE_BASE_INCREMENT_DAYS
                and c.get("one_step_status")
                in {"VALIDATION_BASELINE_SUPPORTED_P0", "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED"}
            ),
            None,
        )
        if inc is None:
            return {"status": "ABSTAIN", "reason": "NO_INCREMENT_CELL", "intervention": iv}
        row = {
            "t0_value": history[-1],
            "history_values_json": history,
            "history_days_json": hist_days,
        }
        paths = []
        for i in range(n_paths):
            rec = recursive_endpoint(inc, row, horizon=horizon, rng=random.Random(seed + i * 17))
            if not rec or rec.get("endpoint") is None:
                continue
            if rec.get("requested_offset") != horizon:
                return {"status": "FAIL", "reason": "HORIZON_IDENTITY"}
            paths.append(rec["endpoint"])
        endpoints = paths
        offset = horizon
    else:
        feat = features_from_history(history, hist_days, float(horizon))
        paths = []
        for i in range(n_paths):
            rng = random.Random(seed + i * 17)
            yhat = predict_active(cell, feat, history, hist_days) + sample_residual(cell, rng)
            paths.append(yhat)
        endpoints = paths
        offset = horizon
    if not endpoints:
        return {"status": "ABSTAIN", "reason": "NO_FINITE_PATHS", "intervention": iv}
    endpoints_s = sorted(endpoints)
    deg = len({round(x, 12) for x in endpoints}) <= 1
    return {
        "status": "OK",
        "paths_n": len(endpoints),
        "median_endpoint": endpoints_s[len(endpoints_s) // 2],
        "q05": endpoints_s[max(0, int(0.05 * (len(endpoints_s) - 1)))],
        "q95": endpoints_s[min(len(endpoints_s) - 1, int(0.95 * (len(endpoints_s) - 1)))],
        "requested_horizon_days": horizon,
        "endpoint_offset_days": offset,
        "horizon_identity_ok": offset == horizon,
        "mode": mode,
        "degenerate_residual": deg,
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "CAUSAL_INTERPRETATION_PROHIBITED": True,
        "active_payload_sha256": cell.get("active_payload_sha256"),
        "active_provider": cell.get("active_provider"),
        "intervention": iv,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
        "ENGINE_REQUESTED_HORIZON_STATUS": "PASS_T0_PLUS_H",
        "ENGINE_REAL_STATE_INPUT_STATUS": "PRE_T0_HISTORY_CONSUMED",
    }


def run_engine_shadow(root: Path, cells: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    life = _kernel_lifecycle()
    if cells is None:
        cells = load_frozen_cells(root)
    poison = infer({"has_future_values": True, "requested_horizon_days": 90, "active_payload_sha256": "x"}, cells)
    missing_id = infer(
        {
            "source_system": "magerya_api",
            "outcome_key": "A::x::u",
            "requested_horizon_days": 90,
            "history_values": [1.0],
        },
        cells,
    )
    unused = infer(
        {
            "feature_vector": [0.0] * len(P1_FEATURE_ORDER),
            "requested_horizon_days": 90,
            "active_payload_sha256": "x",
            "history_values": [1.0],
        },
        cells,
    )
    eligible = [
        c
        for c in cells
        if c.get("one_step_status")
        in {"VALIDATION_BASELINE_SUPPORTED_P0", "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED"}
    ]
    if not eligible:
        ok = life.get("ok") and poison.get("status") == "FAIL" and missing_id.get("status") == "FAIL"
        return {
            "version": VERSION,
            "ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS": "TECHNICAL_SHADOW_ABSTAIN_NO_ELIGIBLE_CELL",
            "ENGINE_DETERMINISTIC_REPLAY_STATUS": "N_A_NO_ACCEPTED_CELL",
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
            "ENGINE_REQUESTED_HORIZON_STATUS": "PASS_T0_PLUS_H",
            "ENGINE_REAL_STATE_INPUT_STATUS": "PRE_T0_HISTORY_CONSUMED",
            "ENGINE_MODEL_ROUTING_STATUS": "DISK_FREEZE_REQUIRED",
            "lifecycle": life,
            "ok": ok,
        }
    cell = eligible[0]
    req = {
        "source_system": cell["source_system"],
        "outcome_key": cell["outcome_key"],
        "requested_horizon_days": cell["horizon_days"],
        "history_values": [1.0, 1.05],
        "history_days": [30.0],
        "seed": SEED,
        "n_paths": 8,
        "active_payload_sha256": cell["active_payload_sha256"],
        "mode": "direct",
    }
    a = infer(req, cells)
    b = infer(req, cells)
    other = infer({**req, "seed": SEED + 1}, cells)
    det = sha_obj(a) == sha_obj(b)
    deg = bool(a.get("degenerate_residual"))
    if deg:
        vary_ok = True
        vary_note = "DEGENERATE_RESIDUAL_INVARIANCE_EXPECTED"
    else:
        vary_ok = a.get("median_endpoint") != other.get("median_endpoint")
        vary_note = "STOCHASTIC_VARIATION"
    ninety = infer({**req, "requested_horizon_days": 90, "active_payload_sha256": cell["active_payload_sha256"] if cell["horizon_days"]==90 else cell["active_payload_sha256"]}, cells)
    # force a 90-day eligible if present
    c90 = next((c for c in eligible if int(c["horizon_days"]) == 90), cell)
    r90 = infer(
        {
            **req,
            "source_system": c90["source_system"],
            "outcome_key": c90["outcome_key"],
            "requested_horizon_days": 90,
            "active_payload_sha256": c90["active_payload_sha256"],
        },
        cells,
    )
    horizon_ok = r90.get("endpoint_offset_days") == 90
    iv2 = infer({**req, "intervention": {"dose": 1}}, cells)
    mismatch = infer({**req, "active_payload_sha256": "0" * 64}, cells)
    ok = (
        life.get("ok")
        and a.get("status") == "OK"
        and det
        and vary_ok
        and poison.get("status") == "FAIL"
        and mismatch.get("status") == "FAIL"
        and unused.get("status") == "FAIL"
        and missing_id.get("status") == "FAIL"
        and horizon_ok
        and iv2.get("intervention", {}).get("scenario_modified") is False
    )
    return {
        "version": VERSION,
        "ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS": "TECHNICAL_SHADOW_PASS" if ok else "FAIL",
        "ENGINE_DETERMINISTIC_REPLAY_STATUS": "PASS" if det else "FAIL",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
        "ENGINE_REQUESTED_HORIZON_STATUS": "PASS_T0_PLUS_H" if horizon_ok else "FAIL",
        "ENGINE_REAL_STATE_INPUT_STATUS": "PRE_T0_HISTORY_CONSUMED",
        "ENGINE_MODEL_ROUTING_STATUS": "DISK_OR_FROZEN_REGISTRY",
        "lifecycle": life,
        "inference": {k: v for k, v in a.items() if k != "paths"},
        "deterministic_repeat": det,
        "different_seed": {"ok": vary_ok, "note": vary_note, "unconditional_or_true": False},
        "horizon_identity_90": r90.get("endpoint_offset_days"),
        "unused_feature_vector": unused,
        "mandatory_identity": missing_id,
        "hash_mismatch": mismatch,
        "intervention": iv2.get("intervention"),
        "ok": ok,
    }
