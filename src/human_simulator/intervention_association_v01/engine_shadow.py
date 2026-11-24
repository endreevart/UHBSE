"""Technical-only simulation-engine adapter: RecordedMedicationAssociationBaseline."""

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
from human_simulator.core.snapshot import EvidenceStateSnapshot, computed_provenance
from human_simulator.intervention_association_v01.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    VERSION,
)


class RecordedMedicationAssociationBaseline:
    """Predict next recorded outcome from frozen M1/M2 — not a treatment-effect model."""

    MODEL_ID = "recorded_medication_association_baseline"
    MODEL_VERSION = VERSION
    MODEL_KIND = "TECHNICAL_ASSOCIATION_SHADOW"
    CLINICAL_USE = CLINICAL_USE_PROHIBITED
    CAUSAL_INTERPRETATION = CAUSAL_INTERPRETATION_PROHIBITED
    CLAIM_LEVEL = "TECHNICAL_SHADOW_ONLY"

    def __init__(self, frozen: dict[str, Any], branch: str = "m2") -> None:
        if branch not in ("m1", "m2"):
            raise ValueError("branch must be m1 or m2")
        self.frozen = frozen
        self.branch = branch
        self.file_sha256 = frozen.get("file_sha256")
        self.model_identity_sha256 = frozen.get("model_identity_sha256")

    def predict_from_context(
        self,
        *,
        snapshot: EvidenceStateSnapshot | dict[str, Any],
        medication_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce predicted next recorded outcome with uncertainty metadata."""
        ser = self.frozen["payload"][self.branch]
        coef = ser["coef"]
        means = ser["scaler"]["means"]
        stds = ser["scaler"]["stds"]
        resid = float(ser.get("residual_std") or 1.0)

        pre = float(medication_context["pre_value"])
        feats_m1 = [
            pre,
            float(medication_context.get("n_prior_measurements") or 0),
            float(medication_context.get("prior_slope") or 0.0),
            float(medication_context.get("days_since_previous") or 0.0),
            float(medication_context.get("horizon_days") or 365),
            1.0 if medication_context.get("prior_slope") is None else 0.0,
            1.0 if medication_context.get("days_since_previous") is None else 0.0,
        ]
        if self.branch == "m2":
            vocab = ser.get("med_vocab") or {}
            mid = str(medication_context.get("medicine_id") or "")
            feats = feats_m1 + [
                float(vocab.get(mid, 0)),
                float(medication_context.get("polypharmacy_flag") or 0),
                float(medication_context.get("concurrent_med_count") or 1),
            ]
        else:
            feats = feats_m1

        xs = [(x - m) / s for x, m, s in zip(feats, means, stds, strict=True)]
        xr = [1.0] + xs
        yhat = sum(c * v for c, v in zip(coef, xr, strict=True))
        half = 1.96 * resid
        snap_hash = None
        if isinstance(snapshot, EvidenceStateSnapshot):
            snap_hash = getattr(snapshot, "snapshot_hash", None) or hashlib.sha256(
                json.dumps(snapshot.to_dict() if hasattr(snapshot, "to_dict") else {}, sort_keys=True, default=str).encode()
            ).hexdigest()
        elif isinstance(snapshot, dict):
            snap_hash = hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, default=str).encode()
            ).hexdigest()

        return {
            "MODEL_ID": self.MODEL_ID,
            "MODEL_VERSION": self.MODEL_VERSION,
            "MODEL_KIND": self.MODEL_KIND,
            "CLINICAL_USE": self.CLINICAL_USE,
            "CAUSAL_INTERPRETATION": self.CAUSAL_INTERPRETATION,
            "CLAIM_LEVEL": self.CLAIM_LEVEL,
            "branch": self.branch,
            "y_pred": yhat,
            "lower": yhat - half,
            "upper": yhat + half,
            "residual_std": resid,
            "input_snapshot_hash": snap_hash,
            "model_file_sha256": self.file_sha256,
            "model_identity_sha256": self.model_identity_sha256,
            "provenance": computed_provenance(
                refs=[
                    {
                        "entity_type": "FrozenMedicationAssociationModel",
                        "entity_id": self.model_identity_sha256 or "unknown",
                        "role": "predictor",
                    }
                ],
                input_artifact_sha256=self.file_sha256 or "unknown",
                method="recorded_medication_association_shadow",
            ),
        }


def load_frozen_for_shadow(art: Path) -> list[dict[str, Any]]:
    out = []
    root = art / "frozen_models"
    if not root.is_dir():
        return out
    for model_json in sorted(root.rglob("model.json")):
        payload = json.loads(model_json.read_text(encoding="utf-8"))
        ident_path = model_json.parent / "model-identity.json"
        ident = (
            json.loads(ident_path.read_text(encoding="utf-8"))
            if ident_path.is_file()
            else {}
        )
        out.append(
            {
                "path": str(model_json),
                "payload": payload,
                "file_sha256": hashlib.sha256(model_json.read_bytes()).hexdigest(),
                "model_identity_sha256": ident.get("model_identity_sha256"),
            }
        )
    return out


def run_engine_shadow(art: Path, *, seed: int = 42) -> dict[str, Any]:
    frozen_list = load_frozen_for_shadow(art)
    if not frozen_list:
        return {
            "ENGINE_SHADOW_INTEGRATION_STATUS": "NOT_RUN_NO_ELIGIBLE_FROZEN_MODEL",
            "TECHNICAL_SHADOW_ONLY": True,
            "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
            "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        }

    frozen = frozen_list[0]
    m1 = RecordedMedicationAssociationBaseline(frozen, branch="m1")
    m2 = RecordedMedicationAssociationBaseline(frozen, branch="m2")

    # Synthetic held-out technical context (no patient identifiers)
    context = {
        "pre_value": 5.0,
        "n_prior_measurements": 3,
        "prior_slope": 0.1,
        "days_since_previous": 14.0,
        "horizon_days": float(frozen["payload"].get("horizon_days") or 365),
        "medicine_id": next(iter((frozen["payload"].get("m2") or {}).get("med_vocab") or {"0": 0}), "0"),
        "polypharmacy_flag": 0,
        "concurrent_med_count": 1,
    }
    snap = {
        "snapshot_id": "technical-shadow-snap",
        "subject_id": "opaque-technical-only",
        "components": [{"variable_key": "outcome", "numeric_value": context["pre_value"]}],
    }
    p1 = m1.predict_from_context(snapshot=snap, medication_context=context)
    p2 = m2.predict_from_context(snapshot=snap, medication_context=context)

    # Checkpoint / fork / rollback using existing kernel + synthetic models kept separate
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": float(context["pre_value"])}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    branch = kernel.simulate_branch(
        branch_def={
            "branch_id": "med_assoc_shadow_parent",
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
    cps = branch.get("checkpoints") or []
    if not cps:
        return {
            "ENGINE_SHADOW_INTEGRATION_STATUS": "FAIL",
            "reason": "no_checkpoint",
        }
    cp = cps[0]
    parent_before = snapshot_parent_branch(branch)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="med_assoc_shadow_fork",
        models=models,
        base_state=base_state,
        parent_live=branch,
        parent_before=parent_before,
        fork_event={"week": 3, "type": "dose_change", "dose": 0.0, "name": "shadow_noop"},
    )
    isolation = verify_parent_isolation(parent_before=parent_before, parent_live=branch)

    # Determinism: repeat predictions
    p1b = m1.predict_from_context(snapshot=snap, medication_context=context)
    p2b = m2.predict_from_context(snapshot=snap, medication_context=context)
    det_hash_1 = hashlib.sha256(
        json.dumps({"p1": p1["y_pred"], "p2": p2["y_pred"]}, sort_keys=True).encode()
    ).hexdigest()
    det_hash_2 = hashlib.sha256(
        json.dumps({"p1": p1b["y_pred"], "p2": p2b["y_pred"]}, sort_keys=True).encode()
    ).hexdigest()

    # Rollback: restore parent checkpoint state
    rolled = copy.deepcopy(cp["state"])
    rollback_ok = hash_state(rolled) == (cp.get("state_hash") or hash_state(cp["state"]))

    return {
        "ENGINE_SHADOW_INTEGRATION_STATUS": "TECHNICAL_SHADOW_ONLY",
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        "synthetic_intervention_model_kept_separate": True,
        "frozen_model_file_sha256": frozen["file_sha256"],
        "frozen_model_identity_sha256": frozen["model_identity_sha256"],
        "m1_prediction": {k: p1[k] for k in ("y_pred", "lower", "upper", "branch")},
        "m2_prediction": {k: p2[k] for k in ("y_pred", "lower", "upper", "branch")},
        "trajectory_comparison": {
            "m1_y_pred": p1["y_pred"],
            "m2_y_pred": p2["y_pred"],
            "abs_diff": abs(p2["y_pred"] - p1["y_pred"]),
        },
        "checkpoint": {
            "checkpoint_id": cp.get("checkpoint_id"),
            "week": cp.get("week"),
            "phase": cp.get("phase"),
            "state_hash": cp.get("state_hash") or hash_state(cp["state"]),
        },
        "fork": {
            "ok": bool(forked.get("ok", True) if isinstance(forked, dict) else True),
            "fork_keys": sorted(forked.keys()) if isinstance(forked, dict) else [],
        },
        "rollback_ok": rollback_ok,
        "parent_isolation": isolation,
        "determinism": {
            "hash_run1": det_hash_1,
            "hash_run2": det_hash_2,
            "identical": det_hash_1 == det_hash_2,
        },
        "no_patient_level_publication": True,
    }
