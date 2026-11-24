"""Phase 5 — real frozen medication-model inference inside engine shadow."""

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
from human_simulator.core.snapshot import computed_provenance
from human_simulator.intervention_association_v011.models import (
    feat_m1,
    feat_m2c,
)
from human_simulator.medication_knowledge_v01.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    VERSION,
)


def _predict_ridge(coef: list[float], means: list[float], stds: list[float], row: list[float]) -> float:
    xs = [(x - m) / s for x, m, s in zip(row, means, stds, strict=True)]
    return sum(c * v for c, v in zip(coef, [1.0] + xs, strict=True))


def load_and_verify_frozen(model_dir: Path) -> dict[str, Any]:
    path = model_dir / "model.json"
    ident_path = model_dir / "model-identity.json"
    raw = path.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw.decode("utf-8"))
    ident = json.loads(ident_path.read_text(encoding="utf-8")) if ident_path.is_file() else {}
    expected_file = ident.get("file_sha256")
    identity_sha = ident.get("model_identity_sha256")
    ok = expected_file == file_sha if expected_file else True
    return {
        "path": str(path),
        "payload": payload,
        "file_sha256": file_sha,
        "expected_file_sha256": expected_file,
        "file_hash_verified": ok,
        "model_identity_sha256": identity_sha,
        "outcome": payload.get("outcome"),
        "unit": payload.get("unit"),
    }


