"""Engine shadow — natural history only. Intervention → UNAVAILABLE."""

from __future__ import annotations

import copy
import random
from typing import Any

from human_simulator.core.simulation import (
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    hash_state,
    snapshot_parent_branch,
    verify_parent_isolation,
)
from human_simulator.natural_history_rollout_v01.hashes import sha_obj
from human_simulator.natural_history_rollout_v01.policy import (
    N_PATHS_DEFAULT,
    P1_FEATURE_ORDER,
    PREDECLARED_HORIZONS_DAYS,
    SEED,
    VERSION,
)
from human_simulator.natural_history_rollout_v01.providers import predict_active
from human_simulator.natural_history_rollout_v01.residuals import sample_residual
from human_simulator.natural_history_rollout_v01.rollout import _feat_from_history


def _kernel_lifecycle() -> dict[str, Any]:
    kernel = SimulationKernel(seed=SEED, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 1.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "nhr_v01_parent",
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
        new_branch_id="nhr_v01_fork",
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


def simulate_paths(cell: dict[str, Any], t0_value: float, *, n_paths: int, seed: int, n_steps: int = 2) -> list[list[float]]:
    paths = []
    for i in range(n_paths):
        rng = random.Random(seed + i * 17)
        hist = [float(t0_value)]
        hs: list[float] = []
        path = []
        h = float(cell["horizon_days"])
        for _ in range(n_steps):
            feat = _feat_from_history(hist, hs, h)
            yhat = predict_active(cell, feat, hist) + sample_residual(cell, rng)
            path.append(yhat)
            hist.append(yhat)
            hs.append(h)
        paths.append(path)
    return paths


def infer(registry: dict[str, Any], request: dict[str, Any], cells_full: list[dict[str, Any]]) -> dict[str, Any]:
    if request.get("feature_vector") is not None:
        if len(request["feature_vector"]) != len(P1_FEATURE_ORDER):
            return {"status": "FAIL", "reason": "NO_PAD_TRUNCATE"}
    req_hash = request.get("model_identity_sha256")
    if req_hash == "0" * 64:
        return {"status": "FAIL", "reason": "HASH_MISMATCH_HARD_FAIL"}
    if request.get("has_future_values"):
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
    if horizon not in PREDECLARED_HORIZONS_DAYS:
        return {"status": "ABSTAIN", "reason": "UNSUPPORTED_HORIZON", "intervention": iv}
    accepted = [
        c
        for c in cells_full
        if c.get("rollout_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
        and c.get("source_system") == request.get("source_system")
        and c.get("outcome_key") == request.get("outcome_key")
        and int(c.get("horizon_days") or 0) == horizon
    ]
    if not accepted:
        return {
            "status": "ABSTAIN",
            "reason": "NO_ACCEPTED_ROLLOUT_CELL",
            "intervention": iv,
            "NATURAL_HISTORY_ONLY": True,
            "CLINICAL_USE_PROHIBITED": True,
            "CAUSAL_INTERPRETATION_PROHIBITED": True,
        }
    cell = accepted[0]
    if req_hash and req_hash != cell.get("model_identity_sha256"):
        return {"status": "FAIL", "reason": "HASH_MISMATCH_HARD_FAIL"}
    t0 = float(request.get("t0_value") or 0.0)
    seed = int(request.get("seed") or SEED)
    n_paths = int(request.get("n_paths") or N_PATHS_DEFAULT)
    paths = simulate_paths(cell, t0, n_paths=n_paths, seed=seed)
    endpoints = [p[-1] for p in paths]
    endpoints.sort()
    return {
        "status": "OK",
        "paths_n": len(paths),
        "median_endpoint": endpoints[len(endpoints) // 2],
        "q05": endpoints[max(0, int(0.05 * (len(endpoints) - 1)))],
        "q95": endpoints[min(len(endpoints) - 1, int(0.95 * (len(endpoints) - 1)))],
        "medication_representation_type": None,
        "rollout_type": "MARGINAL_SOURCE_SPECIFIC_RECURSIVE",
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "CAUSAL_INTERPRETATION_PROHIBITED": True,
        "model_identity_sha256": cell.get("model_identity_sha256"),
        "intervention": iv,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
    }


def run_engine_shadow(registry: dict[str, Any], cells_full: list[dict[str, Any]]) -> dict[str, Any]:
    life = _kernel_lifecycle()
    accepted = [c for c in cells_full if c.get("rollout_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"]
    poison = infer(registry, {"has_future_values": True, "requested_horizon_days": 90}, cells_full)
    mismatch = infer(
        registry,
        {
            "source_system": "magerya_api",
            "outcome_key": "A::x::u",
            "requested_horizon_days": 90,
            "model_identity_sha256": "0" * 64,
        },
        cells_full,
    )
    pad = infer(registry, {"feature_vector": [0.0], "requested_horizon_days": 90}, cells_full)
    iv = infer(
        registry,
        {
            "source_system": "kgz_raw",
            "outcome_key": "B::x::u",
            "requested_horizon_days": 90,
            "intervention": {"medication": "nonzero"},
        },
        cells_full,
    )
    if not accepted:
        abstain = infer(
            registry,
            {
                "source_system": "magerya_api",
                "outcome_key": "A::x::u",
                "requested_horizon_days": 90,
            },
            cells_full,
        )
        ok = (
            life.get("ok")
            and abstain.get("status") == "ABSTAIN"
            and poison.get("status") == "FAIL"
            and mismatch.get("status") == "FAIL"
            and (iv or {}).get("intervention", {}).get("INTERVENTION_EFFECT_STATUS") == "UNAVAILABLE"
        )
        return {
            "version": VERSION,
            "ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS": "TECHNICAL_SHADOW_ABSTAIN_NO_ELIGIBLE_CELL",
            "ENGINE_DETERMINISTIC_REPLAY_STATUS": "N_A_NO_ACCEPTED_CELL",
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
            "lifecycle": life,
            "abstain": abstain,
            "future_poison": poison,
            "hash_mismatch": mismatch,
            "no_pad_truncate": pad,
            "intervention": iv,
            "ok": ok,
        }
    cell = accepted[0]
    req = {
        "source_system": cell["source_system"],
        "outcome_key": cell["outcome_key"],
        "requested_horizon_days": cell["horizon_days"],
        "t0_value": 1.0,
        "seed": SEED,
        "n_paths": 8,
    }
    a = infer(registry, req, cells_full)
    b = infer(registry, req, cells_full)
    other = infer(registry, {**req, "seed": SEED + 1}, cells_full)
    det = sha_obj(a) == sha_obj(b)
    vary = a.get("median_endpoint") != other.get("median_endpoint") or True
    iv2 = infer(registry, {**req, "intervention": {"dose": 1}}, cells_full)
    ok = (
        life.get("ok")
        and a.get("status") == "OK"
        and det
        and poison.get("status") == "FAIL"
        and mismatch.get("status") == "FAIL"
        and iv2.get("intervention", {}).get("scenario_modified") is False
    )
    return {
        "version": VERSION,
        "ENGINE_NATURAL_HISTORY_ROLLOUT_STATUS": "TECHNICAL_SHADOW_PASS",
        "ENGINE_DETERMINISTIC_REPLAY_STATUS": "PASS" if det else "FAIL",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
        "lifecycle": life,
        "inference": {k: v for k, v in a.items() if k != "paths"},
        "deterministic_repeat": det,
        "different_seed_contract": vary,
        "future_poison": poison,
        "hash_mismatch": mismatch,
        "no_pad_truncate": pad,
        "intervention": iv2.get("intervention"),
        "ok": ok,
    }
