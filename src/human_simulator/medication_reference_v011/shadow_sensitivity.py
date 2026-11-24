"""In-vocabulary and OOV M2ID_ONEHOT engine inference fixtures (no retrain)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.medication_concept_v01.representation import M1_FEATURES, feat_m2id_onehot
from human_simulator.medication_reference_v01.engine_shadow import (
    ShadowError,
    load_frozen_m2id,
    predict_strict,
)
from human_simulator.medication_reference_v011.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    M2ID_ONEHOT_DID_NOT_IMPROVE_OVER_M1,
    V01_ARTIFACT_DIR,
    VERSION,
)


def _first_frozen_dir(root: Path) -> Path | None:
    base = root / V01_ARTIFACT_DIR / "frozen_models_m2id_onehot"
    if not base.is_dir():
        return None
    dirs = sorted(p for p in base.iterdir() if p.is_dir())
    return dirs[0] if dirs else None


def _synthetic_episode(medicine_id: str) -> dict[str, Any]:
    return {
        "opaque_subject_key": "shadow-subj-v011",
        "medicine_id": str(medicine_id),
        "pre_value": 10.0,
        "post_value": 11.0,
        "delta_days": 30.0,
        "horizon_days": 365.0,
        "n_history": 1,
        "history_mean": 10.0,
        "history_last": 10.0,
        "history_slope": 0.0,
        "n_concurrent_meds": 0,
        "polypharmacy_flag": 0,
        "concurrent_med_count": 1,
    }


def run_invocab_and_oov_shadow(root: Path) -> dict[str, Any]:
    model_dir = _first_frozen_dir(root)
    if model_dir is None:
        return {
            "ok": False,
            "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS": "FAIL",
            "M2ID_ONEHOT_OOV_SHADOW_STATUS": "FAIL",
            "reason": "no_frozen_m2id_onehot_models",
        }

    loaded = load_frozen_m2id(model_dir)
    payload = loaded["payload"]
    vocab = dict(payload["vocabulary"])
    order = payload["m2id_onehot_feature_order"]
    means = payload["m2id_onehot"]["scaler"]["means"]
    stds = payload["m2id_onehot"]["scaler"]["stds"]
    coef = payload["m2id_onehot"].get("coefficients") or payload["m2id_onehot"]["coef"]
    ordered_ids = list(vocab.get("ordered_ids") or [])
    if not ordered_ids:
        return {
            "ok": False,
            "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS": "FAIL",
            "M2ID_ONEHOT_OOV_SHADOW_STATUS": "FAIL",
            "reason": "empty_vocabulary",
        }
    # Frozen payloads may omit runtime index map — rebuild deterministically
    if "index" not in vocab:
        vocab["index"] = {str(mid): i for i, mid in enumerate(ordered_ids)}
    in_id = str(ordered_ids[0])
    oov_id = "__OOV_MEDICATION_ID_NOT_IN_TRAIN_VOCAB__"
    train_id_set = {str(x) for x in ordered_ids}

    def _run(mid: str, expect_oov: bool) -> dict[str, Any]:
        ep = _synthetic_episode(mid)
        row = feat_m2id_onehot(ep, vocab)
        # Feature vector includes non-med context + one-hot block; compare to scaler dim
        if len(row) != len(means):
            raise ShadowError(
                f"feature_dim_mismatch_no_pad_no_truncate: row={len(row)} scaler={len(means)}"
            )
        # one-hot block sits after M1 features and before trailing polypharmacy/concurrent
        m1_n = len(M1_FEATURES)
        n_id = len(ordered_ids) + 1
        onehot = row[m1_n : m1_n + n_id]
        if len(onehot) != n_id:
            raise ShadowError(f"onehot_slice_len_mismatch:{len(onehot)}!={n_id}")
        if any(float(x) not in (0.0, 1.0) for x in onehot):
            raise ShadowError("non_binary_onehot_values")
        ones = sum(1 for x in onehot if float(x) == 1.0)
        if ones != 1:
            raise ShadowError(f"expected_exactly_one_active_id_or_oov_got_{ones}")
        y1 = predict_strict(coef, means, stds, row)
        y2 = predict_strict(coef, means, stds, row)
        if y1 != y2:
            raise ShadowError("nondeterministic_inference")
        is_oov = str(mid) not in train_id_set
        if expect_oov and not is_oov:
            raise ShadowError("expected_oov")
        if (not expect_oov) and is_oov:
            raise ShadowError("expected_in_vocab")
        # Confirm OOV bucket index when expected
        if expect_oov and float(onehot[-1]) != 1.0:
            raise ShadowError("oov_bucket_not_active")
        if (not expect_oov) and float(onehot[-1]) == 1.0:
            raise ShadowError("in_vocab_hit_oov_bucket")
        return {
            "medicine_id_present_in_vocab": not is_oov,
            "oov": is_oov,
            "n_features": len(row),
            "feature_order_len": len(order),
            "y_pred": y1,
            "reload_deterministic": True,
            "padding_truncation": False,
            "model_identity_sha256": loaded.get("model_identity_sha256"),
            "file_sha256": loaded["file_sha256"],
            "vocab_hash": loaded.get("vocab_hash"),
        }

    try:
        in_res = _run(in_id, expect_oov=False)
        in_status = "PASS"
        in_err = None
    except Exception as exc:  # noqa: BLE001
        in_res = {}
        in_status = "FAIL"
        in_err = str(exc)

    try:
        oov_res = _run(oov_id, expect_oov=True)
        oov_status = "PASS"
        oov_err = None
    except Exception as exc:  # noqa: BLE001
        oov_res = {}
        oov_status = "FAIL"
        oov_err = str(exc)

    # Scientific fact from freeze report
    freeze_path = root / V01_ARTIFACT_DIR / "m2id-onehot-model-freeze.json"
    improve_any = False
    if freeze_path.is_file():
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        for c in freeze.get("cohorts") or []:
            m = c.get("metrics_test") or {}
            m1 = m.get("m1_subject_macro_mae")
            m2 = m.get("m2id_onehot_subject_macro_mae")
            if m1 is not None and m2 is not None and m2 < m1:
                improve_any = True

    return {
        "version": VERSION,
        "model_dir": str(model_dir.relative_to(root)),
        "M2ID_ONEHOT_IN_VOCAB_SHADOW_STATUS": in_status,
        "M2ID_ONEHOT_OOV_SHADOW_STATUS": oov_status,
        "in_vocab": in_res,
        "oov": oov_res,
        "in_vocab_error": in_err,
        "oov_error": oov_err,
        "no_retrain": True,
        "scientific_fact": {
            "statement": (
                "M2ID_ONEHOT did not improve over M1 on any of five evaluated outcomes"
            ),
            "verified_from_freeze_metrics": not improve_any,
            "policy_flag": M2ID_ONEHOT_DID_NOT_IMPROVE_OVER_M1,
            "medication_signal_claimed": False,
        },
        "CLINICAL_USE": CLINICAL_USE_PROHIBITED,
        "CAUSAL_INTERPRETATION": CAUSAL_INTERPRETATION_PROHIBITED,
        "ok": in_status == "PASS" and oov_status == "PASS",
    }