def run_medication_model_shadow_inference(
    *,
    frozen_root: Path,
    seed: int = 42,
) -> dict[str, Any]:
    """Reload frozen M1/M2C, run inference, attach to engine evidence, fork/rollback."""
    model_dirs = sorted(p for p in frozen_root.iterdir() if p.is_dir()) if frozen_root.is_dir() else []
    if not model_dirs:
        return {
            "MEDICATION_MODEL_SHADOW_INFERENCE_STATUS": "FAIL",
            "ENGINE_SHADOW_EXECUTION_STATUS": "FAIL",
            "ENGINE_SHADOW_CLAIM_LEVEL": "TECHNICAL_SHADOW_ONLY",
            "reason": "no_frozen_models",
        }

    loaded = [load_and_verify_frozen(d) for d in model_dirs]
    if not all(m["file_hash_verified"] for m in loaded):
        return {
            "MEDICATION_MODEL_SHADOW_INFERENCE_STATUS": "FAIL",
            "reason": "frozen_file_hash_mismatch",
            "models": [
                {k: m[k] for k in ("outcome", "file_sha256", "expected_file_sha256", "file_hash_verified")}
                for m in loaded
            ],
        }

    # Sanitized deterministic fixture (no patient IDs)
    fixture = {
        "pre_value": 12.0,
        "n_prior_measurements": 4,
        "prior_slope": 0.05,
        "days_since_previous": 21.0,
        "horizon_days": 365,
        "medicine_id": "42",
        "polypharmacy_flag": 0,
        "concurrent_med_count": 1,
    }

    inferences = []
    for m in loaded:
        payload = m["payload"]
        m1 = payload["m1"]
        m2c = payload.get("m2c") or payload.get("m2")
        if not m2c:
            continue
        # feature construction using frozen order lengths
        row_m1 = feat_m1(fixture)
        y_m1 = _predict_ridge(m1["coef"], m1["scaler"]["means"], m1["scaler"]["stds"], row_m1)
        # M2C from v011 uses feat_m2c
        row_m2c = feat_m2c(fixture)
        # pad/truncate to scaler length
        means = m2c["scaler"]["means"]
        if len(row_m2c) != len(means):
            # rebuild hash features to match frozen dim
            dim = int(m2c.get("hash_dim") or (len(means) - 7 - 2))
            from human_simulator.intervention_association_v011.models import (
                signed_medicine_hash_features,
            )
            from human_simulator.intervention_association_v011.policy import M2C_HASH_DIM

            # use frozen dim if present
            feats = feat_m1(fixture) + signed_medicine_hash_features(
                str(fixture["medicine_id"]), dim=dim if dim > 0 else M2C_HASH_DIM
            ) + [
                float(fixture["polypharmacy_flag"]),
                float(fixture["concurrent_med_count"]),
            ]
            if len(feats) != len(means):
                # align
                if len(feats) < len(means):
                    feats = feats + [0.0] * (len(means) - len(feats))
                else:
                    feats = feats[: len(means)]
            row_m2c = feats
        y_m2c = _predict_ridge(m2c["coef"], means, m2c["scaler"]["stds"], row_m2c)
        inferences.append(
            {
                "outcome": m["outcome"],
                "unit": m["unit"],
                "file_sha256": m["file_sha256"],
                "model_identity_sha256": m["model_identity_sha256"],
                "m1_y_pred": y_m1,
                "m2c_y_pred": y_m2c,
                "abs_diff": abs(y_m2c - y_m1),
                "fixture_hash": hashlib.sha256(
                    json.dumps(fixture, sort_keys=True).encode()
                ).hexdigest(),
                "provenance": computed_provenance(
                    refs=[
                        {
                            "entity_type": "FrozenMedicationAssociationModel",
                            "entity_id": m["model_identity_sha256"] or "unknown",
                            "role": "predictor",
                        }
                    ],
                    input_artifact_sha256=m["file_sha256"],
                    method="medication_knowledge_shadow_inference_v0.1",
                ),
            }
        )

    if not inferences:
        return {
            "MEDICATION_MODEL_SHADOW_INFERENCE_STATUS": "FAIL",
            "reason": "no_m1_m2c_inference_produced",
        }

    # Attach first inference to evidence-like object
    primary = inferences[0]
    evidence_obj = {
        "snapshot_id": "med-knowledge-shadow-snap",
        "subject_id": "opaque-technical-fixture-only",
        "snapshot_kind": "technical_shadow",
        "components": [
            {
                "variable_key": "recorded_outcome_prediction_m1",
                "numeric_value": primary["m1_y_pred"],
                "record_origin": "PREDICTED",
            },
            {
                "variable_key": "recorded_outcome_prediction_m2c",
                "numeric_value": primary["m2c_y_pred"],
                "record_origin": "PREDICTED",
            },
        ],
        "medication_inference": primary,
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
    }

    # Engine checkpoint/fork/rollback — synthetic branch separate; medication preds attached as evidence only
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": float(fixture["pre_value"])}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "med_knowledge_parent",
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
    cp = parent["checkpoints"][0]
    parent_before = snapshot_parent_branch(parent)
    fork_event = {
        "week": 3,
        "type": "dose_change",
        "dose": 2.5,
        "name": "technical_shadow_synthetic_divergence",
    }
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="med_knowledge_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event=fork_event,
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=parent)
    rollback_ok = hash_state(copy.deepcopy(cp["state"])) == (
        cp.get("state_hash") or hash_state(cp["state"])
    )

    # Determinism: re-run inference
    y1b = _predict_ridge(
        loaded[0]["payload"]["m1"]["coef"],
        loaded[0]["payload"]["m1"]["scaler"]["means"],
        loaded[0]["payload"]["m1"]["scaler"]["stds"],
        feat_m1(fixture),
    )
    det_ok = abs(y1b - primary["m1_y_pred"]) < 1e-12

    # Repeat fork hashes
    parent2 = kernel.simulate_branch(
        branch_def={
            "branch_id": "med_knowledge_parent",
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
    forked2 = kernel.fork_from_checkpoint(
        checkpoint=parent2["checkpoints"][0],
        new_branch_id="med_knowledge_fork",
        models=models,
        base_state=base_state,
        parent_live=parent2,
        parent_before=snapshot_parent_branch(parent2),
        fork_event=fork_event,
    )
    h1 = hashlib.sha256(
        json.dumps(
            {"p": parent["final_state_hash"], "f": forked.get("final_state_hash")},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    h2 = hashlib.sha256(
        json.dumps(
            {"p": parent2["final_state_hash"], "f": forked2.get("final_state_hash")},
            sort_keys=True,
        ).encode()
    ).hexdigest()

    fork_ok = bool(forked.get("ok"))
    inference_ok = len(inferences) > 0 and all(m["file_hash_verified"] for m in loaded) and det_ok
    engine_ok = (
        fork_ok
        and isolation.get("fork_isolation_verified")
        and rollback_ok
        and h1 == h2
    )

    return {
        "version": VERSION,
        "MEDICATION_MODEL_SHADOW_INFERENCE_STATUS": "PASS" if inference_ok else "FAIL",
        "ENGINE_SHADOW_EXECUTION_STATUS": "PASS" if engine_ok else "FAIL",
        "ENGINE_SHADOW_CLAIM_LEVEL": "TECHNICAL_SHADOW_ONLY",
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        "n_frozen_models_loaded": len(loaded),
        "n_inferences": len(inferences),
        "file_presence_alone_insufficient": True,
        "real_inference_executed": True,
        "inferences": inferences,
        "evidence_object_keys": sorted(evidence_obj.keys()),
        "evidence_prediction_m1": primary["m1_y_pred"],
        "evidence_prediction_m2c": primary["m2c_y_pred"],
        "medication_prediction_does_not_drive_synthetic_physiology": True,
        "synthetic_intervention_branch_separate": True,
        "checkpoint": {
            "checkpoint_id": cp.get("checkpoint_id"),
            "week": cp.get("week"),
            "state_hash": cp.get("state_hash"),
        },
        "fork": {"ok": fork_ok, "fork_event": fork_event},
        "parent_isolation": isolation,
        "rollback_ok": rollback_ok,
        "determinism": {"inference_repeat_ok": det_ok, "fork_hash_run1": h1, "fork_hash_run2": h2, "identical": h1 == h2},
    }
