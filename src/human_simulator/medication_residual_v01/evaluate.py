"""Subject-macro MAE, overlap-group bootstrap, grouped permutation. No pooled-across-unit MAE."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.medication_residual_v01.policy import N_BOOTSTRAP, N_PERMUTATION, N_VAL_FOLDS, SEED


def _finite(xs: list[float]) -> bool:
    return all(math.isfinite(x) for x in xs)


def mae(y: list[float], yhat: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(y, yhat, strict=True)) / max(len(y), 1)


def rmse(y: list[float], yhat: list[float]) -> float:
    return math.sqrt(
        sum((a - b) ** 2 for a, b in zip(y, yhat, strict=True)) / max(len(y), 1)
    )


def subject_macro_mae(
    rows: list[dict[str, Any]], y: list[float], yhat: list[float]
) -> float:
    acc: dict[str, list[float]] = defaultdict(list)
    for r, a, b in zip(rows, y, yhat, strict=True):
        acc[str(r["source_scoped_subject_id"])].append(abs(a - b))
    if not acc:
        return float("nan")
    return sum(sum(v) / len(v) for v in acc.values()) / len(acc)


def _gkey(row: dict[str, Any]) -> str:
    return str(row.get("overlap_group_id") or row["source_scoped_subject_id"])


def bootstrap_improvement_ci(
    rows: list[dict[str, Any]],
    y: list[float],
    y_r1: list[float],
    y_r2: list[float],
    *,
    n: int = N_BOOTSTRAP,
    seed: int = SEED,
) -> dict[str, Any]:
    by: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by[_gkey(r)].append(i)
    keys = list(by)
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        idxs = []
        for k in keys:
            draw = keys[rng.randrange(len(keys))]
            idxs.extend(by[draw])
        if not idxs:
            continue
        yy = [y[i] for i in idxs]
        a = [y_r1[i] for i in idxs]
        b = [y_r2[i] for i in idxs]
        sub = [rows[i] for i in idxs]
        stats.append(subject_macro_mae(sub, yy, a) - subject_macro_mae(sub, yy, b))
    stats.sort()
    if not stats:
        return {"lo": None, "hi": None, "mean": None, "n": 0}
    lo = stats[int(0.025 * (len(stats) - 1))]
    hi = stats[int(0.975 * (len(stats) - 1))]
    return {
        "lo": lo,
        "hi": hi,
        "mean": sum(stats) / len(stats),
        "n": n,
        "grouping": "overlap_group_or_subject",
        "row_level_bootstrap": False,
    }


def grouped_permutation_p(
    rows: list[dict[str, Any]],
    y: list[float],
    y_r1: list[float],
    y_r2: list[float],
    observed: float,
    *,
    n: int = N_PERMUTATION,
    seed: int = SEED,
) -> dict[str, Any]:
    by: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by[_gkey(r)].append(i)
    keys = list(by)
    rng = random.Random(seed + 7)
    r2 = y_r2[:]
    ge = 0
    for _ in range(n):
        perm_keys = keys[:]
        rng.shuffle(perm_keys)
        mapping = dict(zip(keys, perm_keys, strict=True))
        y2p = r2[:]
        for src, dst in mapping.items():
            src_idx = by[src]
            dst_idx = by[dst]
            # permute R2 predictions between groups of equal cardinality via cycle of values
            src_vals = [r2[i] for i in src_idx]
            for j, i in enumerate(dst_idx):
                y2p[i] = src_vals[j % len(src_vals)]
        imp = subject_macro_mae(rows, y, y_r1) - subject_macro_mae(rows, y, y2p)
        if imp >= observed:
            ge += 1
    p = (1 + ge) / (n + 1)
    return {
        "p": p,
        "n": n,
        "grouping": "overlap_group_or_subject",
        "finite": math.isfinite(p),
    }


def fold_directions(
    rows: list[dict[str, Any]],
    y: list[float],
    y_r1: list[float],
    y_r2: list[float],
    *,
    n_folds: int = N_VAL_FOLDS,
) -> dict[str, Any]:
    groups = sorted({_gkey(r) for r in rows})
    if not groups:
        return {"n_folds": 0, "directions": [], "stable_positive": False}
    folds: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        folds[groups.index(_gkey(r)) % n_folds].append(i)
    directions = []
    for f in range(n_folds):
        idxs = folds.get(f) or []
        if len(idxs) < 3:
            continue
        sub = [rows[i] for i in idxs]
        yy = [y[i] for i in idxs]
        a = [y_r1[i] for i in idxs]
        b = [y_r2[i] for i in idxs]
        imp = subject_macro_mae(sub, yy, a) - subject_macro_mae(sub, yy, b)
        directions.append(imp > 0)
    stable = bool(directions) and all(directions)
    return {
        "n_folds": len(directions),
        "directions": directions,
        "stable_positive": stable,
    }


def cell_metrics(
    rows: list[dict[str, Any]],
    pred_r0: list[float],
    pred_r1: list[float],
    pred_r2: list[float],
) -> dict[str, Any]:
    y = [float(r["residual"]) for r in rows]
    finite = _finite(y) and _finite(pred_r0) and _finite(pred_r1) and _finite(pred_r2)
    mae_r0 = subject_macro_mae(rows, y, pred_r0)
    mae_r1 = subject_macro_mae(rows, y, pred_r1)
    mae_r2 = subject_macro_mae(rows, y, pred_r2)
    improvement = mae_r1 - mae_r2
    boot = bootstrap_improvement_ci(rows, y, pred_r1, pred_r2)
    perm = grouped_permutation_p(rows, y, pred_r1, pred_r2, improvement)
    folds = fold_directions(rows, y, pred_r1, pred_r2)
    subjects = {r["source_scoped_subject_id"] for r in rows}
    targets = {r["target_id"] for r in rows}
    lo = boot.get("lo")
    val_accept = (
        finite
        and improvement > 0
        and lo is not None
        and lo > 0
        and (perm.get("p") or 1) < 0.05
        and folds.get("stable_positive") is True
    )
    return {
        "n_rows": len(rows),
        "n_subjects": len(subjects),
        "n_unique_targets": len(targets),
        "mae_r0": mae_r0,
        "mae_r1": mae_r1,
        "mae_r2": mae_r2,
        "rmse_r1": rmse(y, pred_r1),
        "rmse_r2": rmse(y, pred_r2),
        "mae_improvement_r1_minus_r2": improvement,
        "bootstrap": boot,
        "permutation": perm,
        "folds": folds,
        "finite": finite,
        "pooled_across_units": False,
        "row_level_bootstrap": False,
        "validation_gate_pass": val_accept,
    }
