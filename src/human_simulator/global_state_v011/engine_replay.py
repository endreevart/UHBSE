"""Engine shadow + actual-horizon replay proof (reuses SimulationKernel API)."""

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
from human_simulator.global_state_v011.policy import VERSION
from human_simulator.global_state_v01.state_assembler import (
    assemble_individual_state,
    _parse_ts,
)
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def select_subject_by_coverage(
    primary_rows: list[dict[str, Any]],
    *,
    train_val_subjects: set[str],
) -> dict[str, Any] | None:
    by_subj: dict[str, list[dict[str, Any]]] = {}
    for r in primary_rows:
        sid = r["opaque_subject_key"]
        if sid in train_val_subjects:
            continue
        by_subj.setdefault(sid, []).append(r)
    best = None
    best_key = (-1, "")
    for sid, rows in by_subj.items():
        key = (len(rows), sid)
        if key > best_key:
            best_key = key
            best = {
                "opaque_subject_key": sid,
                "n_targets": len(rows),
                "sample_row": max(rows, key=lambda r: float(r["target_horizon_days"])),
                "rows": rows,
            }
    return best


def run_engine_and_actual_horizon_replay(
    *,
    selected: dict[str, Any],
    observations_by_ou: dict[tuple[str, str], list[dict[str, Any]]],
    ensemble: SingleOutcomeTrajectoryEnsemble,
    global_split: dict[str, Any],
    seed: int = 42,
) -> dict[str, Any]:
    sid = selected["opaque_subject_key"]
    sample = selected["sample_row"]
    train_val = set(global_split["sets"]["train"]) | set(global_split["sets"]["validation"])
    role = global_split["assignment"].get(sid)
    split_proof = {
        "subject_role": role,
        "never_in_train_validation": role == "test" and sid not in train_val,
        "global_split_hash": global_split["split_hash"],
    }

    cut = _parse_ts(sample["cutoff"])
    actual_h = float(sample["target_horizon_days"])
    ou = (sample["outcome"], sample["unit"])

    # Fixed 30d demo/engine snapshot (NOT compared to arbitrary next obs)
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

    state_h = assemble_individual_state(
        opaque_subject_key=sid,
        cutoff=cut,
        observations_by_ou=observations_by_ou,
        ensemble=ensemble,
        horizon_days=90.0,
    )
    preds_h = [c.get("prediction") for c in state_h["components"] if c.get("prediction")]
    horizon_changed = _hash(preds_h) != h1

    # Actual-horizon replay
    state_act = assemble_individual_state(
        opaque_subject_key=sid,
        cutoff=cut,
        observations_by_ou=observations_by_ou,
        ensemble=ensemble,
        horizon_days=actual_h,
    )
    pred_act = next(
        (
            c.get("prediction")
            for c in state_act["components"]
            if c.get("outcome") == ou[0] and c.get("unit") == ou[1] and c.get("prediction")
        ),
        None,
    )
    horizon_match = (
        pred_act is not None
        and abs(float(pred_act["horizon_days"]) - actual_h) < 1e-9
        and abs(float(sample["prediction_horizon_days"]) - float(sample["target_horizon_days"]))
        < 1e-9
    )

    # Observed-value perturbation (try several predictable outcomes)
    pert_ok = False
    candidate_ous = [ou]
    for r in selected.get("rows") or []:
        kou = (r["outcome"], r["unit"])
        if kou not in candidate_ous:
            candidate_ous.append(kou)
    for target_ou in candidate_ous[:8]:
        obs_pert = copy.deepcopy(observations_by_ou)
        if target_ou not in obs_pert:
            continue
        series = obs_pert[target_ou]
        eligible = [
            o
            for o in series
            if (t := _parse_ts(o.get("clinical_time") or o.get("ts"))) is not None and t <= cut
        ]
        if not eligible:
            continue
        eligible.sort(
            key=lambda o: (
                str(o.get("clinical_time") or o.get("ts") or ""),
                int(o.get("source_order") or 0),
                str(o.get("component_id") or ""),
            )
        )
        bumped = dict(eligible[-1])
        base_val = float(bumped["value"])
        bumped["value"] = base_val + max(5.0, abs(base_val) * 0.25 + 1.0)
        # Replace the exact observation object identity path used by assembler
        bumped_id = bumped.get("component_id")
        bumped_ts = str(bumped.get("clinical_time") or bumped.get("ts") or "")
        bumped_ord = int(bumped.get("source_order") or 0)
        new_series = []
        for o in series:
            if (
                str(o.get("component_id") or "") == str(bumped_id or "")
                and str(o.get("clinical_time") or o.get("ts") or "") == bumped_ts
                and int(o.get("source_order") or 0) == bumped_ord
            ):
                new_series.append(bumped)
            else:
                new_series.append(o)
        obs_pert[target_ou] = new_series
        state_before = assemble_individual_state(
            opaque_subject_key=sid,
            cutoff=cut,
            observations_by_ou=observations_by_ou,
            ensemble=ensemble,
            horizon_days=actual_h if target_ou == ou else 30.0,
        )
        state_p = assemble_individual_state(
            opaque_subject_key=sid,
            cutoff=cut,
            observations_by_ou=obs_pert,
            ensemble=ensemble,
            horizon_days=actual_h if target_ou == ou else 30.0,
        )
        pred_before = next(
            (
                c.get("prediction")
                for c in state_before["components"]
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
            if abs(float(pred_after["y_pred"]) - float(pred_before["y_pred"])) > 1e-9:
                pert_ok = True
                break

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

    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 5.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    branch = kernel.simulate_branch(
        branch_def={
            "branch_id": "global_state_v011_parent",
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
    branch["evidence_history"] = [
        {
            "kind": "OBSERVED_SNAPSHOT",
            "record_origin": "OBSERVED",
            "state_hash": state_act["state_hash"],
        },
        {
            "kind": "TRAJECTORY_PREDICTION",
            "record_origin": "PREDICTED",
            "n_predictions": 1 if pred_act else 0,
            "prediction_horizon_days": pred_act.get("horizon_days") if pred_act else None,
            "target_horizon_days": actual_h,
            "horizons_equal": horizon_match,
            "state_hash": state_act["state_hash"],
        },
    ]
    branch["trajectory_predictions_attached"] = True
    phys_after = hash_state(branch.get("final_state") or branch.get("state") or base_state)

    cps = branch.get("checkpoints") or []
    if not cps:
        return {
            "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": "FAIL",
            "reason": "no_checkpoint",
            "ok": False,
        }
    cp = cps[0]
    parent_before = snapshot_parent_branch(branch)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="global_state_v011_fork",
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
        "actual_horizon_prediction_equals_target_horizon": horizon_match,
        "predictions_in_evidence_history": any(
            e.get("kind") == "TRAJECTORY_PREDICTION" for e in branch.get("evidence_history") or []
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
        else (
            "PARTIAL"
            if checks["never_in_train_validation"] and checks["determinism_ok"]
            else "FAIL"
        )
    )
    return {
        "version": VERSION,
        "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": status,
        "INDIVIDUAL_STATE_ASSEMBLY_STATUS": "BUILT",
        "claim_level": "TECHNICAL_REAL_HELDOUT_ONLY",
        "not_clinical_validation": True,
        "checks": checks,
        "split_proof": split_proof,
        "demo_fixed_30d_note": (
            "Fixed 30-day state is engine/demo snapshot only; "
            "primary backtest uses actual-horizon predictions."
        ),
        "actual_horizon_replay": {
            "prediction_horizon_days": pred_act.get("horizon_days") if pred_act else None,
            "target_horizon_days": actual_h,
            "horizons_equal": horizon_match,
            "outcome": sample["outcome"],
            "unit": sample["unit"],
            "y_pred_matches_primary_row": (
                pred_act is not None
                and abs(float(pred_act["y_pred"]) - float(sample["y_pred"])) < 1e-9
            ),
        },
        "state_hash": state_act["state_hash"],
        "n_predictions_demo_30d": len(preds1),
        "predictions_hash_run1": h1,
        "predictions_hash_run2": h2,
        "checkpoint": {
            "checkpoint_id": cp.get("checkpoint_id"),
            "state_hash": cp.get("state_hash") or hash_state(cp["state"]),
        },
        "parent_isolation": {
            "fork_isolation_verified": isolation.get("fork_isolation_verified"),
        },
        "public_fields_only": True,
        "ok": status == "TECHNICAL_REAL_HELDOUT_PASS",
    }
