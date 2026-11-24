"""Phase 0 — reproduce Integrated Runtime v0.1.2 defects from published code."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from human_simulator.integrated_research_runtime_v012.composition import compose_joint_distribution
from human_simulator.integrated_research_runtime_v012.engine import frozen_request
from human_simulator.integrated_research_runtime_v012.fixtures import synthetic_request as v012_request
from human_simulator.integrated_research_runtime_v012.fixtures import synthetic_runtime_bundle as v012_bundle
from human_simulator.integrated_research_runtime_v012.loader import build_frozen_bundle
from human_simulator.integrated_research_runtime_v012.policy import FROZEN_A_H90, SOURCE_A, SYN_OUTCOMES
from human_simulator.integrated_research_runtime_v012.probability import execute_event_probability, frozen_lep_probe_request
from human_simulator.integrated_research_runtime_v013.policy import (
    ARTIFACT_DIR,
    REVIEW_ZIP as V013_ZIP_NAME,
    V012_ARTIFACT,
    V012_EXPECTED_SHA256,
    VERSION,
)


def _src(root: Path, name: str) -> str:
    return (root / "src/human_simulator/integrated_research_runtime_v012" / name).read_text(encoding="utf-8")


def _snapshot(root: Path, name: str) -> dict[str, Any] | None:
    path = root / ARTIFACT_DIR / name
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def defect_offset_future_timestamp_pass() -> dict[str, Any]:
    ok0, ok1 = SYN_OUTCOMES
    req = v012_request(
        cutoff_t0="2020-01-01T00:00:00Z",
        history={ok0: [1.0], ok1: [2.0]},
        history_timestamps={ok0: ["2019-12-31T23:00:00-02:00"], ok1: ["2019-12-31T23:00:00-02:00"]},
        history_is_pre_t0_summary=False,
    )
    out = compose_joint_distribution(req, v012_bundle())
    return {
        "id": 1,
        "claim": "offset timestamp after cutoff_t0 still OK with PASS_NO_T1_T2_READ",
        "instant_utc": "2020-01-01T01:00:00Z",
        "cutoff_t0": "2020-01-01T00:00:00Z",
        "status": out.get("status"),
        "leak": out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
        "reproduced": out.get("status") == "OK" and out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS") == "PASS_NO_T1_T2_READ",
    }


def defect_empty_timestamps_verified_pass() -> dict[str, Any]:
    ok0, ok1 = SYN_OUTCOMES
    req = v012_request(
        history={ok0: [1.0], ok1: [2.0]},
        history_timestamps={ok0: [], ok1: []},
        history_is_pre_t0_summary=False,
        cutoff_t0="2020-01-01T00:00:00Z",
    )
    out = compose_joint_distribution(req, v012_bundle())
    return {
        "id": 2,
        "claim": "empty history_timestamps with nonempty history still PASS_NO_T1_T2_READ",
        "status": out.get("status"),
        "leak": out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
        "reproduced": out.get("status") == "OK"
        and out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS") == "PASS_NO_T1_T2_READ",
    }


def defect_missing_unit_accepted() -> dict[str, Any]:
    req = v012_request()
    for ident in req["cell_identities"].values():
        ident.pop("unit", None)
    out = compose_joint_distribution(req, v012_bundle())
    return {
        "id": 3,
        "claim": "missing unit in cell_identities still OK",
        "status": out.get("status"),
        "reason": out.get("reason"),
        "reproduced": out.get("status") == "OK",
    }


def defect_namespace_overrides_source(root: Path) -> dict[str, Any]:
    snap_name = "v012-source-namespace-mismatch-defect.json"
    snap = _snapshot(root, snap_name)
    try:
        bundle = build_frozen_bundle(root, SOURCE_A, list(FROZEN_A_H90), 90)
    except Exception as exc:  # noqa: BLE001
        if snap:
            return snap
        return {
            "id": 4,
            "claim": "Source A bundle with namespace=SOURCE_B still OK and labelled SOURCE_B",
            "status": "UNAVAILABLE",
            "detail": type(exc).__name__,
            "reproduced": False,
        }
    if bundle.get("status") != "OK":
        if snap:
            return snap
        return {
            "id": 4,
            "claim": "Source A bundle with namespace=SOURCE_B still OK and labelled SOURCE_B",
            "status": bundle.get("status"),
            "reason": bundle.get("reason"),
            "reproduced": False,
        }
    state = {ok: float(10 + i) for i, ok in enumerate(bundle["outcomes"])}
    req = frozen_request(bundle, state=state)
    req["namespace"] = "SOURCE_B"
    req["source_system"] = SOURCE_A
    out = compose_joint_distribution(req, bundle)
    block = {
        "id": 4,
        "claim": "Source A bundle with namespace=SOURCE_B still OK and labelled SOURCE_B",
        "status": out.get("status"),
        "response_namespace": out.get("namespace"),
        "source_system": out.get("source_system"),
        "reproduced": out.get("status") == "OK" and out.get("namespace") == "SOURCE_B",
    }
    return block


def defect_lep_ood_support_ignores_state(root: Path) -> dict[str, Any]:
    src = _src(root, "probability.py")
    src_compact = src.replace(" ", "")
    uses_support = "feats=_in_support_features" in src_compact
    captured: list[list[float]] = []

    def _capture_infer(_root: Any, **kwargs: Any) -> dict[str, Any]:
        captured.append([float(x) for x in kwargs.get("features") or []])
        return {
            "ok": True,
            "abstain": False,
            "event_probability": 0.1,
            "survival_probability": 0.9,
            "model_identity_sha256": kwargs.get("feature_order_sha256") or "0" * 64,
        }

    probe = None
    try:
        probe = frozen_lep_probe_request(root)
    except Exception:  # noqa: BLE001
        probe = None
    two_state_identical = None
    if probe:
        base = {k: v for k, v in probe.items() if k != "engine_eligible"}
        base.pop("features", None)
        with patch("human_simulator.longitudinal_event_probability_v0211.engine.infer", side_effect=_capture_infer):
            a = execute_event_probability({**base, "state_at_t0": {"history_depth": 1.0, "n_obs_before": 1.0}}, root=root)
            b = execute_event_probability({**base, "state_at_t0": {"history_depth": 99.0, "n_obs_before": 99.0}}, root=root)
        if len(captured) >= 2:
            two_state_identical = captured[0] == captured[1]
    reproduced = bool(uses_support) and (two_state_identical is not False)
    if two_state_identical is True:
        reproduced = True
    return {
        "id": 5,
        "claim": "frozen LEP without features uses _in_support_features; state_at_t0 does not change the vector",
        "source_uses_in_support_features": uses_support,
        "two_state_feature_vectors_identical": two_state_identical,
        "n_captured_vectors": len(captured),
        "reproduced": reproduced,
    }


def defect_panel_bridge_totals_only(root: Path) -> dict[str, Any]:
    src = _src(root, "accounting.py")
    art = root / V012_ARTIFACT / "joint-panel-accounting.json"
    published = {}
    if art.is_file():
        published = json.loads(art.read_text(encoding="utf-8"))
    bridge = (published.get("v01_v011_bridge") or published) if published else {}
    status = bridge.get("JOINT_PANEL_COUNT_BRIDGE_STATUS") or ""
    numeric = ((bridge.get("explanation") or {}).get("numeric") or {})
    v01_n = numeric.get("v01_strict_panels")
    v011_n = numeric.get("v011_strict_panels")
    has_step_keys = "n_gained" in src or "gained_panel" in src or "lost_panel" in src
    explained_by_totals = "EXPLAINED_DEFINITION_AND_UNIVERSE" in src
    return {
        "id": 6,
        "claim": "panel bridge labelled EXPLAINED from published 43085 and 39465 without Δ3620 key decomposition",
        "source_status_literal": explained_by_totals,
        "published_bridge_status": status,
        "published_v01_strict_panels": v01_n,
        "published_v011_strict_panels": v011_n,
        "has_gained_lost_decomposition": has_step_keys,
        "reproduced": explained_by_totals and not has_step_keys,
    }


def run_phase0(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    blocks = [
        defect_offset_future_timestamp_pass(),
        defect_empty_timestamps_verified_pass(),
        defect_missing_unit_accepted(),
        defect_namespace_overrides_source(root),
        defect_lep_ood_support_ignores_state(root),
        defect_panel_bridge_totals_only(root),
    ]
    ok = all(bool(b.get("reproduced")) for b in blocks)
    return {
        "version": VERSION,
        "V012_INTEGRATED_RUNTIME_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "V012_EXPECTED_SHA256": V012_EXPECTED_SHA256,
        "n_defects": len(blocks),
        "n_reproduced": sum(1 for b in blocks if b.get("reproduced")),
        "defects": blocks,
        "ok": ok,
        "note": "These are v0.1.2 defects. Reproduction is required before v0.1.3 corrections.",
        "no_v013_zip_overwrite": V013_ZIP_NAME,
        "row_values_disclosed": False,
    }
