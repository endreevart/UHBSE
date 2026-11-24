"""Subject-macro metrics. No pooled raw MAE across units."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.natural_history_rollout_v01.policy import (
    COVERAGE_HI,
    COVERAGE_LO,
    ERROR_GROWTH_LIMIT,
    N_BOOTSTRAP,
    SEED,
)
from human_simulator.natural_history_rollout_v01.times import bin_horizon
from human_simulator.natural_history_rollout_v01.rollout import (
    coverage_at,
    evaluate_sequence,
    persistence_sequence,
)


def _mae(pairs: list[tuple[str, float, float]]) -> float:
    per: dict[str, list[float]] = defaultdict(list)
    for s, a, b in pairs:
        per[s].append(abs(a - b))
    if not per:
        return float("nan")
    return sum(sum(v) / len(v) for v in per.values()) / len(per)


def _bootstrap_mae(pairs: list[tuple[str, float, float]], seed: int = SEED) -> dict[str, Any]:
    by: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for s, a, b in pairs:
        by[s].append((a, b))
    keys = list(by)
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
    if not stats:
        return {"lo": None, "hi": None}
    return {
        "lo": stats[int(0.025 * (len(stats) - 1))],
        "hi": stats[int(0.975 * (len(stats) - 1))],
        "grouping": "overlap_group_or_subject",
        "row_level_bootstrap": False,
    }


def rollout_cell_metrics(
    sequences: list[dict[str, Any]],
    cell: dict[str, Any],
) -> dict[str, Any]:
    matched = [
        s
        for s in sequences
        if seq_match(s, cell)
        and any(bin_horizon(float(h)) == int(cell["horizon_days"]) for h in s["step_horizons_json"])
    ]
    rec_rows = []
    tf_rows = []
    pers_rows = []
    step_err: dict[int, list[tuple[str, float, float]]] = defaultdict(list)
    covs = []
    finite = True
    dir_hits = 0
    dir_n = 0
    oos_n = 0
    for seq in matched:
        rec = evaluate_sequence(seq, cell, recursive=True, rng=None)
        tf = evaluate_sequence(seq, cell, recursive=False, rng=None)
        if not rec or not tf:
            continue
        if rec["read_future_values"]:
            raise RuntimeError("recursive rollout read future values")
        for i, (p, o) in enumerate(zip(rec["preds"], rec["obs"], strict=True), start=1):
            if not math.isfinite(p):
                finite = False
            step_err[i].append((rec["subject"], o, p))
        rec_rows.extend((rec["subject"], o, p) for p, o in zip(rec["preds"], rec["obs"], strict=True))
        tf_rows.extend((tf["subject"], o, p) for p, o in zip(tf["preds"], tf["obs"], strict=True))
        pers = persistence_sequence(seq, rec["n_steps"])
        pers_rows.extend((rec["subject"], o, p) for p, o in zip(pers, rec["obs"], strict=True))
        covs.append(coverage_at(cell, rec["preds"], rec["obs"]))
        dir_hits += int(rec.get("direction_hits") or 0)
        dir_n += int(rec.get("n_steps") or 0)
        if rec.get("out_of_support"):
            oos_n += 1
    mae_rec = _mae(rec_rows)
    mae_tf = _mae(tf_rows)
    mae_pers = _mae(pers_rows)
    mae_s1 = _mae(step_err.get(1) or [])
    max_step = max(step_err) if step_err else 0
    mae_max = _mae(step_err.get(max_step) or [])
    growth = (mae_max / mae_s1) if mae_s1 and mae_s1 > 0 else None
    cov = sum(covs) / len(covs) if covs else float("nan")
    boot = _bootstrap_mae(rec_rows)
    not_worse = math.isfinite(mae_rec) and math.isfinite(mae_pers) and mae_rec <= mae_pers + 1e-12
    growth_ok = growth is not None and growth <= ERROR_GROWTH_LIMIT
    cov_ok = math.isfinite(cov) and COVERAGE_LO <= cov <= COVERAGE_HI
    accept = (
        cell.get("one_step_status") == "ONE_STEP_VALIDATION_ACCEPTED"
        and finite
        and growth_ok
        and cov_ok
        and not_worse
        and boot.get("lo") is not None
    )
    if not matched:
        status = "NOT_RUN_FAILED_SEQUENCE_GATE"
    elif accept:
        status = "STOCHASTIC_ROLLOUT_CELL_ACCEPTED"
    elif not not_worse:
        status = "EVALUATED_NOT_ACCEPTED_RECURSIVE_DEGRADATION"
    else:
        status = "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL"
    return {
        "mae_recursive": mae_rec,
        "mae_teacher_forced": mae_tf,
        "mae_persistence_recursive": mae_pers,
        "mae_step1": mae_s1,
        "mae_max_step": mae_max,
        "max_step": max_step,
        "error_growth": growth,
        "coverage": cov,
        "bootstrap": boot,
        "finite": finite,
        "teacher_forced_not_recursive_quality": True,
        "n_sequences": len({s["source_scoped_subject_id"] for s in matched}),
        "pooled_across_units": False,
        "direction_agreement": (dir_hits / dir_n) if dir_n else None,
        "out_of_support_rate": (oos_n / len(matched)) if matched else None,
        "rollout_status": status,
    }


def seq_match(seq: dict[str, Any], cell: dict[str, Any]) -> bool:
    return seq["outcome_key"] == cell["outcome_key"] and seq["source_system"] == cell["source_system"]
