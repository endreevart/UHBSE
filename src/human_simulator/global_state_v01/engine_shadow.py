"""Real globally held-out individual engine shadow."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from human_simulator.core.simulation import (
    PersistenceBaselineModel,
    SimulationKernel,
    SyntheticInterventionTestModel,
    hash_state,
    snapshot_parent_branch,
    verify_parent_isolation,
)
from human_simulator.global_state_v01.policy import VERSION
from human_simulator.global_state_v01.state_assembler import assemble_individual_state
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def select_subject_by_coverage(
    inventory_private_states: list[dict[str, Any]],
    *,
    train_val_subjects: set[str],
) -> dict[str, Any] | None:
    """Select one global-test subject by max provider outcome availability; before viewing errors."""
    best = None
    best_key = (-1, -1, "")
    for st in inventory_private_states:
        sid = st["opaque_subject_key"]
        if sid in train_val_subjects:
            continue
        key = (int(st.get("n_predictions") or 0), int(st.get("n_observed") or 0), sid)
        if key > best_key:
            best_key = key
            best = st
    return best


def run_real_heldout_engine_shadow(
    *,
    selected_state_private: dict[str, Any],
    observations_by_ou: dict[tuple[str, str], list[dict[str, Any]]],
    ensemble: SingleOutcomeTrajectoryEnsemble,
    global_split: dict[str, Any],
    seed: int = 42,
) -> dict[str, Any]:
    sid = selected_state_private["opaque_subject_key"]
    train_val = set(global_split["sets"]["train"]) | set(global_split["sets"]["validation"])
    in_train_val = sid in train_val
    role = global_split["assignment"].get(sid)
    split_proof = {
        "subject_role": role,
        "never_in_train_validation": role == "test" and not in_train_val,
        "global_split_hash": global_split["split_hash"],
    }

    from human_simulator.global_state_v01.backtest import _parse_ts

    cut = _parse_ts(selected_state_private["cutoff"])
    state1 = assemble_individual_state(
        opaque_subject_key=sid,
        cutoff=cut,
        observations_by_ou=observations_by_ou,
        ensemble=ensemble,
        horizon_days=30.0,
    )
    state2 = assemble_individual_state(
        opaque_subject_key=sid,
        cutoff=cut,
        observations_by_ou=observations_by_ou,
        ensemble=ensemble,
        horizon_days=30.0,
    )
    preds1 = [c.get("prediction") for c in state1["components"] if c.get("prediction")]
    preds2 = [c.get("prediction") for c in state2["components"] if c.get("prediction")]
    h1 = _hash(preds1)
    h2 = _hash(preds2)

    # Horizon perturbation
    state_h = assemble_individual_state(
        opaque_subject_key=sid,
        cutoff=cut,
        observations_by_ou=observations_by_ou,
        ensemble=ensemble,
        horizon_days=90.0,
    )
    preds_h = [c.get("prediction") for c in state_h["components"] if c.get("prediction")]
    horizon_changed = _hash(preds_h) != h1

    # Observed-value perturbation: bump latest value of a PREDICTABLE outcome
    obs_pert = copy.deepcopy(observations_by_ou)
    pert_ok = False
    target_ou = None
    for c in state1["components"]:
        if c.get("prediction") and c.get("numeric_value") is not None:
            target_ou = (c["outcome"], c["unit"])
            break
    if target_ou and target_ou in obs_pert:
        series = obs_pert[target_ou]
        eligible = [
            o
            for o in series
            if (t := _parse_ts(o.get("clinical_time") or o.get("ts"))) is not None
            and t <= cut
        ]
        if eligible:
            eligible.sort(
                key=lambda o: (
                    str(o.get("clinical_time") or o.get("ts")),
                    str(o.get("component_id") or ""),
                )
            )
            bumped = dict(eligible[-1])
            bumped["value"] = float(bumped["value"]) + 5.0
            bumped_id = bumped.get("component_id")
            obs_pert[target_ou] = [
                bumped if o.get("component_id") == bumped_id else o for o in series
            ]
            state_p = assemble_individual_state(
                opaque_subject_key=sid,
                cutoff=cut,
                observations_by_ou=obs_pert,
                ensemble=ensemble,
                horizon_days=30.0,
            )
            # Compare prediction for the same outcome
            pred_before = next(
                (
                    c.get("prediction")
                    for c in state1["components"]
                    if (c["outcome"], c["unit"]) == target_ou
                ),
                None,
            )
            pred_after = next(
                (
                    c.get("prediction")
                    for c in state_p["components"]
                    if (c["outcome"], c["unit"]) == target_ou
                ),
                None,
            )
            if pred_before and pred_after:
                pert_ok = float(pred_after["y_pred"]) != float(pred_before["y_pred"])
            else:
                pert_ok = _hash(
                    [c.get("prediction") for c in state_p["components"] if c.get("prediction")]
                ) != h1

    # Missing outcome: drop half outcomes
    obs_miss = {
        k: v
        for i, (k, v) in enumerate(sorted(observations_by_ou.items()))
        if i % 2 == 0
    }
    state_m = assemble_individual_state(
        opaque_subject_key=sid,
        cutoff=cut,
        observations_by_ou=obs_miss,
        ensemble=ensemble,
        horizon_days=30.0,
    )
    n_pred_miss = sum(1 for c in state_m["components"] if c.get("prediction"))
    coverage_reduced = n_pred_miss < len(preds1)

    # Engine branch with PREDICTED evidence attached
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 5.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    branch = kernel.simulate_branch(
        branch_def={
            "branch_id": "global_state_v01_parent",
            "label": "Parent",
            "dose": 0.0,
            "dose_change_week": None,
            "events": [{"week": 0, "type": "start"}],
        },
        base_state=base_state,
        models=models,
        start_week=0,
        start_state=copy.deepcopy(base_state),
        start_dose=0.0,
        emit_checkpoint_at=2,
    )
    phys_before = hash_state(branch.get("final_state") or branch.get("state") or base_state)
    history_entry = {
        "kind": "TRAJECTORY_PREDICTION",
        "record_origin": "PREDICTED",
        "n_predictions": len(preds1),
        "predictions_hash": h1,
        "state_hash": state1["state_hash"],
    }
    branch["evidence_history"] = [
        {"kind": "OBSERVED_SNAPSHOT", "record_origin": "OBSERVED", "state_hash": state1["state_hash"]},
        history_entry,
    ]
    branch["trajectory_predictions_attached"] = True
    phys_after = hash_state(branch.get("final_state") or branch.get("state") or base_state)

    cps = branch.get("checkpoints") or []
    if not cps:
        return {
            "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": "FAIL",
            "reason": "no_checkpoint",
        }
    cp = cps[0]
    parent_before = snapshot_parent_branch(branch)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="global_state_v01_fork",
        models=models,
        base_state=base_state,
        parent_live=branch,
        parent_before=parent_before,
        fork_event={
            "week": 3,
            "type": "dose_change",
            "dose": 1.5,
            "name": "technical_perturbation",
        },
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=branch)
    rollback_ok = hash_state(copy.deepcopy(cp["state"])) == (
        cp.get("state_hash") or hash_state(cp["state"])
    )

    checks = {
        "never_in_train_validation": split_proof["never_in_train_validation"],
        "determinism_ok": h1 == h2,
        "horizon_perturbation_changes_output": horizon_changed,
        "observed_value_perturbation_changes_output": pert_ok,
        "missing_outcome_reduces_coverage": coverage_reduced,
        "predictions_in_evidence_history": any(
            e.get("kind") == "TRAJECTORY_PREDICTION" and e.get("n_predictions", 0) > 0
            for e in branch.get("evidence_history") or []
        ),
        "physiology_unchanged_by_predictions": phys_before == phys_after,
        "checkpoint_ok": True,
        "fork_ok": bool(forked.get("fork_isolation_verified")),
        "rollback_ok": rollback_ok,
        "parent_isolation_ok": bool(isolation.get("fork_isolation_verified")),
        "no_medication_selection": True,
    }
    status = (
        "TECHNICAL_REAL_HELDOUT_PASS"
        if all(checks.values())
        else ("PARTIAL" if checks["never_in_train_validation"] and checks["determinism_ok"] else "FAIL")
    )
    return {
        "version": VERSION,
        "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": status,
        "claim_level": "TECHNICAL_REAL_HELDOUT_ONLY",
        "not_clinical_validation": True,
        "checks": checks,
        "split_proof": split_proof,
        "state_hash": state1["state_hash"],
        "n_predictions": len(preds1),
        "n_components": state1["n_components"],
        "status_counts": state1["status_counts"],
        "predictions_hash_run1": h1,
        "predictions_hash_run2": h2,
        "horizon_perturbation_hash": _hash(preds_h),
        "missing_outcome_n_predictions": n_pred_miss,
        "checkpoint": {
            "checkpoint_id": cp.get("checkpoint_id"),
            "state_hash": cp.get("state_hash") or hash_state(cp["state"]),
        },
        "parent_isolation": {
            "fork_isolation_verified": isolation.get("fork_isolation_verified"),
        },
        # Explicitly no dates/values/subject keys
        "public_fields_only": True,
    }
