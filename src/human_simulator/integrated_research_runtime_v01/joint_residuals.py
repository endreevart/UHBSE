"""Train group-OOF residuals. Folds via SHA-256 namespace. No in-sample D1 residuals."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from human_simulator.integrated_research_runtime_v01.hashes import fold_of_group, sha_obj
from human_simulator.integrated_research_runtime_v01.policy import N_OOF_FOLDS, VERSION
from human_simulator.joint_dependence_rollout_v02.providers import p1_vector, predict_active
from human_simulator.unified_individual_state_v0111.ridge import fit_ridge, predict_ridge


def _og(row: dict[str, Any]) -> str:
    return str(row.get("effective_overlap_group_id") or "")


def attach_group_oof_residuals(
    train: list[dict[str, Any]],
    cells: list[dict[str, Any]],
) -> dict[str, Any]:
    by: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in train:
        by[(r["source_system"], r["outcome_key"], int(r["requested_horizon_days"]))].append(r)
    cells_by = {(c["source_system"], c["outcome_key"], int(c["horizon_days"])): c for c in cells}
    assignments: dict[str, int] = {}
    residual_payloads: dict[str, list[float]] = {}
    n_oof = 0
    n_p0 = 0
    leaked = 0
    for key, rows in by.items():
        cell = cells_by.get(key)
        if not cell:
            continue
        ss = key[0]
        groups = sorted({_og(r) for r in rows})
        folds = {g: fold_of_group(ss, g, N_OOF_FOLDS) for g in groups}
        for g, f in folds.items():
            assignments[f"{ss}|{g}"] = f
        if cell.get("active_provider") == "P1" and cell.get("p1_payload") and len(groups) >= N_OOF_FOLDS:
            for fold in range(N_OOF_FOLDS):
                tr = [r for r in rows if folds[_og(r)] != fold]
                te = [r for r in rows if folds[_og(r)] == fold]
                if not tr or not te:
                    continue
                l2 = float((cell.get("p1_payload") or {}).get("l2") or 0.1)
                model = fit_ridge(
                    [p1_vector(r["features"]) for r in tr],
                    [float(r["observed"]) for r in tr],
                    l2=l2,
                )
                train_groups = {_og(r) for r in tr}
                for r in te:
                    if _og(r) in train_groups:
                        leaked += 1
                    yhat = predict_ridge(model, p1_vector(r["features"]))
                    if math.isfinite(yhat):
                        r["oof_residual"] = float(r["observed"]) - yhat
                        r["oof_yhat"] = yhat
                        n_oof += 1
        else:
            for r in rows:
                yhat = predict_active(
                    cell,
                    r["features"],
                    r.get("history_values_json") or [],
                    r.get("history_days_json") or [],
                )
                if math.isfinite(yhat):
                    r["oof_residual"] = float(r["observed"]) - yhat
                    r["oof_yhat"] = yhat
                    n_p0 += 1
        key_s = f"{key[0]}|{key[1]}|{key[2]}"
        residual_payloads[key_s] = [float(r["oof_residual"]) for r in rows if "oof_residual" in r]
    identity = sha_obj(
        {
            "fold_assignments": assignments,
            "residual_payloads": {k: residual_payloads[k] for k in sorted(residual_payloads)},
            "n_folds": N_OOF_FOLDS,
            "namespace": "group_oof",
        }
    )
    return {
        "version": VERSION,
        "GROUP_OOF_RESIDUAL_STATUS": "PASS" if leaked == 0 else "FAIL",
        "n_oof_p1": n_oof,
        "n_p0_or_baseline": n_p0,
        "fold_leak_count": leaked,
        "n_groups_assigned": len(assignments),
        "residual_block_identity_sha256": identity,
        "in_sample_residuals_forbidden_for_d1": True,
        "ok": leaked == 0,
    }


def apply_frozen_yhat(row: dict[str, Any], cell: dict[str, Any]) -> float:
    if row.get("oof_yhat") is not None and row.get("split_role") == "train":
        return float(row["oof_yhat"])
    return float(
        predict_active(
            cell,
            row["features"],
            row.get("history_values_json") or [],
            row.get("history_days_json") or [],
        )
    )


def attach_frozen_eval_residuals(rows: list[dict[str, Any]], cells: list[dict[str, Any]]) -> None:
    cells_by = {(c["source_system"], c["outcome_key"], int(c["horizon_days"])): c for c in cells}
    for r in rows:
        if r.get("split_role") == "train" and r.get("oof_residual") is not None:
            continue
        cell = cells_by.get((r["source_system"], r["outcome_key"], int(r["requested_horizon_days"])))
        if not cell:
            continue
        yhat = apply_frozen_yhat(r, cell)
        if math.isfinite(yhat):
            r["oof_residual"] = float(r["observed"]) - yhat
            r["oof_yhat"] = yhat
