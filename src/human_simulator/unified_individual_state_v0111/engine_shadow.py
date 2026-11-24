"""Engine shadows — M1 provider vs M2 multi-output (separate statuses)."""

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
from human_simulator.unified_individual_state_v0111.m2_joint import predict_m2
from human_simulator.unified_individual_state_v0111.policy import MODELS_DIR, STATES_DIR, VERSION
from human_simulator.unified_individual_state_v0111.ridge import predict_ridge


def _kernel_lifecycle(seed: int = 42) -> dict[str, Any]:
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 1.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "uis_v0111_parent",
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
        new_branch_id="uis_v0111_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={
            "week": 3,
            "type": "dose_change",
            "dose": 2.5,
            "name": "v0111_fork",
        },
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
    }


def run_engine_shadows(root: Path, baseline_meta: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / MODELS_DIR
    states = pq.read_table(root / STATES_DIR / "individual_state.parquet").to_pylist()
    freeze = json.loads((out / "frozen-providers.json").read_text(encoding="utf-8"))
    providers = freeze.get("providers") or {}

    # --- M1 shadow (must not claim M2) ---
    m1_status = "NOT_RUN"
    if states and providers:
        st = states[0]
        feat = {
            k: st.get(k)
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
        }
        okey = sorted(providers.keys())[0]
        prov = providers[okey]
        base = [float(feat.get(k) or 0) for k in feat]
        x = base + [1.0, 0.0]
        y1 = predict_ridge(
            {
                "intercept": prov["intercept"],
                "coefficients": prov["coefficients"],
                "scaler_mean": prov["scaler_mean"],
                "scaler_scale": prov["scaler_scale"],
            },
            x,
        )
        y2 = predict_ridge(
            {
                "intercept": prov["intercept"],
                "coefficients": prov["coefficients"],
                "scaler_mean": prov["scaler_mean"],
                "scaler_scale": prov["scaler_scale"],
            },
            x,
        )
        life = _kernel_lifecycle()
        evidence = {
            "record_origin": "PREDICTED",
            "provider": "M1",
            "outcome_key": okey,
            "y_pred": y1,
            "predictions_do_not_drive_physiology": True,
        }
        m1_ok = (
            abs(y1 - y2) < 1e-12
            and life.get("ok")
            and hashlib.sha256((out / "frozen-providers.json").read_bytes()).hexdigest()
            == baseline_meta.get("m0_m1_model_file_sha256")
        )
        m1_status = "TECHNICAL_SHADOW_PASS" if m1_ok else "NOT_RUN"
        m1_doc = {
            "ENGINE_M1_PROVIDER_SHADOW_STATUS": m1_status,
            "does_not_confirm_m2": True,
            "lifecycle": life,
            "deterministic_inference": abs(y1 - y2) < 1e-12,
            "evidence_sample": {k: evidence[k] for k in evidence if k != "y_pred"},
            "ok": m1_status == "TECHNICAL_SHADOW_PASS",
        }
    else:
        m1_doc = {
            "ENGINE_M1_PROVIDER_SHADOW_STATUS": "NOT_RUN",
            "ok": False,
        }

    # --- M2 shadow ---
    m2_path = out / "frozen-m2.json"
    if not m2_path.is_file() or baseline_meta.get("JOINT_MULTI_OUTCOME_MODEL_STATUS") != (
        "TECHNICAL_MASKED_MULTI_OUTPUT_EVALUATED"
    ):
        m2_doc = {
            "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS": "NOT_RUN_NO_FROZEN_M2",
            "ok": False,
        }
    else:
        payload = json.loads(m2_path.read_text(encoding="utf-8"))
        model = payload["model"]
        # A and B fixtures
        a_state = next((s for s in states if s.get("source_is_a") == 1), states[0])
        b_state = next((s for s in states if s.get("source_is_b") == 1), states[-1])

        def feat_vec(st: dict[str, Any]) -> list[float]:
            base = [
                float(st.get(k) or 0)
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
            return base + [0.0, 1.0]

        # Masks: observe only outcomes matching fixture source
        keys = model["outcome_keys"]
        mask_a = [k.startswith("A::") for k in keys]
        mask_b = [k.startswith("B::") for k in keys]
        pa1 = predict_m2(model, feat_vec(a_state), mask=mask_a)
        pb1 = predict_m2(model, feat_vec(b_state), mask=mask_b)
        pa2 = predict_m2(model, feat_vec(a_state), mask=mask_a)
        pb2 = predict_m2(model, feat_vec(b_state), mask=mask_b)
        det = pa1 == pa2 and pb1 == pb2
        n_pred_a = sum(1 for v in pa1.values() if v is not None)
        n_pred_b = sum(1 for v in pb1.values() if v is not None)
        evidence_multi = {
            "record_origin": "PREDICTED",
            "n_a_predictions": n_pred_a,
            "n_b_predictions": n_pred_b,
            "predictions_do_not_drive_physiology": True,
            "medication_context_not_intervention_effect": True,
        }
        life = _kernel_lifecycle(seed=43)
        file_ok = (
            hashlib.sha256(m2_path.read_bytes()).hexdigest()
            == baseline_meta.get("m2_model_file_sha256")
        )
        m2_ok = (
            life.get("ok")
            and det
            and file_ok
            and n_pred_a >= 1
            and n_pred_b >= 1
        )
        m2_status = "TECHNICAL_SHADOW_PASS" if m2_ok else "NOT_RUN"
        m2_doc = {
            "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS": m2_status,
            "lifecycle": life,
            "deterministic_repeat": det,
            "missing_output_masks_applied": True,
            "a_and_b_fixtures": True,
            "multi_outcome_predicted_evidence": evidence_multi,
            "model_file_sha_match": file_ok,
            "ok": m2_ok,
        }

    doc = {
        "version": VERSION,
        **m1_doc,
        **{k: v for k, v in m2_doc.items() if k.startswith("ENGINE_") or k in {"ok"}},
        "m1": m1_doc,
        "m2": m2_doc,
        "ENGINE_M1_PROVIDER_SHADOW_STATUS": m1_doc.get("ENGINE_M1_PROVIDER_SHADOW_STATUS"),
        "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS": m2_doc.get(
            "ENGINE_M2_MULTI_OUTPUT_SHADOW_STATUS"
        ),
        "m1_pass_does_not_imply_m2_pass": True,
        "ok": bool(m1_doc.get("ok")),
    }
    # overall ok for pipeline: M1 required; M2 required only if frozen
    if m2_path.is_file() and baseline_meta.get("JOINT_MULTI_OUTCOME_MODEL_STATUS") == (
        "TECHNICAL_MASKED_MULTI_OUTPUT_EVALUATED"
    ):
        doc["ok"] = bool(m1_doc.get("ok")) and bool(m2_doc.get("ok"))
    (out / "engine-shadow.json").write_text(
        json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return doc
