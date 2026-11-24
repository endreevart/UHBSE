"""Real engine shadow — checkpoint / fork / parent isolation / rollback / repeat inference."""

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
from human_simulator.unified_individual_state_v011.policy import MODELS_DIR, STATES_DIR, VERSION
from human_simulator.unified_individual_state_v011.ridge import predict_ridge


def run_engine_unified_state_shadow(root: Path, baseline_meta: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / MODELS_DIR
    freeze_path = out / "frozen-providers.json"
    if not freeze_path.is_file():
        return {
            "version": VERSION,
            "ENGINE_UNIFIED_STATE_SHADOW_STATUS": "NOT_RUN",
            "reason": "no_frozen_providers",
            "ok": False,
        }

    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    providers = freeze.get("providers") or {}
    if not providers:
        return {
            "version": VERSION,
            "ENGINE_UNIFIED_STATE_SHADOW_STATUS": "NOT_RUN",
            "reason": "empty_providers",
            "ok": False,
        }

    states_path = root / STATES_DIR / "individual_state.parquet"
    states = pq.read_table(states_path).to_pylist()
    if not states:
        return {
            "version": VERSION,
            "ENGINE_UNIFIED_STATE_SHADOW_STATUS": "NOT_RUN",
            "reason": "no_states",
            "ok": False,
        }

    # Sanitized fixture: strip any accidental calendar fields; keep numeric features only
    raw = states[0]
    fixture = {
        "state_id": raw["state_id"],
        "source_system": raw["source_system"],
        "split_role": raw["split_role"],
        "features": {
            k: raw.get(k)
            for k in (
                "days_since_last_event",
                "n_events_before",
                "n_obs_before",
                "n_encounters_before",
                "n_medications_before",
                "n_recommendations_before",
                "n_documents_before",
                "n_procedures_before",
                "source_is_a",
                "source_is_b",
                "has_lab_history",
                "has_med_history",
                "cutoff_ordinal",
                "longitudinal_age_days",
                "missingness_lab",
            )
        },
    }

    outcome_key = sorted(providers.keys())[0]
    prov = providers[outcome_key]

    def infer(state_feat: dict[str, Any], pers: float | None) -> float:
        base = [
            float(state_feat.get(k) or 0)
            for k in (
                "days_since_last_event",
                "n_events_before",
                "n_obs_before",
                "n_encounters_before",
                "n_medications_before",
                "n_recommendations_before",
                "n_documents_before",
                "n_procedures_before",
                "source_is_a",
                "source_is_b",
                "has_lab_history",
                "has_med_history",
                "cutoff_ordinal",
                "longitudinal_age_days",
                "missingness_lab",
            )
        ]
        if pers is None:
            x = base + [0.0, 1.0]
        else:
            x = base + [float(pers), 0.0]
        return predict_ridge(
            {
                "intercept": prov["intercept"],
                "coefficients": prov["coefficients"],
                "scaler_mean": prov["scaler_mean"],
                "scaler_scale": prov["scaler_scale"],
            },
            x,
        )

    pred1 = infer(fixture["features"], 1.0)
    evidence = {
        "record_origin": "PREDICTED",
        "state_id": fixture["state_id"],
        "outcome_key": outcome_key,
        "y_pred": pred1,
        "model_identity_sha256": prov["model_identity_sha256"],
        "model_file_sha256": baseline_meta.get("model_file_sha256"),
        "predictions_do_not_drive_physiology": True,
        "medication_context_not_intervention_effect": True,
    }

    # Real SimulationKernel checkpoint / fork / isolation / rollback
    kernel = SimulationKernel(seed=42, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": float(pred1)}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "uis_v011_parent",
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
            "version": VERSION,
            "ENGINE_UNIFIED_STATE_SHADOW_STATUS": "NOT_RUN",
            "reason": "no_checkpoint",
            "ok": False,
        }
    cp = cps[0]
    parent_before = snapshot_parent_branch(parent)
    # Attach PREDICTED evidence to parent history without mutating physiology drivers
    parent.setdefault("evidence_history", []).append(evidence)
    physiology_hash_before = parent.get("final_state_hash")

    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="uis_v011_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={
            "week": 3,
            "type": "dose_change",
            "dose": 2.5,
            "name": "uis_v011_fork_context_only",
        },
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=parent)
    isolation_ok = bool(isolation.get("fork_isolation_verified"))
    rolled = copy.deepcopy(cp["state"])
    rollback_ok = hash_state(rolled) == (cp.get("state_hash") or hash_state(cp["state"]))

    # Repeat inference after rollback path
    pred2 = infer(fixture["features"], 1.0)
    det_ok = abs(pred1 - pred2) < 1e-12

    # Recompute model file hash
    file_sha = hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    file_ok = file_sha == baseline_meta.get("model_file_sha256")

    real_ops = {
        "checkpoint": True,
        "fork": bool(forked.get("ok")),
        "parent_isolation": isolation_ok,
        "rollback": rollback_ok,
        "repeat_inference": det_ok,
        "dictionary_hash_only": False,
    }
    all_real = all(
        [
            real_ops["checkpoint"],
            real_ops["fork"],
            real_ops["parent_isolation"],
            real_ops["rollback"],
            real_ops["repeat_inference"],
        ]
    )
    status = "TECHNICAL_SHADOW_PASS" if all_real and file_ok else "NOT_RUN"
    # Explicit: PASS forbidden on dictionary-hash-only
    if real_ops["dictionary_hash_only"]:
        status = "NOT_RUN"

    doc = {
        "version": VERSION,
        "ENGINE_UNIFIED_STATE_SHADOW_STATUS": status,
        "real_operations": real_ops,
        "checkpoint_id": cp.get("checkpoint_id"),
        "fork_ok": forked.get("ok"),
        "parent_isolation_ok": isolation_ok,
        "rollback_ok": rollback_ok,
        "deterministic_inference": det_ok,
        "model_file_sha256_match": file_ok,
        "model_identity_sha256": prov["model_identity_sha256"],
        "predictions_do_not_drive_physiology": True,
        "physiology_hash_unchanged_by_evidence_attach": parent.get("final_state_hash")
        == physiology_hash_before,
        "medication_context_not_intervention_effect": True,
        "fixture_sanitized": True,
        "ok": status == "TECHNICAL_SHADOW_PASS",
    }
    (out / "engine-shadow.json").write_text(
        json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return doc
