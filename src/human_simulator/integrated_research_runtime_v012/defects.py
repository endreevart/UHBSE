"""Phase 0 — reproduce Integrated Runtime v0.1.1 contract defects from published code."""

from __future__ import annotations

import json
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v011.composition import compose_joint_distribution
from human_simulator.integrated_research_runtime_v011.connectors import SourceAConnector, build_registry
from human_simulator.integrated_research_runtime_v011.fixtures import (
    SYN_ECDF,
    synthetic_request as v011_request,
    synthetic_runtime_bundle as v011_bundle,
)
from human_simulator.integrated_research_runtime_v011.http_app import LocalServer, ResearchApp
from human_simulator.integrated_research_runtime_v011.http_client import HttpClient
from human_simulator.integrated_research_runtime_v011.policy import (
    ARTIFACT_DIR as V011_ART,
    HTTP_HOST,
    SYN_OUTCOMES,
    SYN_SOURCE,
)
from human_simulator.integrated_research_runtime_v011.probability import SYN_MODEL_ID, execute_event_probability
from human_simulator.integrated_research_runtime_v011.workbench import render_workbench
from human_simulator.integrated_research_runtime_v012.policy import (
    ARTIFACT_DIR,
    REVIEW_ZIP as V012_ZIP_NAME,
    V011_EXPECTED_SHA256,
    V01_ARTIFACT,
    V031_MATERIALIZED,
    VERSION,
)
from human_simulator.natural_history_rollout_v011.providers import predict_active


def _src(root: Path, name: str) -> str:
    return (root / "src/human_simulator/integrated_research_runtime_v011" / name).read_text(encoding="utf-8")


def _snapshot(root: Path, name: str) -> dict[str, Any] | None:
    path = root / ARTIFACT_DIR / name
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def defect_identity_mutations() -> dict[str, Any]:
    bundle = v011_bundle()
    mutated = deepcopy(bundle)
    for cell in mutated["cells"].values():
        cell["active_payload_sha256"] = "0" * 64
        cell["feature_order_sha256"] = "1" * 64
        cell["scaler_sha256"] = "2" * 64
        cell["unit"] = "mutated-unit"
    req = v011_request()
    out = compose_joint_distribution(req, mutated)
    return {
        "id": 1,
        "claim": "mutated payload/feature/scaler/unit still OK",
        "status": out.get("status"),
        "reproduced": out.get("status") == "OK",
    }


def defect_feature_hash_as_model_id() -> dict[str, Any]:
    bundle = v011_bundle()
    req = v011_request()
    fo = bundle["feature_order_sha256"]
    assert req["model_id"] == fo
    out = compose_joint_distribution(req, bundle)
    cells = bundle["cells"]
    payload_ids = {c["active_payload_sha256"] for c in cells.values()}
    return {
        "id": 2,
        "claim": "model_id equal to feature-order hash accepted as model identity",
        "model_id_is_feature_order_hash": req["model_id"] == fo,
        "model_id_is_not_active_payload": req["model_id"] not in payload_ids,
        "status": out.get("status"),
        "reproduced": out.get("status") == "OK" and req["model_id"] == fo and req["model_id"] not in payload_ids,
    }


def defect_silent_p0_fallback() -> dict[str, Any]:
    feat = {
        "persistence_value": 7.0,
        "requested_horizon_days": 90.0,
        "n_prior_outcome_measurements": 1.0,
        "days_since_previous": 0.0,
        "days_since_previous_missing": 1.0,
        "prior_delta": 0.0,
        "prior_delta_missing": 1.0,
        "history_depth": 1.0,
        "missingness": 0.0,
    }
    cases = []
    for cell in (
        {"active_provider": "P1", "p1_payload": None},
        {"active_provider": "UNKNOWN_FAMILY"},
        {"active_provider": None},
    ):
        yhat = predict_active(cell, feat, [7.0], [])
        cases.append({"cell": {k: cell[k] for k in cell if k != "p1_payload"}, "yhat": yhat, "equals_p0": yhat == 7.0})
    return {
        "id": 3,
        "claim": "P1 without payload / unknown / None falls back to P0 and would be OK",
        "cases": cases,
        "reproduced": all(c["equals_p0"] for c in cases),
    }


def defect_synthetic_accepts_source_a() -> dict[str, Any]:
    req = v011_request(source_system="magerya_api")
    out = compose_joint_distribution(req, v011_bundle())
    return {
        "id": 4,
        "claim": "synthetic cells accept source_system=magerya_api",
        "status": out.get("status"),
        "reproduced": out.get("status") == "OK",
    }


def defect_missing_cutoff() -> dict[str, Any]:
    req = v011_request()
    req.pop("cutoff_t0", None)
    out = compose_joint_distribution(req, v011_bundle())
    return {
        "id": 5,
        "claim": "missing cutoff_t0 does not stop inference",
        "status": out.get("status"),
        "reproduced": out.get("status") == "OK",
    }


