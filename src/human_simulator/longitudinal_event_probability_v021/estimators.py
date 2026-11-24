"""Survival estimators — Kaplan–Meier, G(t-), Graf IPCW Brier, concordance, calibration."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from typing import Any

G_FLOOR = 1e-6
LOGIT_EPS = 1e-6


def kaplan_meier(times: list[float], events: list[int]) -> dict[str, Any]:
    """KM with tied-time aggregation: at each distinct t, S *= (1 - d_i / n_i)."""
    pairs = sorted(zip(times, events, strict=True))
    by_t: dict[float, list[int]] = defaultdict(list)
    for t, e in pairs:
        by_t[float(t)].append(int(e))
    n_at_risk = len(pairs)
    surv = 1.0
    curve: list[dict[str, Any]] = []
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
        "events": int(sum(events)),
        "curve": curve,
        "tied_time_aggregation": True,
        "estimator": "kaplan_meier_tied_di_over_ni",
    }


def km_survival_at(km: dict[str, Any], t: float) -> float:
    """Right-continuous KM: S(t) includes the jump at t."""
    s = 1.0
    for pt in km.get("curve") or []:
        if pt["t"] <= t:
            s = pt["S"]
        else:
            break
    return s


def km_survival_left_limit(km: dict[str, Any], t: float) -> float:
    """Left-limit G(t-): survival immediately before time t (excludes jump at t)."""
    s = 1.0
    for pt in km.get("curve") or []:
        if pt["t"] < t:
            s = pt["S"]
        else:
            break
    return s


def n_at_risk_at_horizon(km: dict[str, Any], horizon: float) -> int:
    """Number at risk entering the last observed time at or before horizon, else n."""
    n = int(km.get("n") or 0)
    for pt in km.get("curve") or []:
        if pt["t"] <= horizon:
            n = int(pt["n_i"])
        else:
            break
    return n


def censoring_km(times: list[float], events: list[int]) -> dict[str, Any]:
    """KM of the censoring distribution: event_c = 1 if originally censored."""
    c_events = [0 if int(e) == 1 else 1 for e in events]
    km = kaplan_meier(times, c_events)
    km["estimator"] = "censoring_km_for_ipcw"
    km["g_left_limit"] = True
    return km


def ipcw_brier_graf(
    times: list[float],
    events: list[int],
    preds: list[float],
    horizon: float,
    km_censor: dict[str, Any],
    *,
    g_floor: float = G_FLOOR,
) -> dict[str, Any]:
    """Graf IPCW Brier score with division by n (not sum of weights).

    Contribution:
    - event at T_i <= h:  (1/G(T_i-)) * (p - 1)^2
    - event-free T_i > h: (1/G(h)) * (p - 0)^2
    - censored T_i <= h:  0
    Score = (1/n) * sum of contributions.
    """
    n = len(times)
    if n == 0:
        return {
            "brier": None,
            "estimator": "graf_ipcw_brier_divide_by_n",
            "n": 0,
        }
    total = 0.0
    n_event = n_beyond = n_censored = n_truncated = 0
    weight_sum = 0.0
    for t, e, p in zip(times, events, preds, strict=True):
        p = min(1.0, max(0.0, float(p)))
        if t <= horizon and int(e) == 1:
            g = km_survival_left_limit(km_censor, float(t))
            if g < g_floor:
                n_truncated += 1
            w = 1.0 / max(g, g_floor)
            total += w * (p - 1.0) ** 2
            weight_sum += w
            n_event += 1
        elif t > horizon:
            g = km_survival_at(km_censor, float(horizon))
            if g < g_floor:
                n_truncated += 1
            w = 1.0 / max(g, g_floor)
            total += w * (p - 0.0) ** 2
            weight_sum += w
            n_beyond += 1
        else:
            n_censored += 1
    return {
        "brier": total / n,
        "estimator": "graf_ipcw_brier_divide_by_n",
        "not_self_normalized_weighted_mse": True,
        "g_uses_left_limit_for_events": True,
        "g_at_horizon_for_event_free": True,
        "divide_by": "n",
        "n": n,
        "n_event_by_horizon": n_event,
        "n_event_free_beyond": n_beyond,
        "n_censored_before_horizon": n_censored,
        "n_g_truncated": n_truncated,
        "weight_sum": weight_sum,
        "g_floor": g_floor,
    }


def integrated_brier_score(horizon_briers: dict[str, float]) -> float | None:
    """IBS over supported horizons only (trapezoid on sorted unique horizons)."""
    pts = []
    for k, v in horizon_briers.items():
        if v is None:
            continue
        pts.append((float(k), float(v)))
    pts.sort()
    if len(pts) < 2:
        return pts[0][1] if pts else None
    area = 0.0
    for i in range(1, len(pts)):
        dt = pts[i][0] - pts[i - 1][0]
        area += dt * 0.5 * (pts[i][1] + pts[i - 1][1])
    span = pts[-1][0] - pts[0][0]
    return area / span if span > 0 else pts[0][1]


def harrell_c_full(times: list[float], events: list[int], scores: list[float]) -> float:
    """Harrell concordance on all comparable pairs. Higher score => earlier event."""
    n = len(times)
    n_conc = n_tied = n_comp = 0
    for i in range(n):
        if int(events[i]) != 1:
            continue
        ti = times[i]
        si = scores[i]
        for j in range(n):
            if ti >= times[j]:
                continue
            n_comp += 1
            if si > scores[j]:
                n_conc += 1
            elif si == scores[j]:
                n_tied += 1
    if n_comp == 0:
        return 0.5
    return (n_conc + 0.5 * n_tied) / n_comp


def _logit(p: float) -> float:
    p = min(1.0 - LOGIT_EPS, max(LOGIT_EPS, p))
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def ipcw_rows_for_horizon(
    times: list[float],
    events: list[int],
    preds: list[float],
    horizon: float,
    km_censor: dict[str, Any],
    *,
    g_floor: float = G_FLOOR,
) -> list[dict[str, float]]:
    """IPCW-weighted binary rows used for calibration. Censored-before-horizon omitted."""
    out: list[dict[str, float]] = []
    for t, e, p in zip(times, events, preds, strict=True):
        p = min(1.0, max(0.0, float(p)))
        if t <= horizon and int(e) == 1:
            g = km_survival_left_limit(km_censor, float(t))
            w = 1.0 / max(g, g_floor)
            out.append({"y": 1.0, "p": p, "w": w, "logit_p": _logit(p)})
        elif t > horizon:
            g = km_survival_at(km_censor, float(horizon))
            w = 1.0 / max(g, g_floor)
            out.append({"y": 0.0, "p": p, "w": w, "logit_p": _logit(p)})
    return out


def fit_ipcw_logit_calibrator(
    rows: list[dict[str, float]],
    *,
    epochs: int = 80,
    lr: float = 0.05,
) -> dict[str, Any]:
    """Weighted logistic: y ~ intercept + slope * logit(p_raw). IPCW weights."""
    if len(rows) < 8:
        return {
            "method": "ipcw_weighted_logit_slope",
            "intercept": 0.0,
            "slope": 1.0,
            "fitted": False,
            "reason": "insufficient_rows",
            "n": len(rows),
        }
    a, b = 0.0, 1.0
    for _ in range(epochs):
        ga = gb = 0.0
        wsum = 0.0
        for r in rows:
            z = a + b * r["logit_p"]
            p_hat = _sigmoid(z)
            err = p_hat - r["y"]
            w = r["w"]
            ga += w * err
            gb += w * err * r["logit_p"]
            wsum += w
        if wsum <= 0:
            break
        a -= lr * ga / wsum
        b -= lr * gb / wsum
    return {
        "method": "ipcw_weighted_logit_slope",
        "intercept": a,
        "slope": b,
        "fitted": True,
        "n": len(rows),
        "effective_n_weights": sum(r["w"] for r in rows),
    }


def apply_calibrator(cal: dict[str, Any], p_raw: float) -> float:
    if not cal or not cal.get("fitted"):
        return min(1.0, max(0.0, p_raw))
    z = float(cal["intercept"]) + float(cal["slope"]) * _logit(p_raw)
    return _sigmoid(z)


def ipcw_calibration_report(
    rows: list[dict[str, float]],
    *,
    n_bins: int = 10,
    cal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """IPCW-weighted ECE and observed vs predicted. Not OLS bin-rate ~ p."""
    if not rows:
        return {
            "method": "ipcw_weighted_logit_slope",
            "ece": None,
            "slope": None,
            "intercept": None,
            "bins": [],
            "n": 0,
        }
    use = []
    for r in rows:
        p = apply_calibrator(cal, r["p"]) if cal else r["p"]
        use.append({**r, "p_cal": p})
    pairs = sorted(use, key=lambda r: r["p_cal"])
    bs = max(1, len(pairs) // n_bins)
    ece = 0.0
    w_all = sum(r["w"] for r in pairs)
    bins_out = []
    for i in range(0, len(pairs), bs):
        chunk = pairs[i : i + bs]
        if not chunk:
            continue
        w = sum(c["w"] for c in chunk)
        mp = sum(c["p_cal"] * c["w"] for c in chunk) / max(w, 1e-12)
        my = sum(c["y"] * c["w"] for c in chunk) / max(w, 1e-12)
        ece += abs(mp - my) * w / max(w_all, 1e-12)
        bins_out.append(
            {
                "pred": mp,
                "obs_ipcw": my,
                "n": len(chunk),
                "weight_sum": w,
            }
        )
    fitted = cal if cal is not None else {
        "intercept": None,
        "slope": None,
        "fitted": False,
    }
    return {
        "method": "ipcw_weighted_logit_slope",
        "not_ols_bin_rate_on_raw_probability": True,
        "ece": ece,
        "slope": fitted.get("slope"),
        "intercept": fitted.get("intercept"),
        "calibrator_fitted": bool(fitted.get("fitted")),
        "bins": bins_out,
        "n": len(pairs),
        "effective_n_weights": w_all,
        "censored_before_horizon_excluded_from_slope": True,
        "observed_risk_accounts_for_censoring": True,
    }


def feature_order_hash(order: list[str]) -> str:
    canonical = "|".join(order)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def payload_identity_sha256(model: dict[str, Any]) -> str:
    import json

    body = {
        "type": model.get("type"),
        "feature_order": model.get("feature_order"),
        "time_bins_days": model.get("time_bins_days"),
        "scaler_mean": model.get("scaler_mean"),
        "scaler_scale": model.get("scaler_scale"),
        "weights": model.get("weights"),
        "bias": model.get("bias"),
        "calibrator": model.get("calibrator"),
        "censoring_km": {
            "n": (model.get("censoring_km") or {}).get("n"),
            "events": (model.get("censoring_km") or {}).get("events"),
            "curve": (model.get("censoring_km") or {}).get("curve"),
        },
        "source_system": model.get("source_system"),
        "endpoint": model.get("endpoint"),
        "outcome_key": model.get("outcome_key"),
        "version": model.get("version"),
    }
    return hashlib.sha256(
        json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
