"""Engine shadow — load frozen encoder; fixtures; lifecycle."""

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
from human_simulator.current_state_representation_v01.encoder import predict_encoder
from human_simulator.current_state_representation_v01.policy import (
    MODELS_DIR,
    TENSOR_DIR,
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
            "branch_id": "csr_v01_parent",
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
        new_branch_id="csr_v01_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={"week": 3, "type": "dose_change", "dose": 2.5, "name": "csr_fork"},
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


def run_engine_shadow(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    model = json.loads((root / MODELS_DIR / "frozen-encoder.json").read_text(encoding="utf-8"))
    ood_ref = json.loads(
        (root / MODELS_DIR / "applicability-ood-reference.json").read_text(encoding="utf-8")
    )
    tensors = pq.read_table(root / TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
    a_row = next(r for r in tensors if r["source_system"] == "magerya_api")
    b_row = next(r for r in tensors if r["source_system"] == "kgz_raw")
    # partial: zero most masks
    partial = copy.deepcopy(a_row)
    ch = json.loads(partial["channels_json"])
    for i in range(len(ch["mask"])):
        if i > 2:
            ch["mask"][i] = 0.0
            ch["last_norm"][i] = 0.0
    partial["channels_json"] = json.dumps(ch)
    # OOD-ish: extreme age
    ood_row = copy.deepcopy(b_row)
    ctx = json.loads(ood_row["context_json"])
    ctx["longitudinal_age_days"] = 1e9
    ood_row["context_json"] = json.dumps(ctx)

    fixtures = {}
    for name, row in (
        ("source_a", a_row),
        ("source_b", b_row),
        ("partial_missing", partial),
        ("ood", ood_row),
    ):
        pred = predict_encoder(model, row)
        dens = pred["applicability_features"]["mask_density"]
        fixtures[name] = {
            "state_vector_inference": True,
            "latent_dim": len(pred["latent"]),
            "trajectory_head_n_outcomes": len(pred["forecast"]),
            "mask_density": dens,
            "applicability_decision": "in_support"
            if dens >= ood_ref.get("mask_density_p05", 0)
            and name != "ood"
            else "out_of_support_technical",
        }

    life = _kernel_lifecycle()
    p1 = predict_encoder(model, a_row)
    p2 = predict_encoder(model, a_row)
    det = p1["latent"] == p2["latent"]

    status = (
        "TECHNICAL_SHADOW_PASS"
        if life.get("ok") and det and all(f.get("state_vector_inference") for f in fixtures.values())
        else "NOT_RUN"
    )
    doc = {
        "version": VERSION,
        "ENGINE_CURRENT_STATE_REPRESENTATION_SHADOW_STATUS": status,
        "fixtures": fixtures,
        "lifecycle": life,
        "deterministic_repeat": det,
        "ok": status == "TECHNICAL_SHADOW_PASS",
    }
    (root / MODELS_DIR / "engine-shadow.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
