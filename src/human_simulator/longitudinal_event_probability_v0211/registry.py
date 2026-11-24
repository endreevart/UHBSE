"""Cell-level acceptance registry — independent statuses, no transferred count of 9."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v0211.estimators import feature_order_hash
from human_simulator.longitudinal_event_probability_v0211.policy import (
    FEATURE_ORDER,
    MODELS_DIR,
    VERSION,
    cell_id_sha256,
)


def _cell_dict_key(source: str, endpoint: str, outcome: str | None, horizon: int) -> str:
    o = outcome if outcome is not None else "null"
    return f"{source}|{endpoint}|{o}|{int(horizon)}"


def build_registry(
    root: Path,
    results: list[dict[str, Any]],
    *,
    primary_endpoint: str,
    ood_integrity: str = "UNKNOWN",
    freeze_ok: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    cells: dict[str, Any] = {}
    val_accepted = 0
    held_confirmed = 0
    engine_eligible = 0
    rejected = 0
    not_run = 0
    a_val = 0
    b_val = 0
    trained = 0
    frozen = 0
    for res in results:
        if res.get("model"):
            trained += 1
        if res.get("frozen_file"):
            frozen += 1
        src = res.get("source_system")
        endpoint = res.get("endpoint")
        outcome = res.get("outcome_key")
        if res.get("status") in {
            "NOT_RUN_DUE_TO_FAILED_DATA_GATE",
            "NOT_RUN_MISSING_DATASET",
            "NOT_RUN",
        }:
            not_run += 1
            cells[_cell_dict_key(src or "null", endpoint or "null", outcome, 0)] = {
                "source_system": src,
                "endpoint": endpoint,
                "outcome_key": outcome,
                "horizon_days": None,
                "evaluation_status": res.get("status"),
                "validation_gate_status": "NOT_RUN",
                "horizon_identifiability_status": "NOT_RUN",
                "calibration_evaluation_status": "NOT_RUN",
                "heldout_test_status": "NOT_OPENED",
                "engine_eligible": False,
                "rejection_reasons": [res.get("reason") or res.get("status")],
            }
            continue
        for c in res.get("cells") or []:
            h = int(c["horizon_days"])
            key = _cell_dict_key(src, endpoint, outcome, h)
            val_pass = c.get("validation_gate_status") == "PASS"
            held = c.get("heldout_test_status") or "NOT_OPENED"
            ident = c.get("horizon_identifiability_status")
            cal_eval = c.get("calibration_evaluation_status")
            eligible = bool(c.get("engine_eligible")) and freeze_ok and ood_integrity == "PASS"
            if val_pass:
                val_accepted += 1
                if src == "magerya_api":
                    a_val += 1
                elif src == "kgz_raw":
                    b_val += 1
            elif str(c.get("evaluation_status") or "").startswith("NOT_RUN"):
                not_run += 1
            else:
                rejected += 1
            if held == "HELDOUT_TEST_CONFIRMED":
                held_confirmed += 1
            if eligible:
                engine_eligible += 1
            cal = ((res.get("model") or {}).get("calibrators") or {}).get(str(h)) or {}
            cal_hash = hashlib.sha256(
                json.dumps(cal, separators=(",", ":"), sort_keys=True).encode()
            ).hexdigest()
            cells[key] = {
                "source_system": src,
                "endpoint": endpoint,
                "outcome_key": outcome,
                "horizon_days": h,
                "evaluation_status": c.get("evaluation_status"),
                "validation_gate_status": c.get("validation_gate_status"),
                "horizon_identifiability_status": ident,
                "calibration_evaluation_status": cal_eval,
                "calibrator_fit_status": c.get("calibrator_fit_status"),
                "heldout_test_status": held,
                "engine_eligible": eligible,
                "rejection_reasons": c.get("rejection_reasons") or [],
                "validation_gates": c.get("gates"),
                "test_gates": c.get("test_gates"),
                "model_file": res.get("frozen_file"),
                "model_file_sha256": res.get("file_sha256"),
                "model_identity_sha256": res.get("model_identity_sha256"),
                "cell_id_sha256": res.get("cell_id_sha256")
                or cell_id_sha256(src, endpoint, outcome),
                "calibrator": cal,
                "calibrator_sha256": cal_hash,
                "feature_order_sha256": res.get("feature_order_sha256")
                or feature_order_hash(FEATURE_ORDER),
                "scaler_sha256": res.get("scaler_sha256"),
                "censoring_model_sha256": res.get("censoring_model_sha256"),
                "non_claim_level": "technical_probability_cell_only",
                "not_transferred_v021_count_of_nine": True,
            }

    a_primary = [
        c
        for c in cells.values()
        if c.get("source_system") == "magerya_api"
        and c.get("endpoint") == primary_endpoint
        and c.get("validation_gate_status") == "PASS"
        and c.get("horizon_identifiability_status") == "PASS"
    ]
    b_primary = [
        c
        for c in cells.values()
        if c.get("source_system") == "kgz_raw"
        and c.get("endpoint") == primary_endpoint
        and c.get("validation_gate_status") == "PASS"
        and c.get("horizon_identifiability_status") == "PASS"
    ]
    shared = set(c["horizon_days"] for c in a_primary if c.get("horizon_days") is not None) & set(
        c["horizon_days"] for c in b_primary if c.get("horizon_days") is not None
    )
    coverage_gate = {
        "rule": (
            "both_sources_share_primary_endpoint_and_honestly_identifiable_horizon"
        ),
        "primary_endpoint": primary_endpoint,
        "source_a_primary_validation_accepted_horizons": sorted(
            {c["horizon_days"] for c in a_primary if c.get("horizon_days") is not None}
        ),
        "source_b_primary_validation_accepted_horizons": sorted(
            {c["horizon_days"] for c in b_primary if c.get("horizon_days") is not None}
        ),
        "shared_horizons": sorted(shared),
        "passed": bool(shared),
        "not_forced": True,
    }
    if coverage_gate["passed"] and val_accepted > 0:
        global_status = "ACCEPTED"
    elif val_accepted > 0:
        global_status = "PARTIAL_ACCEPTED"
    else:
        global_status = "EVALUATED_NOT_ACCEPTED"

    doc = {
        "version": VERSION,
        "CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS": "BUILT",
        "global_status": global_status,
        "coverage_gate": coverage_gate,
        "VALIDATION_ACCEPTED_CELL_COUNT": val_accepted,
        "HELDOUT_TEST_CONFIRMED_CELL_COUNT": held_confirmed,
        "ENGINE_ELIGIBLE_CELL_COUNT": engine_eligible,
        "SOURCE_A_VALIDATION_ACCEPTED_CELL_COUNT": a_val,
        "SOURCE_B_VALIDATION_ACCEPTED_CELL_COUNT": b_val,
        "rejected_cell_count": rejected,
        "not_run_count": not_run,
        "trained_model_count": trained,
        "frozen_model_count": frozen,
        "unexplained": 0,
        "v021_accepted_count_not_transferred": True,
        "one_b_observation_cell_is_not_a_plus_b_foundation": True,
        "ood_integrity": ood_integrity,
        "freeze_ok": freeze_ok,
        "cells": cells,
    }
    path = root / MODELS_DIR / "accepted-probability-registry.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def load_registry(root: Path) -> dict[str, Any]:
    path = root / MODELS_DIR / "accepted-probability-registry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def lookup_cell(
    registry: dict[str, Any],
    source_system: str,
    endpoint: str,
    outcome_key: str | None,
    horizon_days: int,
) -> dict[str, Any] | None:
    key = _cell_dict_key(source_system, endpoint, outcome_key, int(horizon_days))
    return (registry.get("cells") or {}).get(key)
