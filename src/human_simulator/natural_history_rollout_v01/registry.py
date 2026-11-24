"""Cell registry and public projection."""

from __future__ import annotations

from typing import Any

from human_simulator.natural_history_rollout_v01.hashes import sha_obj
from human_simulator.natural_history_rollout_v01.policy import VERSION


def build_registry(cells: list[dict[str, Any]]) -> dict[str, Any]:
    out = []
    for c in cells:
        rec = {k: v for k, v in c.items() if k not in {"payload", "residual_samples"}}
        rec["cell_id_sha256"] = sha_obj(
            [c.get("source_system"), c.get("outcome_key"), c.get("horizon_days"), VERSION]
        )
        out.append(rec)
    n_one = sum(1 for c in out if c.get("one_step_status") == "ONE_STEP_VALIDATION_ACCEPTED")
    n_one_test = sum(1 for c in out if c.get("one_step_heldout") == "HELDOUT_TEST_CONFIRMED")
    n_roll = sum(1 for c in out if c.get("rollout_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED")
    if n_roll > 0:
        nh = "PARTIAL_ACCEPTED" if n_roll < n_one else "TECHNICAL_NATURAL_HISTORY_ROLLOUT_ACCEPTED"
    elif any(c.get("one_step_status") == "ONE_STEP_VALIDATION_ACCEPTED" for c in out):
        nh = "ONE_STEP_ONLY_RECURSIVE_NOT_ACCEPTED"
    else:
        nh = "NOT_RUN_OR_NO_ACCEPTED_CELL"
    return {
        "version": VERSION,
        "ONE_STEP_PROVIDER_REGISTRY_STATUS": "BUILT",
        "ONE_STEP_VALIDATION_ACCEPTED_CELL_COUNT": n_one,
        "ONE_STEP_HELDOUT_CONFIRMED_CELL_COUNT": n_one_test,
        "RECURSIVE_ROLLOUT_ACCEPTED_CELL_COUNT": n_roll,
        "NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS": nh,
        "MULTI_OUTCOME_ROLLOUT_ASSEMBLY_STATUS": "MARGINAL_SOURCE_SPECIFIC_MULTI_OUTCOME_ROLLOUT",
        "MULTI_OUTCOME_DEPENDENCE_STATUS": "MARGINAL_ONLY_NO_JOINT_MODEL",
        "n_cells": len(out),
        "cells": out,
    }


def public_registry(reg: dict[str, Any]) -> dict[str, Any]:
    cells = []
    for c in reg.get("cells") or []:
        cells.append(
            {
                "source_system": c.get("source_system"),
                "outcome_key": c.get("outcome_key"),
                "horizon_days": c.get("horizon_days"),
                "one_step_status": c.get("one_step_status"),
                "one_step_heldout": c.get("one_step_heldout"),
                "active_provider": c.get("active_provider"),
                "rollout_status": c.get("rollout_status"),
                "mae_p0": c.get("mae_p0"),
                "mae_p1": c.get("mae_p1"),
                "mae_p2": c.get("mae_p2"),
                "rollout_metrics": _pub_metrics(c.get("rollout_metrics")),
                "heldout_rollout": _pub_metrics(c.get("heldout_rollout")),
                "model_identity_sha256": c.get("model_identity_sha256"),
                "feature_order_sha256": c.get("feature_order_sha256"),
                "scaler_sha256": c.get("scaler_sha256"),
                "residual_distribution_sha256": (c.get("residual_dist") or {}).get(
                    "residual_distribution_sha256"
                ),
                "cell_id_sha256": c.get("cell_id_sha256"),
            }
        )
    doc = {k: v for k, v in reg.items() if k != "cells"}
    doc["cells"] = cells
    return doc


def _pub_metrics(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if not m:
        return None
    return {
        "mae_recursive": m.get("mae_recursive"),
        "mae_teacher_forced": m.get("mae_teacher_forced"),
        "mae_persistence_recursive": m.get("mae_persistence_recursive"),
        "mae_step1": m.get("mae_step1"),
        "error_growth": m.get("error_growth"),
        "coverage": m.get("coverage"),
        "bootstrap": m.get("bootstrap"),
        "finite": m.get("finite"),
        "n_sequences": m.get("n_sequences"),
                "rollout_status": m.get("rollout_status"),
                "direction_agreement": m.get("direction_agreement"),
                "out_of_support_rate": m.get("out_of_support_rate"),
                "pooled_across_units": False,
        "teacher_forced_not_recursive_quality": True,
    }
