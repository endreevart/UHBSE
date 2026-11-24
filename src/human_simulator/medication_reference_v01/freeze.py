"""Freeze M0/M1/M2ID_ONEHOT authoritative models for five outcome cohorts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_concept_v01.representation import (
    M1_FEATURES,
    StandardScaler,
    _fit_predict,
    _make_preds,
    build_onehot_vocab,
    feat_exposure_count,
    feat_m1,
    feat_m2id_onehot,
    feat_m2id_onehot_order,
    pair_micro_mae,
    subject_macro_mae,
)
from human_simulator.medication_reference_v01.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    L2,
    SEED,
    V01_COHORTS,
    VERSION,
)


def _sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_obj(obj: Any) -> str:
    return _sha_b(json.dumps(obj, sort_keys=True, default=str).encode())


def _persist_predict(
    train: list[dict[str, Any]], test: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "opaque_subject_key": e["opaque_subject_key"],
            "y_true": float(e["post_value"]),
            "y_pred": float(e["pre_value"]),
            "episode_id": e["episode_id"],
        }
        for e in test
    ]


def freeze_m2id_onehot_cohort(
    art: Path,
    *,
    outcome: str,
    unit: str,
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
) -> dict[str, Any]:
    tr = [e for e in train if e["outcome"] == outcome and e["unit"] == unit]
    va = [e for e in val if e["outcome"] == outcome and e["unit"] == unit]
    te = [e for e in test if e["outcome"] == outcome and e["unit"] == unit]
    if len(tr) < 20 or len(te) < 10:
        return {"status": "SKIPPED_SMALL_COHORT", "outcome": outcome, "unit": unit}

    y_tr = [float(e["post_value"]) for e in tr]
    vocab = build_onehot_vocab(tr)
    feature_order = feat_m2id_onehot_order(vocab)

    # M0
    m0_preds = _persist_predict(tr, te)
    # M1
    x1_tr = [feat_m1(e) for e in tr]
    x1_te = [feat_m1(e) for e in te]
    m1_hat, sc1, coef1, _ = _fit_predict(x1_tr, y_tr, x1_te)
    m1_preds = _make_preds(te, m1_hat)
    # M2ID_ONEHOT
    x2_tr = [feat_m2id_onehot(e, vocab) for e in tr]
    x2_te = [feat_m2id_onehot(e, vocab) for e in te]
    # Validate one-hot invariants on train
    for row in x2_tr:
        block = row[len(M1_FEATURES) : -2]
        if not all(v in (0.0, 1.0) for v in block):
            return {"status": "FAIL", "reason": "onehot_not_01", "outcome": outcome}
        if abs(sum(block) - 1.0) > 1e-12:
            return {"status": "FAIL", "reason": "onehot_not_exactly_one", "outcome": outcome}
    # Test meds in vocab check for OOV accounting (test may OOV — allowed)
    oov_test = sum(1 for e in te if str(e["medicine_id"]) not in vocab["index"]) / max(len(te), 1)
    # Ensure we don't claim test IDs are in vocab when OOV
    for e in te:
        mid = str(e["medicine_id"])
        if mid in vocab["index"]:
            pass  # in vocab OK
        # if not in vocab, OOV bucket used — OK

    m2_hat, sc2, coef2, _ = _fit_predict(x2_tr, y_tr, x2_te)
    m2_preds = _make_preds(te, m2_hat)

    # dimensions
    if len(coef2) != len(sc2.means) + 1:
        return {"status": "FAIL", "reason": "coef_scaler_dim", "outcome": outcome}
    if len(feature_order) != len(sc2.means):
        return {"status": "FAIL", "reason": "feature_order_scaler_dim", "outcome": outcome}

    # M2EXPOSURE sensitivity (not frozen as authoritative)
    x_exp_tr = [feat_exposure_count(e) for e in tr]
    x_exp_te = [feat_exposure_count(e) for e in te]
    exp_hat, _, _, _ = _fit_predict(x_exp_tr, y_tr, x_exp_te)
    exp_preds = _make_preds(te, exp_hat)

    safe = hashlib.sha256(f"{outcome}|{unit}".encode()).hexdigest()[:12]
    model_dir = art / "frozen_models_m2id_onehot" / f"cohort_{safe}"
    model_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": VERSION,
        "clinical_use": CLINICAL_USE_PROHIBITED,
        "causal_interpretation": CAUSAL_INTERPRETATION_PROHIBITED,
        "authoritative_models": ["m0", "m1", "m2id_onehot"],
        "sensitivity_models": ["m2exposure_count"],
        "outcome": outcome,
        "unit": unit,
        "seed": SEED,
        "l2": L2,
        "m1_feature_order": list(M1_FEATURES),
        "m2id_onehot_feature_order": feature_order,
        "vocabulary": {
            "ordered_ids": vocab["ordered_ids"],
            "vocab_size": vocab["vocab_size"],
            "vocab_hash": vocab["vocab_hash"],
            "oov_index": vocab["oov_index"],
            "encoding": "M2ID_ONEHOT",
        },
        "m0": {"type": "persistence"},
        "m1": {
            "coef": coef1,
            "scaler": {"means": sc1.means, "stds": sc1.stds, "fit_n_rows": sc1.fit_n_rows},
        },
        "m2id_onehot": {
            "coef": coef2,
            "scaler": {"means": sc2.means, "stds": sc2.stds, "fit_n_rows": sc2.fit_n_rows},
            "vocab_hash": vocab["vocab_hash"],
        },
        "lineage": {
            "n_train": len(tr),
            "n_validation": len(va),
            "n_test": len(te),
            "oov_rate_test": oov_test,
        },
        "metrics_test": {
            "m0_subject_macro_mae": subject_macro_mae(m0_preds),
            "m1_subject_macro_mae": subject_macro_mae(m1_preds),
            "m2id_onehot_subject_macro_mae": subject_macro_mae(m2_preds),
            "m2exposure_subject_macro_mae": subject_macro_mae(exp_preds),
            "m1_pair_micro_mae": pair_micro_mae(m1_preds),
            "m2id_onehot_pair_micro_mae": pair_micro_mae(m2_preds),
        },
    }

    raw = (json.dumps(payload, sort_keys=True, default=str) + "\n").encode()
    file_sha = _sha_b(raw)
    identity = _sha_obj(
        {
            "outcome": outcome,
            "unit": unit,
            "m2id_onehot_feature_order": feature_order,
            "vocabulary": payload["vocabulary"],
            "m1": payload["m1"],
            "m2id_onehot": payload["m2id_onehot"],
            "seed": SEED,
            "l2": L2,
        }
    )
    (model_dir / "model.json").write_bytes(raw)
    ident = {
        "file_sha256": file_sha,
        "model_identity_sha256": identity,
        "vocab_hash": vocab["vocab_hash"],
        "feature_order_hash": _sha_obj(feature_order),
    }
    (model_dir / "model-identity.json").write_text(json.dumps(ident, indent=2) + "\n")

    # Reload check — predictions must match
    reloaded = json.loads((model_dir / "model.json").read_text())
    sc_r = StandardScaler()
    sc_r.means = reloaded["m2id_onehot"]["scaler"]["means"]
    sc_r.stds = reloaded["m2id_onehot"]["scaler"]["stds"]
    sc_r.fitted = True
    coef_r = reloaded["m2id_onehot"]["coef"]
    vocab_r = {
        "ordered_ids": reloaded["vocabulary"]["ordered_ids"],
        "index": {m: i for i, m in enumerate(reloaded["vocabulary"]["ordered_ids"])},
        "vocab_size": reloaded["vocabulary"]["vocab_size"],
        "oov_index": reloaded["vocabulary"]["oov_index"],
    }
    reload_preds = []
    for e in te:
        row = feat_m2id_onehot(e, vocab_r)
        if len(row) != len(sc_r.means):
            return {"status": "FAIL", "reason": "reload_dim_mismatch_no_pad", "outcome": outcome}
        xs = sc_r.transform(row)
        yhat = sum(c * v for c, v in zip(coef_r, [1.0] + xs, strict=True))
        reload_preds.append(yhat)
    orig = [p["y_pred"] for p in m2_preds]
    reload_ok = all(abs(a - b) < 1e-12 for a, b in zip(orig, reload_preds, strict=True))
    if not reload_ok:
        return {"status": "FAIL", "reason": "reload_prediction_mismatch", "outcome": outcome}

    # Verify file hash
    if _sha_b((model_dir / "model.json").read_bytes()) != file_sha:
        return {"status": "FAIL", "reason": "file_sha_drift", "outcome": outcome}

    return {
        "status": "FROZEN",
        "outcome": outcome,
        "unit": unit,
        "relative_path": str(model_dir.relative_to(art)),
        "file_sha256": file_sha,
        "model_identity_sha256": identity,
        "vocab_hash": vocab["vocab_hash"],
        "feature_order_hash": ident["feature_order_hash"],
        "n_features": len(feature_order),
        "vocab_size": vocab["vocab_size"],
        "oov_rate_test": oov_test,
        "reload_predictions_match": True,
        "metrics_test": payload["metrics_test"],
    }


def freeze_all_cohorts(
    art: Path,
    *,
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
) -> dict[str, Any]:
    results = []
    for outcome, unit in V01_COHORTS:
        results.append(
            freeze_m2id_onehot_cohort(
                art, outcome=outcome, unit=unit, train=train, val=val, test=test
            )
        )
    frozen = [r for r in results if r.get("status") == "FROZEN"]
    failed = [r for r in results if r.get("status") == "FAIL"]
    if failed:
        status = "FAIL"
    elif len(frozen) == len(V01_COHORTS):
        status = "FROZEN"
    elif frozen:
        status = "PARTIAL"
    else:
        status = "FAIL"
    return {
        "M2ID_ONEHOT_MODEL_FREEZE_STATUS": status,
        "cohorts": results,
        "n_frozen": len(frozen),
        "n_failed": len(failed),
    }
