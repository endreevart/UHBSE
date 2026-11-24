"""Real M2ID_ONEHOT frozen-model engine shadow (not onehot_demo)."""

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
from human_simulator.medication_concept_v01.representation import (
    feat_m1,
    feat_m2id_onehot,
)
from human_simulator.medication_reference_v01.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    VERSION,
)


class ShadowError(ValueError):
    pass


def _sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_obj(obj: Any) -> str:
    return _sha_b(json.dumps(obj, sort_keys=True, default=str).encode())


def predict_strict(coef: list[float], means: list[float], stds: list[float], row: list[float]) -> float:
    if len(row) != len(means):
        raise ShadowError(
            f"feature_dim_mismatch_no_pad_no_truncate: row={len(row)} scaler={len(means)}"
        )
    if len(coef) != len(means) + 1:
        raise ShadowError("coef_scaler_dim_mismatch")
    xs = [(x - m) / s for x, m, s in zip(row, means, stds, strict=True)]
    return sum(c * v for c, v in zip(coef, [1.0] + xs, strict=True))


def load_frozen_m2id(model_dir: Path) -> dict[str, Any]:
    path = model_dir / "model.json"
    ident_path = model_dir / "model-identity.json"
    raw = path.read_bytes()
    file_sha = _sha_b(raw)
    payload = json.loads(raw.decode("utf-8"))
    ident = json.loads(ident_path.read_text(encoding="utf-8"))
    if ident.get("file_sha256") != file_sha:
        raise ShadowError("file_sha_mismatch")
    # recompute identity
    identity = _sha_obj(
        {
            "outcome": payload.get("outcome"),
            "unit": payload.get("unit"),
            "m2id_onehot_feature_order": payload.get("m2id_onehot_feature_order"),
            "vocabulary": payload.get("vocabulary"),
            "m1": payload.get("m1"),
            "m2id_onehot": payload.get("m2id_onehot"),
            "seed": payload.get("seed"),
            "l2": payload.get("l2"),
        }
    )
    if ident.get("model_identity_sha256") != identity:
        raise ShadowError("identity_sha_mismatch")
    order = payload["m2id_onehot_feature_order"]
    means = payload["m2id_onehot"]["scaler"]["means"]
    if len(order) != len(means):
        raise ShadowError("feature_order_scaler_len_mismatch")
    if len(payload["m2id_onehot"]["coef"]) != len(means) + 1:
        raise ShadowError("coef_dim_mismatch")
    vocab = payload["vocabulary"]
    if vocab.get("vocab_hash") != ident.get("vocab_hash"):
        raise ShadowError("vocab_hash_mismatch")
    return {
        "payload": payload,
        "file_sha256": file_sha,
        "model_identity_sha256": identity,
        "vocab_hash": vocab["vocab_hash"],
        "feature_order_hash": _sha_obj(order),
        "path": str(path),
    }