def defect_event_any_feature_hash() -> dict[str, Any]:
    req = v011_request(endpoint="TIME_TO_NEXT_LAB_PANEL", model_id=SYN_MODEL_ID)
    req["feature_order_sha256"] = "deadbeef" * 8
    out = execute_event_probability(req)
    return {
        "id": 6,
        "claim": "event-probability fixture accepts arbitrary nonempty feature_order_sha256",
        "status": out.get("status"),
        "reproduced": out.get("status") == "OK",
    }


def defect_http_nondeterministic_crash() -> dict[str, Any]:
    app = ResearchApp()
    reproduced_npaths = False
    reproduced_nan = False
    npaths_reason = None
    nan_reason = None
    with LocalServer(app) as srv:
        c = HttpClient(HTTP_HOST, srv.port)
        req = v011_request(include_paths=True, n_paths=0)
        try:
            out = c.request("POST", "/research/joint-outcome-distribution", req)
            npaths_reason = out.get("reason")
            reproduced_npaths = out.get("reason") is None and "status" not in {out.get("status")} or out.get("http_status") in {
                None
            }
            # v0.1.1 sends HTTP 200 with a traceback-less drop OR 200 with exception uncaught
            reproduced_npaths = not (isinstance(out, dict) and out.get("reason") in {"INVALID_N_PATHS", "N_PATHS_OUT_OF_RANGE"})
        except Exception as exc:  # noqa: BLE001
            reproduced_npaths = True
            npaths_reason = type(exc).__name__
        req2 = v011_request(include_paths=True)
        req2["state_at_t0"] = {SYN_OUTCOMES[0]: float("nan"), SYN_OUTCOMES[1]: 1.0}
        try:
            raw = json.dumps(req2).replace("NaN", "NaN")
            # json.dumps turns nan into NaN token which is invalid JSON; python allows it
            import urllib.request

            http_req = urllib.request.Request(
                f"http://{HTTP_HOST}:{srv.port}/research/joint-outcome-distribution",
                data=raw.encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(http_req, timeout=5) as resp:
                    body = json.loads(resp.read().decode())
                    nan_reason = body.get("reason")
                    reproduced_nan = body.get("reason") not in {"NON_FINITE_VALUE", "INVALID_JSON"}
            except Exception as exc:  # noqa: BLE001
                reproduced_nan = True
                nan_reason = type(exc).__name__
        except Exception as exc:  # noqa: BLE001
            reproduced_nan = True
            nan_reason = type(exc).__name__
    return {
        "id": 7,
        "claim": "invalid state / n_paths<1 can drop the HTTP connection without deterministic error",
        "n_paths_reason": npaths_reason,
        "nan_reason": nan_reason,
        "reproduced": bool(reproduced_npaths or reproduced_nan),
    }


def defect_default_synthetic_not_frozen_execution(root: Path) -> dict[str, Any]:
    app = ResearchApp()
    src = _src(root, "http_app.py")
    return {
        "id": 8,
        "claim": "ResearchApp defaults to synthetic bundle; frozen A/B registry is not executed",
        "default_synthetic": bool((app.bundle or {}).get("synthetic_fixture")),
        "handle_loads_nhr_frozen": "natural-history-rollout-v011" not in src and "load_frozen" not in src,
        "reproduced": bool((app.bundle or {}).get("synthetic_fixture")),
    }


def defect_event_route_is_fixture(root: Path) -> dict[str, Any]:
    src = _src(root, "probability.py")
    http = _src(root, "http_app.py")
    return {
        "id": 9,
        "claim": "HTTP event-probability executes synthetic fixture; frozen LEP not proven",
        "lep_infer_default_none": "lep_infer=None" in src or "lep_infer=None" in src.replace(" ", ""),
        "http_does_not_pass_lep": "lep_infer" not in http,
        "reproduced": "lep_infer" not in http,
    }


def defect_workbench_string_test(root: Path) -> dict[str, Any]:
    tests_path = root / "tests/test_integrated_research_runtime_v011_unit.py"
    if not tests_path.is_file():
        snap = _snapshot(root, "v011-workbench-fetch-string-defect.json")
        if snap:
            return snap
    html = render_workbench()
    tests = tests_path.read_text(encoding="utf-8")
    return {
        "id": 10,
        "claim": "workbench tests check fetch() HTML strings, not browser execution",
        "html_has_fetch": "fetch(" in html,
        "unit_test_asserts_fetch_string": 'assert "fetch(" in html' in tests,
        "playwright_absent": "playwright" not in tests.lower() and "browser" not in tests.lower(),
        "reproduced": 'assert "fetch(" in html' in tests,
    }


def defect_clinical_count_three(root: Path) -> dict[str, Any]:
    parquet = root / V031_MATERIALIZED / "research_observation_component.parquet"
    if not parquet.is_file():
        snap = _snapshot(root, "v011-clinical-count-three-defect.json")
        if snap:
            return snap
    src = _src(root, "connectors.py")
    reg = build_registry(root)
    return {
        "id": 11,
        "claim": "CLINICAL_SOURCE_CONNECTOR_COUNT includes unified layer as a third clinical source",
        "count": reg.get("CLINICAL_SOURCE_CONNECTOR_COUNT"),
        "unified_appended": "unified_materialized_state_layer" in src,
        "reproduced": int(reg.get("CLINICAL_SOURCE_CONNECTOR_COUNT") or 0) == 3,
    }


def defect_connector_constant_foreign(root: Path) -> dict[str, Any]:
    src = _src(root, "connectors.py")
    a = SourceAConnector(root)
    agg = a.read_aggregate()
    return {
        "id": 12,
        "claim": "A/B scan one Parquet; foreign_source flag is a constant; read_aggregate is not filtered",
        "constant_true": 'foreign_source_not_returned_as_this_connector": True' in src.replace(" ", "")
        or '"foreign_source_not_returned_as_this_connector": True' in src,
        "read_aggregate_unfiltered": agg == {"ok": True, "row_values_disclosed": False},
        "same_parquet_both_connectors": src.count("research_observation_component.parquet") >= 2,
        "reproduced": bool(
            (
                'foreign_source_not_returned_as_this_connector": True' in src.replace(" ", "")
                or '"foreign_source_not_returned_as_this_connector": True' in src
            )
            and agg == {"ok": True, "row_values_disclosed": False}
        ),
    }


def defect_excluded_as_remainder(root: Path) -> dict[str, Any]:
    src = _src(root, "accounting.py")
    return {
        "id": 13,
        "claim": "excluded_invalid_rows is the leftover balance, forcing residual_selected=0",
        "leftover_assigned": "invalid = leftover" in src,
        "reproduced": "invalid = leftover" in src,
    }


def defect_panel_count_drift(root: Path) -> dict[str, Any]:
    snap = root / ARTIFACT_DIR / "v011-panel-count-drift-defect.json"
    v01_path = root / V01_ARTIFACT / "joint-panel-accounting.json"
    v011_path = root / V011_ART / "joint-panel-accounting.json"
    if not v01_path.is_file() or not v011_path.is_file():
        if snap.is_file():
            return json.loads(snap.read_text(encoding="utf-8"))
    v01 = json.loads(v01_path.read_text(encoding="utf-8"))
    v011 = json.loads(v011_path.read_text(encoding="utf-8"))
    n01 = int(v01.get("n_strict_panels") or 0)
    n011 = int((v011.get("live") or {}).get("row_counts", {}).get("strict_panels") or 0)
    return {
        "id": 14,
        "claim": "strict panel count 43085 (v0.1) vs 39465 (v0.1.1) is unexplained in v0.1.1",
        "v01_strict_panels": n01,
        "v011_strict_panels": n011,
        "delta": n01 - n011,
        "bridge_published_in_v011": "43085" in json.dumps(v011),
        "reproduced": n01 == 43085 and n011 == 39465 and "43085" not in json.dumps(v011),
    }


def defect_zip_status_pending(root: Path) -> dict[str, Any]:
    snap = root / ARTIFACT_DIR / "v011-zip-pending-vs-attestation-defect.json"
    zpath = root / "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1-review.zip"
    if not zpath.is_file() and snap.is_file():
        return json.loads(snap.read_text(encoding="utf-8"))
    inside = {}
    if zpath.is_file():
        with zipfile.ZipFile(zpath) as zf:
            raw = zf.read(
                "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1/status-contract.json"
            )
            inside = json.loads(raw.decode("utf-8"))
    att = {}
    att_path = root / "artifacts/external-review/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.1-review.attestation.json"
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
    return {
        "id": 15,
        "claim": "ZIP status-contract leaves publication PENDING while detached attestation is PASS",
        "zip_publication_integrity": inside.get("PUBLICATION_INTEGRITY_STATUS"),
        "zip_self_containment": inside.get("REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"),
        "attestation_publication_integrity": att.get("PUBLICATION_INTEGRITY_STATUS"),
        "reproduced": inside.get("PUBLICATION_INTEGRITY_STATUS") == "PENDING"
        and att.get("PUBLICATION_INTEGRITY_STATUS") == "PASS",
    }


def run_phase0(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    blocks = [
        defect_identity_mutations(),
        defect_feature_hash_as_model_id(),
        defect_silent_p0_fallback(),
        defect_synthetic_accepts_source_a(),
        defect_missing_cutoff(),
        defect_event_any_feature_hash(),
        defect_http_nondeterministic_crash(),
        defect_default_synthetic_not_frozen_execution(root),
        defect_event_route_is_fixture(root),
        defect_workbench_string_test(root),
        defect_clinical_count_three(root),
        defect_connector_constant_foreign(root),
        defect_excluded_as_remainder(root),
        defect_panel_count_drift(root),
        defect_zip_status_pending(root),
    ]
    ok = all(bool(b.get("reproduced")) for b in blocks)
    return {
        "version": VERSION,
        "V011_INTEGRATED_RUNTIME_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "V011_EXPECTED_SHA256": V011_EXPECTED_SHA256,
        "n_defects": len(blocks),
        "n_reproduced": sum(1 for b in blocks if b.get("reproduced")),
        "defects": blocks,
        "ok": ok,
        "note": "These are v0.1.1 defects. Reproduction is required before v0.1.2 corrections.",
        "no_v012_zip_overwrite": V012_ZIP_NAME,
    }
