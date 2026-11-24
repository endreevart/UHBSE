"""Strict frozen provider loader. Namespaces SYNTHETIC_FIXTURE / SOURCE_A / SOURCE_B."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v015.hashes import (
    feature_order_sha256,
    nhr_identity_sha,
    scaler_sha256,
    sha256_file,
    sha_obj,
)
from human_simulator.integrated_research_runtime_v015.policy import (
    FROZEN_A_H90,
    FROZEN_B_P0_H90,
    NHR_MODELS,
    NS_A,
    NS_B,
    NS_SYN,
    SOURCE_A,
    SOURCE_B,
    VERSION,
    outcome_unit,
)
from human_simulator.natural_history_rollout_v011.residuals import sample_residual


ELIGIBLE_TIERS = {
    "VALIDATION_BASELINE_SUPPORTED_P0",
    "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED",
}


class LoaderAbstain(Exception):
    def __init__(self, reason: str, **extra: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.extra = extra


def _fail(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "FAIL", "reason": reason, **extra}


def _abstain(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "ABSTAIN", "reason": reason, **extra}


def namespace_for_source(source_system: str) -> str | None:
    if source_system == "synthetic":
        return NS_SYN
    if source_system == SOURCE_A:
        return NS_A
    if source_system == SOURCE_B:
        return NS_B
    return None


def _cells_path(root: Path) -> Path:
    return Path(root) / NHR_MODELS / "pre-test-cells.json"


def _payload_path(root: Path, ident: str) -> Path:
    return Path(root) / NHR_MODELS / f"frozen-payload-{ident[:16]}.json"


def load_nhr_catalog(root: Path) -> list[dict[str, Any]]:
    path = _cells_path(root)
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return list(doc.get("cells") or [])


def _post_test_blocks(root: Path, ident: str) -> tuple[dict[str, list[float]] | None, str | None]:
    path = Path(root) / NHR_MODELS / "post-test-cells.json"
    if not path.is_file():
        return None, "POST_TEST_CELLS_ABSENT"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for c in doc.get("cells") or []:
        if c.get("active_payload_sha256") != ident:
            continue
        blocks = c.get("residual_blocks")
        if not isinstance(blocks, dict) or not blocks:
            return None, "RESIDUAL_BLOCKS_EMPTY"
        return {str(k): [float(x) for x in v] for k, v in blocks.items()}, None
    return None, "RESIDUAL_BLOCKS_CELL_NOT_FOUND"


def _verify_residual_sha(blocks: dict[str, list[float]], expected: str, contract: str) -> bool:
    resid = [x for xs in blocks.values() for x in xs]
    digest = sha_obj(
        {
            "sorted": [round(x, 6) for x in sorted(resid)],
            "n_blocks": len(blocks),
            "contract": contract,
        }
    )
    return digest == expected


def load_frozen_cell(
    root: Path,
    *,
    source_system: str,
    outcome_key: str,
    horizon_days: int,
) -> dict[str, Any]:
    ns = namespace_for_source(source_system)
    if ns == NS_SYN:
        return _abstain("SYNTHETIC_NAMESPACE_HAS_NO_FROZEN_NHR_CELL")
    if ns is None:
        return _fail("UNKNOWN_SOURCE_SYSTEM")
    catalog = load_nhr_catalog(root)
    if not catalog:
        return _abstain("FROZEN_NHR_CATALOG_UNAVAILABLE")
    matches = [
        c
        for c in catalog
        if c.get("source_system") == source_system
        and c.get("outcome_key") == outcome_key
        and int(c.get("horizon_days") or 0) == int(horizon_days)
    ]
    if not matches:
        return _abstain(
            "NO_FROZEN_CELL",
            source_system=source_system,
            outcome_key=outcome_key,
            requested_horizon_days=horizon_days,
        )
    cell = matches[0]
    tier = cell.get("one_step_status")
    if tier not in ELIGIBLE_TIERS:
        return _abstain("CELL_NOT_INFERENCE_ELIGIBLE", one_step_status=tier)
    ident = cell.get("active_payload_sha256")
    if not ident:
        return _fail("MISSING_ACTIVE_PAYLOAD_IDENTITY")
    ppath = _payload_path(root, ident)
    if not ppath.is_file():
        return _abstain("FROZEN_PAYLOAD_FILE_UNAVAILABLE", payload_file=ppath.name)
    raw = ppath.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    body = payload.get("active_identity") or {}
    recomputed = nhr_identity_sha(body)
    if recomputed != ident:
        return _fail("PAYLOAD_IDENTITY_RECOMPUTE_MISMATCH", expected=ident, recomputed=recomputed)
    provider = payload.get("active_provider") or body.get("active_provider")
    if provider not in {"P0", "P1", "P2"}:
        return _fail("UNKNOWN_PROVIDER_NO_P0_FALLBACK", active_provider=provider)
    if provider == "P1" and not payload.get("p1_payload"):
        return _fail("P1_PAYLOAD_MISSING")
    if provider == "P2":
        return _abstain("P2_PAYLOAD_NOT_EXECUTED_IN_THIS_RUNTIME")
    if body.get("source_system") != source_system:
        return _fail("PAYLOAD_SOURCE_MISMATCH")
    if body.get("outcome_key") != outcome_key:
        return _fail("PAYLOAD_OUTCOME_MISMATCH")
    if int(body.get("horizon_days") or -1) != int(horizon_days):
        return _fail("PAYLOAD_HORIZON_MISMATCH")
    unit = outcome_unit(outcome_key)
    if body.get("unit") not in {None, unit} and body.get("unit") != unit:
        return _fail("PAYLOAD_UNIT_MISMATCH", payload_unit=body.get("unit"), outcome_unit=unit)
    fo = list(body.get("feature_order") or [])
    if not fo:
        return _fail("PAYLOAD_FEATURE_ORDER_MISSING")
    fo_hash = feature_order_sha256(fo)
    registry_fo = cell.get("feature_order_sha256")
    registry_fo_consistent = registry_fo == fo_hash
    p1_payload = payload.get("p1_payload") if provider == "P1" else None
    sc_hash = scaler_sha256(p1_payload, provider=provider)
    dist = payload.get("residual_dist") or {}
    resid_sha = dist.get("residual_distribution_sha256") or body.get("residual_distribution_sha256")
    if not resid_sha:
        return _abstain("RESIDUAL_IDENTITY_MISSING")
    contract = dist.get("sampling_contract") or body.get("residual_sampling_contract") or ""
    blocks, blocks_err = _post_test_blocks(root, ident)
    if blocks is None:
        return _abstain("RESIDUAL_BLOCKS_UNAVAILABLE", detail=blocks_err)
    if not _verify_residual_sha(blocks, str(resid_sha), str(contract)):
        return _fail("RESIDUAL_HASH_MISMATCH")
    runtime_cell = {
        "status": "OK",
        "namespace": ns,
        "source_system": source_system,
        "outcome_key": outcome_key,
        "unit": unit,
        "horizon_days": int(horizon_days),
        "active_provider": provider,
        "active_payload_sha256": ident,
        "feature_order": fo,
        "feature_order_sha256": fo_hash,
        "registry_feature_order_sha256": registry_fo,
        "registry_feature_order_consistent": registry_fo_consistent,
        "registry_feature_order_note": None
        if registry_fo_consistent
        else "REGISTRY_FEATURE_ORDER_SHA256_IS_GLOBAL_P1_NOT_PAYLOAD",
        "scaler_sha256": sc_hash,
        "residual_distribution_sha256": resid_sha,
        "residual_sampling_contract": contract,
        "scale_contract": "NATIVE_UNIT_NO_TRANSFORM",
        "p1_payload": p1_payload,
        "residual_dist": {k: v for k, v in dist.items() if k != "blocks"},
        "residual_blocks": blocks,
        "one_step_status": tier,
        "evidence_tier": tier,
        "inference_eligible": True,
        "payload_file_sha256": sha256_file(ppath),
        "synthetic_fixture": False,
    }
    return runtime_cell


def public_cell_record(cell: dict[str, Any]) -> dict[str, Any]:
    drop = {"residual_blocks", "p1_payload", "residual_dist"}
    return {k: v for k, v in cell.items() if k not in drop}


def sample_verified_residual(cell: dict[str, Any], rng) -> float:
    return float(sample_residual(cell, rng))


def default_frozen_targets() -> dict[str, Any]:
    return {
        "source_a_horizon_90": {
            "source_system": SOURCE_A,
            "namespace": NS_A,
            "horizon_days": 90,
            "outcome_keys": list(FROZEN_A_H90),
        },
        "source_b_horizon_90": {
            "source_system": SOURCE_B,
            "namespace": NS_B,
            "horizon_days": 90,
            "outcome_keys": [FROZEN_B_P0_H90],
        },
    }


def build_frozen_bundle(root: Path, source_system: str, outcome_keys: list[str], horizon_days: int) -> dict[str, Any]:
    ns = namespace_for_source(source_system)
    cells: dict[str, Any] = {}
    notes = []
    for ok in outcome_keys:
        rec = load_frozen_cell(root, source_system=source_system, outcome_key=ok, horizon_days=horizon_days)
        if rec.get("status") != "OK":
            return rec
        cells[ok] = rec
        if rec.get("registry_feature_order_note"):
            notes.append({"outcome_key": ok, "note": rec["registry_feature_order_note"]})
    return {
        "status": "OK",
        "namespace": ns,
        "source_system": source_system,
        "horizon_days": horizon_days,
        "outcomes": list(outcome_keys),
        "cells": cells,
        "synthetic_fixture": False,
        "JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT": 0,
        "scale_contract": "NATIVE_UNIT_NO_TRANSFORM",
        "registry_notes": notes,
        "family": "D0_INDEPENDENT_NATIVE_MARGINAL_RESIDUALS",
    }
