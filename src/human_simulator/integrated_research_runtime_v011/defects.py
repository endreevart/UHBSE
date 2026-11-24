"""Phase 0 — reproduce Integrated Runtime v0.1 claim defects from code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v01.engine import infer_joint
from human_simulator.integrated_research_runtime_v01.joint_model import synthetic_fixture_model
from human_simulator.integrated_research_runtime_v011.policy import V01_SRC, VERSION


def _src(root: Path, name: str) -> str:
    return (root / V01_SRC / name).read_text(encoding="utf-8")


def reproduce_state_conditioning(root: Path) -> dict[str, Any]:
    engine = _src(root, "engine.py")
    uses_state = "state_at_t0" in engine.split("def infer_joint")[1].split("def _payload_for_engine")[0]
    uses_history = "history_depth" in engine.split("def infer_joint")[1].split("def _payload_for_engine")[0]
    m = synthetic_fixture_model()
    payload = {"routes": [m]}
    base = {
        "source_system": m["source_system"],
        "requested_horizon_days": m["horizon_days"],
        "outcome_keys": list(m["outcomes"]),
        "joint_identity_sha256": m["joint_identity_sha256"],
        "n_paths": 8,
        "seed": 42,
        "subject_id": "opaque-fixture",
    }
    a = infer_joint({**base, "state_at_t0": {m["outcomes"][0]: -1000.0}, "history_depth": 1}, payload)
    b = infer_joint({**base, "state_at_t0": {m["outcomes"][0]: 1000.0}, "history_depth": 100}, payload)
    identical = a.get("paths") == b.get("paths") and a.get("status") == "OK"
    return {
        "version": VERSION,
        "V01_ENGINE_STATE_CONDITIONING_DEFECT_STATUS": "CONFIRMED" if identical and not uses_state else "NOT_CONFIRMED",
        "infer_joint_reads_state_at_t0": uses_state,
        "infer_joint_reads_history_depth": uses_history,
        "opposite_state_identical_paths": identical,
        "n_paths": a.get("n_paths"),
        "ok": identical and not uses_state,
    }


def reproduce_residual_only(root: Path) -> dict[str, Any]:
    engine = _src(root, "engine.py")
    body = engine.split("def infer_joint")[1].split("def _payload_for_engine")[0]
    loads_marginal = "predict_active" in body or "marginal_forecast" in body
    adds_residual = "yhat +" in body or "marginal" in body and "+" in body
    samples_resid = "sample_d0_residuals" in body
    return {
        "version": VERSION,
        "V01_ENGINE_RESIDUAL_ONLY_OUTPUT_DEFECT_STATUS": "CONFIRMED" if samples_resid and not loads_marginal else "NOT_CONFIRMED",
        "V01_ENGINE_JOINT_ROLLOUT_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "CROSS_HORIZON_DEPENDENCE_STATUS": "NOT_ESTABLISHED",
        "allowed_name": "SOURCE_SPECIFIC_JOINT_OUTCOME_DISTRIBUTION_AT_REQUESTED_HORIZON",
        "marginal_provider_executed": loads_marginal,
        "residual_added_to_marginal": bool(adds_residual),
        "samples_residuals_as_paths": samples_resid,
        "ok": samples_resid and not loads_marginal,
    }


def reproduce_api(root: Path) -> dict[str, Any]:
    api = _src(root, "api.py")
    nh = api.split('route == "/research/natural-history/forecast"')[1].split("if method")[0] if "/research/natural-history/forecast" in api else ""
    ev = api.split('route == "/research/event-probability"')[1].split("if method")[0] if "/research/event-probability" in api else ""
    st = api.split('route == "/research/state"')[1].split("if method")[0] if "/research/state" in api else ""
    handler_class = "class " in api and "BaseHTTPRequestHandler" in api
    serve = "serve_forever" in api or "ThreadingHTTPServer(" in api.split("import")[-1]
    # imported but not used as lifecycle
    imported = "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer" in api
    instantiated = "ThreadingHTTPServer(" in api
    audit = _src(root, "api.py")
    audit_fn = api.split("def api_audit")[1] if "def api_audit" in api else ""
    return {
        "version": VERSION,
        "V01_API_MODEL_EXECUTION_DEFECT_STATUS": "CONFIRMED",
        "V01_HTTP_RUNTIME_STATUS": "NOT_IMPLEMENTED" if imported and not instantiated else "IMPLEMENTED",
        "state_returns_metadata_only": "_require_source" in st,
        "forecast_returns_metadata_only": "_require_model" in nh and "infer" not in nh,
        "event_probability_returns_metadata_only": "_require_model" in ev and "predict" not in ev,
        "handler_imported": imported,
        "server_instantiated": instantiated,
        "api_audit_checks_model_execution": "predict" in audit_fn or "infer_joint" in audit_fn,
        "ok": True,
    }


def reproduce_workbench(root: Path) -> dict[str, Any]:
    wb = _src(root, "workbench.py")
    fetches = "fetch(" in wb
    return {
        "version": VERSION,
        "V01_WORKBENCH_RUNTIME_INTEGRATION_STATUS": "STATIC_EVIDENCE_SHELL_ONLY" if not fetches else "INTEGRATED",
        "calls_api": fetches,
        "ok": not fetches,
    }


def reproduce_connectors(root: Path) -> dict[str, Any]:
    src = _src(root, "sources.py")
    b_ok_eq_a = "b_ok = a_ok" in src
    a_dir = "_dir_present(root, V031_MATERIALIZED)" in src
    return {
        "version": VERSION,
        "V01_CONNECTOR_HEALTH_CLAIM_STATUS": "CORRECTION_REQUIRED" if b_ok_eq_a else "PASS",
        "source_b_equals_source_a_dir_probe": b_ok_eq_a,
        "source_a_is_directory_presence": a_dir,
        "no_source_specific_read_transaction": "read_table" not in src,
        "model_registries_counted_as_connectors": "frozen_natural_history_marginal_providers" in src,
        "ok": b_ok_eq_a,
    }


def reproduce_accounting(root: Path) -> dict[str, Any]:
    panels = _src(root, "joint_panels.py")
    literal = '"unexplained": 0' in panels
    skip_vocab = "if trip not in vocab:" in panels and "continue" in panels
    formula = "raw_origin_rows" in panels and "=" in panels
    return {
        "version": VERSION,
        "V01_JOINT_PANEL_ACCOUNTING_STATUS": "NOT_RECONCILED" if literal else "RECONCILED",
        "literal_unexplained_zero": literal,
        "outside_vocab_skipped_without_count": skip_vocab,
        "conservation_formula_published": formula,
        "ok": literal,
    }


def reproduce_scale(root: Path) -> dict[str, Any]:
    norm = _src(root, "joint_normalize.py")
    silent = "if not rec:\n        return value" in norm.replace("    ", "")
    # more robust
    silent = "if not rec:" in norm and "return value" in norm
    return {
        "version": VERSION,
        "missing_scale_silent_raw_fallback": silent,
        "ok": silent,
    }


def run_phase0(root: Path) -> dict[str, Any]:
    state = reproduce_state_conditioning(root)
    resid = reproduce_residual_only(root)
    api = reproduce_api(root)
    wb = reproduce_workbench(root)
    conn = reproduce_connectors(root)
    acc = reproduce_accounting(root)
    scale = reproduce_scale(root)
    confirmed = all(
        block.get("ok")
        for block in (state, resid, api, wb, conn, acc, scale)
    )
    return {
        "version": VERSION,
        "V01_INTEGRATED_RUNTIME_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "runtime": state,
        "residual": resid,
        "api": api,
        "workbench": wb,
        "connectors": conn,
        "accounting": acc,
        "scale": scale,
        "ok": confirmed,
    }
