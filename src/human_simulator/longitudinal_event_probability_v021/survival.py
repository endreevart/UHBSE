"""Train discrete-time hazard, evaluate with Graf IPCW Brier and IPCW calibration, freeze payloads."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v021.estimators import (
    apply_calibrator,
    censoring_km,
    feature_order_hash,
    fit_ipcw_logit_calibrator,
    harrell_c_full,
    integrated_brier_score,
    ipcw_brier_graf,
    ipcw_calibration_report,
    ipcw_rows_for_horizon,
    kaplan_meier,
    km_survival_at,
    n_at_risk_at_horizon,
    payload_identity_sha256,
)
from human_simulator.longitudinal_event_probability_v021.policy import (
    CANDIDATE_HORIZONS_DAYS,
    FEATURE_ORDER,
    GATE_CAL_SLOPE_HI,
    GATE_CAL_SLOPE_LO,
    GATE_MAX_ECE,
    GATE_MIN_VAL_CONCORDANCE,
    LANDMARK_DIR,
    MAX_LANDMARKS_PER_ROLE_EVAL,
    MIN_TEST_SUBJECTS,
    MIN_TRAIN_EVENTS,
    MIN_TRAIN_SUBJECTS,
    MIN_VAL_EVENTS,
    MIN_VAL_SUBJECTS,
    MODELS_DIR,
    NAMESPACE,
    SEED,
    TIME_BINS_DAYS,
    VERSION,
    cell_id_sha256,
)


def _fit_scaler(X: list[list[float]]) -> tuple[list[float], list[float]]:
    d = len(X[0]) if X else 0
    means = [0.0] * d
    scales = [1.0] * d
    if not X:
        return means, scales
    n = len(X)
    for j in range(d):
        col = [row[j] for row in X]
        mu = sum(col) / n
        var = sum((v - mu) ** 2 for v in col) / n
        means[j] = mu
        scales[j] = math.sqrt(var) if var > 1e-12 else 1.0
    return means, scales


def _transform(X: list[list[float]], means: list[float], scales: list[float]) -> list[list[float]]:
    return [[(v - m) / s for v, m, s in zip(row, means, scales, strict=True)] for row in X]


def _sigmoid(z: float) -> float:
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _person_periods(rows: list[dict[str, Any]], bins: tuple[float, ...]) -> list[dict[str, Any]]:
    out = []
    edges = [0.0] + list(bins)
    for r in rows:
        t = float(r["time_days"])
        e = int(r["event"])
        feats = json.loads(r["features_json"])
        for b in range(len(edges) - 1):
            start, end = edges[b], edges[b + 1]
            if t <= start:
                break
            y = 1 if (e == 1 and start < t <= end) else 0
            censored_in_bin = e == 0 and start < t <= end
            out.append(
                {
                    "bin_idx": b,
                    "y": y,
                    "features": feats,
                }
            )
            if y == 1 or censored_in_bin or t <= end:
                break
    return out


def fit_discrete_hazard(
    train_rows: list[dict[str, Any]],
    sel_rows: list[dict[str, Any]],
    *,
    l2_grid: tuple[float, ...] = (0.01, 0.1, 1.0),
    epochs: int = 8,
    lr: float = 0.05,
    seed: int = SEED,
) -> dict[str, Any]:
    rng = random.Random(seed)
    bins = TIME_BINS_DAYS
    n_bins = len(bins)

    def design(rows):
        pps = _person_periods(rows, bins)
        X, y = [], []
        for p in pps:
            f = list(p["features"])
            oh = [0.0] * n_bins
            oh[p["bin_idx"]] = 1.0
            X.append(f + oh)
            y.append(float(p["y"]))
        return X, y

    Xtr, ytr = design(train_rows)
    means, scales = _fit_scaler(Xtr)
    Xs = _transform(Xtr, means, scales)
    dim = len(Xs[0]) if Xs else len(FEATURE_ORDER) + n_bins
    best = None
    best_val = float("inf")
    for l2 in l2_grid:
        w = [rng.uniform(-0.01, 0.01) for _ in range(dim)]
        b = 0.0
        for _ep in range(epochs):
            order = list(range(len(Xs)))
            rng.shuffle(order)
            for i in order:
                z = b + sum(w[j] * Xs[i][j] for j in range(dim))
                p = _sigmoid(z)
                err = p - ytr[i]
                for j in range(dim):
                    w[j] -= lr * (err * Xs[i][j] + l2 * w[j])
                b -= lr * err
        Xv, yv = design(sel_rows if sel_rows else train_rows)
        Xvs = _transform(Xv, means, scales)
        nll = 0.0
        for i in range(len(Xvs)):
            z = b + sum(w[j] * Xvs[i][j] for j in range(dim))
            p = _sigmoid(z)
            p = min(max(p, 1e-6), 1 - 1e-6)
            nll += -(yv[i] * math.log(p) + (1 - yv[i]) * math.log(1 - p))
        nll /= max(len(Xvs), 1)
        if nll < best_val:
            best_val = nll
            best = {"weights": w[:], "bias": b, "l2": l2, "val_nll": nll}
    assert best is not None
    return {
        "type": "discrete_time_logistic_hazard",
        "feature_order": list(FEATURE_ORDER),
        "time_bins_days": list(bins),
        "scaler_mean": means,
        "scaler_scale": scales,
        "weights": best["weights"],
        "bias": best["bias"],
        "l2_selected_on_model_selection_fold": best["l2"],
        "val_nll": best["val_nll"],
        "seed": seed,
        "method_version": "lep-v021-dthazard",
        "version": VERSION,
    }


def predict_survival_curve(model: dict[str, Any], features: list[float]) -> list[tuple[float, float]]:
    bins = model["time_bins_days"]
    n_bins = len(bins)
    means, scales = model["scaler_mean"], model["scaler_scale"]
    w, bias = model["weights"], model["bias"]
    s = 1.0
    out = []
    for b in range(n_bins):
        oh = [0.0] * n_bins
        oh[b] = 1.0
        x = features + oh
        xs = [(v - m) / sc for v, m, sc in zip(x, means, scales, strict=True)]
        z = bias + sum(w[j] * xs[j] for j in range(len(xs)))
        h = _sigmoid(z)
        s *= 1.0 - h
        out.append((float(bins[b]), s))
    return out


def predict_event_prob_raw(model: dict[str, Any], features: list[float], horizon: float) -> float:
    curve = predict_survival_curve(model, features)
    s = 1.0
    for t, st in curve:
        if t <= horizon:
            s = st
        else:
            break
    return 1.0 - s


def predict_event_prob(model: dict[str, Any], features: list[float], horizon: float) -> float:
    raw = predict_event_prob_raw(model, features, horizon)
    cal = (model.get("calibrators") or {}).get(str(int(horizon)))
    if cal:
        return apply_calibrator(cal, raw)
    return raw


def _fold_of(overlap_group_id: str) -> int:
    h = hashlib.sha256(f"{NAMESPACE}|val-fold|{overlap_group_id}".encode()).hexdigest()
    return int(h, 16) % 3


def _subsample_complete_groups(
    rows: list[dict[str, Any]], max_n: int, seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(rows) <= max_n:
        return rows, {
            "sampled": False,
            "n": len(rows),
            "complete_groups": True,
        }
    rng = random.Random(seed)
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["overlap_group_id"]].append(r)
    ids = sorted(by.keys())
    rng.shuffle(ids)
    out = []
    used = []
    for gid in ids:
        grp = by[gid]
        if out and len(out) + len(grp) > max_n:
            continue
        out.extend(grp)
        used.append(gid)
        if len(out) >= max_n:
            break
    manifest = {
        "sampled": True,
        "n": len(out),
        "n_groups": len(used),
        "complete_groups": True,
        "group_ids_sha256": hashlib.sha256(
            json.dumps(used, separators=(",", ":")).encode()
        ).hexdigest(),
        "seed": seed,
    }
    return out, manifest


def _subject_bootstrap(rows: list[dict[str, Any]], metric_fn, n: int = 40, seed: int = SEED) -> dict[str, Any]:
    rng = random.Random(seed)
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["overlap_group_id"]].append(r)
    ids = sorted(by.keys())
    if not ids:
        return {}
    vals = []
    for _ in range(n):
        sample_ids = [ids[rng.randrange(len(ids))] for _ in ids]
        sample_rows = [r for sid in sample_ids for r in by[sid]]
        v = metric_fn(sample_rows)
        if v is not None and math.isfinite(v):
            vals.append(v)
    if not vals:
        return {}
    vals.sort()
    return {
        "n_bootstrap": n,
        "resample_unit": "overlap_group",
        "mean": sum(vals) / len(vals),
        "p05": vals[int(0.05 * len(vals))],
        "p95": vals[min(len(vals) - 1, int(0.95 * len(vals)))],
    }


def train_and_evaluate_endpoint(
    root: Path,
    *,
    parquet_name: str,
    endpoint_name: str,
    source_system: str,
    outcome_key: str | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / LANDMARK_DIR / parquet_name
    if not path.is_file():
        return {
            "status": "NOT_RUN_MISSING_DATASET",
            "endpoint": endpoint_name,
            "source_system": source_system,
            "outcome_key": outcome_key,
        }
    rows = [
        r
        for r in pq.read_table(path).to_pylist()
        if r["source_system"] == source_system
        and (outcome_key is None or r.get("outcome_key") == outcome_key)
    ]
    train = [r for r in rows if r["split_role"] == "train"]
    val = [r for r in rows if r["split_role"] == "validation"]
    test = [r for r in rows if r["split_role"] == "test"]

    n_tr_s = len({r["source_scoped_subject_id"] for r in train})
    n_va_s = len({r["source_scoped_subject_id"] for r in val})
    n_te_s = len({r["source_scoped_subject_id"] for r in test})
    n_tr_e = sum(r["event"] for r in train)
    n_va_e = sum(r["event"] for r in val)
    gate = {
        "n_train_subjects": n_tr_s,
        "n_val_subjects": n_va_s,
        "n_test_subjects": n_te_s,
        "n_train_events": n_tr_e,
        "n_val_events": n_va_e,
        "n_train_landmarks": len(train),
        "n_val_landmarks": len(val),
        "n_test_landmarks": len(test),
    }
    if (
        n_tr_s < MIN_TRAIN_SUBJECTS
        or n_va_s < MIN_VAL_SUBJECTS
        or n_te_s < MIN_TEST_SUBJECTS
        or n_tr_e < MIN_TRAIN_EVENTS
        or n_va_e < MIN_VAL_EVENTS
        or not train
        or not val
        or not test
    ):
        return {
            "status": "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
            "gate": gate,
            "endpoint": endpoint_name,
            "source_system": source_system,
            "outcome_key": outcome_key,
            "cells": [],
        }

    sel, cal_fit, cal_eval = [], [], []
    for r in val:
        f = _fold_of(r["overlap_group_id"])
        if f == 0:
            sel.append(r)
        elif f == 1:
            cal_fit.append(r)
        else:
            cal_eval.append(r)
    fold_note = "validation_overlap_groups_hashed_mod_3"
    if len(sel) < 20 or len(cal_fit) < 20 or len(cal_eval) < 20:
        sel = val[::2]
        cal_fit = val[::2]
        cal_eval = val[1::2]
        fold_note = "merged_model_selection_with_calibration_fit_due_to_small_folds"

    train_f, train_man = _subsample_complete_groups(train, MAX_LANDMARKS_PER_ROLE_EVAL, SEED)
    sel_f, sel_man = _subsample_complete_groups(sel, MAX_LANDMARKS_PER_ROLE_EVAL // 2, SEED + 1)
    cal_fit_f, cal_fit_man = _subsample_complete_groups(
        cal_fit, MAX_LANDMARKS_PER_ROLE_EVAL // 2, SEED + 2
    )
    cal_eval_f, cal_eval_man = _subsample_complete_groups(
        cal_eval, MAX_LANDMARKS_PER_ROLE_EVAL // 2, SEED + 3
    )
    test_f, test_man = _subsample_complete_groups(test, MAX_LANDMARKS_PER_ROLE_EVAL // 2, SEED + 4)

    km0 = kaplan_meier([r["time_days"] for r in train_f], [r["event"] for r in train_f])
    km_c = censoring_km([r["time_days"] for r in train_f], [r["event"] for r in train_f])
    model = fit_discrete_hazard(train_f, sel_f)
    model["source_system"] = source_system
    model["endpoint"] = endpoint_name
    model["outcome_key"] = outcome_key
    model["feature_order_sha256"] = feature_order_hash(model["feature_order"])
    model["scaler_sha256"] = hashlib.sha256(
        json.dumps(
            {"mean": model["scaler_mean"], "scale": model["scaler_scale"]},
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    model["censoring_km"] = km_c
    model["censoring_model_sha256"] = hashlib.sha256(
        json.dumps(km_c, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    model["cell_id_sha256"] = cell_id_sha256(source_system, endpoint_name, outcome_key)

    def preds_raw(split_rows: list[dict[str, Any]], h: float) -> list[float]:
        return [
            predict_event_prob_raw(model, json.loads(r["features_json"]), h) for r in split_rows
        ]

    calibrators: dict[str, Any] = {}
    for h in CANDIDATE_HORIZONS_DAYS:
        rows_cal = ipcw_rows_for_horizon(
            [r["time_days"] for r in cal_fit_f],
            [r["event"] for r in cal_fit_f],
            preds_raw(cal_fit_f, h),
            h,
            km_c,
        )
        calibrators[str(int(h))] = fit_ipcw_logit_calibrator(rows_cal)
    model["calibrators"] = calibrators

    def eval_split(split_rows: list[dict[str, Any]], *, use_calibrated: bool) -> dict[str, Any]:
        if len(split_rows) <= 2500:
            c_rows = split_rows
            c_manifest = {"sampled": False, "n": len(split_rows), "method": "full"}
        else:
            c_rows, c_manifest = _subsample_complete_groups(split_rows, 2500, SEED + 17)
            c_manifest["method"] = "deterministic_complete_overlap_groups"
        scores = [
            predict_event_prob_raw(model, json.loads(r["features_json"]), 90.0) for r in c_rows
        ]
        c_index = harrell_c_full(
            [r["time_days"] for r in c_rows],
            [r["event"] for r in c_rows],
            scores,
        )
        horizons_out = {}
        for h in CANDIDATE_HORIZONS_DAYS:
            n_risk = n_at_risk_at_horizon(
                kaplan_meier([r["time_days"] for r in split_rows], [r["event"] for r in split_rows]),
                h,
            )
            n_ev_h = sum(1 for r in split_rows if r["event"] == 1 and r["time_days"] <= h)
            if n_risk < 20 or n_ev_h < 5:
                horizons_out[str(int(h))] = {
                    "status": "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
                    "n_at_risk": n_risk,
                    "n_events": n_ev_h,
                }
                continue
            raw = preds_raw(split_rows, h)
            cal = calibrators.get(str(int(h))) if use_calibrated else None
            preds_m1 = [apply_calibrator(cal, p) if cal else p for p in raw]
            preds_m0 = [1.0 - km_survival_at(km0, h)] * len(split_rows)
            times = [r["time_days"] for r in split_rows]
            events = [r["event"] for r in split_rows]
            b1 = ipcw_brier_graf(times, events, preds_m1, h, km_c)
            b0 = ipcw_brier_graf(times, events, preds_m0, h, km_c)
            ipcw_r = ipcw_rows_for_horizon(times, events, raw, h, km_c)
            cal_rep = ipcw_calibration_report(ipcw_r, cal=cal)
            horizons_out[str(int(h))] = {
                "n_at_risk": n_risk,
                "n_events": n_ev_h,
                "ipcw_brier_m1": b1["brier"],
                "ipcw_brier_m0": b0["brier"],
                "ipcw_brier_estimator": b1["estimator"],
                "m1_better_brier": (b1["brier"] is not None and b0["brier"] is not None and b1["brier"] < b0["brier"]),
                "n_censored_before_horizon": b1["n_censored_before_horizon"],
                "n_g_truncated": b1["n_g_truncated"],
                "calibration": cal_rep,
                "mean_predicted_m1": sum(preds_m1) / len(preds_m1),
            }
        briers = {
            k: v["ipcw_brier_m1"]
            for k, v in horizons_out.items()
            if v.get("ipcw_brier_m1") is not None
        }
        boot = _subject_bootstrap(
            c_rows,
            lambda rs: harrell_c_full(
                [r["time_days"] for r in rs],
                [r["event"] for r in rs],
                [
                    predict_event_prob_raw(model, json.loads(r["features_json"]), 90.0)
                    for r in rs
                ],
            ),
        )
        return {
            "n": len(split_rows),
            "events": sum(r["event"] for r in split_rows),
            "concordance_m1": c_index,
            "concordance_horizon_days": 90,
            "concordance_sampling": c_manifest,
            "concordance_bootstrap": boot,
            "integrated_brier_supported_horizons": integrated_brier_score(briers),
            "horizons": horizons_out,
        }

    val_m = eval_split(cal_eval_f, use_calibrated=True)
    supported: list[int] = []
    cells: list[dict[str, Any]] = []
    for h_s, hv in (val_m.get("horizons") or {}).items():
        if hv.get("status") == "NOT_RUN_DUE_TO_FAILED_DATA_GATE":
            cells.append(
                {
                    "source_system": source_system,
                    "endpoint": endpoint_name,
                    "outcome_key": outcome_key,
                    "horizon_days": int(h_s),
                    "evaluation_status": "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
                    "acceptance_status": "NOT_ACCEPTED",
                }
            )
            continue
        cal = hv.get("calibration") or {}
        slope = cal.get("slope")
        ece = cal.get("ece")
        ok_h = (
            hv.get("m1_better_brier") is True
            and val_m["concordance_m1"] >= GATE_MIN_VAL_CONCORDANCE
            and slope is not None
            and GATE_CAL_SLOPE_LO <= slope <= GATE_CAL_SLOPE_HI
            and ece is not None
            and ece <= GATE_MAX_ECE
        )
        if ok_h:
            supported.append(int(h_s))
        cells.append(
            {
                "source_system": source_system,
                "endpoint": endpoint_name,
                "outcome_key": outcome_key,
                "horizon_days": int(h_s),
                "evaluation_status": "EVALUATED",
                "acceptance_status": "ACCEPTED" if ok_h else "EVALUATED_NOT_ACCEPTED",
                "gates": {
                    "m1_better_brier": hv.get("m1_better_brier"),
                    "concordance": val_m["concordance_m1"],
                    "slope": slope,
                    "ece": ece,
                },
            }
        )

    # Test opened once after selection, calibrator fit, supported-horizon decision, freeze.
    test_m = eval_split(test_f, use_calibrated=True)
    ident = payload_identity_sha256(model)
    model["model_identity_sha256"] = ident
    model["supported_horizons_validation"] = supported

    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    fname = f"frozen-{model['cell_id_sha256'][:16]}.json"
    payload_path = root / MODELS_DIR / fname
    payload_bytes = json.dumps(model, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_path.write_bytes(payload_bytes)
    file_sha = hashlib.sha256(payload_bytes).hexdigest()
    model["file_sha256"] = file_sha
    model["frozen_file"] = fname
    # rewrite with file hash included
    payload_path.write_text(
        json.dumps(model, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    model["file_sha256"] = hashlib.sha256(payload_path.read_bytes()).hexdigest()

    return {
        "status": "EVALUATED",
        "endpoint": endpoint_name,
        "source_system": source_system,
        "outcome_key": outcome_key,
        "gate": gate,
        "fold_scheme": fold_note,
        "sampling_manifests": {
            "train": train_man,
            "model_selection": sel_man,
            "calibration_fit": cal_fit_man,
            "calibration_eval": cal_eval_man,
            "test": test_man,
        },
        "km0": {
            "n": km0["n"],
            "events": km0["events"],
            "tied_time_aggregation": True,
            "n_at_risk_by_horizon": {
                str(int(h)): n_at_risk_at_horizon(km0, h) for h in CANDIDATE_HORIZONS_DAYS
            },
        },
        "model_identity_sha256": ident,
        "file_sha256": model["file_sha256"],
        "frozen_file": fname,
        "cell_id_sha256": model["cell_id_sha256"],
        "feature_order_sha256": model["feature_order_sha256"],
        "scaler_sha256": model["scaler_sha256"],
        "censoring_model_sha256": model["censoring_model_sha256"],
        "supported_horizons_validation": supported,
        "cells": cells,
        "validation": val_m,
        "test": test_m,
        "KAPLAN_MEIER_BASELINE_STATUS": "BUILT",
        "DISCRETE_TIME_HAZARD_MODEL_STATUS": "TRAINED",
        "IPCW_BRIER_STATUS": "graf_ipcw_brier_divide_by_n",
        "SURVIVAL_CALIBRATION_METHOD_STATUS": "ipcw_weighted_logit_slope",
        "model": model,
    }
