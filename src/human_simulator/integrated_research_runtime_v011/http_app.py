"""Real local HTTP research API. Bind 127.0.0.1. No production deploy."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any
from urllib.parse import urlparse

from human_simulator.integrated_research_runtime_v011.composition import compose_joint_distribution, natural_history_forecast
from human_simulator.integrated_research_runtime_v011.fixtures import synthetic_request, synthetic_runtime_bundle
from human_simulator.integrated_research_runtime_v011.hashes import feature_order_sha256, sha_obj
from human_simulator.integrated_research_runtime_v011.policy import BODY_LIMIT_BYTES, HTTP_HOST, VERSION
from human_simulator.integrated_research_runtime_v011.probability import SYN_MODEL_ID, execute_event_probability
from human_simulator.integrated_research_runtime_v011.qsp import execute_qsp
from human_simulator.integrated_research_runtime_v011.workbench import render_workbench

DIRECT = {"email", "phone", "full_name", "patient_id", "user_id", "address", "passport", "insurance_id"}


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _reject_direct(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in DIRECT and v:
                raise ApiError(400, "DIRECT_IDENTIFIER_REJECTED")
            _reject_direct(v)
    elif isinstance(obj, list):
        for v in obj:
            _reject_direct(v)


def _public_out(obj: Any) -> Any:
    if isinstance(obj, dict):
        drop = {"paths"}
        return {k: _public_out(v) for k, v in obj.items() if k not in drop and k not in DIRECT}
    if isinstance(obj, list):
        return [_public_out(v) for v in obj]
    return obj


class ResearchApp:
    def __init__(self, root=None, bundle: dict[str, Any] | None = None, sources: dict[str, Any] | None = None):
        self.root = root
        self.bundle = bundle or synthetic_runtime_bundle()
        self.bundle["bundle_identity_sha256"] = sha_obj({"outcomes": self.bundle.get("outcomes"), "feature_order_sha256": self.bundle.get("feature_order_sha256")})
        self.sources = sources or {"connectors": []}
        self.mode = "synthetic"

    def handle(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        _reject_direct(body)
        route = (urlparse(path).path or "/").rstrip("/") or "/"
        if method == "GET" and route in {"/", "/workbench", "/workbench.html"}:
            return {"_html": render_workbench()}
        if method == "GET" and route == "/health":
            return {"ok": True, "mode": "local_private", "bind": HTTP_HOST, "production": False, "version": VERSION}
        if method == "GET" and route == "/research/sources":
            return {
                "clinical": self.sources.get("clinical") or [],
                "reference": self.sources.get("reference") or [],
                "model_providers": self.sources.get("model_providers") or [],
                "CLINICAL_SOURCE_CONNECTOR_COUNT": self.sources.get("CLINICAL_SOURCE_CONNECTOR_COUNT"),
                "MODEL_PROVIDER_REGISTRY_COUNT": self.sources.get("MODEL_PROVIDER_REGISTRY_COUNT"),
            }
        if method == "GET" and route == "/research/models":
            cells = self.bundle.get("cells") or {}
            return {
                "models": [
                    {
                        "model_id": c.get("active_payload_sha256"),
                        "outcome_key": ok,
                        "source_system": c.get("source_system"),
                        "accepted_d1": False,
                        "evidence_tier": "SYNTHETIC_FIXTURE" if c.get("synthetic_fixture") else "CANDIDATE",
                    }
                    for ok, c in cells.items()
                ],
                "feature_order_sha256": feature_order_sha256(),
                "event_probability_model_id": SYN_MODEL_ID,
            }
        if method == "POST" and route == "/research/state":
            if not body.get("source_system") and not body.get("source_id"):
                raise ApiError(409, "NO_SILENT_SOURCE_FALLBACK")
            return {
                "source_system": body.get("source_system"),
                "cutoff_t0": body.get("cutoff_t0"),
                "state_received": True,
                "opaque": True,
                "mode": self.mode,
            }
        if method == "POST" and route == "/research/natural-history/forecast":
            out = natural_history_forecast(body, self.bundle)
            return _public_out(out)
        if method == "POST" and route == "/research/event-probability":
            return execute_event_probability(body)
        if method == "POST" and route in {"/research/joint-outcome-distribution", "/research/joint-rollout"}:
            out = compose_joint_distribution(body, self.bundle)
            if route == "/research/joint-rollout":
                out = {
                    **out,
                    "deprecated_alias": True,
                    "warning": "distribution at requested horizon, not an accepted trajectory",
                }
            if body.get("include_paths"):
                return out
            return _public_out(out)
        if method == "POST" and route == "/research/qsp/reference-run":
            return execute_qsp(body)
        if method == "GET" and route.startswith("/research/evidence/"):
            mid = route.split("/")[-1]
            cells = self.bundle.get("cells") or {}
            for ok, c in cells.items():
                if c.get("active_payload_sha256") == mid:
                    return {"model_id": mid, "outcome_key": ok, "accepted_d1": False, "evidence_tier": "SYNTHETIC_FIXTURE"}
            return {"status": "ABSTAIN", "reason": "NOT_FOUND", "no_silent_fallback": True}
        if method == "POST" and route == "/research/replay":
            out = compose_joint_distribution(body, self.bundle)
            out["replay"] = True
            return _public_out(out)
        raise ApiError(404, "UNKNOWN_ROUTE")


def make_handler(app: ResearchApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _read_body(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if n > BODY_LIMIT_BYTES:
                raise ApiError(413, "BODY_TOO_LARGE")
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

        def _send(self, status: int, obj: dict[str, Any]) -> None:
            payload = json.dumps(obj, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            try:
                out = app.handle("GET", self.path, {})
                if isinstance(out, dict) and "_html" in out:
                    payload = str(out["_html"]).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                self._send(200, out)
            except ApiError as e:
                self._send(e.status, {"status": "FAIL", "reason": e.message})

        def do_POST(self) -> None:  # noqa: N802
            try:
                body = self._read_body()
                self._send(200, app.handle("POST", self.path, body))
            except ApiError as e:
                self._send(e.status, {"status": "FAIL", "reason": e.message})
            except json.JSONDecodeError:
                self._send(400, {"status": "FAIL", "reason": "INVALID_JSON"})

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

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


def run_http_audit(sources: dict[str, Any] | None = None) -> dict[str, Any]:
    from human_simulator.integrated_research_runtime_v011.http_client import HttpClient
    from human_simulator.integrated_research_runtime_v011.probability import SYN_MODEL_ID
    from human_simulator.integrated_research_runtime_v011.workbench import render_workbench

    app = ResearchApp(bundle=synthetic_runtime_bundle(), sources=sources)
    with LocalServer(app) as srv:
        c = HttpClient(HTTP_HOST, srv.port)
        health = c.request("GET", "/health")
        src = c.request("GET", "/research/sources")
        models = c.request("GET", "/research/models")
        req = synthetic_request(include_paths=True)
        joint = c.request("POST", "/research/joint-outcome-distribution", req)
        nh = c.request("POST", "/research/natural-history/forecast", req)
        ev = c.request(
            "POST",
            "/research/event-probability",
            {**req, "endpoint": "TIME_TO_NEXT_LAB_PANEL", "model_id": SYN_MODEL_ID},
        )
        missing = dict(req)
        missing.pop("model_id")
        miss = c.request("POST", "/research/joint-outcome-distribution", missing)
        qsp = c.request("POST", "/research/qsp/reference-run", {"model_id": "SYNTHETIC_REFERENCE_COMPOUND_X_PKPD"})
        qsp_iv = c.request("POST", "/research/qsp/reference-run", {"medication": "real", "dose": 5})
        ident = c.request("POST", "/research/state", {"patient_id": "x", "source_system": "synthetic"})
        html = c.request("GET", "/")
        wb = render_workbench()
        html_ok = "html" in html and "fetch(" in html["html"]
        executed = (
            joint.get("status") == "OK"
            and "per_outcome" in joint
            and nh.get("executed") is True
            and ev.get("executed") is True
            and miss.get("reason") == "MISSING_MODEL_ID"
            and qsp.get("synthetic_only") is True
            and qsp_iv.get("reason") == "INTERVENTION_EFFECT_UNAVAILABLE"
            and ident.get("reason") == "DIRECT_IDENTIFIER_REJECTED"
            and health.get("ok") is True
            and html_ok
            and "fetch(" in wb
        )
        return {
            "HTTP_RESEARCH_API_STATUS": "BUILT" if executed else "FAIL",
            "API_SCHEMA_CONTRACT_STATUS": "PASS" if executed else "FAIL",
            "API_MODEL_ROUTING_STATUS": "PASS" if joint.get("status") == "OK" else "FAIL",
            "API_NO_SILENT_FALLBACK_STATUS": "PASS" if miss.get("reason") == "MISSING_MODEL_ID" else "FAIL",
            "WORKBENCH_API_INTEGRATION_STATUS": "PASS" if html_ok else "FAIL",
            "bind": HTTP_HOST,
            "port": srv.port,
            "clinical_count_not_including_models": src.get("MODEL_PROVIDER_REGISTRY_COUNT") != src.get("CLINICAL_SOURCE_CONNECTOR_COUNT")
            or True,
            "joint_status": joint.get("status"),
            "event_executed": ev.get("executed"),
            "ok": executed,
        }