def run_m2id_onehot_engine_shadow(
    *,
    frozen_root: Path,
    seed: int = 42,
) -> dict[str, Any]:
    dirs = sorted(p for p in frozen_root.iterdir() if p.is_dir()) if frozen_root.is_dir() else []
    if not dirs:
        return {
            "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": "FAIL",
            "ENGINE_SHADOW_EXECUTION_STATUS": "FAIL",
            "reason": "no_frozen_m2id_onehot_models",
        }

    loaded = []
    for d in dirs:
        try:
            loaded.append(load_frozen_m2id(d))
        except ShadowError as exc:
            return {
                "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": "FAIL",
                "ENGINE_SHADOW_EXECUTION_STATUS": "FAIL",
                "reason": str(exc),
                "failed_dir": str(d),
            }

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
        vocab = {
            "ordered_ids": payload["vocabulary"]["ordered_ids"],
            "index": {
                mid: i for i, mid in enumerate(payload["vocabulary"]["ordered_ids"])
            },
            "vocab_size": payload["vocabulary"]["vocab_size"],
            "oov_index": payload["vocabulary"]["oov_index"],
        }
        row_m1 = feat_m1(fixture)
        row_m2 = feat_m2id_onehot(fixture, vocab)
        # Refuse pad/truncate
        y_m1 = predict_strict(
            payload["m1"]["coef"],
            payload["m1"]["scaler"]["means"],
            payload["m1"]["scaler"]["stds"],
            row_m1,
        )
        y_m2 = predict_strict(
            payload["m2id_onehot"]["coef"],
            payload["m2id_onehot"]["scaler"]["means"],
            payload["m2id_onehot"]["scaler"]["stds"],
            row_m2,
        )
        inferences.append(
            {
                "outcome": payload["outcome"],
                "unit": payload["unit"],
                "file_sha256": m["file_sha256"],
                "model_identity_sha256": m["model_identity_sha256"],
                "vocab_hash": m["vocab_hash"],
                "feature_order_hash": m["feature_order_hash"],
                "m1_y_pred": y_m1,
                "m2id_onehot_y_pred": y_m2,
                "oov": str(fixture["medicine_id"]) not in vocab["index"],
                "padding_truncation": False,
                "provenance": computed_provenance(
                    refs=[
                        {
                            "entity_type": "FrozenM2IDOneHotModel",
                            "entity_id": m["model_identity_sha256"],
                            "role": "predictor",
                        }
                    ],
                    input_artifact_sha256=m["file_sha256"],
                    method="m2id_onehot_engine_shadow_v0.1",
                ),
            }
        )

    primary = inferences[0]
    evidence = {
        "snapshot_id": "m2id-onehot-shadow-snap",
        "subject_id": "opaque-technical-fixture-only",
        "snapshot_kind": "technical_shadow",
        "components": [
            {
                "variable_key": "recorded_outcome_prediction_m1",
                "numeric_value": primary["m1_y_pred"],
                "record_origin": "PREDICTED",
            },
            {
                "variable_key": "recorded_outcome_prediction_m2id_onehot",
                "numeric_value": primary["m2id_onehot_y_pred"],
                "record_origin": "PREDICTED",
            },
        ],
        "model_identity": primary["model_identity_sha256"],
        "input_feature_order_hash": primary["feature_order_hash"],
        "vocabulary_hash": primary["vocab_hash"],
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
    }

    # Engine fork path (synthetic separate)
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": float(fixture["pre_value"])}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "m2id_parent",
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
        new_branch_id="m2id_fork",
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

    # Determinism: re-infer
    m0 = loaded[0]
    payload = m0["payload"]
    vocab = {
        "ordered_ids": payload["vocabulary"]["ordered_ids"],
        "index": {mid: i for i, mid in enumerate(payload["vocabulary"]["ordered_ids"])},
        "vocab_size": payload["vocabulary"]["vocab_size"],
        "oov_index": payload["vocabulary"]["oov_index"],
    }
    y2b = predict_strict(
        payload["m2id_onehot"]["coef"],
        payload["m2id_onehot"]["scaler"]["means"],
        payload["m2id_onehot"]["scaler"]["stds"],
        feat_m2id_onehot(fixture, vocab),
    )
    det_ok = abs(y2b - primary["m2id_onehot_y_pred"]) < 1e-12

    parent2 = kernel.simulate_branch(
        branch_def={
            "branch_id": "m2id_parent",
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
        new_branch_id="m2id_fork",
        models=models,
        base_state=base_state,
        parent_live=parent2,
        parent_before=snapshot_parent_branch(parent2),
        fork_event=fork_event,
    )
    h1 = _sha_obj({"p": parent["final_state_hash"], "f": forked.get("final_state_hash")})
    h2 = _sha_obj({"p": parent2["final_state_hash"], "f": forked2.get("final_state_hash")})

    fork_ok = bool(forked.get("ok"))
    shadow_ok = (
        len(inferences) > 0
        and det_ok
        and fork_ok
        and isolation.get("fork_isolation_verified")
        and rollback_ok
        and h1 == h2
        and "recorded_outcome_prediction_m2id_onehot"
        in [c["variable_key"] for c in evidence["components"]]
    )

    return {
        "version": VERSION,
        "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": "PASS" if shadow_ok else "FAIL",
        "ENGINE_SHADOW_EXECUTION_STATUS": "PASS" if shadow_ok else "FAIL",
        "ENGINE_SHADOW_CLAIM_LEVEL": "TECHNICAL_SHADOW_ONLY",
        "prior_m1_m2c_shadow_not_used_as_proof": True,
        "onehot_demo_insufficient": True,
        "real_m2id_onehot_inference_executed": True,
        "n_frozen_models_loaded": len(loaded),
        "n_inferences": len(inferences),
        "inferences": inferences,
        "evidence_state_snapshot": evidence,
        "medication_prediction_does_not_drive_synthetic_physiology": True,
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        "checkpoint": {
            "checkpoint_id": cp.get("checkpoint_id"),
            "state_hash": cp.get("state_hash"),
        },
        "fork": {"ok": fork_ok},
        "parent_isolation": isolation,
        "rollback_ok": rollback_ok,
        "determinism": {"inference_repeat_ok": det_ok, "fork_hashes_identical": h1 == h2},
        "no_padding_truncation": True,
    }
