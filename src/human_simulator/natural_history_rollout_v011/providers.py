"""P0/P1/P2 with honest evidence tiers. Identity describes the active provider."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from human_simulator.natural_history_rollout_v011.hashes import sha_obj
from human_simulator.natural_history_rollout_v011.policy import (
    FORBIDDEN_MEDICATION_FIELDS,
    L2,
    MIN_TRAIN_SUBJECTS,
    MIN_TRAIN_TARGETS,
    MIN_VAL_SUBJECTS,
    MIN_VAL_TARGETS,
    P1_FEATURE_ORDER,
    PREDECLARED_ABSOLUTE_GRID_DAYS,
    VERSION,
)
from human_simulator.natural_history_rollout_v011.sequences import t0_features
from human_simulator.unified_individual_state_v0111.ridge import fit_ridge, predict_ridge


def p1_vector(feat: dict[str, Any]) -> list[float]:
    for banned in FORBIDDEN_MEDICATION_FIELDS:
        if banned in feat or banned in P1_FEATURE_ORDER:
            raise RuntimeError(f"medication field leaked: {banned}")
    return [float(feat[k]) for k in P1_FEATURE_ORDER]


def predict_p0(feat: dict[str, Any]) -> float:
    return float(feat["persistence_value"])


def predict_p2(feat: dict[str, Any], history: list[float], hist_days: list[float], horizon: float) -> float:
    if len(history) < 3 or not hist_days:
        return float(feat["persistence_value"])
    slopes = []
    for i in range(1, len(history)):
        dt = float(hist_days[i - 1]) if i - 1 < len(hist_days) else 0.0
        if dt <= 0:
            continue
        slopes.append((history[i] - history[i - 1]) / dt)
    if not slopes:
        return float(feat["persistence_value"])
    slopes.sort()
    mid = slopes[len(slopes) // 2]
    return float(history[-1] + mid * horizon)


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


def _cell_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (row["source_system"], row["outcome_key"], int(row["requested_horizon_days"]))


def train_providers(train: list[dict[str, Any]], val: list[dict[str, Any]]) -> dict[str, Any]:
    tr_by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    va_by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in train:
        tr_by[_cell_key(r)].append(r)
    for r in val:
        va_by[_cell_key(r)].append(r)
    cells = []
    keys = {
        (ss, ok, h)
        for ss, ok in {(r["source_system"], r["outcome_key"]) for r in train + val}
        for h in PREDECLARED_ABSOLUTE_GRID_DAYS
    }
    for key in sorted(keys | set(tr_by) | set(va_by)):
        tr = tr_by.get(key, [])
        va = va_by.get(key, [])
        ss, ok, h = key
        n_tr_s = len({r["source_scoped_subject_id"] for r in tr})
        n_va_s = len({r["source_scoped_subject_id"] for r in va})
        gate = {
            "n_train_subjects": n_tr_s,
            "n_val_subjects": n_va_s,
            "n_train_targets": len(tr),
            "n_val_targets": len(va),
            "test_unread": True,
        }
        data_ok = (
            n_tr_s >= MIN_TRAIN_SUBJECTS
            and n_va_s >= MIN_VAL_SUBJECTS
            and len(tr) >= MIN_TRAIN_TARGETS
            and len(va) >= MIN_VAL_TARGETS
        )
        if not data_ok:
            cells.append(
                {
                    "source_system": ss,
                    "outcome_key": ok,
                    "horizon_days": h,
                    "one_step_status": "VALIDATION_DATA_GATE_FAILED",
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
            predict_p2(
                r["features"],
                r.get("history_values_json") or [r["features"]["persistence_value"]],
                r.get("history_days_json") or [],
                h,
            )
            for r in va
        ]
        mae0 = _mae(sub_va, y_va, p0_va)
        mae1 = _mae(sub_va, y_va, p1_va)
        mae2 = _mae(sub_va, y_va, p2_va)
        scores = {"P0": mae0, "P1": mae1, "P2": mae2}
        active = min(scores, key=lambda k: scores[k] if math.isfinite(scores[k]) else 1e18)
        y_mean = sum(y_tr) / len(y_tr)
        y_var = sum((x - y_mean) ** 2 for x in y_tr) / max(len(y_tr), 1)
        p1_payload = {
            "family": "P1_ridge",
            "feature_order": list(P1_FEATURE_ORDER),
            "scaler_mean": model["scaler_mean"],
            "scaler_scale": model["scaler_scale"],
            "intercept": model["intercept"],
            "coefficients": model["coefficients"],
            "l2": L2,
        }
        incremental = active in {"P1", "P2"} and math.isfinite(scores[active]) and scores[active] < mae0 - 1e-12
        if active == "P0":
            status = "VALIDATION_BASELINE_SUPPORTED_P0"
        elif incremental:
            status = "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED"
        else:
            status = "VALIDATION_EVALUATED_NOT_ACCEPTED"
        identity_body = {
            "version": VERSION,
            "active_provider": active,
            "family": "P0_persistence" if active == "P0" else ("P2_robust_trend" if active == "P2" else "P1_ridge"),
            "source_system": ss,
            "outcome_key": ok,
            "horizon_days": h,
            "feature_order": list(P1_FEATURE_ORDER) if active == "P1" else ["persistence_value"],
            "time_grid": list(PREDECLARED_ABSOLUTE_GRID_DAYS),
            "acceptance_tier": status,
        }
        if active == "P1":
            identity_body.update(
                {
                    "scaler_mean": model["scaler_mean"],
                    "scaler_scale": model["scaler_scale"],
                    "intercept": model["intercept"],
                    "coefficients": model["coefficients"],
                    "l2": L2,
                }
            )
        cells.append(
            {
                "source_system": ss,
                "outcome_key": ok,
                "horizon_days": h,
                "one_step_status": status,
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
                "p1_payload": p1_payload,
                "feature_order_sha256": sha_obj(list(P1_FEATURE_ORDER)),
                "active_identity_body": identity_body,
                "active_payload_sha256": sha_obj(identity_body),
            }
        )
    return {
        "version": VERSION,
        "SOURCE_B_NATURAL_HISTORY_PROVIDER_TRAINING_STATUS": "TRAINED_SOURCE_SPECIFIC",
        "TRAIN_ONLY_PROVIDER_SELECTION_STATUS": "VALIDATION_ONLY",
        "cells": cells,
        "ok": True,
    }


def finalize_identity(cell: dict[str, Any]) -> str:
    body = dict(cell.get("active_identity_body") or {})
    body["residual_distribution_sha256"] = (cell.get("residual_dist") or {}).get(
        "residual_distribution_sha256"
    )
    body["residual_sampling_contract"] = (cell.get("residual_dist") or {}).get("sampling_contract")
    digest = sha_obj(body)
    cell["active_payload_sha256"] = digest
    cell["active_identity_body"] = body
    return digest


def predict_active(cell: dict[str, Any], feat: dict[str, Any], history: list[float], hist_days: list[float] | None = None) -> float:
    active = cell.get("active_provider") or "P0"
    h = float(feat.get("requested_horizon_days") or cell.get("horizon_days") or 0)
    if active == "P1" and cell.get("p1_payload"):
        return float(predict_ridge(cell["p1_payload"], p1_vector(feat)))
    if active == "P2":
        return predict_p2(feat, history, hist_days or [], h)
    return predict_p0(feat)


def predict_p0_row(feat: dict[str, Any]) -> float:
    return predict_p0(feat)


def features_from_history(history: list[float], hist_days: list[float], requested_h: float) -> dict[str, Any]:
    return t0_features(history, hist_days, requested_h)
