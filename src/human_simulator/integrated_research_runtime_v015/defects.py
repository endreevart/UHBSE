"""Phase 0 — reproduce Integrated Runtime v0.1.4 falsey future-field bypass."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v014.composition import compose_joint_distribution
from human_simulator.integrated_research_runtime_v014.fixtures import synthetic_request
from human_simulator.integrated_research_runtime_v014.http_app import LocalServer, ResearchApp
from human_simulator.integrated_research_runtime_v014.http_client import HttpClient
from human_simulator.integrated_research_runtime_v014.policy import HTTP_HOST, SOURCE_B
from human_simulator.integrated_research_runtime_v014.probability import (
    SYN_FEATURE_ORDER_SHA256,
    SYN_MODEL_ID,
    execute_event_probability,
)
from human_simulator.integrated_research_runtime_v014.schemas import EventRequest, JointRequest, parse_model
from human_simulator.integrated_research_runtime_v015.policy import (
    ARTIFACT_DIR,
    REVIEW_ZIP as V015_ZIP_NAME,
    V014_EXPECTED_SHA256,
    VERSION,
)

FALSEY = (None, 0, 0.0, False, "", [], {})
DATA_FIELDS = ("t1", "t2", "future_intervals", "actual_recorded_label_offset_days")


def _lep_syn() -> dict[str, Any]:
    return {
        "namespace": "SYNTHETIC_FIXTURE",
        "source_system": "synthetic",
        "endpoint": "TIME_TO_NEXT_LAB_PANEL",
        "requested_horizon_days": 90,
        "model_id": SYN_MODEL_ID,
        "feature_order_sha256": SYN_FEATURE_ORDER_SHA256,
        "cutoff_t0": "2000-01-01T00:00:00Z",
        "state_at_t0": {"history_depth": 2},
    }


def _lep_frozen() -> dict[str, Any]:
    return {
        "namespace": "SOURCE_B",
        "source_system": SOURCE_B,
        "endpoint": "TIME_TO_NEXT_LAB_PANEL",
        "requested_horizon_days": 90,
        "model_id": "0" * 64,
        "feature_order_sha256": SYN_FEATURE_ORDER_SHA256,
        "cutoff_t0": "2000-01-01T00:00:00Z",
        "state_at_t0": {"history_depth": 2},
    }


def _source_cause(root: Path) -> dict[str, Any]:
    comp = (root / "src/human_simulator/integrated_research_runtime_v014/composition.py").read_text(encoding="utf-8")
    prob = (root / "src/human_simulator/integrated_research_runtime_v014/probability.py").read_text(encoding="utf-8")
    schemas = (root / "src/human_simulator/integrated_research_runtime_v014/schemas.py").read_text(encoding="utf-8")
    return {
        "composition_uses_request_get_truthiness": "request.get(\"t1\")" in comp and "request.get(\"t2\")" in comp,
        "probability_uses_request_get_truthiness": "request.get(\"t1\")" in prob and "request.get(\"t2\")" in prob,
        "parse_model_exclude_none_false": "model_dump(exclude_none=False)" in schemas,
        "has_future_uses_bool_or": "def _has_future" in comp,
    }


def _pydantic_indistinguishable() -> dict[str, Any]:
    base = synthetic_request()
    dumped_missing = parse_model(JointRequest, deepcopy(base))
    explicit = deepcopy(base)
    explicit["t1"] = None
    dumped_null = parse_model(JointRequest, explicit)
    return {
        "missing_t1_in_dump": "t1" in dumped_missing,
        "explicit_null_t1_in_dump": "t1" in dumped_null,
        "missing_value": dumped_missing.get("t1"),
        "explicit_null_value": dumped_null.get("t1"),
        "indistinguishable_after_dump": dumped_missing.get("t1") is None and dumped_null.get("t1") is None,
        "cause": "model_dump(exclude_none=False) inserts optional defaults so missing and explicit null both become t1=None",
    }


def defect_falsey_future_field_bypass(root: Path) -> dict[str, Any]:
    cause = _source_cause(root)
    dump_cause = _pydantic_indistinguishable()
    nhr_cases: list[dict[str, Any]] = []
    base = synthetic_request()
    missing = compose_joint_distribution(deepcopy(base))
    nhr_cases.append(
        {
            "field": "<absent>",
            "value_repr": "<absent>",
            "status": missing.get("status"),
            "reason": missing.get("reason"),
            "leak": missing.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
            "bypassed": missing.get("status") == "OK",
            "role": "positive_control_missing_field",
        }
    )
    nonempty = {
        "t1": "2020-01-02T00:00:00Z",
        "t2": "2020-01-03T00:00:00Z",
        "future_intervals": [1.0],
        "actual_recorded_label_offset_days": 90,
        "has_future_values": True,
    }
    for field in DATA_FIELDS:
        for value in FALSEY:
            req = deepcopy(base)
            req[field] = value
            out = compose_joint_distribution(req)
            nhr_cases.append(
                {
                    "field": field,
                    "value_repr": repr(value),
                    "status": out.get("status"),
                    "reason": out.get("reason"),
                    "leak": out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
                    "bypassed": out.get("status") == "OK" or out.get("reason") != "FUTURE_INFORMATION_LEAKAGE",
                    "role": "falsey_or_null",
                }
            )
        req = deepcopy(base)
        req[field] = nonempty[field]
        out = compose_joint_distribution(req)
        nhr_cases.append(
            {
                "field": field,
                "value_repr": repr(nonempty[field]),
                "status": out.get("status"),
                "reason": out.get("reason"),
                "bypassed": out.get("reason") != "FUTURE_INFORMATION_LEAKAGE",
                "role": "nonempty_control",
            }
        )
    syn = _lep_syn()
    frozen = _lep_frozen()
    lep_cases: list[dict[str, Any]] = []
    for field in ("t1", "t2"):
        for value in (0, 0.0, False, None, ""):
            s_out = execute_event_probability({**syn, field: value})
            lep_cases.append(
                {
                    "route": "synthetic_event_probability",
                    "field": field,
                    "value_repr": repr(value),
                    "status": s_out.get("status"),
                    "reason": s_out.get("reason"),
                    "bypassed": s_out.get("status") == "OK" or s_out.get("reason") != "FUTURE_INFORMATION_LEAKAGE",
                    "check": "direct_python_api",
                }
            )
            f_out = execute_event_probability({**frozen, field: value})
            lep_cases.append(
                {
                    "route": "frozen_ordinary_event_probability",
                    "field": field,
                    "value_repr": repr(value),
                    "status": f_out.get("status"),
                    "reason": f_out.get("reason"),
                    "STATE_CONDITIONED_LEP_STATUS": f_out.get("STATE_CONDITIONED_LEP_STATUS"),
                    "bypassed": f_out.get("reason") != "FUTURE_INFORMATION_LEAKAGE",
                    "reached_ordinary_abstain": f_out.get("reason")
                    in {"LEP_STATE_ADAPTER_NOT_IMPLEMENTED", "LEP_CLIENT_VECTOR_IS_NOT_VERIFIED_STATE_ADAPTER"},
                    "check": "direct_python_api",
                }
            )
    proven = {
        "nhr_t1_0": next(c for c in nhr_cases if c["field"] == "t1" and c["value_repr"] == "0"),
        "nhr_t2_0": next(c for c in nhr_cases if c["field"] == "t2" and c["value_repr"] == "0"),
        "syn_lep_t1_0": next(
            c for c in lep_cases if c["route"] == "synthetic_event_probability" and c["field"] == "t1" and c["value_repr"] == "0"
        ),
        "frozen_ordinary_lep_t1_0": next(
            c
            for c in lep_cases
            if c["route"] == "frozen_ordinary_event_probability" and c["field"] == "t1" and c["value_repr"] == "0"
        ),
    }
    live: dict[str, Any] = {}
    app = ResearchApp(root=root)
    with LocalServer(app) as srv:
        c = HttpClient(HTTP_HOST, srv.port)
        joint = deepcopy(base)
        live["nhr_t1_0"] = c.request("POST", "/research/joint-outcome-distribution", {**joint, "t1": 0})
        live["nhr_t2_0"] = c.request("POST", "/research/natural-history/forecast", {**joint, "t2": 0})
        live["nhr_rollout_t1_false"] = c.request("POST", "/research/joint-rollout", {**joint, "t1": False})
        live["nhr_replay_t1_empty"] = c.request("POST", "/research/replay", {**joint, "t1": ""})
        live["syn_lep_t1_0"] = c.request("POST", "/research/event-probability", {**syn, "t1": 0})
        live["syn_lep_t2_0"] = c.request("POST", "/research/event-probability", {**syn, "t2": 0})
        live["frozen_ordinary_t1_0"] = c.request("POST", "/research/event-probability", {**frozen, "t1": 0})
        live["reference_probe_t1_0"] = c.request("POST", "/research/event-probability/reference-probe", {**frozen, "t1": 0})
        live["nhr_missing"] = c.request("POST", "/research/joint-outcome-distribution", deepcopy(base))
        live["nhr_t1_null"] = c.request("POST", "/research/joint-outcome-distribution", {**deepcopy(base), "t1": None})
    live_summary = {
        k: {
            "http_status": v.get("http_status"),
            "status": v.get("status"),
            "reason": v.get("reason"),
            "leak": v.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
            "STATE_CONDITIONED_LEP_STATUS": v.get("STATE_CONDITIONED_LEP_STATUS"),
        }
        for k, v in live.items()
    }
    reproduced = (
        cause["composition_uses_request_get_truthiness"]
        and cause["probability_uses_request_get_truthiness"]
        and cause["parse_model_exclude_none_false"]
        and dump_cause["indistinguishable_after_dump"]
        and proven["nhr_t1_0"]["bypassed"]
        and proven["nhr_t2_0"]["bypassed"]
        and proven["syn_lep_t1_0"]["bypassed"]
        and proven["frozen_ordinary_lep_t1_0"]["bypassed"]
        and live["nhr_t1_0"].get("http_status") == 200
        and live["nhr_t2_0"].get("http_status") == 200
        and live["syn_lep_t1_0"].get("http_status") == 200
        and live["frozen_ordinary_t1_0"].get("reason") != "FUTURE_INFORMATION_LEAKAGE"
        and live["nhr_missing"].get("status") == "OK"
        and live["nhr_t1_null"].get("status") == "OK"
    )
    return {
        "id": 1,
        "claim": "v0.1.4 future-field checks use truthiness, so falsey/null values bypass FUTURE_INFORMATION_LEAKAGE",
        "source_cause": cause,
        "pydantic_dump_cause": dump_cause,
        "proven_manifestations": proven,
        "nhr_direct_cases": nhr_cases,
        "lep_direct_cases": lep_cases,
        "live_http": live_summary,
        "reproduced": bool(reproduced),
        "note": "Live HTTP and direct API on published v0.1.4 code. Frozen probe/ordinary results are real HTTP, not a substituted backend.",
    }


def run_phase0(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    block = defect_falsey_future_field_bypass(root)
    ok = bool(block.get("reproduced"))
    return {
        "version": VERSION,
        "V014_INTEGRATED_RUNTIME_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "V014_EXPECTED_SHA256": V014_EXPECTED_SHA256,
        "n_defects": 1,
        "n_reproduced": 1 if ok else 0,
        "defects": [block],
        "ok": ok,
        "note": "v0.1.4 falsey future-field bypass. Reproduction is required before v0.1.5 corrections.",
        "no_v015_zip_overwrite": V015_ZIP_NAME,
        "row_values_disclosed": False,
        "artifact_dir": ARTIFACT_DIR,
    }
