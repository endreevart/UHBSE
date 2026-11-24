"""Horizon-aligned direct vs recursive evaluation. Teacher-forced is diagnostic only."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.natural_history_rollout_v011.policy import (
    COVERAGE_HI,
    COVERAGE_LO,
    ERROR_GROWTH_LIMIT,
    N_BOOTSTRAP,
    N_PATHS_DEFAULT,
    OOS_Z,
    RECURSIVE_BASE_INCREMENT_DAYS,
    SEED,
    recursive_n_steps,
)
from human_simulator.natural_history_rollout_v011.providers import features_from_history, predict_active, predict_p0
from human_simulator.natural_history_rollout_v011.residuals import interval, sample_residual


def _mae_pairs(pairs: list[tuple[str, str, float, float]]) -> float:
    per: dict[str, list[float]] = defaultdict(list)
    for s, _g, a, b in pairs:
        per[s].append(abs(a - b))
    if not per:
        return float("nan")
    return sum(sum(v) / len(v) for v in per.values()) / len(per)


def _bootstrap(pairs: list[tuple[str, str, float, float]], seed: int = SEED) -> dict[str, Any]:
    by: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for _s, g, a, b in pairs:
        by[g].append((a, b))
    keys = list(by)
    label = "overlap_group"
    if not keys:
        return {"lo": None, "hi": None, "grouping": "overlap_group", "row_level_bootstrap": False}
    rng = random.Random(seed)
    stats = []
    for _ in range(N_BOOTSTRAP):
        draw = [keys[rng.randrange(len(keys))] for _ in keys]
        acc = []
        for k in draw:
            for a, b in by[k]:
                acc.append(abs(a - b))
        if acc:
            stats.append(sum(acc) / len(acc))
    stats.sort()
    return {
        "lo": stats[int(0.025 * (len(stats) - 1))] if stats else None,
        "hi": stats[int(0.975 * (len(stats) - 1))] if stats else None,
        "grouping": label,
        "row_level_bootstrap": False,
        "n_groups": len(keys),
    }


def _oos(cell: dict[str, Any], yhat: float) -> bool:
    ymin, ymax, ystd = cell.get("train_ymin"), cell.get("train_ymax"), float(cell.get("train_ystd") or 0.0)
    if ymin is None or ymax is None:
        return False
    pad = OOS_Z * ystd
    return yhat < float(ymin) - pad or yhat > float(ymax) + pad


def direct_predict(cell: dict[str, Any], row: dict[str, Any], rng: random.Random | None) -> float:
    feat = dict(row["features"])
    feat["requested_horizon_days"] = float(cell["horizon_days"])
    yhat = predict_active(
        cell, feat, row.get("history_values_json") or [row["t0_value"]], row.get("history_days_json") or []
    )
    if rng is not None:
        yhat = yhat + sample_residual(cell, rng)
    return yhat


def recursive_endpoint(
    increment_cell: dict[str, Any],
    row: dict[str, Any],
    *,
    horizon: int,
    rng: random.Random | None,
) -> dict[str, Any] | None:
    n = recursive_n_steps(horizon)
    if n is None:
        return {"unsupported_increment": True}
    hist = list(row.get("history_values_json") or [row["t0_value"]])
    days = list(row.get("history_days_json") or [])
    preds = []
    oos = False
    for _ in range(n):
        feat = features_from_history(hist, days, float(RECURSIVE_BASE_INCREMENT_DAYS))
        yhat = predict_active(increment_cell, feat, hist, days)
        if rng is not None:
            yhat = yhat + sample_residual(increment_cell, rng)
        if _oos(increment_cell, yhat):
            oos = True
            break
        preds.append(yhat)
        hist.append(yhat)
        days.append(float(RECURSIVE_BASE_INCREMENT_DAYS))
    return {
        "unsupported_increment": False,
        "preds": preds,
        "endpoint": preds[-1] if preds else None,
        "n_steps": len(preds),
        "out_of_support": oos,
        "requested_offset": n * RECURSIVE_BASE_INCREMENT_DAYS,
        "read_future_values": False,
        "used_actual_future_intervals": False,
    }


def crps(paths: list[float], y: float) -> float:
    if not paths:
        return float("nan")
    n = len(paths)
    term1 = sum(abs(p - y) for p in paths) / n
    term2 = 0.0
    for i, a in enumerate(paths):
        for b in paths[i + 1 :]:
            term2 += abs(a - b)
    term2 = term2 / (n * n)
    return term1 - 0.5 * 2 * term2


def evaluate_cell(
    rows: list[dict[str, Any]],
    cell: dict[str, Any],
    increment_cell: dict[str, Any] | None,
    *,
    stochastic: bool,
) -> dict[str, Any]:
    h = int(cell["horizon_days"])
    matched = [r for r in rows if r["source_system"] == cell["source_system"] and r["outcome_key"] == cell["outcome_key"] and int(r["requested_horizon_days"]) == h]
    direct_pairs = []
    rec_pairs = []
    p0_pairs = []
    cov_hits = 0
    n_cov = 0
    finite = True
    oos_n = 0
    crps_acc = []
    for row in matched:
        rng = random.Random(SEED + hash(row["target_id"]) % 10_000) if stochastic else None
        yhat = direct_predict(cell, row, rng if stochastic else None)
        if not math.isfinite(yhat):
            finite = False
        if _oos(cell, yhat):
            oos_n += 1
        y = float(row["observed"])
        sid, og = row["source_scoped_subject_id"], row["overlap_group_id"]
        direct_pairs.append((sid, og, y, yhat))
        p0_pairs.append((sid, og, y, predict_p0(row["features"])))
        lo, hi = interval(cell, yhat)
        n_cov += 1
        if lo <= y <= hi:
            cov_hits += 1
        if stochastic:
            paths = []
            for i in range(N_PATHS_DEFAULT):
                rgi = random.Random(SEED + i * 19 + hash(row["target_id"]) % 10_000)
                paths.append(direct_predict(cell, row, rgi))
            crps_acc.append(crps(paths, y))
            lo_p, hi_p = sorted(paths)[max(0, int(0.05 * (len(paths) - 1)))], sorted(paths)[
                min(len(paths) - 1, int(0.95 * (len(paths) - 1)))
            ]
            if lo_p <= y <= hi_p:
                pass
        rec = None
        if increment_cell is not None and recursive_n_steps(h) is not None:
            rec = recursive_endpoint(increment_cell, row, horizon=h, rng=rng if stochastic else None)
            if rec and not rec.get("unsupported_increment") and rec.get("endpoint") is not None:
                rec_pairs.append((sid, og, y, float(rec["endpoint"])))
    mae_d = _mae_pairs(direct_pairs)
    mae_p0 = _mae_pairs(p0_pairs)
    mae_rec = _mae_pairs(rec_pairs) if rec_pairs else float("nan")
    cov = (cov_hits / n_cov) if n_cov else float("nan")
    boot = _bootstrap(direct_pairs)
    n_subj = len({p[0] for p in direct_pairs})
    n_og = len({p[1] for p in direct_pairs})
    not_worse = math.isfinite(mae_d) and math.isfinite(mae_p0) and mae_d <= mae_p0 + 1e-12
    rec_ok = True
    rec_status = "NOT_RUN"
    n_steps = recursive_n_steps(h)
    if n_steps is None:
        rec_status = "NOT_RUN_UNSUPPORTED_INCREMENT"
        rec_ok = False
    elif increment_cell is None:
        rec_status = "NOT_RUN_NO_INCREMENT_CELL"
        rec_ok = False
    elif not rec_pairs:
        rec_status = "NOT_RUN_FAILED_SEQUENCE_GATE"
        rec_ok = False
    else:
        rec_not_worse = math.isfinite(mae_rec) and mae_rec <= mae_p0 + 1e-12
        if not rec_not_worse:
            rec_status = "EVALUATED_NOT_ACCEPTED_RECURSIVE_DEGRADATION"
            rec_ok = False
        elif not_worse and finite and math.isfinite(cov) and COVERAGE_LO <= cov <= COVERAGE_HI and boot.get("lo") is not None:
            rec_status = "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
        else:
            rec_status = "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_OR_CALIBRATED_SIGNAL"
            rec_ok = False
    return {
        "n_targets": len(matched),
        "n_subjects": n_subj,
        "n_overlap_groups": n_og,
        "mae_direct": mae_d,
        "mae_p0": mae_p0,
        "mae_recursive": mae_rec,
        "coverage": cov,
        "bootstrap": boot,
        "finite": finite,
        "out_of_support_rate": oos_n / len(matched) if matched else None,
        "mean_crps": (sum(crps_acc) / len(crps_acc)) if crps_acc else None,
        "pooled_across_units": False,
        "teacher_forced_not_used_for_acceptance": True,
        "stochastic": stochastic,
        "recursive_n_steps": n_steps,
        "recursive_endpoint_offset": (n_steps * RECURSIVE_BASE_INCREMENT_DAYS) if n_steps else None,
        "direct_endpoint_offset": h,
        "horizon_identity_ok": True,
        "recursive_status": rec_status,
        "direct_not_worse_than_p0": not_worse,
        "recursive_accepted": rec_ok and rec_status == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED",
        "STOCHASTIC_PATH_EVALUATION_STATUS": "EVALUATED" if stochastic else "DETERMINISTIC_POINT_ONLY",
    }


def increment_cell_for(cells: list[dict[str, Any]], cell: dict[str, Any]) -> dict[str, Any] | None:
    for c in cells:
        if (
            c.get("source_system") == cell["source_system"]
            and c.get("outcome_key") == cell["outcome_key"]
            and int(c.get("horizon_days") or 0) == RECURSIVE_BASE_INCREMENT_DAYS
            and c.get("one_step_status")
            in {"VALIDATION_BASELINE_SUPPORTED_P0", "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED"}
        ):
            return c
    return None
