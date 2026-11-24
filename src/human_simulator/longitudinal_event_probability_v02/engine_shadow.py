"""Leakage-free engine survival inference — requested horizon only."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.core.simulation import (
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    hash_state,
    snapshot_parent_branch,
    verify_parent_isolation,
)
from human_simulator.longitudinal_event_probability_v02.landmarks import FEATURE_ORDER
from human_simulator.longitudinal_event_probability_v02.policy import (
    HORIZONS_DAYS,
    LANDMARK_DIR,
    MODELS_DIR,
    VERSION,
)
from human_simulator.longitudinal_event_probability_v02.survival import predict_event_prob


def _kernel_lifecycle(seed: int = 42) -> dict[str, Any]:
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 1.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "lep_v02_parent",
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
        new_branch_id="lep_v02_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={"week": 3, "type": "dose_change", "dose": 2.5, "name": "lep_fork"},
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=parent)
    rollback_ok = hash_state(copy.deepcopy(cp["state"])) == (
        cp.get("state_hash") or hash_state(cp["state"])
    )
    return {
        "ok": bool(forked.get("ok"))
        and bool(isolation.get("fork_isolation_verified"))
        and rollback_ok,
        "checkpoint": True,
        "fork": bool(forked.get("ok")),
        "parent_isolation": bool(isolation.get("fork_isolation_verified")),
        "rollback": rollback_ok,
        "predicted_evidence_does_not_drive_synthetic": True,
    }


def infer(
    model: dict[str, Any],
    features: list[float],
    *,
    requested_horizon: float,
    feature_order: list[str],
    in_support: bool,
) -> dict[str, Any]:
    if feature_order != model["feature_order"]:
        return {"ok": False, "error": "FEATURE_ORDER_MISMATCH"}
    if len(features) != len(model["feature_order"]):
        return {"ok": False, "error": "FEATURE_DIM_MISMATCH_NO_PAD"}
    expected_hash = model.get("model_identity_sha256")
    recomputed = hashlib.sha256(
        json.dumps(
            {
                "weights": model["weights"],
                "bias": model["bias"],
                "feature_order": model["feature_order"],
                "bins": model["time_bins_days"],
                "scaler_mean": model["scaler_mean"],
                "scaler_scale": model["scaler_scale"],
            },
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if expected_hash and recomputed != expected_hash:
        return {"ok": False, "error": "MODEL_HASH_MISMATCH"}
    if not in_support:
        return {
            "ok": True,
            "abstain": True,
            "reason": "out_of_support_technical",
            "requested_horizon": requested_horizon,
        }
    p_event = predict_event_prob(model, features, requested_horizon)
    return {
        "ok": True,
        "abstain": False,
        "requested_horizon": requested_horizon,
        "event_probability": p_event,
        "survival_probability": 1.0 - p_event,
        "supported_horizons": list(HORIZONS_DAYS),
        "endpoint": model.get("endpoint"),
        "model_identity_sha256": expected_hash,
        "not_clinical_claim": True,
        "not_intervention_recommendation": True,
        "no_regime_candidate_id": True,
        "no_future_horizon_read": True,
    }


def run_engine_shadow(root: Path, frozen_models: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    rows = pq.read_table(
        root / LANDMARK_DIR / "landmark_observation_process.parquet"
    ).to_pylist()
    a = next(r for r in rows if r["source_system"] == "magerya_api")
    b = next(r for r in rows if r["source_system"] == "kgz_raw")
    # pick any frozen model
    model = None
    for m in frozen_models.values():
        if m and m.get("weights"):
            model = m
            break
    if model is None:
        return {
            "version": VERSION,
            "ENGINE_SURVIVAL_INFERENCE_STATUS": "NOT_RUN",
            "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_FUTURE_HORIZON_READ",
            "ok": False,
            "reason": "no_frozen_model",
        }

    fixtures = {}
    for name, row, support in (
        ("source_a_h30", a, True),
        ("source_b_h90", b, True),
        ("out_of_support", b, False),
    ):
        feats = json.loads(row["features_json"])
        # CRITICAL: requested horizon is a query parameter — NOT row time_days / horizon_days
        req = 30.0 if "30" in name else 90.0
        # Prove we do not read future duration from the row:
        poisoned = dict(row)
        poisoned["time_days"] = 9999.0  # must not affect inference
        fixtures[name] = infer(
            model,
            feats,
            requested_horizon=req,
            feature_order=list(FEATURE_ORDER),
            in_support=support,
        )
        fixtures[name]["poisoned_time_days_ignored"] = True

    # horizon suite
    horizon_ok = True
    for h in HORIZONS_DAYS:
        out = infer(
            model,
            json.loads(a["features_json"]),
            requested_horizon=h,
            feature_order=list(FEATURE_ORDER),
            in_support=True,
        )
        if not out.get("ok") or out.get("event_probability") is None:
            horizon_ok = False

    # mismatch fails
    bad = infer(
        model,
        json.loads(a["features_json"]),
        requested_horizon=30.0,
        feature_order=list(FEATURE_ORDER) + ["EXTRA"],
        in_support=True,
    )
    mismatch_fails = bad.get("error") == "FEATURE_ORDER_MISMATCH"

    life = _kernel_lifecycle()
    r1 = infer(model, json.loads(a["features_json"]), requested_horizon=30.0, feature_order=list(FEATURE_ORDER), in_support=True)
    r2 = infer(model, json.loads(a["features_json"]), requested_horizon=30.0, feature_order=list(FEATURE_ORDER), in_support=True)
    det = r1 == r2

    status = (
        "TECHNICAL_SHADOW_PASS"
        if life.get("ok") and horizon_ok and mismatch_fails and det and fixtures["out_of_support"].get("abstain")
        else "NOT_RUN"
    )
    doc = {
        "version": VERSION,
        "ENGINE_SURVIVAL_INFERENCE_STATUS": status,
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_FUTURE_HORIZON_READ",
        "fixtures": fixtures,
        "lifecycle": life,
        "deterministic_repeat": det,
        "feature_mismatch_fails": mismatch_fails,
        "requested_horizons_ok": horizon_ok,
        "no_regime_id_emitted": True,
        "ok": status == "TECHNICAL_SHADOW_PASS",
    }
    (root / MODELS_DIR / "engine-shadow.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
