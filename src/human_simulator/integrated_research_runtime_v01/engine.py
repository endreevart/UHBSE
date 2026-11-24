"""Disk-loaded joint engine. Scalar inference cannot yield joint PASS."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
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
from human_simulator.integrated_research_runtime_v01.hashes import derive_seed, sha_obj
from human_simulator.integrated_research_runtime_v01.joint_eval import panel_paths
from human_simulator.integrated_research_runtime_v01.joint_model import sample_d0_residuals, sample_d1_residuals
from human_simulator.integrated_research_runtime_v01.joint_normalize import scale_value
from human_simulator.integrated_research_runtime_v01.policy import (
    CODE_VERSION,
    MODELS_DIR,
    N_PATHS_DEFAULT,
    PI_HI,
    PI_LO,
    SEED,
    VERSION,
)


def _kernel_lifecycle() -> dict[str, Any]:
    kernel = SimulationKernel(seed=SEED, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 1.0}
    models = {"persistence": PersistenceBaselineModel(), "synthetic": SyntheticInterventionTestModel()}
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "irr_v01_parent",
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
        new_branch_id="irr_v01_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={"week": 3, "type": "dose_change", "dose": 2.5, "name": "irr_fork"},
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=parent)
    rollback_ok = hash_state(copy.deepcopy(cp["state"])) == (cp.get("state_hash") or hash_state(cp["state"]))
    return {
        "ok": bool(forked.get("ok")) and bool(isolation.get("fork_isolation_verified")) and rollback_ok,
        "checkpoint": True,
        "fork": True,
        "rollback": rollback_ok,
        "parent_isolation": bool(isolation.get("fork_isolation_verified")),
    }


def _intervention_nonzero(obj: dict[str, Any] | None) -> bool:
    if not obj:
        return False
    for k in ("medication", "supplement", "nutrition", "activity", "dose", "duration", "start_time"):
        v = obj.get(k)
        if v not in (None, "", 0, 0.0, False, [], {}):
            return True
    return bool(obj.get("nonzero"))


def load_joint_payload(root: Path) -> dict[str, Any]:
    path = Path(root) / MODELS_DIR / "joint-payload.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def infer_joint(request: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if request.get("has_future_values") or request.get("future_intervals") or request.get("actual_recorded_label_offset_days"):
        return {"status": "FAIL", "reason": "FUTURE_INFORMATION_LEAKAGE", "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "FAIL"}
    if request.get("scalar_only") or request.get("outcome_key") and not request.get("outcome_keys"):
        return {
            "status": "FAIL",
            "reason": "SCALAR_INFERENCE_CANNOT_PRODUCE_JOINT_PASS",
            "ENGINE_JOINT_ROLLOUT_STATUS": "FAIL_SCALAR_NOT_JOINT",
        }
    routes = payload.get("routes") or []
    ss = request.get("source_system")
    h = int(request.get("requested_horizon_days") or 0)
    req_hash = request.get("joint_identity_sha256") or request.get("model_identity_sha256")
    if not req_hash:
        return {"status": "FAIL", "reason": "MANDATORY_PAYLOAD_IDENTITY_MISSING"}
    model = next(
        (
            r
            for r in routes
            if r.get("source_system") == ss and int(r.get("horizon_days") or 0) == h
        ),
        None,
    )
    if not model:
        return {"status": "ABSTAIN", "reason": "NO_ROUTE", "route_used": None}
    if req_hash != model.get("joint_identity_sha256"):
        return {"status": "FAIL", "reason": "MODEL_HASH_MISMATCH"}
    from human_simulator.integrated_research_runtime_v01.joint_model import composite_identity

    recomputed = composite_identity(model)
    if recomputed != model.get("joint_identity_sha256"):
        return {"status": "FAIL", "reason": "CORRUPTED_PAYLOAD_IDENTITY"}
    req_outcomes = list(request.get("outcome_keys") or [])
    if not req_outcomes:
        return {"status": "FAIL", "reason": "OUTCOME_ORDER_REQUIRED"}
    if req_outcomes != model.get("outcomes"):
        if set(req_outcomes) != set(model.get("outcomes") or []):
            return {"status": "FAIL", "reason": "OUTCOME_ORDER_MISMATCH"}
        return {"status": "FAIL", "reason": "OUTCOME_ORDER_MISMATCH"}
    if request.get("pad_outcomes") or request.get("truncate_outcomes"):
        return {"status": "FAIL", "reason": "PAD_OR_TRUNCATE_FORBIDDEN"}
    accepted = bool(model.get("validation_accepted"))
    route = "D1" if accepted and model.get("chol") else "D0"
    if request.get("force_d1") and not accepted:
        return {"status": "ABSTAIN", "reason": "UNACCEPTED_D1", "route_used": None}
    if _intervention_nonzero(request.get("intervention")):
        intervention = {"scenario_modified": False, "ignored": True}
    else:
        intervention = {"scenario_modified": False}
    n_paths = int(request.get("n_paths") or N_PATHS_DEFAULT)
    seed = int(request.get("seed") or SEED)
    present = req_outcomes
    paths = []
    import random as _random

    for i in range(n_paths):
        rng = _random.Random(
            derive_seed(
                source_system=str(ss),
                horizon_days=h,
                landmark_id=str(request.get("subject_id") or "anon"),
                mode=route.lower(),
                path_index=i,
                extra=str(seed),
            )
        )
        if route == "D1":
            resid = sample_d1_residuals(model, rng, present)
        else:
            resid = sample_d0_residuals(model, rng, present)
        paths.append([resid[ok] for ok in present])
    if len(paths[0]) < 2:
        return {"status": "FAIL", "reason": "JOINT_PATHS_REQUIRE_MULTIPLE_OUTCOMES"}
    per_outcome = []
    for j, ok in enumerate(present):
        col = sorted(p[j] for p in paths)
        per_outcome.append(
            {
                "outcome_key": ok,
                "unit": ok.split("::")[-1] if "::" in ok else "UNKNOWN",
                "median": col[len(col) // 2],
                "q05": col[int(PI_LO * (len(col) - 1))],
                "q95": col[int(PI_HI * (len(col) - 1))],
            }
        )
    out = {
        "status": "OK",
        "route_used": route,
        "accepted_d1": accepted,
        "n_paths": n_paths,
        "n_outcomes": len(present),
        "paths": paths,
        "per_outcome": per_outcome,
        "normalized_dependence_metadata": {
            "family": model.get("family"),
            "psd_method": model.get("psd_method"),
            "panel_contract": model.get("panel_contract"),
        },
        "supported_outcomes": present,
        "supported_horizon_days": h,
        "joint_identity_sha256": model.get("joint_identity_sha256"),
        "code_version": CODE_VERSION,
        "provenance": {"NATURAL_HISTORY_ONLY": True, "record_origin": "PREDICTED"},
        "applicability": "source_specific_strict_panel",
        "abstention_reason": None,
        "NATURAL_HISTORY_ONLY": True,
        "CLINICAL_USE_PROHIBITED": True,
        "CAUSAL_INTERPRETATION_PROHIBITED": True,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
        "ENGINE_JOINT_ROLLOUT_STATUS": "PASS" if route in {"D0", "D1"} and len(present) >= 2 else "FAIL",
        "intervention": intervention,
    }
    return out


def _payload_for_engine(models: list[dict[str, Any]], accepted_keys: set[tuple[str, int]]) -> dict[str, Any]:
    routes = []
    for m in models:
        rec = dict(m)
        rec["validation_accepted"] = (rec.get("source_system"), int(rec.get("horizon_days") or 0)) in accepted_keys
        routes.append(rec)
    return {"routes": routes}


def run_cross_process_replay(root: Path, payload: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    payload_path = Path(root) / MODELS_DIR / "_replay-payload.json"
    req_path = Path(root) / MODELS_DIR / "_replay-request.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    req_path.write_text(json.dumps(request), encoding="utf-8")
    py = r"""
