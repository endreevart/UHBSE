"""Phase 0 — reproduce Integrated Runtime v0.1.3 LEP routing and feature-provenance defects."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from human_simulator.integrated_research_runtime_v013.http_app import LocalServer, ResearchApp
from human_simulator.integrated_research_runtime_v013.http_client import HttpClient
from human_simulator.integrated_research_runtime_v013.policy import HTTP_HOST, LEP_MODELS, SOURCE_B
from human_simulator.integrated_research_runtime_v013.probability import execute_event_probability, frozen_lep_probe_request
from human_simulator.integrated_research_runtime_v014.policy import (
    ARTIFACT_DIR,
    REVIEW_ZIP as V014_ZIP_NAME,
    V013_EXPECTED_SHA256,
    VERSION,
)


def _feature_order() -> list[str]:
    from human_simulator.longitudinal_event_probability_v0211.policy import FEATURE_ORDER

    return list(FEATURE_ORDER)


def _feat_hash() -> str:
    from human_simulator.longitudinal_event_probability_v0211.estimators import feature_order_hash

    return feature_order_hash(_feature_order())


def _mock_ok_infer(mid: str):
    def _infer(_root: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "abstain": False,
            "event_probability": 0.42,
            "survival_probability": 0.58,
            "model_identity_sha256": mid,
        }

    return _infer


def _clinical_req(mid: str, feat_hash: str) -> dict[str, Any]:
    return {
        "namespace": "SOURCE_B",
        "source_system": SOURCE_B,
        "endpoint": "TIME_TO_NEXT_LAB_PANEL",
        "requested_horizon_days": 90,
        "model_id": mid,
        "feature_order_sha256": feat_hash,
        "cutoff_t0": "2000-01-01T00:00:00Z",
        "state_at_t0": {"history_depth": 2},
    }


def _fake_common(mid: str, feat_hash: str, order: list[str]):
    infer = _mock_ok_infer(mid)

    def _common(_root: Any, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "ss": request.get("source_system"),
            "ns": "SOURCE_B",
            "endpoint": request.get("endpoint"),
            "h": int(request.get("requested_horizon_days") or 0),
            "mid": mid,
            "feat_hash": feat_hash,
            "infer": infer,
            "FEATURE_ORDER": order,
        }

    return _common


def _live_http(root: Path, body: dict[str, Any]) -> dict[str, Any] | None:
    if not (root / LEP_MODELS).is_dir():
        return None
    app = ResearchApp(root=root)
    with LocalServer(app) as srv:
        c = HttpClient(HTTP_HOST, srv.port)
        return c.request("POST", "/research/event-probability", body)


def defect_body_selects_reference_probe(root: Path) -> dict[str, Any]:
    src = (root / "src/human_simulator/integrated_research_runtime_v013/probability.py").read_text(encoding="utf-8")
    src_http = (root / "src/human_simulator/integrated_research_runtime_v013/http_app.py").read_text(encoding="utf-8")
    body_selects = "request.get(\"REFERENCE_FEATURE_PROBE\") is True" in src and "lep_input_mode" in src
    http_plain_uses_body = "execute_event_probability(parsed, root=self.root)" in src_http
    order = _feature_order()
    feat_hash = _feat_hash()
    mid = "a" * 64
    routing_flag: dict[str, Any] = {"check": "routing_status_not_frozen_model_execution"}
    routing_mode: dict[str, Any] = {"check": "routing_status_not_frozen_model_execution"}
    live: dict[str, Any] | None = None
    reproduced_routing = False
    fake = _fake_common(mid, feat_hash, order)
    with patch("human_simulator.integrated_research_runtime_v013.probability._frozen_lep_common", side_effect=fake):
        flag_req = {**_clinical_req(mid, feat_hash), "REFERENCE_FEATURE_PROBE": True}
        flag_out = execute_event_probability(flag_req, root=root)
        mode_req = {**_clinical_req(mid, feat_hash), "lep_input_mode": "REFERENCE_FEATURE_PROBE"}
        mode_req.pop("REFERENCE_FEATURE_PROBE", None)
        mode_out = execute_event_probability(mode_req, root=root)
    routing_flag = {
        "check": "routing_status_not_frozen_model_execution",
        "status": flag_out.get("status"),
        "route": flag_out.get("route"),
        "reference_probe": flag_out.get("reference_probe"),
        "FROZEN_LEP_REFERENCE_PROBE_STATUS": flag_out.get("FROZEN_LEP_REFERENCE_PROBE_STATUS"),
        "url_used": "/research/event-probability (direct execute_event_probability, not /reference-probe)",
        "client_switch": "REFERENCE_FEATURE_PROBE=true",
    }
    routing_mode = {
        "check": "routing_status_not_frozen_model_execution",
        "status": mode_out.get("status"),
        "route": mode_out.get("route"),
        "reference_probe": mode_out.get("reference_probe"),
        "FROZEN_LEP_REFERENCE_PROBE_STATUS": mode_out.get("FROZEN_LEP_REFERENCE_PROBE_STATUS"),
        "url_used": "/research/event-probability (direct execute_event_probability, not /reference-probe)",
        "client_switch": "lep_input_mode=REFERENCE_FEATURE_PROBE",
    }
    reproduced_routing = (
        flag_out.get("route") == "FROZEN_LEP_REFERENCE_PROBE"
        or flag_out.get("reference_probe") is True
    ) and (
        mode_out.get("route") == "FROZEN_LEP_REFERENCE_PROBE"
        or mode_out.get("reference_probe") is True
    )
    probe = frozen_lep_probe_request(root)
    if probe:
        live_body = {k: v for k, v in probe.items() if k != "engine_eligible"}
        live_body["REFERENCE_FEATURE_PROBE"] = True
        live = _live_http(root, live_body)
        if live and (live.get("route") == "FROZEN_LEP_REFERENCE_PROBE" or live.get("reference_probe") is True):
            reproduced_routing = True
            live["check"] = "frozen_provider_http_when_available"
    return {
        "id": 1,
        "claim": "body REFERENCE_FEATURE_PROBE / lep_input_mode selects frozen reference probe on the ordinary URL",
        "source_body_selects_probe": body_selects,
        "ordinary_http_path_forwards_body": http_plain_uses_body,
        "routing_status_REFERENCE_FEATURE_PROBE": routing_flag,
        "routing_status_lep_input_mode": routing_mode,
        "live_http": live,
        "reproduced": bool(body_selects and http_plain_uses_body and reproduced_routing),
    }


def defect_client_vector_counts_as_state_conditioned(root: Path) -> dict[str, Any]:
    src = (root / "src/human_simulator/integrated_research_runtime_v013/probability.py").read_text(encoding="utf-8")
    accepts_features = "REQUEST_FEATURES" in src
    accepts_state_keys = "STATE_AT_T0_EXPLICIT_FEATURE_ORDER_KEY" in src
    order = _feature_order()
    feat_hash = _feat_hash()
    mid = "b" * 64
    dummy = [float(i + 1) for i in range(len(order))]
    state_keys = {k: float(i + 1) for i, k in enumerate(order)}
    features_case: dict[str, Any]
    keys_case: dict[str, Any]
    live: dict[str, Any] | None = None
    fake = _fake_common(mid, feat_hash, order)
    with patch("human_simulator.integrated_research_runtime_v013.probability._frozen_lep_common", side_effect=fake):
        feat_req = {
            **_clinical_req(mid, feat_hash),
            "REFERENCE_FEATURE_PROBE": False,
            "lep_input_mode": "STATE_CONDITIONED",
            "features": dummy,
        }
        feat_out = execute_event_probability(feat_req, root=root)
        key_req = {
            **_clinical_req(mid, feat_hash),
            "REFERENCE_FEATURE_PROBE": False,
            "lep_input_mode": "STATE_CONDITIONED",
            "state_at_t0": state_keys,
        }
        key_req.pop("features", None)
        key_out = execute_event_probability(key_req, root=root)
    features_case = {
        "check": "routing_status_not_frozen_model_execution",
        "status": feat_out.get("status"),
        "state_conditioned": feat_out.get("state_conditioned"),
        "STATE_CONDITIONED_LEP_STATUS": feat_out.get("STATE_CONDITIONED_LEP_STATUS"),
        "route": feat_out.get("route"),
        "vector_kind": "CLIENT_FEATURES_FIELD",
    }
    keys_case = {
        "check": "routing_status_not_frozen_model_execution",
        "status": key_out.get("status"),
        "state_conditioned": key_out.get("state_conditioned"),
        "STATE_CONDITIONED_LEP_STATUS": key_out.get("STATE_CONDITIONED_LEP_STATUS"),
        "route": key_out.get("route"),
        "vector_kind": "FEATURE_ORDER_KEYS_IN_STATE_AT_T0",
    }
    reproduced_exec = (
        feat_out.get("STATE_CONDITIONED_LEP_STATUS") == "PASS"
        and feat_out.get("state_conditioned") is True
        and key_out.get("STATE_CONDITIONED_LEP_STATUS") == "PASS"
        and key_out.get("state_conditioned") is True
    )
    probe = frozen_lep_probe_request(root)
    if probe:
        live_req = {k: v for k, v in probe.items() if k not in {"engine_eligible", "REFERENCE_FEATURE_PROBE", "lep_input_mode"}}
        live_req["features"] = dummy
        live = _live_http(root, live_req)
        if live and live.get("STATE_CONDITIONED_LEP_STATUS") == "PASS" and live.get("state_conditioned") is True:
            reproduced_exec = True
            live["check"] = "frozen_provider_http_when_available"
    return {
        "id": 2,
        "claim": "client features or FEATURE_ORDER keys in state_at_t0 can yield STATE_CONDITIONED_LEP_STATUS=PASS",
        "source_accepts_request_features": accepts_features,
        "source_accepts_feature_order_keys_in_state": accepts_state_keys,
        "client_features_case": features_case,
        "feature_order_keys_in_state_case": keys_case,
        "live_http": live,
        "reproduced": bool(accepts_features and accepts_state_keys and reproduced_exec),
        "source_system_used": SOURCE_B,
    }


def run_phase0(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    blocks = [
        defect_body_selects_reference_probe(root),
        defect_client_vector_counts_as_state_conditioned(root),
    ]
    ok = all(bool(b.get("reproduced")) for b in blocks)
    return {
        "version": VERSION,
        "V013_INTEGRATED_RUNTIME_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "V013_EXPECTED_SHA256": V013_EXPECTED_SHA256,
        "n_defects": len(blocks),
        "n_reproduced": sum(1 for b in blocks if b.get("reproduced")),
        "defects": blocks,
        "ok": ok,
        "note": "v0.1.3 LEP route-boundary defects. Routing/status checks may stub LEP infer; frozen HTTP is separate when the private provider exists.",
        "no_v014_zip_overwrite": V014_ZIP_NAME,
        "row_values_disclosed": False,
        "artifact_dir": ARTIFACT_DIR,
    }
