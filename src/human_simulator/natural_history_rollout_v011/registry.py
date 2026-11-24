"""Cell registry and public projection."""

from __future__ import annotations

from typing import Any

from human_simulator.natural_history_rollout_v011.policy import VERSION


def build_registry(cells: list[dict[str, Any]]) -> dict[str, Any]:
    out = []
    for c in cells:
        rec = {
            k: v
            for k, v in c.items()
            if k
            not in {
                "p1_payload",
                "residual_blocks",
                "active_identity_body",
                "features",
            }
        }
        out.append(rec)
    n_sel = sum(
        1
        for c in out
        if c.get("one_step_status")
        in {"VALIDATION_BASELINE_SUPPORTED_P0", "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED"}
    )
    n_base = sum(1 for c in out if c.get("one_step_status") == "VALIDATION_BASELINE_SUPPORTED_P0")
    n_inc = sum(1 for c in out if c.get("one_step_status") == "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED")
    n_hold_eval = sum(1 for c in out if c.get("one_step_heldout") in {"HELDOUT_TEST_CONFIRMED", "HELDOUT_TEST_NOT_CONFIRMED"})
    n_hold_ok = sum(1 for c in out if c.get("one_step_heldout") == "HELDOUT_TEST_CONFIRMED")
    n_rec_val = sum(1 for c in out if c.get("recursive_validation_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED")
    n_rec_hold = sum(1 for c in out if c.get("recursive_heldout_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED")
    if n_rec_val > 0:
        nh = "PARTIAL_ACCEPTED_WITH_EXPLICIT_CELL_REGISTRY"
    elif n_sel > 0:
        nh = "ONE_STEP_ONLY_RECURSIVE_NOT_ACCEPTED"
    else:
        nh = "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
    val_sel = {
        (c["source_system"], c["outcome_key"], c["horizon_days"])
        for c in out
        if c.get("one_step_status")
        in {"VALIDATION_BASELINE_SUPPORTED_P0", "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED"}
    }
    hold_ok = {
        (c["source_system"], c["outcome_key"], c["horizon_days"])
        for c in out
        if c.get("one_step_heldout") == "HELDOUT_TEST_CONFIRMED"
    }
    return {
        "version": VERSION,
        "ONE_STEP_PROVIDER_REGISTRY_STATUS": "BUILT",
        "ONE_STEP_VALIDATION_SELECTED_CELL_COUNT": n_sel,
        "ONE_STEP_VALIDATION_BASELINE_SUPPORTED_CELL_COUNT": n_base,
        "ONE_STEP_VALIDATION_INCREMENTAL_ACCEPTED_CELL_COUNT": n_inc,
        "ONE_STEP_HELDOUT_EVALUABLE_CELL_COUNT": n_hold_eval,
        "ONE_STEP_HELDOUT_CONFIRMED_CELL_COUNT": n_hold_ok,
        "ONE_STEP_VALIDATION_HELDOUT_INTERSECTION_COUNT": len(val_sel & hold_ok),
        "RECURSIVE_ROLLOUT_VALIDATION_ACCEPTED_CELL_COUNT": n_rec_val,
        "RECURSIVE_ROLLOUT_HELDOUT_CONFIRMED_CELL_COUNT": n_rec_hold,
        "NATURAL_HISTORY_STOCHASTIC_ROLLOUT_STATUS": nh,
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
                "mae_p0": c.get("mae_p0"),
                "mae_p1": c.get("mae_p1"),
                "mae_p2": c.get("mae_p2"),
                "direct_metrics": _pub_metrics(c.get("direct_metrics")),
                "heldout_metrics": _pub_metrics(c.get("heldout_metrics")),
                "recursive_validation_status": c.get("recursive_validation_status"),
                "recursive_heldout_status": c.get("recursive_heldout_status"),
                "active_payload_sha256": c.get("active_payload_sha256"),
                "feature_order_sha256": c.get("feature_order_sha256"),
                "residual_distribution_sha256": (c.get("residual_dist") or {}).get(
                    "residual_distribution_sha256"
                ),
            }
        )
    doc = {k: v for k, v in reg.items() if k != "cells"}
    doc["cells"] = cells
    return doc


def _pub_metrics(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if not m:
        return None
    return {
        "mae_direct": m.get("mae_direct"),
        "mae_p0": m.get("mae_p0"),
        "mae_recursive": m.get("mae_recursive"),
        "coverage": m.get("coverage"),
        "bootstrap": m.get("bootstrap"),
        "finite": m.get("finite"),
        "n_targets": m.get("n_targets"),
        "n_subjects": m.get("n_subjects"),
        "n_overlap_groups": m.get("n_overlap_groups"),
        "mean_crps": m.get("mean_crps"),
        "recursive_status": m.get("recursive_status"),
        "direct_endpoint_offset": m.get("direct_endpoint_offset"),
        "recursive_endpoint_offset": m.get("recursive_endpoint_offset"),
        "pooled_across_units": False,
        "teacher_forced_not_used_for_acceptance": True,
        "stochastic": m.get("stochastic"),
    }