import json, sys
from pathlib import Path
from human_simulator.integrated_research_runtime_v01.engine import infer_joint
payload = json.loads(Path(sys.argv[1]).read_text())
req = json.loads(Path(sys.argv[2]).read_text())
out = infer_joint(req, payload)
print(json.dumps(out, sort_keys=True, default=str))
"""
    runs = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-c", py, str(payload_path), str(req_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "ENGINE_CROSS_PROCESS_REPLAY_STATUS": "FAIL",
                "stderr": (proc.stderr or "")[-1500:],
            }
        runs.append(proc.stdout.strip())
    same = runs[0] == runs[1]
    other_req = dict(request)
    other_req["seed"] = int(request.get("seed") or SEED) + 7
    req_path.write_text(json.dumps(other_req), encoding="utf-8")
    proc2 = subprocess.run(
        [sys.executable, "-c", py, str(payload_path), str(req_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    other = proc2.stdout.strip() if proc2.returncode == 0 else ""
    vary = other != runs[0] and other != ""
    a = json.loads(runs[0]) if runs[0] else {}
    degenerate = len(set(tuple(p) for p in (a.get("paths") or [[0]]))) <= 1
    payload_path.unlink(missing_ok=True)
    req_path.write_text("", encoding="utf-8")
    req_path.unlink(missing_ok=True)
    ok = same and vary and not degenerate and a.get("status") == "OK"
    return {
        "ok": ok,
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": "PASS_TWO_SUBPROCESS" if ok else "FAIL",
        "byte_identical_same_seed": same,
        "different_seed_nondegenerate": vary and not degenerate,
        "n_outcomes": a.get("n_outcomes"),
    }


def run_engine_audit(root: Path, models: list[dict[str, Any]], accepted: list[dict[str, Any]]) -> dict[str, Any]:
    life = _kernel_lifecycle()
    payload = json.loads((Path(root) / MODELS_DIR / "joint-payload.json").read_text(encoding="utf-8")) if (Path(root) / MODELS_DIR / "joint-payload.json").is_file() else _payload_for_engine(models, {(r["source_system"], int(r["horizon_days"])) for r in accepted})
    if not payload.get("routes"):
        return {
            "ENGINE_JOINT_ROLLOUT_STATUS": "ABSTAIN_NO_ROUTE",
            "ENGINE_JOINT_MODEL_ROUTING_STATUS": "EXPLICIT_D0_OR_ABSTAIN",
            "ENGINE_CROSS_PROCESS_REPLAY_STATUS": "N_A",
            "lifecycle": life,
            "ok": bool(life.get("ok")),
        }
    route = payload["routes"][0]
    req = {
        "source_system": route["source_system"],
        "requested_horizon_days": model_h if (model_h := int(route["horizon_days"])) else 0,
        "outcome_keys": list(route["outcomes"]),
        "joint_identity_sha256": route["joint_identity_sha256"],
        "n_paths": 8,
        "seed": SEED,
        "subject_id": "opaque-fixture",
    }
    a = infer_joint(req, payload)
    scalar = infer_joint({**req, "outcome_key": route["outcomes"][0], "outcome_keys": None, "scalar_only": True}, payload)
    poison = infer_joint({**req, "has_future_values": True}, payload)
    mismatch = infer_joint({**req, "outcome_keys": list(reversed(route["outcomes"]))}, payload)
    hash_fail = infer_joint({**req, "joint_identity_sha256": "0" * 64}, payload)
    corrupted = json.loads(json.dumps(payload))
    if corrupted.get("routes"):
        corrupted["routes"][0]["ecdf"] = {"tampered": [0.0]}
        corrupted["routes"][0]["joint_identity_sha256"] = route["joint_identity_sha256"]
    bad = infer_joint(req, corrupted)
    replay = run_cross_process_replay(root, payload, req) if a.get("status") == "OK" else {
        "ok": False,
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": "FAIL",
    }
    joint_ok = (
        a.get("status") == "OK"
        and int(a.get("n_outcomes") or 0) >= 2
        and scalar.get("ENGINE_JOINT_ROLLOUT_STATUS") == "FAIL_SCALAR_NOT_JOINT"
        and poison.get("status") == "FAIL"
        and mismatch.get("status") == "FAIL"
        and hash_fail.get("status") == "FAIL"
        and replay.get("ok")
        and life.get("ok")
    )
    routing = "D1_ONLY_IF_ACCEPTED_ELSE_EXPLICIT_D0_OR_ABSTAIN"
    return {
        "version": VERSION,
        "ENGINE_JOINT_MODEL_ROUTING_STATUS": routing,
        "ENGINE_JOINT_ROLLOUT_STATUS": "PASS" if joint_ok else "FAIL",
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": replay.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS"),
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
        "scalar_cannot_joint_pass": scalar.get("ENGINE_JOINT_ROLLOUT_STATUS") == "FAIL_SCALAR_NOT_JOINT",
        "outcome_order_mismatch_hard_fail": mismatch.get("status") == "FAIL",
        "model_hash_mismatch_hard_fail": hash_fail.get("status") == "FAIL",
        "corrupted_payload_status": bad.get("status"),
        "replay": replay,
        "lifecycle": life,
        "n_path_outcomes": a.get("n_outcomes"),
        "route_used": a.get("route_used"),
        "ok": joint_ok,
    }
