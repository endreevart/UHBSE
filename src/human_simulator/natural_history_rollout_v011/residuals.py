"""Train-only residual process. Independent step innovations; overlap-group reservoir."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.natural_history_rollout_v011.hashes import sha_obj
from human_simulator.natural_history_rollout_v011.policy import N_OOF_FOLDS, PI_HI, PI_LO, SEED, VERSION
from human_simulator.natural_history_rollout_v011.providers import p1_vector, predict_active
from human_simulator.unified_individual_state_v0111.ridge import fit_ridge, predict_ridge


def _quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    i = min(len(ys) - 1, max(0, int(q * (len(ys) - 1))))
    return ys[i]


def _oof_p1_residuals(rows: list[dict[str, Any]], payload: dict[str, Any]) -> list[tuple[str, float]]:
    groups = sorted({r["overlap_group_id"] for r in rows})
    if len(groups) < N_OOF_FOLDS:
        out = []
        for r in rows:
            yhat = predict_ridge(payload, p1_vector(r["features"]))
            if math.isfinite(yhat):
                out.append((r["overlap_group_id"], float(r["observed"]) - yhat))
        return out
    folds = {g: i % N_OOF_FOLDS for i, g in enumerate(groups)}
    assigned: dict[str, list[float]] = {}
    for fold in range(N_OOF_FOLDS):
        tr = [r for r in rows if folds[r["overlap_group_id"]] != fold]
        te = [r for r in rows if folds[r["overlap_group_id"]] == fold]
        if not tr or not te:
            continue
        model = fit_ridge([p1_vector(r["features"]) for r in tr], [r["observed"] for r in tr], l2=payload["l2"])
        for r in te:
            yhat = predict_ridge(model, p1_vector(r["features"]))
            if math.isfinite(yhat):
                assigned.setdefault(r["overlap_group_id"], []).append(float(r["observed"]) - yhat)
    out = []
    for g, xs in assigned.items():
        for x in xs:
            out.append((g, x))
    return out


def fit_residuals(train: list[dict[str, Any]], cells: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in train:
        by[(r["source_system"], r["outcome_key"], int(r["requested_horizon_days"]))].append(r)
    public = []
    for cell in cells:
        if cell.get("one_step_status") in {None, "VALIDATION_DATA_GATE_FAILED"}:
            continue
        key = (cell["source_system"], cell["outcome_key"], int(cell["horizon_days"]))
        rows = by.get(key) or []
        pairs: list[tuple[str, float]] = []
        oof = False
        if cell.get("active_provider") == "P1" and cell.get("p1_payload"):
            pairs = _oof_p1_residuals(rows, cell["p1_payload"])
            oof = len({r["overlap_group_id"] for r in rows}) >= N_OOF_FOLDS
        else:
            for r in rows:
                yhat = predict_active(
                    cell,
                    r["features"],
                    r.get("history_values_json") or [],
                    r.get("history_days_json") or [],
                )
                if math.isfinite(yhat):
                    pairs.append((r["overlap_group_id"], float(r["observed"]) - yhat))
        if not pairs:
            continue
        blocks: dict[str, list[float]] = defaultdict(list)
        for g, x in pairs:
            blocks[g].append(x)
        resid = [x for _, x in pairs]
        mean = sum(resid) / len(resid)
        var = sum((x - mean) ** 2 for x in resid) / max(len(resid), 1)
        dist = {
            "n": len(resid),
            "n_blocks": len(blocks),
            "mean": mean,
            "std": math.sqrt(var) if var > 0 else 0.0,
            "q05": _quantile(resid, PI_LO),
            "q50": _quantile(resid, 0.5),
            "q95": _quantile(resid, PI_HI),
            "oof": oof,
            "sampling_contract": "INDEPENDENT_STEP_INNOVATIONS_NO_SERIAL_RESIDUAL_MODEL",
            "block_reservoir": "overlap_group",
            "normal_not_assumed": True,
            "prefix_4000_not_used": True,
        }
        dist["residual_distribution_sha256"] = sha_obj(
            {
                "sorted": [round(x, 6) for x in sorted(resid)],
                "n_blocks": len(blocks),
                "contract": dist["sampling_contract"],
            }
        )
        cell["residual_dist"] = dist
        cell["residual_blocks"] = dict(blocks)
        from human_simulator.natural_history_rollout_v011.providers import finalize_identity

        finalize_identity(cell)
        public.append(
            {
                "source_system": cell["source_system"],
                "outcome_key": cell["outcome_key"],
                "horizon_days": cell["horizon_days"],
                "n": dist["n"],
                "n_blocks": dist["n_blocks"],
                "q05": dist["q05"],
                "q50": dist["q50"],
                "q95": dist["q95"],
                "residual_distribution_sha256": dist["residual_distribution_sha256"],
                "sampling_contract": dist["sampling_contract"],
                "oof": oof,
                "normal_not_assumed": True,
            }
        )
    return {
        "version": VERSION,
        "STOCHASTIC_RESIDUAL_DISTRIBUTION_STATUS": "FITTED_TRAIN_OOF_OR_BASELINE",
        "RESIDUAL_SERIAL_DEPENDENCE_STATUS": "INDEPENDENT_STEP_INNOVATIONS_NO_SERIAL_RESIDUAL_MODEL",
        "public": public,
        "ok": True,
    }


def sample_residual(cell: dict[str, Any], rng: random.Random) -> float:
    blocks = cell.get("residual_blocks") or {}
    if blocks:
        keys = list(blocks)
        chosen = keys[rng.randrange(len(keys))]
        xs = blocks[chosen] or [0.0]
        return float(xs[rng.randrange(len(xs))])
    return 0.0


def interval(cell: dict[str, Any], point: float) -> tuple[float, float]:
    dist = cell.get("residual_dist") or {}
    return point + float(dist.get("q05") or 0.0), point + float(dist.get("q95") or 0.0)
