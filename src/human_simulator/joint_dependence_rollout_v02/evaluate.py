"""Direct/recursive evaluation: path median, CRPS, effective-group bootstrap, ERROR_GROWTH_LIMIT."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.joint_dependence_rollout_v02.hashes import derive_seed
from human_simulator.joint_dependence_rollout_v02.policy import (
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
from human_simulator.joint_dependence_rollout_v02.providers import features_from_history, predict_active
from human_simulator.joint_dependence_rollout_v02.residuals import interval, sample_residual
from human_simulator.joint_dependence_rollout_v02.scores import crps_paths
from human_simulator.natural_history_rollout_v011.providers import predict_p0


def _og(row: dict[str, Any]) -> str:
    return str(row.get("effective_overlap_group_id") or row.get("overlap_group_id") or "")


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
    if not keys:
        return {"lo": None, "hi": None, "grouping": "effective_overlap_group", "row_level_bootstrap": False}
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
        "grouping": "effective_overlap_group",
        "row_level_bootstrap": False,
        "n_groups": len(keys),
    }


def _oos(cell: dict[str, Any], yhat: float) -> bool:
    ymin, ymax, ystd = cell.get("train_ymin"), cell.get("train_ymax"), float(cell.get("train_ystd") or 0.0)
    if ymin is None or ymax is None:
        return False
    pad = OOS_Z * ystd
    return yhat < float(ymin) - pad or yhat > float(ymax) + pad


def _row_seed(row: dict[str, Any], *, mode: str, path_index: int) -> int:
    return derive_seed(
        source_system=str(row.get("source_system") or ""),
        outcome_key=str(row.get("outcome_key") or ""),
        horizon_days=int(row.get("requested_horizon_days") or 0),
        split_role=str(row.get("split_role") or ""),
        target_id=str(row.get("target_id") or ""),
        landmark_id=str(row.get("t0_id") or ""),
        mode=mode,
        path_index=path_index,
    )


def direct_paths(cell: dict[str, Any], row: dict[str, Any], n_paths: int = N_PATHS_DEFAULT) -> list[float]:
    feat = dict(row["features"])
    feat["requested_horizon_days"] = float(cell["horizon_days"])
    hist = row.get("history_values_json") or [row["t0_value"]]
    days = row.get("history_days_json") or []
    y0 = predict_active(cell, feat, hist, days)
    paths = []
    for i in range(n_paths):
        rng = random.Random(_row_seed(row, mode="direct", path_index=i))
        paths.append(y0 + sample_residual(cell, rng))
    return paths


def recursive_paths(
    increment_cell: dict[str, Any],
    row: dict[str, Any],
    *,
    horizon: int,
    n_paths: int = N_PATHS_DEFAULT,
) -> dict[str, Any]:
    n = recursive_n_steps(horizon)
    if n is None:
        return {"unsupported_increment": True, "paths": []}
    out = []
    oos_n = 0
    for i in range(n_paths):
        rng = random.Random(_row_seed(row, mode="recursive", path_index=i))
        hist = list(row.get("history_values_json") or [row["t0_value"]])
        days = list(row.get("history_days_json") or [])
        last = None
        failed = False
        for _ in range(n):
            feat = features_from_history(hist, days, float(RECURSIVE_BASE_INCREMENT_DAYS))
            yhat = predict_active(increment_cell, feat, hist, days) + sample_residual(increment_cell, rng)
            if _oos(increment_cell, yhat):
                failed = True
                oos_n += 1
                break
            hist.append(yhat)
            days.append(float(RECURSIVE_BASE_INCREMENT_DAYS))
            last = yhat
        if not failed and last is not None:
            out.append(last)
    return {
        "unsupported_increment": False,
        "paths": out,
        "n_steps": n,
        "requested_offset": n * RECURSIVE_BASE_INCREMENT_DAYS,
        "out_of_support_paths": oos_n,
        "read_future_values": False,
        "used_actual_future_intervals": False,
    }


def evaluate_cell(
    rows: list[dict[str, Any]],
    cell: dict[str, Any],
    increment_cell: dict[str, Any] | None,
) -> dict[str, Any]:
    h = int(cell["horizon_days"])
    matched = [
        r
        for r in rows
        if r["source_system"] == cell["source_system"]
        and r["outcome_key"] == cell["outcome_key"]
        and int(r["requested_horizon_days"]) == h
    ]
    direct_pairs = []
    rec_pairs = []
    p0_pairs = []
    cov_hits = 0
    rec_cov_hits = 0
    n_cov = 0
    rec_n_cov = 0
    finite = True
    oos_n = 0
    crps_acc = []
    rec_crps = []
    emp_cov_hits = 0
    emp_n = 0
    for row in matched:
        paths = direct_paths(cell, row)
        if not paths or any(not math.isfinite(x) for x in paths):
            finite = False
            continue
        yhat = sorted(paths)[len(paths) // 2]
        if _oos(cell, yhat):
            oos_n += 1
        y = float(row["observed"])
        sid, og = row["source_scoped_subject_id"], _og(row)
        direct_pairs.append((sid, og, y, yhat))
        p0_pairs.append((sid, og, y, predict_p0(row["features"])))
        lo, hi = interval(cell, yhat)
        n_cov += 1
        if lo <= y <= hi:
            cov_hits += 1
        crps_acc.append(crps_paths(paths, y))
        lo_p, hi_p = sorted(paths)[max(0, int(0.05 * (len(paths) - 1)))], sorted(paths)[
            min(len(paths) - 1, int(0.95 * (len(paths) - 1)))
        ]
        emp_n += 1
        if lo_p <= y <= hi_p:
            emp_cov_hits += 1
        if increment_cell is not None and recursive_n_steps(h) is not None:
            rec = recursive_paths(increment_cell, row, horizon=h)
            rpaths = rec.get("paths") or []
            if rpaths:
                ry = sorted(rpaths)[len(rpaths) // 2]
                rec_pairs.append((sid, og, y, ry))
                rec_crps.append(crps_paths(rpaths, y))
                rec_n_cov += 1
                rlo, rhi = sorted(rpaths)[max(0, int(0.05 * (len(rpaths) - 1)))], sorted(rpaths)[
                    min(len(rpaths) - 1, int(0.95 * (len(rpaths) - 1)))
                ]
                if rlo <= y <= rhi:
                    rec_cov_hits += 1
    mae_d = _mae_pairs(direct_pairs)
    mae_p0 = _mae_pairs(p0_pairs)
    mae_rec = _mae_pairs(rec_pairs) if rec_pairs else float("nan")
    cov = (cov_hits / n_cov) if n_cov else float("nan")
    emp_cov = (emp_cov_hits / emp_n) if emp_n else float("nan")
    rec_cov = (rec_cov_hits / rec_n_cov) if rec_n_cov else float("nan")
    boot = _bootstrap(direct_pairs)
    rec_boot = _bootstrap(rec_pairs) if rec_pairs else {"lo": None, "hi": None, "grouping": "effective_overlap_group"}
    n_subj = len({p[0] for p in direct_pairs})
    n_og = len({p[1] for p in direct_pairs})
    not_worse = math.isfinite(mae_d) and math.isfinite(mae_p0) and mae_d <= mae_p0 + 1e-12
    n_steps = recursive_n_steps(h)
    rec_status = "NOT_RUN"
    rec_ok = False
    if n_steps is None:
        rec_status = "NOT_RUN_UNSUPPORTED_INCREMENT"
    elif increment_cell is None:
        rec_status = "NOT_RUN_NO_INCREMENT_CELL"
    elif not rec_pairs:
        rec_status = "NOT_RUN_FAILED_SEQUENCE_GATE"
    else:
        rec_not_worse = math.isfinite(mae_rec) and mae_rec <= mae_p0 + 1e-12
        growth_ok = (not math.isfinite(mae_d)) or mae_rec <= ERROR_GROWTH_LIMIT * mae_d + 1e-12
        rec_cov_ok = rec_cov is not None and math.isfinite(rec_cov) and COVERAGE_LO <= rec_cov <= COVERAGE_HI
        if not rec_not_worse:
            rec_status = "EVALUATED_NOT_ACCEPTED_RECURSIVE_DEGRADATION"
        elif not growth_ok:
            rec_status = "EVALUATED_NOT_ACCEPTED_ERROR_GROWTH"
        elif not rec_cov_ok or rec_boot.get("lo") is None:
            rec_status = "EVALUATED_NOT_ACCEPTED_NO_CALIBRATED_RECURSIVE_SIGNAL"
        else:
            rec_status = "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
            rec_ok = True
    gate_ok = (
        finite
        and math.isfinite(cov)
        and COVERAGE_LO <= cov <= COVERAGE_HI
        and boot.get("lo") is not None
        and not_worse
        and n_subj >= 1
    )
    return {
        "n_targets": len(matched),
        "n_subjects": n_subj,
        "n_overlap_groups": n_og,
        "mae_direct": mae_d,
        "mae_p0": mae_p0,
        "mae_recursive": mae_rec,
        "coverage": cov,
        "empirical_path_coverage": emp_cov,
        "recursive_empirical_path_coverage": rec_cov,
        "bootstrap": boot,
        "recursive_bootstrap": rec_boot,
        "finite": finite,
        "out_of_support_rate": oos_n / len(matched) if matched else None,
        "mean_crps": (sum(crps_acc) / len(crps_acc)) if crps_acc else None,
        "mean_crps_recursive": (sum(rec_crps) / len(rec_crps)) if rec_crps else None,
        "pooled_across_units": False,
        "teacher_forced_not_used_for_acceptance": True,
        "path_summary": "path_median",
        "recursive_n_steps": n_steps,
        "recursive_endpoint_offset": (n_steps * RECURSIVE_BASE_INCREMENT_DAYS) if n_steps else None,
        "direct_endpoint_offset": h,
        "error_growth_limit_applied": True,
        "recursive_status": rec_status,
        "direct_not_worse_than_p0": not_worse,
        "validation_gate_accepted": gate_ok,
        "recursive_accepted": rec_ok,
        "BOOTSTRAP_GROUPING_STATUS": "EFFECTIVE_OVERLAP_GROUP",
        "RECURSIVE_STOCHASTIC_EVALUATION_STATUS": "PATH_MEDIAN_CRPS_COVERAGE_BOOTSTRAP",
        "STOCHASTIC_PATH_EVALUATION_STATUS": "EVALUATED",
    }


def increment_cell_for(cells: list[dict[str, Any]], cell: dict[str, Any]) -> dict[str, Any] | None:
    for c in cells:
        if (
            c.get("source_system") == cell["source_system"]
            and c.get("outcome_key") == cell["outcome_key"]
            and int(c.get("horizon_days") or 0) == RECURSIVE_BASE_INCREMENT_DAYS
            and (
                c.get("validation_gate_accepted")
                or c.get("one_step_status") in {"BASELINE_SUPPORTED_P0", "VALIDATION_SELECTED"}
            )
        ):
            return c
    return None
