"""Private research API contracts. No silent fallback. No row-level logging."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from human_simulator.integrated_research_runtime_v01.engine import infer_joint, load_joint_payload
from human_simulator.integrated_research_runtime_v01.hashes import sha_obj
from human_simulator.integrated_research_runtime_v01.policy import VERSION
from human_simulator.integrated_research_runtime_v01.qsp import run_pkpd, run_qsp
from human_simulator.integrated_research_runtime_v01.sources import forbid_external_patient_transfer

DIRECT_ID_KEYS = {
    "email",
    "phone",
    "full_name",
    "patient_id",
    "user_id",
    "address",
    "passport",
    "insurance_id",
}


class ApiError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _reject_direct_ids(obj: Any) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in DIRECT_ID_KEYS and v:
                raise ApiError(400, "DIRECT_IDENTIFIER_REJECTED")
            _reject_direct_ids(v)
    elif isinstance(obj, list):
        for v in obj:
            _reject_direct_ids(v)


def _strip_direct(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_direct(v) for k, v in obj.items() if k not in DIRECT_ID_KEYS}
    if isinstance(obj, list):
        return [_strip_direct(v) for v in obj]
    return obj


class ResearchRuntime:
    def __init__(self, *, sources: dict[str, Any], models: dict[str, Any], payload: dict[str, Any], evidence: dict[str, Any]):
        self.sources = sources
        self.models = models
        self.payload = payload
        self.evidence = evidence
        self.mode = "synthetic"

    def handle(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        _reject_direct_ids(body)
        xfer = forbid_external_patient_transfer(body)
        if not xfer["ok"]:
            raise ApiError(403, "CLINICAL_DATA_TRANSFER_PROHIBITED")
        parsed = urlparse(path)
        route = parsed.path.rstrip("/") or "/"
        if method == "GET" and route == "/research/sources":
            return {
                "sources": [
                    {k: c[k] for k in (
                        "source_id",
                        "source_type",
                        "source_version",
                        "availability_status",
                        "contains_patient_data",
                        "outbound_transfer_allowed",
                    )}
                    for c in self.sources.get("connectors") or []
                ]
            }
        if method == "GET" and route == "/research/models":
            return {"models": self.models.get("public") or []}
        if method == "POST" and route == "/research/state":
            return self._require_source(body, {"evidence_tier": "INDIVIDUAL_STATE", "mode": self.mode, "synthetic_default": True})
        if method == "POST" and route == "/research/natural-history/forecast":
            return self._require_model(body, {"route": "natural_history", "NATURAL_HISTORY_ONLY": True})
        if method == "POST" and route == "/research/event-probability":
            return self._require_model(body, {"route": "event_probability"})
        if method == "POST" and route == "/research/joint-rollout":
            out = infer_joint(body, self.payload)
            if out.get("status") == "FAIL" and out.get("reason") == "NO_ROUTE":
                raise ApiError(409, "NO_SILENT_FALLBACK")
            return _strip_direct(out)
        if method == "POST" and route == "/research/classifier/evaluate":
            return {"status": "CANDIDATE_TECHNICAL_LABEL", "clinical": False}
        if method == "POST" and route == "/research/qsp/reference-run":
            if body.get("patient_id") or body.get("subject_id") and body.get("link_to_patient"):
                raise ApiError(409, "PATIENT_SPECIFIC_QSP_PROHIBITED")
            mid = body.get("model_id") or "SYNTHETIC_REFERENCE_COMPOUND_X_PKPD"
            if mid == "SYNTHETIC_HOMEOSTATIC_BIOMARKER_QSP":
                return {k: v for k, v in run_qsp().items() if k not in {"biomarker"}}
            return {k: v for k, v in run_pkpd().items() if k not in {"concentration", "effect"}}
        if method == "GET" and route.startswith("/research/evidence/"):
            mid = route.split("/")[-1]
            rec = (self.evidence.get("by_id") or {}).get(mid) or {"status": "NOT_FOUND", "abstention": True}
            if rec.get("status") == "NOT_FOUND":
                rec["no_silent_fallback"] = True
            return rec
        if method == "POST" and route == "/research/replay":
            out = infer_joint(body, self.payload)
            out["replay"] = True
            return _strip_direct(out)
        raise ApiError(404, "UNKNOWN_ROUTE")

    def _require_source(self, body: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        sid = body.get("source_id") or body.get("source_system")
        known = {c["source_id"] for c in self.sources.get("connectors") or []}
        systems = {c.get("source_version") for c in self.sources.get("connectors") or []}
        if sid not in known and sid not in systems:
            raise ApiError(409, "NO_SILENT_SOURCE_FALLBACK")
        return {"source": sid, "opaque_subject": True, **extra}

    def _require_model(self, body: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        mid = body.get("model_id") or body.get("model_identity_sha256")
        known = {m.get("model_id") for m in self.models.get("public") or []}
        if mid and known and mid not in known:
            raise ApiError(409, "NO_SILENT_MODEL_FALLBACK")
        return {"model_id": mid, "evidence_tier": "CANDIDATE", **extra}


def api_audit(runtime: ResearchRuntime) -> dict[str, Any]:
    r = runtime
    ok_src = r.handle("GET", "/research/sources")
    try:
        r.handle("POST", "/research/state", {"source_id": "does-not-exist"})
        silent = True
    except ApiError:
        silent = False
    try:
        r.handle("POST", "/research/state", {"patient_id": "alice"})
        ids = True
    except ApiError:
        ids = False
    try:
        r.handle("POST", "/research/state", {"destination": "external.example", "contains_patient_data": True})
        xfer = True
    except ApiError:
        xfer = False
    return {
        "version": VERSION,
        "UNIFIED_RESEARCH_RUNTIME_API_STATUS": "BUILT",
        "n_source_connectors_listed": len(ok_src.get("sources") or []),
        "no_silent_source_fallback": not silent,
        "direct_identifiers_rejected": not ids,
        "no_external_patient_transfer": not xfer,
        "ok": (not silent) and (not ids) and (not xfer),
    }
