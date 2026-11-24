"""Immutable cell registry: source × outcome×unit × horizon × representation."""

from __future__ import annotations

from typing import Any

from human_simulator.medication_residual_v01.hashes import sha_obj
from human_simulator.medication_residual_v01.policy import VERSION


def _engine_eligible(cell: dict[str, Any], *, freeze_ok: bool, nc_ok: bool) -> bool:
    if cell.get("representation") == "R2HASH":
        return False
    if cell.get("validation_status") != "VALIDATION_ACCEPTED":
        return False
    if cell.get("heldout_status") != "HELDOUT_TEST_CONFIRMED":
        return False
    if not freeze_ok:
        return False
    if not nc_ok:
        return False
    if not cell.get("applicability_pass", True):
        return False
    if not cell.get("feature_contract_pass", True):
        return False
    return True


def build_registry(
    cells: list[dict[str, Any]],
    *,
    freeze_ok: bool,
    nc_ok: bool,
) -> dict[str, Any]:
    out = []
    for c in cells:
        rec = dict(c)
        rec["engine_eligible"] = _engine_eligible(rec, freeze_ok=freeze_ok, nc_ok=nc_ok)
        rec["cell_id_sha256"] = sha_obj(
            [
                rec.get("source_system"),
                rec.get("outcome_key"),
                rec.get("horizon_days"),
                rec.get("representation"),
                VERSION,
            ]
        )
        out.append(rec)
    n_val = sum(1 for c in out if c.get("validation_status") == "VALIDATION_ACCEPTED")
    n_held = sum(1 for c in out if c.get("heldout_status") == "HELDOUT_TEST_CONFIRMED")
    n_eng = sum(1 for c in out if c.get("engine_eligible"))
    if not out:
        foundation = "NOT_RUN_DUE_TO_FAILED_DATA_GATE"
        incremental = "NOT_RUN"
    elif n_held == 0 and n_val == 0:
        foundation = "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL"
        incremental = "NO_INCREMENTAL_SIGNAL"
    elif n_eng == 0 and n_val > 0:
        foundation = "PARTIAL_ACCEPTED"
        incremental = "VALIDATION_ONLY_NOT_ENGINE"
    elif n_eng == 0:
        foundation = "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL"
        incremental = "NO_INCREMENTAL_SIGNAL"
    elif n_eng < len(out):
        foundation = "PARTIAL_ACCEPTED"
        incremental = "PARTIAL"
    else:
        foundation = "TECHNICAL_SOURCE_RECORD_MEDICATION_RESIDUAL_ACCEPTED"
        incremental = "ACCEPTED_TECHNICAL"
    return {
        "version": VERSION,
        "CELL_LEVEL_MEDICATION_RESIDUAL_REGISTRY_STATUS": "BUILT",
        "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT": n_val,
        "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT": n_held,
        "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT": n_eng,
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": foundation,
        "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS": incremental,
        "n_cells": len(out),
        "cells": out,
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_EVALUATED",
        "CAUSAL_EFFECT_STATUS": "NOT_EVALUATED",
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
    }


def public_registry(reg: dict[str, Any]) -> dict[str, Any]:
    cells = []
    for c in reg.get("cells") or []:
        cells.append(
            {
                "source_system": c.get("source_system"),
                "outcome_key": c.get("outcome_key"),
                "horizon_days": c.get("horizon_days"),
                "representation": c.get("representation"),
                "validation_status": c.get("validation_status"),
                "heldout_status": c.get("heldout_status"),
                "engine_eligible": c.get("engine_eligible"),
                "reason": c.get("reason"),
                "authoritative": c.get("authoritative"),
                "model_identity_sha256": c.get("model_identity_sha256"),
                "feature_order_sha256": c.get("feature_order_sha256"),
                "scaler_sha256": c.get("scaler_sha256"),
                "cell_id_sha256": c.get("cell_id_sha256"),
                "metrics_validation": _public_metrics(c.get("metrics_validation")),
                "metrics_test": _public_metrics(c.get("metrics_test")),
            }
        )
    doc = {k: v for k, v in reg.items() if k != "cells"}
    doc["cells"] = cells
    return doc


def _public_metrics(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if not m:
        return None
    return {
        "n_rows": m.get("n_rows"),
        "n_subjects": m.get("n_subjects"),
        "n_unique_targets": m.get("n_unique_targets"),
        "mae_r0": m.get("mae_r0"),
        "mae_r1": m.get("mae_r1"),
        "mae_r2": m.get("mae_r2"),
        "rmse_r1": m.get("rmse_r1"),
        "rmse_r2": m.get("rmse_r2"),
        "mae_improvement_r1_minus_r2": m.get("mae_improvement_r1_minus_r2"),
        "bootstrap": m.get("bootstrap"),
        "permutation": m.get("permutation"),
        "folds": m.get("folds"),
        "finite": m.get("finite"),
        "validation_gate_pass": m.get("validation_gate_pass"),
        "pooled_across_units": False,
    }
