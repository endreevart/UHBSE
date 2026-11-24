"""Engine-shadow with successful synthetic fork probe (TECHNICAL_SHADOW_ONLY)."""

from __future__ import annotations

import copy
import hashlib
import json
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
from human_simulator.intervention_association_v011.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    VERSION,
)


def run_engine_shadow_probe(*, seed: int = 42) -> dict[str, Any]:
    """Deterministic technical fork that must produce fork.ok == true."""
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 100.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "v011_shadow_parent",
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
        return {
            "ENGINE_SHADOW_EXECUTION_STATUS": "FAIL",
            "ENGINE_SHADOW_CLAIM_LEVEL": "TECHNICAL_SHADOW_ONLY",
            "reason": "no_checkpoint",
            "fork": {"ok": False},
        }
    cp = cps[0]
    parent_before = snapshot_parent_branch(parent)
    # Non-zero dose change → observable synthetic divergence (not clinical)
    fork_event = {
        "week": 3,
        "type": "dose_change",
        "dose": 2.5,
        "name": "technical_shadow_synthetic_divergence",
    }
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="v011_shadow_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event=fork_event,
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=parent)
    rolled = copy.deepcopy(cp["state"])
    rollback_ok = hash_state(rolled) == (cp.get("state_hash") or hash_state(cp["state"]))

    # Repeat for determinism
    parent2 = kernel.simulate_branch(
        branch_def={
            "branch_id": "v011_shadow_parent",
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
    cp2 = parent2["checkpoints"][0]
    forked2 = kernel.fork_from_checkpoint(
        checkpoint=cp2,
        new_branch_id="v011_shadow_fork",
        models=models,
        base_state=base_state,
        parent_live=parent2,
        parent_before=snapshot_parent_branch(parent2),
        fork_event=fork_event,
    )
    h1 = hashlib.sha256(
        json.dumps(
            {
                "parent": parent.get("final_state_hash"),
                "fork": forked.get("final_state_hash"),
                "cp": cp.get("state_hash"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    h2 = hashlib.sha256(
        json.dumps(
            {
                "parent": parent2.get("final_state_hash"),
                "fork": forked2.get("final_state_hash"),
                "cp": cp2.get("state_hash"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    fork_ok = bool(forked.get("ok"))
    finals_differ = bool(
        (forked.get("fork_effect") or {}).get("final_hashes_differ")
        or forked.get("final_state_hash") != parent.get("final_state_hash")
    )
    exec_ok = (
        fork_ok
        and finals_differ
        and isolation.get("fork_isolation_verified")
        and rollback_ok
        and h1 == h2
    )
    return {
        "version": VERSION,
        "ENGINE_SHADOW_EXECUTION_STATUS": "PASS" if exec_ok else "FAIL",
        "ENGINE_SHADOW_CLAIM_LEVEL": "TECHNICAL_SHADOW_ONLY",
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        "synthetic_intervention_model_kept_separate": True,
        "medication_association_models_not_used_in_fork_probe": True,
        "checkpoint": {
            "checkpoint_id": cp.get("checkpoint_id"),
            "week": cp.get("week"),
            "phase": cp.get("phase"),
            "state_hash": cp.get("state_hash") or hash_state(cp["state"]),
            "continue_from_week": cp.get("continue_from_week"),
        },
        "fork": {
            "ok": fork_ok,
            "fork_event": fork_event,
            "continuation_start_week": forked.get("continuation_start_week"),
            "final_state_hash": forked.get("final_state_hash"),
            "fork_effect": forked.get("fork_effect"),
            "synthetic_reason": "dose_change_2.5_vs_counterfactual_same_checkpoint",
        },
        "parent_isolation": isolation,
        "rollback_ok": rollback_ok,
        "determinism": {"hash_run1": h1, "hash_run2": h2, "identical": h1 == h2},
        "v01_defect": "v0.1 used dose=0.0 fork_event yielding fork.ok=false; corrected",
    }


def attach_medication_predictions(art: Path, shadow: dict[str, Any]) -> dict[str, Any]:
    """Optional M1/M2C prediction metadata when frozen models exist."""
    root = art / "frozen_models"
    if not root.is_dir():
        shadow["medication_prediction_attached"] = False
        return shadow
    models = list(root.rglob("model.json"))
    shadow["medication_prediction_attached"] = bool(models)
    shadow["n_frozen_models_available"] = len(models)
    return shadow
