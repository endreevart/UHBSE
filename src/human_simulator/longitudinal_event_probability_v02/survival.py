"""Correct KM + discrete-time logistic hazard + IPCW evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.longitudinal_event_probability_v02.landmarks import FEATURE_ORDER
from human_simulator.longitudinal_event_probability_v02.policy import (
    GATE_CAL_SLOPE_HI,
    GATE_CAL_SLOPE_LO,
    GATE_MAX_ECE,
    GATE_MIN_VAL_CONCORDANCE,
    HORIZONS_DAYS,
    LANDMARK_DIR,
    MAX_LANDMARKS_PER_ROLE_EVAL,
    MIN_TEST_SUBJECTS,
    MIN_TRAIN_EVENTS,
    MIN_TRAIN_SUBJECTS,
    MIN_VAL_EVENTS,
    MIN_VAL_SUBJECTS,
    MODELS_DIR,
    RUNTIME_DIR,
    SEED,
    TIME_BINS_DAYS,
    VERSION,
)


def kaplan_meier(times: list[float], events: list[int]) -> dict[str, Any]:
    """KM with tied-time aggregation: at each t, d_i deaths / n_i at risk."""
    pairs = sorted(zip(times, events, strict=True))
    # group by time
    by_t: dict[float, list[int]] = defaultdict(list)
    for t, e in pairs:
        by_t[t].append(e)
    n_at_risk = len(pairs)
    surv = 1.0
    curve = []
    for t in sorted(by_t):
        group = by_t[t]
        d_i = sum(group)
        c_i = len(group) - d_i
        if n_at_risk > 0 and d_i > 0:
            surv *= 1.0 - d_i / n_at_risk
        curve.append(
            {
                "t": t,
                "S": surv,
                "d_i": d_i,
                "c_i": c_i,
                "n_i": n_at_risk,
            }
        )
        n_at_risk -= len(group)
    return {
        "n": len(pairs),
        "events": sum(events),
        "curve": curve,
        "tied_time_aggregation": True,
    }


def km_survival_at(km: dict[str, Any], t: float) -> float:
    s = 1.0
    for pt in km.get("curve") or []:
        if pt["t"] <= t:
            s = pt["S"]
        else:
            break
    return s


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


def _person_periods(
    rows: list[dict[str, Any]], bins: tuple[float, ...]
) -> list[dict[str, Any]]:
    """Expand to person-period: one row per time bin until event or censor."""
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
            # at risk entering bin
            y = 1 if (e == 1 and start < t <= end) else 0
            censored_in_bin = e == 0 and start < t <= end
            # if censored mid-bin still contribute as y=0 and stop after
            bin_idx = b
            out.append(
                {
                    "landmark_id": r["landmark_id"],
                    "source_scoped_subject_id": r["source_scoped_subject_id"],
                    "overlap_group_id": r["overlap_group_id"],
                    "bin_idx": bin_idx,
                    "bin_end": end,
                    "y": y,
                    "features": feats,
                    "stop": y == 1 or censored_in_bin or t <= end,
                }
            )
            if y == 1 or censored_in_bin or t <= end:
                break
    return out


def fit_discrete_hazard(
    train_rows: list[dict[str, Any]],
    val_rows: list[dict[str, Any]],
    *,
    l2_grid: tuple[float, ...] = (0.01, 0.1, 1.0),
    epochs: int = 8,
    lr: float = 0.05,
    seed: int = SEED,
) -> dict[str, Any]:
    rng = random.Random(seed)
    bins = TIME_BINS_DAYS
    n_bins = len(bins)
    d = len(FEATURE_ORDER)

    def design(rows):
        pps = _person_periods(rows, bins)
        X, y, meta = [], [], []
        for p in pps:
            # features + bin one-hot
            f = list(p["features"])
            oh = [0.0] * n_bins
            oh[p["bin_idx"]] = 1.0
            X.append(f + oh)
            y.append(float(p["y"]))
            meta.append(p)
        return X, y, meta

    Xtr, ytr, _ = design(train_rows)
    means, scales = _fit_scaler(Xtr)
    Xs = _transform(Xtr, means, scales)
    dim = len(Xs[0]) if Xs else d + n_bins

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
        # val NLL
        Xv, yv, _ = design(val_rows)
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
            best = {
                "weights": w[:],
                "bias": b,
                "l2": l2,
                "val_nll": nll,
            }
    assert best is not None
    model = {
        "type": "discrete_time_logistic_hazard",
        "feature_order": list(FEATURE_ORDER),
        "time_bins_days": list(bins),
        "scaler_mean": means,
        "scaler_scale": scales,
        "weights": best["weights"],
        "bias": best["bias"],
        "l2_selected_on_validation": best["l2"],
        "val_nll": best["val_nll"],
        "seed": seed,
        "method_version": "lep-v02-dthazard",
    }
    return model


def predict_survival_curve(model: dict[str, Any], features: list[float]) -> list[tuple[float, float]]:
    """Return list of (bin_end, S(t)) using product of (1-h)."""
    bins = model["time_bins_days"]
    n_bins = len(bins)
    d = len(model["feature_order"])
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


def predict_event_prob(model: dict[str, Any], features: list[float], horizon: float) -> float:
    curve = predict_survival_curve(model, features)
    s = 1.0
    for t, st in curve:
        if t <= horizon:
            s = st
        else:
            break
    return 1.0 - s


def _subject_bootstrap(
    rows: list[dict[str, Any]],
    metric_fn,
    n: int = 40,
    seed: int = SEED,
) -> dict[str, Any]:
    """Bootstrap by subject (not rows)."""
    rng = random.Random(seed)
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["source_scoped_subject_id"]].append(r)
    ids = sorted(by.keys())
    if not ids:
        return {}
    vals = []
    for _ in range(n):
        sample_ids = [ids[rng.randrange(len(ids))] for _ in ids]
        sample_rows = [r for sid in sample_ids for r in by[sid]]
        vals.append(metric_fn(sample_rows))
    vals = [v for v in vals if v is not None and math.isfinite(v)]
    if not vals:
        return {}
    vals.sort()
    return {
        "n_bootstrap": n,
        "mean": sum(vals) / len(vals),
        "p05": vals[int(0.05 * len(vals))],
        "p95": vals[min(len(vals) - 1, int(0.95 * len(vals)))],
    }


def harrell_c(rows: list[dict[str, Any]], scores: list[float]) -> float:
    # higher score => earlier event
    n = len(rows)
    if n > 500:
        rng = random.Random(SEED)
        idx = sorted(rng.sample(range(n), 500))
        rows = [rows[i] for i in idx]
        scores = [scores[i] for i in idx]
    n_conc = n_tied = n_comp = 0
    for i in range(len(rows)):
        if rows[i]["event"] != 1:
            continue
        for j in range(len(rows)):
            if rows[i]["time_days"] >= rows[j]["time_days"]:
                continue
            n_comp += 1
            if scores[i] > scores[j]:
                n_conc += 1
            elif scores[i] == scores[j]:
                n_tied += 1
    if n_comp == 0:
        return 0.5
    return (n_conc + 0.5 * n_tied) / n_comp


def ipcw_brier(
    rows: list[dict[str, Any]],
    preds: list[float],
    horizon: float,
    km_censor: dict[str, Any],
) -> float:
    """IPCW Brier at horizon. G(t) = KM of censoring distribution."""
    # Censoring indicator: treat event=0 as censoring event for G
    # G(t-) survival of censoring process
    total = 0.0
    wsum = 0.0
    for r, p in zip(rows, preds, strict=True):
        t = float(r["time_days"])
        e = int(r["event"])
        # observed event by horizon
        if t <= horizon and e == 1:
            y = 1.0
            g = km_survival_at(km_censor, t)
            w = 1.0 / max(g, 1e-3)
        elif t > horizon:
            y = 0.0
            g = km_survival_at(km_censor, horizon)
            w = 1.0 / max(g, 1e-3)
        else:
            # censored before horizon — weight 0
            continue
        total += w * (p - y) ** 2
        wsum += w
    return total / max(wsum, 1e-9)


def calibration_stats(y: list[float], p: list[float], n_bins: int = 10) -> dict[str, Any]:
    if not y:
        return {"ece": None, "slope": None, "intercept": None}
    # ECE
    pairs = sorted(zip(p, y, strict=True))
    bs = max(1, len(pairs) // n_bins)
    ece = 0.0
    bins_out = []
    for i in range(0, len(pairs), bs):
        chunk = pairs[i : i + bs]
        if not chunk:
            continue
        mp = sum(c[0] for c in chunk) / len(chunk)
        my = sum(c[1] for c in chunk) / len(chunk)
        ece += abs(mp - my) * len(chunk) / len(pairs)
        bins_out.append({"pred": mp, "obs": my, "n": len(chunk)})
    # slope/intercept via simple linear regression obs ~ a + b*pred on bin means
    if len(bins_out) >= 2:
        xs = [b["pred"] for b in bins_out]
        ys = [b["obs"] for b in bins_out]
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
        den = sum((x - mx) ** 2 for x in xs) or 1.0
        slope = num / den
        intercept = my - slope * mx
    else:
        slope = intercept = None
    return {"ece": ece, "slope": slope, "intercept": intercept, "bins": bins_out}


def _subsample_rows(rows: list[dict[str, Any]], max_n: int, seed: int) -> list[dict[str, Any]]:
    if len(rows) <= max_n:
        return rows
    rng = random.Random(seed)
    # subject-stratified
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["source_scoped_subject_id"]].append(r)
    ids = sorted(by.keys())
    rng.shuffle(ids)
    out = []
    for sid in ids:
        out.extend(by[sid])
        if len(out) >= max_n:
            break
    return out[:max_n]


def train_and_evaluate_endpoint(
    root: Path,
    *,
    parquet_name: str,
    endpoint_name: str,
    source_system: str,
    outcome_key: str | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    rows = pq.read_table(root / LANDMARK_DIR / parquet_name).to_pylist()
    rows = [r for r in rows if r["source_system"] == source_system]
    if outcome_key:
        rows = [r for r in rows if r.get("outcome_key") == outcome_key]

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
    }
    if (
        n_tr_s < MIN_TRAIN_SUBJECTS
        or n_va_s < MIN_VAL_SUBJECTS
        or n_te_s < MIN_TEST_SUBJECTS
        or n_tr_e < MIN_TRAIN_EVENTS
        or n_va_e < MIN_VAL_EVENTS
    ):
        return {
            "status": "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
            "gate": gate,
            "endpoint": endpoint_name,
            "source_system": source_system,
            "outcome_key": outcome_key,
        }

    train_f = _subsample_rows(train, MAX_LANDMARKS_PER_ROLE_EVAL, SEED)
    val_f = _subsample_rows(val, MAX_LANDMARKS_PER_ROLE_EVAL // 2, SEED + 1)
    test_f = _subsample_rows(test, MAX_LANDMARKS_PER_ROLE_EVAL // 2, SEED + 2)

    km0 = kaplan_meier([r["time_days"] for r in train_f], [r["event"] for r in train_f])
    # censoring KM for IPCW: flip event
    km_c = kaplan_meier(
        [r["time_days"] for r in train_f],
        [1 - r["event"] for r in train_f],
    )
    model = fit_discrete_hazard(train_f, val_f)

    def eval_split(split_rows: list[dict[str, Any]], open_test: bool = False) -> dict[str, Any]:
        scores = []
        for r in split_rows:
            feats = json.loads(r["features_json"])
            # risk score = predicted event prob at 90d for ranking
            scores.append(predict_event_prob(model, feats, 90.0))
        c_index = harrell_c(split_rows, scores)
        horizons_out = {}
        for h in HORIZONS_DAYS:
            # at-risk gate: enough with follow-up potential
            n_risk = sum(1 for r in split_rows if r["time_days"] >= h or r["event"] == 1)
            n_ev_h = sum(1 for r in split_rows if r["event"] == 1 and r["time_days"] <= h)
            if n_risk < 20 or n_ev_h < 5:
                horizons_out[str(int(h))] = {
                    "status": "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
                    "n_at_risk_proxy": n_risk,
                    "n_events": n_ev_h,
                }
                continue
            preds_m1 = [
                predict_event_prob(model, json.loads(r["features_json"]), h) for r in split_rows
            ]
            preds_m0 = [1.0 - km_survival_at(km0, h)] * len(split_rows)
            # clamp
            preds_m1 = [min(1.0, max(0.0, p)) for p in preds_m1]
            brier_m1 = ipcw_brier(split_rows, preds_m1, h, km_c)
            brier_m0 = ipcw_brier(split_rows, preds_m0, h, km_c)
            y = [
                1.0
                if (r["event"] == 1 and r["time_days"] <= h)
                else (0.0 if r["time_days"] > h else None)
                for r in split_rows
            ]
            yp = [(yi, pi) for yi, pi in zip(y, preds_m1, strict=True) if yi is not None]
            cal = calibration_stats([a for a, _ in yp], [b for _, b in yp]) if yp else {}
            horizons_out[str(int(h))] = {
                "n_at_risk_proxy": n_risk,
                "n_events": n_ev_h,
                "ipcw_brier_m1": brier_m1,
                "ipcw_brier_m0": brier_m0,
                "m1_better_brier": brier_m1 < brier_m0,
                "calibration": cal,
                "mean_predicted_m1": sum(preds_m1) / len(preds_m1),
            }
        boot = _subject_bootstrap(
            split_rows,
            lambda rs: harrell_c(
                rs,
                [predict_event_prob(model, json.loads(r["features_json"]), 90.0) for r in rs],
            ),
        )
        return {
            "n": len(split_rows),
            "events": sum(r["event"] for r in split_rows),
            "concordance_m1": c_index,
            "concordance_bootstrap": boot,
            "horizons": horizons_out,
        }

    val_m = eval_split(val_f)
    # Validation gates for acceptance (before test)
    supported = []
    for h, hv in (val_m.get("horizons") or {}).items():
        if hv.get("status") == "NOT_RUN_DUE_TO_FAILED_DATA_GATE":
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
            and all(0 <= predict_event_prob(model, json.loads(r["features_json"]), float(h)) <= 1 for r in val_f[:50])
        )
        if ok_h:
            supported.append(int(h))
    foundation = (
        "TECHNICAL_PROBABILITY_FOUNDATION_ACCEPTED"
        if supported
        else "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_OR_CALIBRATED_SIGNAL"
    )

    test_m = eval_split(test_f)  # opened after freeze decision recorded
    ident = hashlib.sha256(
        json.dumps(
            {
                "weights": model["weights"],
                "bias": model["bias"],
                "feature_order": model["feature_order"],
                "bins": model["time_bins_days"],
                "scaler_mean": model["scaler_mean"],
                "scaler_scale": model["scaler_scale"],
            },
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    model["model_identity_sha256"] = ident

    return {
        "status": "EVALUATED",
        "foundation_status": foundation,
        "supported_horizons_validation": supported,
        "endpoint": endpoint_name,
        "source_system": source_system,
        "outcome_key": outcome_key,
        "gate": gate,
        "km0": {"n": km0["n"], "events": km0["events"], "curve_tail": (km0["curve"] or [])[-5:]},
        "model": model,
        "validation": val_m,
        "test": test_m,
        "KAPLAN_MEIER_BASELINE_STATUS": "BUILT",
        "DISCRETE_TIME_HAZARD_MODEL_STATUS": "TRAINED",
    }
