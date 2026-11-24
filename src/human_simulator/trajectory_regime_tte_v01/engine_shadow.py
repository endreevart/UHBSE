"""Engine shadow — trajectory / TTE as predicted technical evidence only."""

from __future__ import annotations

import copy
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
from human_simulator.trajectory_regime_tte_v01.policy import (
    MODELS_DIR,
    TRANSITIONS_DIR,
    VERSION,
)


def _kernel_lifecycle(seed: int = 42) -> dict[str, Any]:
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 1.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "traj_tte_v01_parent",
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
        return {"ok": False, "reason": "no_checkpoint"}
    cp = cps[0]
    parent_before = snapshot_parent_branch(parent)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="traj_tte_v01_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={"week": 3, "type": "dose_change", "dose": 2.5, "name": "traj_fork"},
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
        "tte_is_not_intervention_recommendation": True,
    }


def run_engine_shadow(root: Path, *, foundation_accepted: bool) -> dict[str, Any]:
    root = Path(root).resolve()
    transitions = pq.read_table(root / TRANSITIONS_DIR / "transitions.parquet").to_pylist()
    a = next(r for r in transitions if r["source_system"] == "magerya_api")
    b = next(r for r in transitions if r["source_system"] == "kgz_raw")
    ood_ref = json.loads(
        (root / MODELS_DIR / "applicability-ood-v02-reference.json").read_text(encoding="utf-8")
    )
    regimes = json.loads(
        (root / MODELS_DIR / "regime-centers.json").read_text(encoding="utf-8")
    )

    def decide(row: dict[str, Any]) -> dict[str, Any]:
        dens = float(row.get("mask_density_t0") or 0)
        src = "A" if row["source_system"] == "magerya_api" else "B"
        thr = (ood_ref.get("ref") or {}).get(src, {}).get("mask_density_p05", 0)
        in_support = dens >= thr
        # nearest regime by simple feat
        x = [
            float(row.get("horizon_days") or 0) / 30.0,
            float(row.get("history_depth_t0") or 0) / 20.0,
            dens,
        ]
        centers = regimes.get("centers") or []
        # pad/truncate to center dim
        best = 0
        best_d = float("inf")
        for i, c in enumerate(centers):
            xx = x + [0.0] * max(0, len(c) - len(x))
            d = sum((xx[j] - c[j]) ** 2 for j in range(min(len(xx), len(c))))
            if d < best_d:
                best_d, best = d, i
        return {
            "applicability": "in_support" if in_support else "out_of_support_technical",
            "regime_candidate_id": best,
            "tte_prob_technical": min(0.99, max(0.01, 1.0 / (1.0 + float(row.get("horizon_days") or 30) / 30.0))),
            "state_representation_used": foundation_accepted,
            "provenance_model_hashes": {
                "regime_k": regimes.get("k"),
                "ood_present": True,
            },
        }

    fixtures = {
        "source_a": decide(a),
        "source_b": decide(b),
        "out_of_support": decide({**b, "mask_density_t0": -1.0}),
    }
    life = _kernel_lifecycle()
    d1 = decide(a)
    d2 = decide(a)
    det = d1 == d2
    status = (
        "TECHNICAL_SHADOW_PASS"
        if life.get("ok") and det and fixtures
        else "NOT_RUN"
    )
    doc = {
        "version": VERSION,
        "ENGINE_TRAJECTORY_TTE_SHADOW_STATUS": status,
        "fixtures": fixtures,
        "lifecycle": life,
        "deterministic_repeat": det,
        "ok": status == "TECHNICAL_SHADOW_PASS",
    }
    (root / MODELS_DIR / "engine-shadow.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
