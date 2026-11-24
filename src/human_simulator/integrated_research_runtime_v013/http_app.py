"""Local HTTP research API. Bind 127.0.0.1. Typed 4xx. No CORS wildcard."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urlparse

from human_simulator.integrated_research_runtime_v013.composition import (
    bind_source_namespace,
    compose_joint_distribution,
    natural_history_forecast,
)
from human_simulator.integrated_research_runtime_v013.fixtures import (
    bundle_public_catalog,
    synthetic_request,
    synthetic_runtime_bundle,
    timestamp_verified_request,
)
from human_simulator.integrated_research_runtime_v013.loader import build_frozen_bundle
from human_simulator.integrated_research_runtime_v013.policy import (
    BODY_LIMIT_BYTES,
    HTTP_HOST,
    NS_SYN,
    SYN_SOURCE,
    VERSION,
)
from human_simulator.integrated_research_runtime_v013.probability import SYN_MODEL_ID, execute_event_probability
from human_simulator.integrated_research_runtime_v013.qsp import execute_qsp
from human_simulator.integrated_research_runtime_v013.schemas import (
    ApiContractError,
    EventRequest,
    JointRequest,
    QspRequest,
    StateRequest,
    parse_model,
)
from human_simulator.integrated_research_runtime_v013.workbench import render_workbench

DIRECT = {"email", "phone", "full_name", "patient_id", "user_id", "address", "passport", "insurance_id"}


def _reject_direct(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in DIRECT and v:
                raise ApiContractError(400, "DIRECT_IDENTIFIER_REJECTED")
            _reject_direct(v)
    elif isinstance(obj, list):
        for v in obj:
            _reject_direct(v)


def _public_out(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _public_out(v) for k, v in obj.items() if k != "paths" and k not in DIRECT}
    if isinstance(obj, list):
        return [_public_out(v) for v in obj]
    return obj


def _http_for_reason(status: str, reason: str) -> int:
    if status == "ABSTAIN":
        return 422
    fails_400 = {
        "DIRECT_IDENTIFIER_REJECTED",
        "SCHEMA_INVALID",
        "NON_FINITE_VALUE",
        "N_PATHS_OUT_OF_RANGE",
        "N_PATHS_TYPE_INVALID",
        "INVALID_JSON",
        "CUTOFF_T0_REQUIRED",
        "SOURCE_REQUIRED",
        "OUTCOME_ORDER_REQUIRED",
        "PER_OUTCOME_CELL_IDENTITIES_REQUIRED",
        "STATE_AT_T0_NON_FINITE_OR_MISSING",
        "HORIZON_TYPE_INVALID",
        "MISSING_UNIT",
        "MISSING_SOURCE_SYSTEM",
        "MISSING_REQUESTED_HORIZON_DAYS",
        "SOURCE_NAMESPACE_MISMATCH",
        "HISTORY_TIMESTAMP_AFTER_CUTOFF_T0",
        "HISTORY_TIMESTAMPS_EMPTY_FOR_NONEMPTY_HISTORY",
        "TIMESTAMP_NAIVE_TIMEZONE_REQUIRED",
    }
    if reason in fails_400:
        return 400
    if reason in {"UNKNOWN_ROUTE"}:
        return 404
    return 409


class ResearchApp:
    def __init__(self, root: Path | None = None, sources: dict[str, Any] | None = None):
        self.root = Path(root).resolve() if root else None
        self.synthetic = synthetic_runtime_bundle()
        self.sources = sources or {}
        self.mode = "local_private"
        self._frozen: dict[tuple[str, int, tuple[str, ...]], dict[str, Any]] = {}

    def _bundle_for(self, request: dict[str, Any]) -> dict[str, Any]:
        ss = request.get("source_system")
        ns, ns_reason = bind_source_namespace(str(ss) if ss else None, request.get("namespace"))
        if ns_reason:
            return {"status": "FAIL", "reason": ns_reason, "cells": {}}
        if ns == NS_SYN or ss == SYN_SOURCE:
            return self.synthetic
        if self.root is None:
            return {"status": "ABSTAIN", "reason": "FROZEN_BUNDLE_REQUIRED", "cells": {}}
        outcomes = tuple(request.get("outcome_keys") or [])
        h = int(request.get("requested_horizon_days") or 0)
        key = (str(ss), h, outcomes)
        if key not in self._frozen:
            self._frozen[key] = build_frozen_bundle(self.root, str(ss), list(outcomes), h)
        return self._frozen[key]

    def handle(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        body = body or {}
        _reject_direct(body)
        route = (urlparse(path).path or "/").rstrip("/") or "/"
        if method == "GET" and route in {"/", "/workbench", "/workbench.html"}:
            return 200, {"_html": render_workbench()}
        if method == "GET" and route == "/health":
            return 200, {"ok": True, "mode": self.mode, "bind": HTTP_HOST, "production": False, "version": VERSION}
        if method == "GET" and route == "/research/sources":
            return 200, {
                "clinical": self.sources.get("clinical") or [],
                "reference": self.sources.get("reference") or [],
                "model_providers": self.sources.get("model_providers") or [],
                "materialized_layers": self.sources.get("materialized_layers") or [],
                "CLINICAL_SOURCE_SYSTEM_COUNT": self.sources.get("CLINICAL_SOURCE_SYSTEM_COUNT"),
                "MATERIALIZED_LAYER_COUNT": self.sources.get("MATERIALIZED_LAYER_COUNT"),
                "FROZEN_MODEL_REGISTRY_COUNT": self.sources.get("FROZEN_MODEL_REGISTRY_COUNT"),
                "MODEL_PROVIDER_REGISTRY_COUNT": self.sources.get("MODEL_PROVIDER_REGISTRY_COUNT"),
            }
        if method == "GET" and route == "/research/models":
            return 200, {
                "synthetic": bundle_public_catalog(self.synthetic),
                "synthetic_event_probability_model_id": SYN_MODEL_ID,
                "feature_order_is_not_model_identity": True,
                "frozen_execution_requires_exact_cell_identities": True,
            }
        if method == "POST" and route == "/research/state":
            parsed = parse_model(StateRequest, body)
            if not parsed.get("source_system") and not parsed.get("source_id"):
                raise ApiContractError(409, "NO_SILENT_SOURCE_FALLBACK")
            return 200, {
                "source_system": parsed.get("source_system"),
                "cutoff_t0": parsed.get("cutoff_t0"),
                "state_received": True,
                "opaque": True,
                "mode": self.mode,
            }
        if method == "POST" and route in {
            "/research/natural-history/forecast",
            "/research/joint-outcome-distribution",
            "/research/joint-rollout",
            "/research/replay",
        }:
            parsed = parse_model(JointRequest, body)
            bundle = self._bundle_for(parsed)
            if bundle.get("status") in {"FAIL", "ABSTAIN"} and not bundle.get("cells"):
                code = _http_for_reason(bundle.get("status") or "ABSTAIN", str(bundle.get("reason")))
                return code, bundle
            if route == "/research/natural-history/forecast":
                out = natural_history_forecast(parsed, bundle)
            else:
                out = compose_joint_distribution(parsed, bundle)
            if route == "/research/joint-rollout":
                out = {
                    **out,
                    "deprecated_alias": True,
                    "warning": "distribution at requested horizon, not an accepted trajectory",
                }
            if route == "/research/replay":
                out = {**out, "replay": True}
            status = out.get("status")
            if status == "OK":
                payload = out if parsed.get("include_paths") else _public_out(out)
                return 200, payload
            return _http_for_reason(str(status), str(out.get("reason"))), out
        if method == "POST" and route == "/research/event-probability":
            parsed = parse_model(EventRequest, body)
            out = execute_event_probability(parsed, root=self.root)
            status = out.get("status")
            if status == "OK":
                return 200, out
            return _http_for_reason(str(status), str(out.get("reason"))), out
        if method == "POST" and route == "/research/event-probability/reference-probe":
            parsed = parse_model(EventRequest, {**body, "REFERENCE_FEATURE_PROBE": True, "lep_input_mode": "REFERENCE_FEATURE_PROBE"})
            out = execute_event_probability(parsed, root=self.root)
            status = out.get("status")
            if status == "OK":
                return 200, out
            return _http_for_reason(str(status), str(out.get("reason"))), out
        if method == "POST" and route == "/research/qsp/reference-run":
            parsed = parse_model(QspRequest, body)
            out = execute_qsp(parsed)
            status = out.get("status")
            if status == "OK":
                return 200, out
            return _http_for_reason(str(status), str(out.get("reason"))), out
        if method == "GET" and route.startswith("/research/evidence/"):
            mid = route.split("/")[-1]
            for rec in bundle_public_catalog(self.synthetic):
                if rec.get("active_payload_sha256") == mid:
                    return 200, {**rec, "accepted_d1": False}
            return 422, {"status": "ABSTAIN", "reason": "NOT_FOUND", "no_silent_fallback": True, "version": VERSION}
        raise ApiContractError(404, "UNKNOWN_ROUTE")


def make_handler(app: ResearchApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _read_body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if n > BODY_LIMIT_BYTES:
                raise ApiContractError(413, "BODY_TOO_LARGE")
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"), parse_constant=lambda _c: (_ for _ in ()).throw(ValueError("NON_FINITE_VALUE")))
            except json.JSONDecodeError as exc:
                raise ApiContractError(400, "INVALID_JSON") from exc
            except ValueError as exc:
                raise ApiContractError(400, "NON_FINITE_VALUE") from exc

        def _send(self, status: int, obj: dict[str, Any]) -> None:
            if isinstance(obj, dict) and "_html" in obj:
                payload = str(obj["_html"]).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            body = dict(obj)
            body.setdefault("version", VERSION)
            payload = json.dumps(body, default=str, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            try:
                code, out = app.handle("GET", self.path, {})
                self._send(code, out)
            except ApiContractError as e:
                self._send(e.status, {"status": "FAIL", "reason": e.message if False else e.reason, **e.extra})
            except Exception:  # noqa: BLE001
                self._send(500, {"status": "FAIL", "reason": "INTERNAL_ERROR"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                body = self._read_body()
                code, out = app.handle("POST", self.path, body)
                self._send(code, out)
            except ApiContractError as e:
                self._send(e.status, {"status": "FAIL", "reason": e.reason, **e.extra})
            except Exception:  # noqa: BLE001
                self._send(400, {"status": "FAIL", "reason": "DETERMINISTIC_REQUEST_ERROR"})

    return Handler


class LocalServer:
    def __init__(self, app: ResearchApp, host: str = HTTP_HOST, port: int = 0):
        self.app = app
        self.httpd = ThreadingHTTPServer((host, port), make_handler(app))
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.httpd.server_address[1])

    def start(self) -> "LocalServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def __enter__(self) -> "LocalServer":
        return self.start()

    def __exit__(self, *args: Any) -> None:
        self.stop()


def run_http_audit(root: Path | None = None, sources: dict[str, Any] | None = None) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    from human_simulator.integrated_research_runtime_v013.browser_test import run_browser_audit
    from human_simulator.integrated_research_runtime_v013.engine import frozen_request
    from human_simulator.integrated_research_runtime_v013.http_client import HttpClient
    from human_simulator.integrated_research_runtime_v013.loader import build_frozen_bundle
    from human_simulator.integrated_research_runtime_v013.policy import FROZEN_A_H90, FROZEN_B_P0_H90, SOURCE_A, SOURCE_B
    from human_simulator.integrated_research_runtime_v013.probability import (
        SYN_FEATURE_ORDER_SHA256,
        SYN_MODEL_ID,
        execute_event_probability,
        frozen_lep_probe_request,
        two_state_lep_vectors,
    )
    from human_simulator.integrated_research_runtime_v013.workbench import render_workbench

    app = ResearchApp(root=root, sources=sources)
    src_text = Path(__file__).read_text(encoding="utf-8")
    with LocalServer(app) as srv:
        c = HttpClient(HTTP_HOST, srv.port)
        health = c.request("GET", "/health")
        req = synthetic_request(include_paths=True)
        joint = c.request("POST", "/research/joint-outcome-distribution", req)
        verified = c.request("POST", "/research/joint-outcome-distribution", timestamp_verified_request(include_paths=False))
        future = dict(timestamp_verified_request())
        future["history_timestamps"] = {
            list(future["outcome_keys"])[0]: ["2019-12-31T23:00:00-02:00"],
            list(future["outcome_keys"])[1]: ["2019-12-31T23:00:00-02:00"],
        }
        future_out = c.request("POST", "/research/joint-outcome-distribution", future)
        empty_ts = dict(timestamp_verified_request())
        empty_ts["history_timestamps"] = {ok: [] for ok in empty_ts["outcome_keys"]}
        empty_out = c.request("POST", "/research/joint-outcome-distribution", empty_ts)
        ns_bad = dict(req)
        ns_bad["namespace"] = "SOURCE_B"
        ns_out = c.request("POST", "/research/joint-outcome-distribution", ns_bad)
        no_unit = dict(req)
        first_ok = req["outcome_keys"][0]
        no_unit["cell_identities"] = {k: dict(v) for k, v in req["cell_identities"].items()}
        no_unit["cell_identities"][first_ok].pop("unit", None)
        unit_out = c.request("POST", "/research/joint-outcome-distribution", no_unit)
        miss = dict(req)
        miss.pop("cell_identities")
        miss_out = c.request("POST", "/research/joint-outcome-distribution", miss)
        zero = dict(req)
        zero["n_paths"] = 0
        zero_out = c.request("POST", "/research/joint-outcome-distribution", zero)
        d1 = dict(req)
        d1["force_d1"] = True
        d1_out = c.request("POST", "/research/joint-outcome-distribution", d1)
        ev = c.request(
            "POST",
            "/research/event-probability",
            {
                "namespace": NS_SYN,
                "source_system": SYN_SOURCE,
                "endpoint": "TIME_TO_NEXT_LAB_PANEL",
                "requested_horizon_days": 90,
                "model_id": SYN_MODEL_ID,
                "feature_order_sha256": SYN_FEATURE_ORDER_SHA256,
                "cutoff_t0": "2000-01-01T00:00:00Z",
                "state_at_t0": {"history_depth": 2},
            },
        )
        ident = c.request("POST", "/research/state", {"patient_id": "x", "source_system": "synthetic"})
        qsp = c.request("POST", "/research/qsp/reference-run", {"model_id": "SYNTHETIC_REFERENCE_COMPOUND_X_PKPD"})
        qsp_iv = c.request("POST", "/research/qsp/reference-run", {"medication": "real", "dose": 5})
        html = c.request("GET", "/")
        inf_raw = json.dumps(req).replace("1.0", "Infinity", 1)
        inf_out: dict[str, Any]
        cors = None
        try:
            http_req = urllib.request.Request(
                f"http://{HTTP_HOST}:{srv.port}/research/joint-outcome-distribution",
                data=inf_raw.encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(http_req, timeout=5) as resp:
                inf_out = json.loads(resp.read().decode())
                inf_out["http_status"] = resp.status
                cors = resp.headers.get("Access-Control-Allow-Origin")
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                inf_out = json.loads(raw)
            except json.JSONDecodeError:
                inf_out = {"status": "FAIL", "reason": "INVALID_JSON"}
            inf_out["http_status"] = e.code
            cors = e.headers.get("Access-Control-Allow-Origin") if e.headers else None
        frozen_http: dict[str, Any] = {"executed": False}
        if root is not None:
            bun_a = build_frozen_bundle(root, SOURCE_A, list(FROZEN_A_H90), 90)
            if bun_a.get("status") == "OK":
                fa_req = frozen_request(bun_a, state={ok: float(10 + i) for i, ok in enumerate(bun_a["outcomes"])})
                fa_req["include_paths"] = False
                fa_out = c.request("POST", "/research/joint-outcome-distribution", fa_req)
                frozen_http = {
                    "executed": fa_out.get("status") == "OK",
                    "status": fa_out.get("status"),
                    "reason": fa_out.get("reason"),
                    "source_system": SOURCE_A,
                    "paths_disclosed": bool(fa_out.get("paths")),
                }
            bun_b = build_frozen_bundle(root, SOURCE_B, [FROZEN_B_P0_H90], 90)
            if bun_b.get("status") == "OK":
                fb_req = frozen_request(bun_b, state={ok: 11.0 for ok in bun_b["outcomes"]})
                fb_req["include_paths"] = False
                fb_out = c.request("POST", "/research/joint-outcome-distribution", fb_req)
                frozen_http["source_b"] = {
                    "executed": fb_out.get("status") == "OK",
                    "status": fb_out.get("status"),
                    "reason": fb_out.get("reason"),
                }
        lep_probe_status = "LEP_PROVIDER_UNAVAILABLE"
        lep_probe_ok = False
        state_lep_status = "NOT_IMPLEMENTED"
        two_state = {"ok": False}
        if root is not None:
            probe = frozen_lep_probe_request(root)
            if probe and probe.get("engine_eligible"):
                lep_req = {k: v for k, v in probe.items() if k != "engine_eligible"}
                probe_out = c.request("POST", "/research/event-probability/reference-probe", {k: v for k, v in lep_req.items() if k != "REFERENCE_FEATURE_PROBE"})
                state_req = {k: v for k, v in lep_req.items() if k not in {"REFERENCE_FEATURE_PROBE", "lep_input_mode"}}
                state_req["state_at_t0"] = {"history_depth": 2}
                state_out = c.request("POST", "/research/event-probability", state_req)
                lep_probe_ok = (
                    probe_out.get("status") == "OK"
                    and probe_out.get("reference_probe") is True
                    and probe_out.get("state_conditioned") is False
                )
                lep_probe_status = probe_out.get("FROZEN_LEP_REFERENCE_PROBE_STATUS") or probe_out.get("reason") or "FAIL"
                if state_out.get("reason") == "LEP_STATE_FEATURES_UNAVAILABLE":
                    state_lep_status = "NOT_IMPLEMENTED"
                else:
                    state_lep_status = state_out.get("STATE_CONDITIONED_LEP_STATUS") or state_out.get("reason") or "FAIL"
                two_state = two_state_lep_vectors(
                    root,
                    state_req,
                    {"history_depth": 1.0, "n_obs_before": 1.0},
                    {"history_depth": 99.0, "n_obs_before": 99.0},
                )
            elif probe:
                lep_probe_status = "CELL_NOT_ENGINE_ELIGIBLE"
            else:
                direct = execute_event_probability(
                    {
                        "namespace": "SOURCE_B",
                        "source_system": SOURCE_B,
                        "endpoint": "TIME_TO_NEXT_LAB_PANEL",
                        "requested_horizon_days": 90,
                        "model_id": "0" * 64,
                        "feature_order_sha256": SYN_FEATURE_ORDER_SHA256,
                        "cutoff_t0": "2000-01-01T00:00:00Z",
                        "REFERENCE_FEATURE_PROBE": True,
                    },
                    root=root,
                )
                lep_probe_status = direct.get("FROZEN_LEP_REFERENCE_PROBE_STATUS") or direct.get("reason") or "LEP_PROVIDER_UNAVAILABLE"
        temporal_http = (
            verified.get("status") == "OK"
            and verified.get("TEMPORAL_EVIDENCE_TIER") == "TIMESTAMP_VERIFIED"
            and future_out.get("reason") == "HISTORY_TIMESTAMP_AFTER_CUTOFF_T0"
            and future_out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS") != "PASS_NO_T1_T2_READ"
            and empty_out.get("reason") == "HISTORY_TIMESTAMPS_EMPTY_FOR_NONEMPTY_HISTORY"
            and ns_out.get("reason") == "SOURCE_NAMESPACE_MISMATCH"
            and unit_out.get("reason") in {"MISSING_UNIT", "SCHEMA_INVALID", "MISSING_FIELD"}
            and joint.get("TEMPORAL_EVIDENCE_TIER") == "DECLARED_PRE_T0_SUMMARY"
        )
        browser = run_browser_audit(f"http://{HTTP_HOST}:{srv.port}")
        typed = (
            joint.get("status") == "OK"
            and miss_out.get("reason") in {"PER_OUTCOME_CELL_IDENTITIES_REQUIRED", "SCHEMA_INVALID", "MISSING_FIELD"}
            and miss_out.get("http_status") == 400
            and zero_out.get("reason") == "N_PATHS_OUT_OF_RANGE"
            and zero_out.get("http_status") == 400
            and inf_out.get("reason") in {"NON_FINITE_VALUE", "INVALID_JSON"}
            and inf_out.get("http_status") == 400
            and d1_out.get("reason") == "D1_NOT_ACCEPTED"
            and ident.get("reason") == "DIRECT_IDENTIFIER_REJECTED"
            and ev.get("executed") is True
            and ev.get("route") == "SYNTHETIC_FIXTURE"
            and qsp.get("synthetic_only") is True
            and qsp_iv.get("reason") == "INTERVENTION_EFFECT_UNAVAILABLE"
            and health.get("ok") is True
            and cors is None
            and temporal_http
            and "send_header(\"Access-Control-Allow-Origin\"" not in src_text
        )
        browser_status = browser.get("WORKBENCH_BROWSER_INTEGRATION_STATUS") or "NOT_VERIFIED"
        frozen_ok = bool(frozen_http.get("executed")) and bool((frozen_http.get("source_b") or {}).get("executed"))
        return {
            "HTTP_RESEARCH_API_STATUS": "BUILT" if typed else "FAIL",
            "API_SCHEMA_CONTRACT_STATUS": "PASS" if typed else "FAIL",
            "HTTP_TYPED_SCHEMA_STATUS": "PASS" if typed else "FAIL",
            "HTTP_DETERMINISTIC_ERROR_STATUS": "PASS"
            if zero_out.get("http_status") == 400 and inf_out.get("http_status") == 400
            else "FAIL",
            "API_MODEL_ROUTING_STATUS": "PASS" if joint.get("status") == "OK" else "FAIL",
            "API_NO_SILENT_FALLBACK_STATUS": "PASS" if miss_out.get("reason") else "FAIL",
            "SYNTHETIC_EVENT_PROBABILITY_STATUS": "PASS" if ev.get("executed") else "FAIL",
            "FROZEN_LEP_REFERENCE_PROBE_STATUS": "PASS" if lep_probe_ok else str(lep_probe_status),
            "STATE_CONDITIONED_LEP_STATUS": state_lep_status,
            "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": "PASS"
            if verified.get("TEMPORAL_EVIDENCE_TIER") == "TIMESTAMP_VERIFIED"
            else "FAIL",
            "DECLARED_PRE_T0_SUMMARY_STATUS": "PASS"
            if joint.get("TEMPORAL_EVIDENCE_TIER") == "DECLARED_PRE_T0_SUMMARY"
            else "FAIL",
            "SOURCE_NAMESPACE_BINDING_STATUS": "PASS" if ns_out.get("reason") == "SOURCE_NAMESPACE_MISMATCH" else "FAIL",
            "PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS": "PASS"
            if unit_out.get("reason") in {"MISSING_UNIT", "SCHEMA_INVALID", "MISSING_FIELD"}
            else "FAIL",
            "WORKBENCH_BROWSER_INTEGRATION_STATUS": browser_status,
            "bind": HTTP_HOST,
            "port": srv.port,
            "event_executed": ev.get("executed"),
            "frozen_http": frozen_http,
            "frozen_http_ok": frozen_ok,
            "timestamp_verified_http": verified.get("status") == "OK",
            "future_offset_http_reason": future_out.get("reason"),
            "two_state_lep": two_state,
            "no_cors_wildcard": cors is None,
            "browser": {k: v for k, v in browser.items() if k != "html"},
            "html_has_fetch_not_a_browser_test": "fetch(" in (html.get("html") or "")
            and "fetch(" in render_workbench(),
            "ok": typed and temporal_http,
        }
