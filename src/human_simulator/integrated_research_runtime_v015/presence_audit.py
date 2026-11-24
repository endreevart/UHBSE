"""Direct API + live HTTP field-presence audit after the v0.1.5 contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

from human_simulator.integrated_research_runtime_v015.composition import compose_joint_distribution
from human_simulator.integrated_research_runtime_v015.fixtures import synthetic_request
from human_simulator.integrated_research_runtime_v015.future_fields import (
    DATA_BEARING_FUTURE_FIELDS,
    FALSEY_PRESENCE_VALUES,
    HAS_FUTURE_FIELD,
    NONEMPTY_BY_FIELD,
    REASON_LEAK,
    REASON_SCHEMA,
    future_information_contract,
)
from human_simulator.integrated_research_runtime_v015.policy import SOURCE_B, VERSION
from human_simulator.integrated_research_runtime_v015.probability import (
    HTTP_ROUTE_PROBE,
    HTTP_ROUTE_STATE,
    SYN_FEATURE_ORDER_SHA256,
    SYN_MODEL_ID,
    execute_event_probability,
)


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


def _record(field: str, kind: str, value: Any, out: dict[str, Any], *, expect_reason: str | None) -> dict[str, Any]:
    ok = True
    if expect_reason is None:
        ok = out.get("status") not in {None} and out.get("reason") != REASON_LEAK
        if out.get("reason") == REASON_LEAK:
            ok = False
    else:
        ok = out.get("status") == "FAIL" and out.get("reason") == expect_reason
        if expect_reason == REASON_LEAK:
            ok = ok and out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS") == "FAIL"
            ok = ok and out.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") != "PASS"
            ok = ok and out.get("infer_called") is not True
            ok = ok and out.get("residual_sampled") is not True
            ok = ok and out.get("model_execution") is not True
    return {
        "field": field,
        "kind": kind,
        "value_repr": repr(value),
        "expect_reason": expect_reason,
        "status": out.get("status"),
        "reason": out.get("reason"),
        "http_status": out.get("http_status"),
        "ok": ok,
    }


def run_direct_presence_audit() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    infer = MagicMock()
    residual = MagicMock(return_value=0.0)
    with (
        patch("human_simulator.longitudinal_event_probability_v0211.engine.infer", infer),
        patch("human_simulator.integrated_research_runtime_v015.composition.sample_verified_residual", residual),
    ):
        base_nhr = synthetic_request()
        missing = compose_joint_distribution(deepcopy(base_nhr))
        rows.append(_record("t1", "missing", "<absent>", missing, expect_reason=None))
        for field in DATA_BEARING_FUTURE_FIELDS:
            for value in FALSEY_PRESENCE_VALUES:
                req = deepcopy(base_nhr)
                req[field] = value
                out = compose_joint_distribution(req)
                rows.append(_record(field, "nhr_direct", value, out, expect_reason=REASON_LEAK))
            req = deepcopy(base_nhr)
            req[field] = NONEMPTY_BY_FIELD[field]
            out = compose_joint_distribution(req)
            rows.append(_record(field, "nhr_direct_nonempty", NONEMPTY_BY_FIELD[field], out, expect_reason=REASON_LEAK))
        syn = _lep_syn()
        frozen = _lep_frozen()
        for field in DATA_BEARING_FUTURE_FIELDS:
            for value in (0, None, False, ""):
                sreq = {**syn, field: value}
                fout = execute_event_probability(sreq)
                rows.append(_record(field, "synthetic_lep_direct", value, fout, expect_reason=REASON_LEAK))
                freq = {**frozen, field: value}
                zout = execute_event_probability(freq, http_route=HTTP_ROUTE_STATE)
                rows.append(_record(field, "frozen_ordinary_lep_direct", value, zout, expect_reason=REASON_LEAK))
                pout = execute_event_probability(freq, http_route=HTTP_ROUTE_PROBE)
                rows.append(_record(field, "reference_probe_direct", value, pout, expect_reason=REASON_LEAK))
        false_flag = deepcopy(base_nhr)
        false_flag[HAS_FUTURE_FIELD] = False
        out_false = compose_joint_distribution(false_flag)
        rows.append(_record(HAS_FUTURE_FIELD, "false_allowed_not_proof", False, out_false, expect_reason=None))
        true_flag = deepcopy(base_nhr)
        true_flag[HAS_FUTURE_FIELD] = True
        out_true = compose_joint_distribution(true_flag)
        rows.append(_record(HAS_FUTURE_FIELD, "true_blocked", True, out_true, expect_reason=REASON_LEAK))
        for bad in (None, 0, 1, "", "false", [], {}):
            breq = deepcopy(base_nhr)
            breq[HAS_FUTURE_FIELD] = bad
            bout = compose_joint_distribution(breq)
            rows.append(_record(HAS_FUTURE_FIELD, "invalid_type", bad, bout, expect_reason=REASON_SCHEMA))
        both = deepcopy(base_nhr)
        both[HAS_FUTURE_FIELD] = False
        both["t1"] = 0
        out_both = compose_joint_distribution(both)
        rows.append(_record("t1+has_future_values=false", "false_does_not_cancel", 0, out_both, expect_reason=REASON_LEAK))
    nhr_ok = missing.get("status") == "OK"
    infer_ok = infer.call_count == 0
    residual_on_leak = residual.call_count == 0 or all(
        r["ok"] for r in rows if r["expect_reason"] == REASON_LEAK
    )
    ok = nhr_ok and infer_ok and all(r["ok"] for r in rows)
    return {
        "version": VERSION,
        "ok": ok,
        "n_cases": len(rows),
        "n_pass": sum(1 for r in rows if r["ok"]),
        "infer_called_on_forbidden": infer.call_count,
        "residual_called_on_forbidden": residual.call_count if not nhr_ok else residual.call_count,
        "missing_field_proceeds": nhr_ok,
        "cases": rows,
        "FALSEY_FUTURE_FIELD_REJECTION_STATUS": "PASS" if ok else "FAIL",
        "FUTURE_FIELD_PRESENCE_CONTRACT_STATUS": "PASS" if ok else "FAIL",
        "note": "Direct Python API uses original request dict keys. infer/residual mocks are ROUTING_CONTRACT_ONLY.",
    }


def run_http_presence_matrix(client: Any, syn_joint: dict[str, Any], syn_lep: dict[str, Any], frozen_lep: dict[str, Any] | None) -> dict[str, Any]:
    routes = (
        "/research/natural-history/forecast",
        "/research/joint-outcome-distribution",
        "/research/joint-rollout",
        "/research/replay",
    )
    lep_routes = (
        "/research/event-probability",
        "/research/event-probability/reference-probe",
    )
    rows: list[dict[str, Any]] = []
    for route in routes:
        miss = client.request("POST", route, deepcopy(syn_joint))
        rows.append(
            {
                "route": route,
                "kind": "missing",
                "ok": miss.get("status") == "OK" and miss.get("reason") != REASON_LEAK,
                "http_status": miss.get("http_status"),
                "reason": miss.get("reason"),
                "status": miss.get("status"),
            }
        )
        for field in DATA_BEARING_FUTURE_FIELDS:
            for value in (*FALSEY_PRESENCE_VALUES, NONEMPTY_BY_FIELD[field]):
                body = deepcopy(syn_joint)
                body[field] = value
                out = client.request("POST", route, body)
                rows.append(
                    {
                        "route": route,
                        "field": field,
                        "kind": "present",
                        "value_repr": repr(value),
                        "ok": out.get("http_status") == 400
                        and out.get("status") == "FAIL"
                        and out.get("reason") == REASON_LEAK
                        and out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS") == "FAIL"
                        and out.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") != "PASS"
                        and out.get("infer_called") is not True
                        and out.get("model_execution") is not True,
                        "http_status": out.get("http_status"),
                        "reason": out.get("reason"),
                    }
                )
        null_body = deepcopy(syn_joint)
        null_body["t1"] = None
        null_out = client.request("POST", route, null_body)
        miss_ok = miss.get("status") == "OK"
        null_fail = null_out.get("reason") == REASON_LEAK
        rows.append(
            {
                "route": route,
                "kind": "missing_vs_null",
                "ok": miss_ok and null_fail,
                "missing_status": miss.get("status"),
                "null_reason": null_out.get("reason"),
            }
        )
        hf_true = deepcopy(syn_joint)
        hf_true[HAS_FUTURE_FIELD] = True
        t_out = client.request("POST", route, hf_true)
        rows.append(
            {
                "route": route,
                "kind": "has_future_values_true",
                "ok": t_out.get("http_status") == 400 and t_out.get("reason") == REASON_LEAK,
                "http_status": t_out.get("http_status"),
                "reason": t_out.get("reason"),
            }
        )
        hf_false = deepcopy(syn_joint)
        hf_false[HAS_FUTURE_FIELD] = False
        f_out = client.request("POST", route, hf_false)
        rows.append(
            {
                "route": route,
                "kind": "has_future_values_false_not_proof",
                "ok": f_out.get("status") == "OK"
                and f_out.get("reason") != REASON_LEAK
                and f_out.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") != "PASS",
                "status": f_out.get("status"),
                "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": f_out.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"),
                "note": "false is allowed; declared-summary OK is not timestamp proof from the flag",
            }
        )
        for bad in (0, "false", None):
            b = deepcopy(syn_joint)
            b[HAS_FUTURE_FIELD] = bad
            o = client.request("POST", route, b)
            rows.append(
                {
                    "route": route,
                    "kind": "has_future_values_invalid",
                    "value_repr": repr(bad),
                    "ok": o.get("http_status") == 400 and o.get("reason") == REASON_SCHEMA,
                    "http_status": o.get("http_status"),
                    "reason": o.get("reason"),
                }
            )
    for route in lep_routes:
        payload = deepcopy(frozen_lep or syn_lep)
        if route.endswith("reference-probe") and frozen_lep is None:
            payload = deepcopy(syn_lep)
        for field in DATA_BEARING_FUTURE_FIELDS:
            for value in (*FALSEY_PRESENCE_VALUES, NONEMPTY_BY_FIELD[field]):
                body = deepcopy(syn_lep if not route.endswith("reference-probe") else payload)
                if route.endswith("reference-probe") and frozen_lep:
                    body = deepcopy(frozen_lep)
                body[field] = value
                out = client.request("POST", route, body)
                rows.append(
                    {
                        "route": route,
                        "field": field,
                        "kind": "lep_present",
                        "value_repr": repr(value),
                        "ok": out.get("http_status") == 400
                        and out.get("reason") == REASON_LEAK
                        and out.get("infer_called") is not True,
                        "http_status": out.get("http_status"),
                        "reason": out.get("reason"),
                    }
                )
    fail_vs_ok = any(r.get("kind") == "missing_vs_null" and r.get("ok") for r in rows)
    ok = all(bool(r.get("ok")) for r in rows)
    return {
        "ok": ok,
        "n_cases": len(rows),
        "n_pass": sum(1 for r in rows if r.get("ok")),
        "HTTP_EXPLICIT_FIELD_PRESENCE_STATUS": "PASS" if ok and fail_vs_ok else "FAIL",
        "FALSEY_FUTURE_FIELD_REJECTION_STATUS": "PASS" if ok else "FAIL",
        "cases": rows,
    }


def missing_vs_null_direct() -> dict[str, Any]:
    base = synthetic_request()
    missing = deepcopy(base)
    explicit = deepcopy(base)
    explicit["t1"] = None
    contract_missing = future_information_contract(missing)
    contract_null = future_information_contract(explicit)
    return {
        "missing_keys_include_t1": "t1" in missing,
        "explicit_null_keys_include_t1": "t1" in explicit,
        "missing_rejected": contract_missing is not None,
        "explicit_null_rejected": contract_null is not None and contract_null.get("reason") == REASON_LEAK,
        "ok": "t1" not in missing and "t1" in explicit and contract_missing is None and contract_null is not None,
    }
