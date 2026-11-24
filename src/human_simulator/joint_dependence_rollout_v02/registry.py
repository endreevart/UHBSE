"""Registry projection."""

from __future__ import annotations

from typing import Any

from human_simulator.joint_dependence_rollout_v02.policy import VERSION


def build_registry(cells: list[dict[str, Any]], joint_routes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out = []
    for c in cells:
        rec = {
            k: v
            for k, v in c.items()
            if k not in {"p1_payload", "residual_blocks", "active_identity_body", "features"}
        }
        out.append(rec)
    n_sel = sum(1 for c in out if c.get("validation_selected"))
    n_gate = sum(1 for c in out if c.get("validation_gate_accepted"))
    n_base = sum(1 for c in out if c.get("one_step_status") == "BASELINE_SUPPORTED_P0")
    n_hold = sum(1 for c in out if c.get("corrective_heldout") == "CORRECTIVE_HELDOUT_CONFIRMED")
    n_rec_val = sum(1 for c in out if c.get("recursive_validation_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED")
    n_rec_hold = sum(1 for c in out if c.get("recursive_heldout_status") == "STOCHASTIC_ROLLOUT_CELL_ACCEPTED")
    j_acc = sum(1 for r in (joint_routes or []) if r.get("status") == "JOINT_DEPENDENCE_CELL_ACCEPTED")
    j_hold = sum(1 for r in (joint_routes or []) if r.get("heldout_status") == "JOINT_DEPENDENCE_CELL_ACCEPTED")
    if j_acc > 0:
        found = "PARTIAL_ACCEPTED_WITH_EXPLICIT_CELL_REGISTRY"
    elif n_gate > 0:
        found = "MARGINAL_CORRECTED_JOINT_NOT_ACCEPTED"
    else:
        found = "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
    return {
        "version": VERSION,
        "CORRECTED_MARGINAL_PROVIDER_REGISTRY_STATUS": "BUILT",
        "MARGINAL_VALIDATION_SELECTED_CELL_COUNT": n_sel,
        "MARGINAL_VALIDATION_GATE_ACCEPTED_CELL_COUNT": n_gate,
        "MARGINAL_BASELINE_SUPPORTED_CELL_COUNT": n_base,
        "MARGINAL_CORRECTIVE_HELDOUT_CONFIRMED_CELL_COUNT": n_hold,
        "RECURSIVE_VALIDATION_ACCEPTED_CELL_COUNT": n_rec_val,
        "RECURSIVE_CORRECTIVE_HELDOUT_CONFIRMED_CELL_COUNT": n_rec_hold,
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": j_acc,
        "JOINT_CORRECTIVE_HELDOUT_CONFIRMED_ROUTE_COUNT": j_hold,
        "JOINT_DEPENDENCE_FOUNDATION_STATUS": found
        if j_acc == 0
        else "PARTIAL_ACCEPTED_WITH_EXPLICIT_CELL_REGISTRY",
        "n_cells": len(out),
        "cells": out,
        "joint_routes": joint_routes or [],
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
                "validation_selected": c.get("validation_selected"),
                "validation_gate_accepted": c.get("validation_gate_accepted"),
                "corrective_heldout": c.get("corrective_heldout"),
                "active_provider": c.get("active_provider"),
                "mae_p0": c.get("mae_p0"),
                "mae_p1": c.get("mae_p1"),
                "recursive_validation_status": c.get("recursive_validation_status"),
                "recursive_heldout_status": c.get("recursive_heldout_status"),
                "active_payload_sha256": c.get("active_payload_sha256"),
                "direct_metrics": _pub_metrics(c.get("direct_metrics")),
                "heldout_metrics": _pub_metrics(c.get("heldout_metrics")),
            }
        )
    doc = {k: v for k, v in reg.items() if k != "cells"}
    doc["cells"] = cells
    routes = []
    for r in reg.get("joint_routes") or []:
        routes.append({k: v for k, v in r.items() if k not in {"chol", "ecdf", "corr_raw"}})
    doc["joint_routes"] = routes
    return doc


def _pub_metrics(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if not m:
        return None
    return {
        "mae_direct": m.get("mae_direct"),
        "mae_p0": m.get("mae_p0"),
        "mae_recursive": m.get("mae_recursive"),
        "coverage": m.get("coverage"),
        "empirical_path_coverage": m.get("empirical_path_coverage"),
        "recursive_empirical_path_coverage": m.get("recursive_empirical_path_coverage"),
        "mean_crps": m.get("mean_crps"),
        "mean_crps_recursive": m.get("mean_crps_recursive"),
        "bootstrap": m.get("bootstrap"),
        "recursive_bootstrap": m.get("recursive_bootstrap"),
        "finite": m.get("finite"),
        "n_targets": m.get("n_targets"),
        "n_subjects": m.get("n_subjects"),
        "n_overlap_groups": m.get("n_overlap_groups"),
        "recursive_status": m.get("recursive_status"),
        "path_summary": "path_median",
        "teacher_forced_not_used_for_acceptance": True,
    }
