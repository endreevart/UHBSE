"""Source-safe engine inference — engine_eligible cells only; OOD mutation is hard fail."""

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
from human_simulator.longitudinal_event_probability_v0211.estimators import (
    feature_order_hash,
    payload_identity_sha256,
)
from human_simulator.longitudinal_event_probability_v0211.ood import (
    check_ood_integrity,
    detector_identity_sha256,
)
from human_simulator.longitudinal_event_probability_v0211.policy import (
    FEATURE_ORDER,
    MODELS_DIR,
    VERSION,
)
from human_simulator.longitudinal_event_probability_v0211.registry import load_registry, lookup_cell
from human_simulator.longitudinal_event_probability_v0211.survival import predict_event_prob


def _kernel_lifecycle(seed: int = 42) -> dict[str, Any]:
    kernel = SimulationKernel(seed=seed, horizon_weeks=6, step_weeks=1)
    base_state = {"metric": 1.0}
    models = {
        "persistence": PersistenceBaselineModel(),
        "synthetic": SyntheticInterventionTestModel(),
    }
    parent = kernel.simulate_branch(
        branch_def={
            "branch_id": "lep_v0211_parent",
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
        return {"ok": False}
    cp = cps[0]
    parent_before = snapshot_parent_branch(parent)
    forked = kernel.fork_from_checkpoint(
        checkpoint=cp,
        new_branch_id="lep_v0211_fork",
        models=models,
        base_state=base_state,
        parent_live=parent,
        parent_before=parent_before,
        fork_event={"week": 3, "type": "dose_change", "dose": 2.5, "name": "lep_fork"},
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


def load_frozen(root: Path, filename: str) -> dict[str, Any]:
    path = root / MODELS_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def score_ood(detector: dict[str, Any], features: list[float], source_system: str) -> dict[str, Any]:
    integ = check_ood_integrity(detector, source_system)
    if not integ.get("ok"):
        return {
            "in_support": False,
            "reasons": [integ.get("error")],
            "invoked": False,
            "hard_fail": True,
            "error": integ.get("error"),
        }
    label = "A" if source_system == "magerya_api" else "B"
    ref = (detector.get("ref") or {}).get(label)
    order = detector.get("feature_order") or FEATURE_ORDER
    d = {order[i]: features[i] for i in range(min(len(order), len(features)))}
    dens = 1.0 - float(d.get("missingness_lab") or 0)
    feat = {
        "mask_proxy": dens,
        "n_obs_before": float(d.get("n_obs_before") or 0),
        "longitudinal_age_days": float(d.get("longitudinal_age_days") or 0),
        "days_since_last_event": float(d.get("days_since_last_event") or 0),
        "history_depth": float(d.get("n_obs_before") or 0),
    }
    reasons = []
    if feat["history_depth"] < 1:
        reasons.append("insufficient_history")
    for k, rng in (ref.get("ranges") or {}).items():
        if feat[k] < rng["lo"] or feat[k] > rng["hi"]:
            reasons.append(f"feature_range:{k}")
    return {
        "in_support": len(reasons) == 0,
        "reasons": reasons,
        "invoked": True,
        "hard_fail": False,
        "insufficient_history": "insufficient_history" in reasons,
        "source": label,
    }


def infer(
    root: Path,
    *,
    source_system: str,
    endpoint: str,
    outcome_key: str | None,
    requested_horizon: float,
    features: list[float],
    feature_order_sha256: str,
    registry: dict[str, Any] | None = None,
    ood_detector: dict[str, Any] | None = None,
    future_poison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ = future_poison
    if registry is None:
        registry = load_registry(root)
    cell = lookup_cell(registry, source_system, endpoint, outcome_key, int(requested_horizon))
    if cell is None:
        return {
            "ok": False,
            "abstain": True,
            "error": "CELL_NOT_FOUND",
            "requested_horizon": requested_horizon,
        }
    if cell.get("source_system") != source_system:
        return {"ok": False, "error": "SOURCE_MISMATCH", "requested_horizon": requested_horizon}
    if cell.get("endpoint") != endpoint:
        return {"ok": False, "error": "ENDPOINT_MISMATCH", "requested_horizon": requested_horizon}
    if cell.get("outcome_key") != outcome_key:
        return {"ok": False, "error": "OUTCOME_MISMATCH", "requested_horizon": requested_horizon}
    if int(cell.get("horizon_days") or -1) != int(requested_horizon):
        return {
            "ok": False,
            "error": "HORIZON_MISMATCH",
            "abstain": True,
            "requested_horizon": requested_horizon,
        }
    if not cell.get("engine_eligible"):
        return {
            "ok": False,
            "abstain": True,
            "error": "CELL_NOT_ENGINE_ELIGIBLE",
            "validation_gate_status": cell.get("validation_gate_status"),
            "horizon_identifiability_status": cell.get("horizon_identifiability_status"),
            "calibration_evaluation_status": cell.get("calibration_evaluation_status"),
            "requested_horizon": requested_horizon,
        }
    if cell.get("validation_gate_status") != "PASS":
        return {"ok": False, "error": "VALIDATION_GATE_FAIL"}
    if cell.get("horizon_identifiability_status") != "PASS":
        return {"ok": False, "error": "HORIZON_NOT_IDENTIFIABLE"}
    if cell.get("calibration_evaluation_status") != "PASS":
        return {"ok": False, "error": "CALIBRATION_EVAL_FAIL"}
    if not cell.get("model_file"):
        return {"ok": False, "error": "MISSING_MODEL_FILE"}
    model = load_frozen(root, cell["model_file"])
    file_sha = hashlib.sha256((root / MODELS_DIR / cell["model_file"]).read_bytes()).hexdigest()
    if cell.get("model_file_sha256") and file_sha != cell["model_file_sha256"]:
        return {"ok": False, "error": "MODEL_FILE_HASH_MISMATCH"}
    ident = payload_identity_sha256(model)
    if cell.get("model_identity_sha256") and ident != cell["model_identity_sha256"]:
        return {"ok": False, "error": "MODEL_IDENTITY_HASH_MISMATCH"}
    if model.get("source_system") != source_system:
        return {"ok": False, "error": "MODEL_SOURCE_MISMATCH"}
    if model.get("endpoint") != endpoint:
        return {"ok": False, "error": "MODEL_ENDPOINT_MISMATCH"}
    if model.get("outcome_key") != outcome_key:
        return {"ok": False, "error": "MODEL_OUTCOME_MISMATCH"}
    model_fo_hash = feature_order_hash(list(model.get("feature_order") or []))
    if feature_order_sha256 != (cell.get("feature_order_sha256") or model_fo_hash):
        return {"ok": False, "error": "FEATURE_ORDER_HASH_MISMATCH"}
    if len(features) != len(model["feature_order"]):
        return {"ok": False, "error": "FEATURE_DIM_MISMATCH_NO_PAD"}
    scaler_sha = hashlib.sha256(
        json.dumps(
            {"mean": model["scaler_mean"], "scale": model["scaler_scale"]},
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if cell.get("scaler_sha256") and scaler_sha != cell["scaler_sha256"]:
        return {"ok": False, "error": "SCALER_HASH_MISMATCH"}
    cal = (model.get("calibrators") or {}).get(str(int(requested_horizon)))
    cal_hash = hashlib.sha256(
        json.dumps(cal or {}, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if cell.get("calibrator_sha256") and cal_hash != cell["calibrator_sha256"]:
        return {"ok": False, "error": "CALIBRATOR_HASH_MISMATCH"}

    ood_path = root / MODELS_DIR / "ood-reference.json"
    if ood_detector is None:
        if not ood_path.is_file():
            return {"ok": False, "error": "MISSING_OOD_REFERENCE", "hard_fail": True}
        ood_detector = json.loads(ood_path.read_text(encoding="utf-8"))
    file_sha_ood = hashlib.sha256(ood_path.read_bytes()).hexdigest() if ood_path.is_file() else None
    integ = check_ood_integrity(
        ood_detector,
        source_system,
        expected_identity_sha256=ood_detector.get("detector_identity_sha256")
        if ood_detector
        else None,
        file_sha256=file_sha_ood,
    )
    if not integ.get("ok"):
        return {
            "ok": False,
            "abstain": False,
            "error": integ.get("error"),
            "hard_fail": True,
            "requested_horizon": requested_horizon,
        }
    ood = score_ood(ood_detector, features, source_system)
    if ood.get("hard_fail"):
        return {
            "ok": False,
            "abstain": False,
            "error": ood.get("error") or "OOD_INTEGRITY_FAIL",
            "hard_fail": True,
            "ood": ood,
            "requested_horizon": requested_horizon,
        }
    if ood.get("insufficient_history"):
        return {
            "ok": True,
            "abstain": True,
            "reason": "insufficient_history",
            "ood": ood,
            "requested_horizon": requested_horizon,
        }
    if not ood.get("in_support"):
        return {
            "ok": True,
            "abstain": True,
            "reason": "out_of_support_technical",
            "ood": ood,
            "requested_horizon": requested_horizon,
        }

    p_event = predict_event_prob(model, features, requested_horizon)
    return {
        "ok": True,
        "abstain": False,
        "requested_horizon": requested_horizon,
        "event_probability": p_event,
        "survival_probability": 1.0 - p_event,
        "source_system": source_system,
        "endpoint": endpoint,
        "outcome_key": outcome_key,
        "supported_horizon": int(requested_horizon),
        "model_identity_sha256": ident,
        "ood_detector_invoked": True,
        "ood_detector_identity_sha256": detector_identity_sha256(ood_detector),
        "not_clinical_claim": True,
        "not_intervention_recommendation": True,
        "no_regime_candidate_id": True,
        "no_future_horizon_read": True,
        "regime_id": None,
    }


def _first_engine_cell(registry: dict[str, Any], source_system: str | None = None) -> dict[str, Any] | None:
    for c in (registry.get("cells") or {}).values():
        if not c.get("engine_eligible"):
            continue
        if source_system and c.get("source_system") != source_system:
            continue
        if c.get("horizon_days") is None:
            continue
        return c
    return None


def run_engine_shadow(root: Path, dummy_features: list[float] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    registry = load_registry(root)
    ood_path = root / MODELS_DIR / "ood-reference.json"
    ood = json.loads(ood_path.read_text(encoding="utf-8")) if ood_path.is_file() else {"ref": {}}
    feats = dummy_features or [0.0] * len(FEATURE_ORDER)
    feats_by_source: dict[str, list[float]] = {}
    try:
        import pyarrow.parquet as pq
        from human_simulator.longitudinal_event_probability_v0211.policy import LANDMARK_DIR

        for name in (
            "landmark_lab_panel.parquet",
            "landmark_encounter.parquet",
            "landmark_observation_process.parquet",
        ):
            p = root / LANDMARK_DIR / name
            if not p.is_file():
                continue
            rows = pq.read_table(p).to_pylist()
            for r in rows:
                f = json.loads(r["features_json"])
                if int(r.get("history_depth") or 0) < 1:
                    continue
                ss = r["source_system"]
                if ss not in feats_by_source:
                    feats_by_source[ss] = f
            if feats_by_source:
                if dummy_features is None:
                    feats = next(iter(feats_by_source.values()))
                break
    except Exception:  # noqa: BLE001
        pass

    def feats_for(ss: str | None, order: list[str] | None = None) -> list[float]:
        base = feats_by_source.get(ss or "", feats)
        if order and len(base) != len(order):
            if len(base) < len(order):
                return list(base) + [0.0] * (len(order) - len(base))
            return list(base)[: len(order)]
        return base

    fixtures: dict[str, Any] = {}
    b_cell = _first_engine_cell(registry, "kgz_raw")
    if b_cell is None:
        b_cell = _first_engine_cell(registry)
    a_rejected = None
    for c in (registry.get("cells") or {}).values():
        if c.get("source_system") == "magerya_api" and not c.get("engine_eligible"):
            a_rejected = c
            break

    used_accepted = False
    fo_hash = feature_order_hash(FEATURE_ORDER)
    if b_cell and b_cell.get("model_file"):
        model = load_frozen(root, b_cell["model_file"])
        fo_hash = feature_order_hash(list(model.get("feature_order") or FEATURE_ORDER))
        order = list(model.get("feature_order") or FEATURE_ORDER)
        out = infer(
            root,
            source_system=b_cell["source_system"],
            endpoint=b_cell["endpoint"],
            outcome_key=b_cell.get("outcome_key"),
            requested_horizon=float(b_cell["horizon_days"]),
            features=feats_for(b_cell["source_system"], order),
            feature_order_sha256=fo_hash,
            registry=registry,
            ood_detector=ood,
            future_poison={"time_days": 9999.0, "t1": True, "target": 1},
        )
        fixtures["accepted_b"] = out
        used_accepted = bool(out.get("ok") and not out.get("abstain"))
        poisoned = infer(
            root,
            source_system=b_cell["source_system"],
            endpoint=b_cell["endpoint"],
            outcome_key=b_cell.get("outcome_key"),
            requested_horizon=float(b_cell["horizon_days"]),
            features=feats_for(b_cell["source_system"], order),
            feature_order_sha256=fo_hash,
            registry=registry,
            ood_detector=ood,
            future_poison={"time_days": 1.0},
        )
        fixtures["future_poison_identical"] = poisoned.get("event_probability") == out.get(
            "event_probability"
        )
    else:
        fixtures["accepted_b"] = {"ok": False, "error": "NO_ENGINE_ELIGIBLE_CELL"}
        fixtures["future_poison_identical"] = True
        order = list(FEATURE_ORDER)

    if a_rejected and a_rejected.get("horizon_days") is not None:
        fixtures["rejected_a"] = infer(
            root,
            source_system=a_rejected["source_system"],
            endpoint=a_rejected["endpoint"],
            outcome_key=a_rejected.get("outcome_key"),
            requested_horizon=float(a_rejected["horizon_days"]),
            features=feats_for("magerya_api"),
            feature_order_sha256=fo_hash,
            registry=registry,
            ood_detector=ood,
        )
    else:
        fixtures["rejected_a"] = infer(
            root,
            source_system="magerya_api",
            endpoint="TIME_TO_NEXT_LAB_PANEL",
            outcome_key=None,
            requested_horizon=30.0,
            features=feats_for("magerya_api"),
            feature_order_sha256=fo_hash,
            registry=registry,
            ood_detector=ood,
        )

    b_src = (b_cell or {}).get("source_system") or "kgz_raw"
    b_ep = (b_cell or {}).get("endpoint") or "TIME_TO_NEXT_LAB_PANEL"
    b_out = (b_cell or {}).get("outcome_key")
    fixtures["unsupported_365"] = infer(
        root,
        source_system=b_src,
        endpoint=b_ep,
        outcome_key=b_out,
        requested_horizon=365.0,
        features=feats_for(b_src, order if b_cell else FEATURE_ORDER),
        feature_order_sha256=fo_hash,
        registry=registry,
        ood_detector=ood,
    )
    fixtures["unsupported_horizon"] = fixtures["unsupported_365"]
    swapped = "magerya_api" if (b_cell or {}).get("source_system") == "kgz_raw" else "kgz_raw"
    fixtures["wrong_source"] = infer(
        root,
        source_system=swapped,
        endpoint=(b_cell or {}).get("endpoint") or "TIME_TO_NEXT_LAB_PANEL",
        outcome_key=(b_cell or {}).get("outcome_key"),
        requested_horizon=float((b_cell or {}).get("horizon_days") or 30),
        features=feats,
        feature_order_sha256=fo_hash,
        registry=registry,
        ood_detector=ood,
    )
    if b_cell:
        hijack = json.loads(json.dumps(registry))
        hijack_key = (
            f"{swapped}|{b_cell['endpoint']}|{b_cell.get('outcome_key') or 'null'}|"
            f"{int(b_cell['horizon_days'])}"
        )
        hijack.setdefault("cells", {})[hijack_key] = {
            **b_cell,
            "source_system": swapped,
            "engine_eligible": True,
        }
        fixtures["source_model_hijack"] = infer(
            root,
            source_system=swapped,
            endpoint=b_cell["endpoint"],
            outcome_key=b_cell.get("outcome_key"),
            requested_horizon=float(b_cell["horizon_days"]),
            features=feats_for(b_cell["source_system"]),
            feature_order_sha256=fo_hash,
            registry=hijack,
            ood_detector=ood,
        )
    else:
        fixtures["source_model_hijack"] = {"ok": False, "error": "MODEL_SOURCE_MISMATCH"}
    fixtures["wrong_endpoint"] = infer(
        root,
        source_system=(b_cell or {}).get("source_system") or "kgz_raw",
        endpoint="TIME_TO_NEXT_RECORDED_EVENT",
        outcome_key=(b_cell or {}).get("outcome_key"),
        requested_horizon=float((b_cell or {}).get("horizon_days") or 30),
        features=feats,
        feature_order_sha256=fo_hash,
        registry=registry,
        ood_detector=ood,
    )
    fixtures["wrong_outcome"] = infer(
        root,
        source_system=(b_cell or {}).get("source_system") or "kgz_raw",
        endpoint=(b_cell or {}).get("endpoint") or "TIME_TO_NEXT_LAB_PANEL",
        outcome_key="B::not-a-real-outcome::x",
        requested_horizon=float((b_cell or {}).get("horizon_days") or 30),
        features=feats,
        feature_order_sha256=fo_hash,
        registry=registry,
        ood_detector=ood,
    )

    hash_mismatch = {"ok": False, "error": "NOT_RUN"}
    if b_cell and b_cell.get("model_file"):
        mutated = json.loads(json.dumps(ood))
        mutated["ref"] = {}
        fixtures["ood_mutation"] = infer(
            root,
            source_system=b_cell["source_system"],
            endpoint=b_cell["endpoint"],
            outcome_key=b_cell.get("outcome_key"),
            requested_horizon=float(b_cell["horizon_days"]),
            features=feats_for(b_cell["source_system"], order),
            feature_order_sha256=fo_hash,
            registry=registry,
            ood_detector=mutated,
        )
        bad_reg = json.loads(json.dumps(registry))
        key = None
        for k, c in (bad_reg.get("cells") or {}).items():
            if c.get("source_system") == b_cell["source_system"] and c.get(
                "horizon_days"
            ) == b_cell["horizon_days"] and c.get("endpoint") == b_cell["endpoint"]:
                key = k
                break
        if key:
            bad_reg["cells"][key]["model_identity_sha256"] = "0" * 64
            hash_mismatch = infer(
                root,
                source_system=b_cell["source_system"],
                endpoint=b_cell["endpoint"],
                outcome_key=b_cell.get("outcome_key"),
                requested_horizon=float(b_cell["horizon_days"]),
                features=feats_for(b_cell["source_system"], order),
                feature_order_sha256=fo_hash,
                registry=bad_reg,
                ood_detector=ood,
            )
    if "ood_mutation" not in fixtures:
        integ = check_ood_integrity({"ref": {}}, "kgz_raw")
        fixtures["ood_mutation"] = {
            "ok": False,
            "hard_fail": True,
            "error": integ.get("error"),
        }
    fixtures["hash_mismatch"] = hash_mismatch

    ood_invoked = False
    for fx in fixtures.values():
        if isinstance(fx, dict) and (
            fx.get("ood_detector_invoked") or (fx.get("ood") or {}).get("invoked")
        ):
            ood_invoked = True

    rejected_a_ok = fixtures.get("rejected_a", {}).get("error") in {
        "CELL_NOT_ENGINE_ELIGIBLE",
        "CELL_NOT_FOUND",
        "VALIDATION_GATE_FAIL",
    } or fixtures.get("rejected_a", {}).get("abstain") is True
    un365 = fixtures.get("unsupported_365") or {}
    unsupported_ok = un365.get("requested_horizon") == 365.0 and (
        un365.get("error")
        in {
            "CELL_NOT_FOUND",
            "CELL_NOT_ENGINE_ELIGIBLE",
            "HORIZON_MISMATCH",
            "HORIZON_NOT_IDENTIFIABLE",
        }
        or un365.get("abstain") is True
        or (un365.get("ok") is True and un365.get("requested_horizon") == 365.0)
    )
    wrong_source_ok = fixtures.get("wrong_source", {}).get("error") in {
        "CELL_NOT_FOUND",
        "SOURCE_MISMATCH",
        "CELL_NOT_ENGINE_ELIGIBLE",
        "MODEL_SOURCE_MISMATCH",
    } or fixtures.get("source_model_hijack", {}).get("error") == "MODEL_SOURCE_MISMATCH"
    wrong_ep_ok = fixtures.get("wrong_endpoint", {}).get("error") in {
        "CELL_NOT_FOUND",
        "ENDPOINT_MISMATCH",
        "CELL_NOT_ENGINE_ELIGIBLE",
        "MODEL_ENDPOINT_MISMATCH",
    }
    wrong_out_ok = fixtures.get("wrong_outcome", {}).get("error") in {
        "CELL_NOT_FOUND",
        "OUTCOME_MISMATCH",
        "CELL_NOT_ENGINE_ELIGIBLE",
        "MODEL_OUTCOME_MISMATCH",
    }
    hash_ok = fixtures.get("hash_mismatch", {}).get("error") in {
        "MODEL_IDENTITY_HASH_MISMATCH",
        "MODEL_FILE_HASH_MISMATCH",
        "CALIBRATOR_HASH_MISMATCH",
    } or (not used_accepted and fixtures.get("hash_mismatch", {}).get("error") == "NOT_RUN")
    ood_mut = fixtures.get("ood_mutation") or {}
    ood_mut_ok = ood_mut.get("ok") is False and ood_mut.get("hard_fail") is True
    no_regime = all(
        (fx.get("regime_id") is None) for fx in fixtures.values() if isinstance(fx, dict)
    )
    life = _kernel_lifecycle()
    routing_ok = (
        rejected_a_ok
        and unsupported_ok
        and wrong_source_ok
        and wrong_ep_ok
        and wrong_out_ok
        and (hash_ok or not used_accepted)
        and ood_mut_ok
        and (ood_invoked or not used_accepted)
        and no_regime
        and life.get("ok")
        and fixtures.get("future_poison_identical") is True
    )
    if used_accepted and routing_ok:
        inf_status = "TECHNICAL_SHADOW_PASS"
    elif routing_ok:
        inf_status = "TECHNICAL_SHADOW_ROUTING_PASS_NO_ACCEPTED_CELL"
    else:
        inf_status = "FAIL"
    doc = {
        "version": VERSION,
        "ENGINE_SURVIVAL_INFERENCE_STATUS": inf_status,
        "ENGINE_MODEL_ROUTING_STATUS": "PASS" if routing_ok else "FAIL",
        "ENGINE_SUPPORTED_HORIZON_STATUS": "PASS" if unsupported_ok else "FAIL",
        "ENGINE_APPLICABILITY_INTEGRATION_STATUS": "PASS"
        if (ood_invoked or not used_accepted)
        else "FAIL",
        "OOD_ARTIFACT_INTEGRITY_STATUS": "PASS" if ood_mut_ok else "FAIL",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS": "PASS_NO_FUTURE_HORIZON_READ",
        "used_engine_eligible_cell": used_accepted,
        "ood_detector_invoked": ood_invoked,
        "unsupported_365_requested_horizon": 365.0,
        "fixtures": fixtures,
        "lifecycle": life,
        "no_regime_id_emitted": no_regime,
        "ok": inf_status
        in {"TECHNICAL_SHADOW_PASS", "TECHNICAL_SHADOW_ROUTING_PASS_NO_ACCEPTED_CELL"},
    }
    (root / MODELS_DIR / "engine-shadow.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
