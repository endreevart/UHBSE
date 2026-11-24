"""P0 persistence, P1 ridge with requested horizon, P2 robust trend. No medication features."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from human_simulator.natural_history_rollout_v01.hashes import sha_obj
from human_simulator.natural_history_rollout_v01.policy import (
    FORBIDDEN_MEDICATION_FIELDS,
    L2,
    MIN_TRAIN_SUBJECTS,
    MIN_TRAIN_TRANSITIONS,
    MIN_VAL_SUBJECTS,
    MIN_VAL_TRANSITIONS,
    P1_FEATURE_ORDER,
    VERSION,
)
from human_simulator.unified_individual_state_v0111.ridge import fit_ridge, predict_ridge


def p1_vector(feat: dict[str, Any]) -> list[float]:
    for banned in FORBIDDEN_MEDICATION_FIELDS:
        if banned in feat or banned in P1_FEATURE_ORDER:
            raise RuntimeError(f"medication field leaked: {banned}")
    return [float(feat[k]) for k in P1_FEATURE_ORDER]


def predict_p0(feat: dict[str, Any]) -> float:
    return float(feat["persistence_value"])


def predict_p2(feat: dict[str, Any], history: list[float], horizon: float) -> float:
    if len(history) < 3:
        return float(feat["persistence_value"])
    slopes = []
    for i in range(1, len(history)):
        slopes.append(history[i] - history[i - 1])
    slopes.sort()
    mid = slopes[len(slopes) // 2]
    return float(history[-1] + mid * (horizon / max(float(feat.get("days_since_previous") or 1.0), 1.0)))


def _cell_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (row["source_system"], row["outcome_key"], int(row["requested_horizon_days"]))


def _mae(subj: list[str], y: list[float], p: list[float]) -> float:
    per: dict[str, list[float]] = defaultdict(list)
    for s, a, b in zip(subj, y, p, strict=True):
        per[s].append(abs(a - b))
    if not per:
        return float("nan")
    return sum(sum(v) / len(v) for v in per.values()) / len(per)


def _rmse(subj: list[str], y: list[float], p: list[float]) -> float:
    per: dict[str, list[float]] = defaultdict(list)
    for s, a, b in zip(subj, y, p, strict=True):
        per[s].append((a - b) ** 2)
    if not per:
        return float("nan")
    return math.sqrt(sum(sum(v) / len(v) for v in per.values()) / len(per))


def _median_ae(y: list[float], p: list[float]) -> float:
    if not y:
        return float("nan")
    xs = sorted(abs(a - b) for a, b in zip(y, p, strict=True))
    return xs[len(xs) // 2]


def train_providers(train: list[dict[str, Any]], val: list[dict[str, Any]]) -> dict[str, Any]:
    tr_by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    va_by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in train:
        tr_by[_cell_key(r)].append(r)
    for r in val:
        va_by[_cell_key(r)].append(r)
    cells = []
    for key in sorted(set(tr_by) | set(va_by)):
        tr = tr_by.get(key, [])
        va = va_by.get(key, [])
        n_tr_s = len({r["source_scoped_subject_id"] for r in tr})
        n_va_s = len({r["source_scoped_subject_id"] for r in va})
        gate = {
            "n_train_subjects": n_tr_s,
            "n_val_subjects": n_va_s,
            "n_train_transitions": len(tr),
            "n_val_transitions": len(va),
            "test_unread": True,
        }
        data_ok = (
            n_tr_s >= MIN_TRAIN_SUBJECTS
            and n_va_s >= MIN_VAL_SUBJECTS
            and len(tr) >= MIN_TRAIN_TRANSITIONS
            and len(va) >= MIN_VAL_TRANSITIONS
        )
        ss, ok, h = key
        if not data_ok:
            cells.append(
                {
                    "source_system": ss,
                    "outcome_key": ok,
                    "horizon_days": h,
                    "one_step_status": "NOT_RUN_FAILED_DATA_GATE",
                    "active_provider": None,
                    "gate": gate,
                }
            )
            continue
        y_tr = [r["observed"] for r in tr]
        y_va = [r["observed"] for r in va]
        sub_va = [r["source_scoped_subject_id"] for r in va]
        p0_va = [predict_p0(r["features"]) for r in va]
        x_tr = [p1_vector(r["features"]) for r in tr]
        x_va = [p1_vector(r["features"]) for r in va]
        model = fit_ridge(x_tr, y_tr, l2=L2)
        p1_va = [predict_ridge(model, x) for x in x_va]
        p2_va = [
            predict_p2(r["features"], r.get("history_values") or [r["features"]["persistence_value"]], h)
            for r in va
        ]
        mae0 = _mae(sub_va, y_va, p0_va)
        mae1 = _mae(sub_va, y_va, p1_va)
        mae2 = _mae(sub_va, y_va, p2_va)
        scores = {"P0": mae0, "P1": mae1, "P2": mae2}
        active = min(scores, key=lambda k: scores[k] if math.isfinite(scores[k]) else 1e18)
        y_mean = sum(y_tr) / len(y_tr)
        y_var = sum((x - y_mean) ** 2 for x in y_tr) / max(len(y_tr), 1)
        payload = {
            "version": VERSION,
            "family": "P1_ridge",
            "feature_order": list(P1_FEATURE_ORDER),
            "feature_order_sha256": sha_obj(list(P1_FEATURE_ORDER)),
            "scaler_mean": model["scaler_mean"],
            "scaler_scale": model["scaler_scale"],
            "intercept": model["intercept"],
            "coefficients": model["coefficients"],
            "l2": L2,
            "source_system": ss,
            "outcome_key": ok,
            "horizon_days": h,
            "no_medication_features": True,
        }
        payload["model_identity_sha256"] = sha_obj(
            {k: payload[k] for k in ("feature_order", "scaler_mean", "scaler_scale", "intercept", "coefficients", "l2")}
        )
        cells.append(
            {
                "source_system": ss,
                "outcome_key": ok,
                "horizon_days": h,
                "one_step_status": "ONE_STEP_VALIDATION_ACCEPTED",
                "active_provider": active,
                "mae_p0": mae0,
                "mae_p1": mae1,
                "mae_p2": mae2,
                "rmse_active": _rmse(sub_va, y_va, {"P0": p0_va, "P1": p1_va, "P2": p2_va}[active]),
                "median_ae_active": _median_ae(y_va, {"P0": p0_va, "P1": p1_va, "P2": p2_va}[active]),
                "train_ymin": min(y_tr),
                "train_ymax": max(y_tr),
                "train_ystd": math.sqrt(y_var) if y_var > 0 else 0.0,
                "gate": gate,
                "payload": payload,
                "feature_order_sha256": payload["feature_order_sha256"],
                "model_identity_sha256": payload["model_identity_sha256"],
                "scaler_sha256": sha_obj({"m": model["scaler_mean"], "s": model["scaler_scale"]}),
            }
        )
    return {
        "version": VERSION,
        "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS": "TRAINED_SOURCE_SPECIFIC",
        "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": "VALIDATION_ONLY",
        "cells": cells,
        "ok": True,
    }


def predict_active(cell: dict[str, Any], feat: dict[str, Any], history: list[float]) -> float:
    active = cell.get("active_provider") or "P0"
    h = float(feat.get("requested_horizon_days") or cell.get("horizon_days") or 0)
    if active == "P1" and cell.get("payload"):
        return float(predict_ridge(cell["payload"], p1_vector(feat)))
    if active == "P2":
        return predict_p2(feat, history, h)
    return predict_p0(feat)
