"""Immutable cell-level accepted probability registry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v021.estimators import feature_order_hash
from human_simulator.longitudinal_event_probability_v021.policy import (
    FEATURE_ORDER,
    MODELS_DIR,
    VERSION,
    cell_id_sha256,
    cell_key,
)


def _cell_dict_key(source: str, endpoint: str, outcome: str | None, horizon: int) -> str:
    o = outcome if outcome is not None else "null"
    return f"{source}|{endpoint}|{o}|{int(horizon)}"


def build_registry(
    root: Path,
    results: list[dict[str, Any]],
    *,
    primary_endpoint: str,
) -> dict[str, Any]:
    root = Path(root).resolve()
    (root / MODELS_DIR).mkdir(parents=True, exist_ok=True)
    cells: dict[str, Any] = {}
    accepted = 0
    rejected = 0
    not_run = 0
    a_acc = 0
    b_acc = 0
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
        if res.get("status") in {"NOT_RUN_DUE_TO_FAILED_DATA_GATE", "NOT_RUN_MISSING_DATASET", "NOT_RUN"}:
            not_run += 1
            cells[_cell_dict_key(src, endpoint, outcome, 0)] = {
                "source_system": src,
                "endpoint": endpoint,
                "outcome_key": outcome,
                "horizon_days": None,
                "evaluation_status": res.get("status"),
                "acceptance_status": "NOT_RUN",
                "reason": res.get("status"),
            }
            continue
        for c in res.get("cells") or []:
            h = int(c["horizon_days"])
            key = _cell_dict_key(src, endpoint, outcome, h)
            acc = c.get("acceptance_status") == "ACCEPTED"
            if acc:
                accepted += 1
                if src == "magerya_api":
                    a_acc += 1
                elif src == "kgz_raw":
                    b_acc += 1
            elif c.get("evaluation_status", "").startswith("NOT_RUN"):
                not_run += 1
            else:
                rejected += 1
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
                "acceptance_status": "ACCEPTED" if acc else c.get("acceptance_status"),
                "validation_gates": c.get("gates"),
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
                "supported_horizon": acc,
                "non_claim_level": "technical_probability_cell_only",
            }

    a_primary = [
        c
        for c in cells.values()
        if c.get("source_system") == "magerya_api"
        and c.get("endpoint") == primary_endpoint
        and c.get("acceptance_status") == "ACCEPTED"
    ]
    b_primary = [
        c
        for c in cells.values()
        if c.get("source_system") == "kgz_raw"
        and c.get("endpoint") == primary_endpoint
        and c.get("acceptance_status") == "ACCEPTED"
    ]
    shared = set(c["horizon_days"] for c in a_primary if c.get("horizon_days") is not None) & set(
        c["horizon_days"] for c in b_primary if c.get("horizon_days") is not None
    )
    coverage_gate = {
        "rule": "both_sources_primary_endpoint_share_at_least_one_accepted_horizon",
        "primary_endpoint": primary_endpoint,
        "source_a_primary_accepted_horizons": sorted(
            {c["horizon_days"] for c in a_primary if c.get("horizon_days") is not None}
        ),
        "source_b_primary_accepted_horizons": sorted(
            {c["horizon_days"] for c in b_primary if c.get("horizon_days") is not None}
        ),
        "shared_horizons": sorted(shared),
        "passed": bool(shared),
    }
    if coverage_gate["passed"]:
        global_status = "ACCEPTED"
    elif accepted > 0:
        global_status = "PARTIAL_ACCEPTED"
    else:
        global_status = "EVALUATED_NOT_ACCEPTED"

    unexplained = 0
    doc = {
        "version": VERSION,
        "CELL_LEVEL_ACCEPTANCE_REGISTRY_STATUS": "BUILT",
        "global_status": global_status,
        "coverage_gate": coverage_gate,
        "ACCEPTED_PROBABILITY_CELL_COUNT": accepted,
        "SOURCE_A_ACCEPTED_PROBABILITY_CELL_COUNT": a_acc,
        "SOURCE_B_ACCEPTED_PROBABILITY_CELL_COUNT": b_acc,
        "rejected_cell_count": rejected,
        "not_run_count": not_run,
        "trained_model_count": trained,
        "frozen_model_count": frozen,
        "unexplained": unexplained,
        "one_b_observation_cell_is_not_a_plus_b_foundation": True,
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
