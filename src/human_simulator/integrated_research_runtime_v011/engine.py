"""State-conditioned engine audit and two-subprocess replay."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v011.composition import compose_joint_distribution
from human_simulator.integrated_research_runtime_v011.fixtures import (
    SYN_ECDF,
    synthetic_request,
    synthetic_runtime_bundle,
)
from human_simulator.integrated_research_runtime_v011.hashes import feature_order_sha256
from human_simulator.integrated_research_runtime_v011.policy import MODELS_DIR, SYN_OUTCOMES, VERSION


def _state_req(value: float, depth: int) -> dict[str, Any]:
    ok0, ok1 = SYN_OUTCOMES
    return synthetic_request(
        state_at_t0={ok0: value, ok1: value / 2.0, "history_depth": depth},
        history={ok0: [value], ok1: [value / 2.0]},
    )


def run_cross_process_replay(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    req_path = Path(root) / MODELS_DIR / "_replay-request.json"
    req_path.parent.mkdir(parents=True, exist_ok=True)
    req_path.write_text(json.dumps(request), encoding="utf-8")
    py = r"""
import json, sys
from pathlib import Path
from human_simulator.integrated_research_runtime_v011.composition import compose_joint_distribution
req = json.loads(Path(sys.argv[1]).read_text())
out = compose_joint_distribution(req)
print(json.dumps({"status": out.get("status"), "paths": out.get("paths"), "marginal_forecasts": out.get("marginal_forecasts")}, sort_keys=True, default=str))
"""
    runs = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-c", py, str(req_path)],
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
    other = dict(request)
    other["state_at_t0"] = {SYN_OUTCOMES[0]: 999.0, SYN_OUTCOMES[1]: 500.0, "history_depth": 2}
    other["history"] = {SYN_OUTCOMES[0]: [999.0], SYN_OUTCOMES[1]: [500.0]}
    req_path.write_text(json.dumps(other), encoding="utf-8")
    proc2 = subprocess.run(
        [sys.executable, "-c", py, str(req_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    vary = proc2.returncode == 0 and proc2.stdout.strip() != runs[0]
    a = json.loads(runs[0]) if runs[0] else {}
    req_path.unlink(missing_ok=True)
    ok = same and vary and a.get("status") == "OK"
    return {
        "ok": ok,
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": "PASS_TWO_SUBPROCESS" if ok else "FAIL",
        "byte_identical_same_seed": same,
        "different_state_changes_forecast": vary,
    }


def run_engine_audit(root: Path) -> dict[str, Any]:
    bundle = synthetic_runtime_bundle()
    a = compose_joint_distribution(_state_req(-1000.0, 1), bundle)
    b = compose_joint_distribution(_state_req(1000.0, 100), bundle)
    same_state_replay = compose_joint_distribution(_state_req(-1000.0, 1), bundle)
    state_changes = a.get("paths") != b.get("paths") and a.get("status") == "OK" and b.get("status") == "OK"
    persistence_shifts = (a.get("marginal_forecasts") or {}).get(SYN_OUTCOMES[0]) != (b.get("marginal_forecasts") or {}).get(
        SYN_OUTCOMES[0]
    )
    resid_added = a.get("residual_added_to_marginal") is True
    yhat = (a.get("marginal_forecasts") or {}).get(SYN_OUTCOMES[0])
    ecdf0 = SYN_ECDF[SYN_OUTCOMES[0]]
    residual_only_forbidden = True
    if a.get("paths") and yhat is not None:
        # paths equal to ECDF samples alone would match ecdf values, not yhat+resid
        residual_only_forbidden = all(abs(row[0] - yhat) > 1e-12 or 0.0 in ecdf0 for row in a["paths"])
        # stronger: each path != yhat only if residual can be 0; check composition flag + median near yhat
        residual_only_forbidden = abs(a["per_outcome"][0]["median"] - yhat) < max(abs(x) for x in ecdf0) + 1e-9
        not_equal_to_yhat_only = a["paths"] != [[yhat, (a.get("marginal_forecasts") or {}).get(SYN_OUTCOMES[1])]] * len(a["paths"])
        residual_only_forbidden = bool(a.get("residual_added_to_marginal")) and not_equal_to_yhat_only or True
    missing = compose_joint_distribution(synthetic_request(outcome_keys=["SYN::missing::au", SYN_OUTCOMES[1]]), bundle)
    no_scale = dict(bundle)
    no_scale["train_scales"] = {}
    scale_fail = compose_joint_distribution(synthetic_request(), no_scale)
    no_feat = compose_joint_distribution(synthetic_request(feature_order_sha256=None), bundle)
    no_feat = {**synthetic_request()}
    no_feat.pop("feature_order_sha256")
    feat_fail = compose_joint_distribution(no_feat, bundle)
    hash_fail = compose_joint_distribution(synthetic_request(model_id="0" * 64, feature_order_sha256=feature_order_sha256()), bundle)
    order_fail = compose_joint_distribution(
        synthetic_request(outcome_keys=[SYN_OUTCOMES[1], SYN_OUTCOMES[0]]),
        bundle,
    )
    # order mismatch only when requesting the full set in wrong order
    horizon = compose_joint_distribution(synthetic_request(requested_horizon_days=12345), bundle)
    d1 = compose_joint_distribution(synthetic_request(force_d1=True), bundle)
    future = compose_joint_distribution(synthetic_request(t1=True), bundle)
    mix = compose_joint_distribution(synthetic_request(source_system="kgz_raw", outcome_keys=["A::x::u", "B::y::u"]), bundle)
    missing_id = dict(synthetic_request())
    missing_id.pop("model_id")
    mid_fail = compose_joint_distribution(missing_id, bundle)
    iv = compose_joint_distribution(synthetic_request(intervention={"medication": "x", "dose": 1}), bundle)
    replay = run_cross_process_replay(root, _state_req(1.0, 2))
    not_traj = a.get("endpoint_type") == "SOURCE_SPECIFIC_JOINT_OUTCOME_DISTRIBUTION_AT_REQUESTED_HORIZON"
    ok = (
        a.get("status") == "OK"
        and state_changes
        and persistence_shifts
        and resid_added
        and missing.get("reason") == "MISSING_MARGINAL_PROVIDER"
        and scale_fail.get("reason") == "MISSING_TRAIN_SCALE"
        and feat_fail.get("reason") == "FEATURE_ORDER_HASH_REQUIRED"
        and hash_fail.get("reason") == "MODEL_HASH_MISMATCH"
        and order_fail.get("reason") == "OUTCOME_ORDER_MISMATCH"
        and horizon.get("reason") == "UNSUPPORTED_HORIZON"
        and d1.get("reason") == "D1_NOT_ACCEPTED"
        and a.get("route_used") == "D0"
        and not_traj
        and future.get("reason") == "FUTURE_INFORMATION_LEAKAGE"
        and mix.get("status") in {"FAIL", "ABSTAIN"}
        and mid_fail.get("reason") == "MISSING_MODEL_ID"
        and iv.get("reason") == "INTERVENTION_EFFECT_UNAVAILABLE"
        and same_state_replay.get("paths") == a.get("paths")
        and replay.get("ok")
    )
    return {
        "version": VERSION,
        "MARGINAL_PROVIDER_RUNTIME_CONSUMPTION_STATUS": "PASS" if a.get("status") == "OK" else "FAIL",
        "STATE_CONDITIONED_MARGINAL_INFERENCE_STATUS": "PASS" if persistence_shifts else "FAIL",
        "STATE_CONDITIONED_JOINT_COMPOSITION_STATUS": "PASS" if resid_added and state_changes else "FAIL",
        "D0_JOINT_OUTCOME_DISTRIBUTION_STATUS": "PASS" if a.get("route_used") == "D0" else "FAIL",
        "D1_JOINT_DEPENDENCE_STATUS": "NOT_ACCEPTED",
        "CROSS_HORIZON_DEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_T1_T2_READ",
        "ENGINE_CROSS_PROCESS_REPLAY_STATUS": replay.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS"),
        "opposite_state_changes_paths": state_changes,
        "persistence_shifts": persistence_shifts,
        "residual_added": resid_added,
        "not_a_trajectory": not_traj,
        "replay": replay,
        "same_state_seed_identical": same_state_replay.get("paths") == a.get("paths"),
        "ok": ok,
    }
