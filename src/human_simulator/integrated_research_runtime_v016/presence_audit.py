"""Direct API + live HTTP field-presence audit with separated execution counters."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

from human_simulator.integrated_research_runtime_v016 import composition as composition_mod
from human_simulator.integrated_research_runtime_v016.composition import compose_joint_distribution
from human_simulator.integrated_research_runtime_v016.loader import sample_verified_residual as real_sample_verified_residual
from human_simulator.integrated_research_runtime_v016.fixtures import synthetic_request
from human_simulator.integrated_research_runtime_v016.future_fields import (
    DATA_BEARING_FUTURE_FIELDS,
    FALSEY_PRESENCE_VALUES,
    HAS_FUTURE_FIELD,
    NONEMPTY_BY_FIELD,
    REASON_LEAK,
    REASON_SCHEMA,
    future_information_contract,
)
from human_simulator.integrated_research_runtime_v016.policy import NS_B, NS_SYN, SOURCE_B, SYN_SOURCE, VERSION
from human_simulator.integrated_research_runtime_v016.probability import (
    HTTP_ROUTE_PROBE,
    HTTP_ROUTE_STATE,
    SYN_FEATURE_ORDER_SHA256,
    SYN_MODEL_ID,
    execute_event_probability,
)
from human_simulator.longitudinal_event_probability_v0211 import engine as lep_engine

HAS_FUTURE_INVALID: tuple[Any, ...] = (None, 0, 1, 0.0, 1.0, "", "false", [], {})
SCENARIO_IDENTITY = ("route", "scenario_class", "namespace", "source_system", "provider_class")


def _lep_syn() -> dict[str, Any]:
    return {
        "namespace": NS_SYN,
        "source_system": SYN_SOURCE,
        "endpoint": "TIME_TO_NEXT_LAB_PANEL",
        "requested_horizon_days": 90,
        "model_id": SYN_MODEL_ID,
        "feature_order_sha256": SYN_FEATURE_ORDER_SHA256,
        "cutoff_t0": "2000-01-01T00:00:00Z",
        "state_at_t0": {"history_depth": 2},
    }


def value_kind(value: Any, *, absent: bool = False) -> str:
    if absent:
        return "absent"
    if value is None:
        return "null"
    if value is False:
        return "false"
    if value is True:
        return "true"
    if type(value) is int and value == 0:
        return "0"
    if type(value) is float and value == 0.0:
        return "0.0"
    if type(value) is int and value == 1:
        return "1"
    if type(value) is float and value == 1.0:
        return "1.0"
    if value == "":
        return "empty_str"
    if value == []:
        return "empty_list"
    if value == {}:
        return "empty_obj"
    if value == "false":
        return "str_false"
    return "nonempty"


def _data_bearing_values() -> list[tuple[Any, str]]:
    out: list[tuple[Any, str]] = []
    for value in FALSEY_PRESENCE_VALUES:
        out.append((value, value_kind(value)))
    return out


class ExecutionSpies:
    def __init__(self) -> None:
        self.real_infer = lep_engine.infer
        self.real_residual = real_sample_verified_residual
        self.real_predict = composition_mod._predict
        self.infer = MagicMock(side_effect=lambda *a, **k: self.real_infer(*a, **k))
        self.residual = MagicMock(side_effect=lambda *a, **k: self.real_residual(*a, **k))
        self.predict = MagicMock(side_effect=lambda *a, **k: self.real_predict(*a, **k))

    def snapshot(self) -> tuple[int, int, int]:
        return self.infer.call_count, self.residual.call_count, self.predict.call_count

    def delta(self, before: tuple[int, int, int]) -> dict[str, int]:
        infer_d = self.infer.call_count - before[0]
        residual_d = self.residual.call_count - before[1]
        predict_d = self.predict.call_count - before[2]
        return {
            "infer_call_delta": infer_d,
            "residual_call_delta": residual_d,
            "model_execution_delta": infer_d + predict_d,
        }


def _patches(spies: ExecutionSpies):
    return (
        patch("human_simulator.longitudinal_event_probability_v0211.engine.infer", spies.infer),
        patch("human_simulator.integrated_research_runtime_v016.composition.sample_verified_residual", spies.residual),
        patch("human_simulator.integrated_research_runtime_v016.composition._predict", spies.predict),
    )


def run_direct_presence_audit() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    spies = ExecutionSpies()
    residual_allowed_missing = 0
    residual_allowed_false = 0
    residual_forbidden = 0
    infer_forbidden = 0
    model_forbidden = 0
    p_infer, p_residual, p_predict = _patches(spies)
    with p_infer, p_residual, p_predict:
        base_nhr = synthetic_request()
        before = spies.snapshot()
        missing = compose_joint_distribution(deepcopy(base_nhr))
        d = spies.delta(before)
        residual_allowed_missing += d["residual_call_delta"]
        cases.append(
            {
                "field": "t1",
                "presence_kind": "absent",
                "value_kind": "absent",
                "scenario_class": "nhr_direct",
                "status": missing.get("status"),
                "reason": missing.get("reason"),
                **d,
                "ok": missing.get("status") == "OK" and missing.get("reason") != REASON_LEAK,
            }
        )
        for field in DATA_BEARING_FUTURE_FIELDS:
            for value, kind in (*_data_bearing_values(), (NONEMPTY_BY_FIELD[field], "nonempty")):
                req = deepcopy(base_nhr)
                req[field] = value
                before = spies.snapshot()
                out = compose_joint_distribution(req)
                d = spies.delta(before)
                residual_forbidden += d["residual_call_delta"]
                infer_forbidden += d["infer_call_delta"]
                model_forbidden += d["model_execution_delta"]
                ok = (
                    out.get("status") == "FAIL"
                    and out.get("reason") == REASON_LEAK
                    and out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS") == "FAIL"
                    and d["residual_call_delta"] == 0
                    and d["infer_call_delta"] == 0
                    and d["model_execution_delta"] == 0
                )
                cases.append(
                    {
                        "field": field,
                        "presence_kind": "present",
                        "value_kind": kind,
                        "scenario_class": "nhr_direct",
                        "status": out.get("status"),
                        "reason": out.get("reason"),
                        **d,
                        "ok": ok,
                    }
                )
        syn = _lep_syn()
        for field in DATA_BEARING_FUTURE_FIELDS:
            for value, kind in ((0, "0"), (None, "null"), (False, "false"), ("", "empty_str")):
                before = spies.snapshot()
                fout = execute_event_probability({**syn, field: value})
                d = spies.delta(before)
                residual_forbidden += d["residual_call_delta"]
                infer_forbidden += d["infer_call_delta"]
                model_forbidden += d["model_execution_delta"]
                cases.append(
                    {
                        "field": field,
                        "presence_kind": "present",
                        "value_kind": kind,
                        "scenario_class": "synthetic_ordinary_lep_direct",
                        "status": fout.get("status"),
                        "reason": fout.get("reason"),
                        **d,
                        "ok": fout.get("reason") == REASON_LEAK and d["infer_call_delta"] == 0 and d["model_execution_delta"] == 0,
                    }
                )
        false_flag = deepcopy(base_nhr)
        false_flag[HAS_FUTURE_FIELD] = False
        before = spies.snapshot()
        out_false = compose_joint_distribution(false_flag)
        d = spies.delta(before)
        residual_allowed_false += d["residual_call_delta"]
        cases.append(
            {
                "field": HAS_FUTURE_FIELD,
                "presence_kind": "present",
                "value_kind": "false",
                "scenario_class": "nhr_direct",
                "status": out_false.get("status"),
                "reason": out_false.get("reason"),
                "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS": out_false.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"),
                **d,
                "ok": out_false.get("status") == "OK" and out_false.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") != "PASS",
            }
        )
        true_flag = deepcopy(base_nhr)
        true_flag[HAS_FUTURE_FIELD] = True
        before = spies.snapshot()
        out_true = compose_joint_distribution(true_flag)
        d = spies.delta(before)
        residual_forbidden += d["residual_call_delta"]
        infer_forbidden += d["infer_call_delta"]
        model_forbidden += d["model_execution_delta"]
        cases.append(
            {
                "field": HAS_FUTURE_FIELD,
                "presence_kind": "present",
                "value_kind": "true",
                "status": out_true.get("status"),
                "reason": out_true.get("reason"),
                **d,
                "ok": out_true.get("reason") == REASON_LEAK and d["residual_call_delta"] == 0,
            }
        )
        for bad in HAS_FUTURE_INVALID:
            breq = deepcopy(base_nhr)
            breq[HAS_FUTURE_FIELD] = bad
            before = spies.snapshot()
            bout = compose_joint_distribution(breq)
            d = spies.delta(before)
            model_forbidden += d["model_execution_delta"]
            residual_forbidden += d["residual_call_delta"]
            cases.append(
                {
                    "field": HAS_FUTURE_FIELD,
                    "presence_kind": "present",
                    "value_kind": value_kind(bad),
                    "status": bout.get("status"),
                    "reason": bout.get("reason"),
                    **d,
                    "ok": bout.get("reason") == REASON_SCHEMA and d["residual_call_delta"] == 0,
                }
            )
        both = deepcopy(base_nhr)
        both[HAS_FUTURE_FIELD] = False
        both["t1"] = 0
        before = spies.snapshot()
        out_both = compose_joint_distribution(both)
        d = spies.delta(before)
        residual_forbidden += d["residual_call_delta"]
        infer_forbidden += d["infer_call_delta"]
        model_forbidden += d["model_execution_delta"]
        cases.append(
            {
                "field": "t1+has_future_values=false",
                "presence_kind": "present",
                "value_kind": "0",
                "status": out_both.get("status"),
                "reason": out_both.get("reason"),
                **d,
                "ok": out_both.get("reason") == REASON_LEAK and d["residual_call_delta"] == 0,
            }
        )
    zeros = residual_forbidden == 0 and infer_forbidden == 0 and model_forbidden == 0
    ok = (
        missing.get("status") == "OK"
        and zeros
        and residual_allowed_missing > 0
        and all(c["ok"] for c in cases)
    )
    return {
        "version": VERSION,
        "ok": ok,
        "n_cases": len(cases),
        "n_pass": sum(1 for c in cases if c["ok"]),
        "residual_calls_on_allowed_missing_control": residual_allowed_missing,
        "residual_calls_on_allowed_false_flag_control": residual_allowed_false,
        "residual_calls_on_forbidden": residual_forbidden,
        "infer_calls_on_forbidden": infer_forbidden,
        "model_execution_calls_on_forbidden": model_forbidden,
        "FORBIDDEN_REQUEST_MODEL_EXECUTION_AUDIT_STATUS": "PASS" if zeros else "FAIL",
        "FALSEY_FUTURE_FIELD_REJECTION_STATUS": "PASS" if ok else "FAIL",
        "FUTURE_FIELD_PRESENCE_CONTRACT_STATUS": "PASS" if ok else "FAIL",
        "cases": cases,
        "note": "Counters are per-call deltas. Allowed NHR controls may sample residual. Forbidden payloads must not.",
    }


def _identity(route: str, scenario_class: str, payload: dict[str, Any], provider_class: str) -> dict[str, Any]:
    return {
        "route": route,
        "scenario_class": scenario_class,
        "namespace": payload.get("namespace"),
        "source_system": payload.get("source_system"),
        "provider_class": provider_class,
    }


def _http_call(client: Any, spies: ExecutionSpies, method: str, route: str, body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    before = spies.snapshot()
    out = client.request(method, route, body)
    return out, spies.delta(before)


def run_http_presence_matrix(
    client: Any,
    syn_joint: dict[str, Any],
    syn_lep: dict[str, Any],
    frozen_lep: dict[str, Any] | None,
    *,
    frozen_provider_available: bool = False,
) -> dict[str, Any]:
    spies = ExecutionSpies()
    cases: list[dict[str, Any]] = []
    residual_forbidden = 0
    infer_forbidden = 0
    model_forbidden = 0
    residual_allowed_missing = 0
    residual_allowed_false = 0
    nhr_scenarios = (
        ("/research/natural-history/forecast", "nhr_forecast"),
        ("/research/joint-outcome-distribution", "nhr_joint"),
        ("/research/joint-rollout", "nhr_rollout"),
        ("/research/replay", "nhr_replay"),
    )
    p_infer, p_residual, p_predict = _patches(spies)
    with p_infer, p_residual, p_predict:
        frozen_controls: dict[str, Any] = {"frozen_provider_available": frozen_provider_available}
        if frozen_lep:
            probe_body = deepcopy(frozen_lep)
            probe_out, probe_d = _http_call(client, spies, "POST", "/research/event-probability/reference-probe", probe_body)
            frozen_controls["reference_probe_control"] = {
                "http_status": probe_out.get("http_status"),
                "status": probe_out.get("status"),
                "reason": probe_out.get("reason"),
                **probe_d,
                "ok": probe_out.get("http_status") == 200 and probe_out.get("status") == "OK",
            }
            ordinary_body = deepcopy(frozen_lep)
            ordinary_body.setdefault("state_at_t0", {"history_depth": 2})
            abs_out, abs_d = _http_call(client, spies, "POST", "/research/event-probability", ordinary_body)
            frozen_controls["ordinary_adapter_abstention_control"] = {
                "http_status": abs_out.get("http_status"),
                "status": abs_out.get("status"),
                "reason": abs_out.get("reason"),
                "STATE_CONDITIONED_LEP_STATUS": abs_out.get("STATE_CONDITIONED_LEP_STATUS"),
                **abs_d,
                "ok": abs_out.get("http_status") == 422
                and abs_out.get("status") == "ABSTAIN"
                and abs_out.get("STATE_CONDITIONED_LEP_STATUS") == "NOT_IMPLEMENTED",
            }
            leak_body = deepcopy(ordinary_body)
            leak_body["t1"] = 0
            leak_out, leak_d = _http_call(client, spies, "POST", "/research/event-probability", leak_body)
            residual_forbidden += leak_d["residual_call_delta"]
            infer_forbidden += leak_d["infer_call_delta"]
            model_forbidden += leak_d["model_execution_delta"]
            frozen_controls["ordinary_future_field_pre_adapter"] = {
                "http_status": leak_out.get("http_status"),
                "status": leak_out.get("status"),
                "reason": leak_out.get("reason"),
                **leak_d,
                "ok": leak_out.get("http_status") == 400
                and leak_out.get("reason") == REASON_LEAK
                and leak_d["infer_call_delta"] == 0
                and leak_d["model_execution_delta"] == 0,
            }
        else:
            frozen_controls["reference_probe_control"] = {"ok": False, "reason": "FROZEN_PROVIDER_UNAVAILABLE"}
            frozen_controls["ordinary_adapter_abstention_control"] = {"ok": False}
            frozen_controls["ordinary_future_field_pre_adapter"] = {"ok": False}

        def add_case(**kwargs: Any) -> None:
            cases.append(kwargs)

        for route, scenario in nhr_scenarios:
            ident = _identity(route, scenario, syn_joint, "SYNTHETIC_FIXTURE")
            miss, d = _http_call(client, spies, "POST", route, deepcopy(syn_joint))
            residual_allowed_missing += d["residual_call_delta"]
            add_case(
                **ident,
                field=None,
                presence_kind="absent",
                value_kind="absent",
                http_status=miss.get("http_status"),
                status=miss.get("status"),
                reason=miss.get("reason"),
                infer_call_delta=d["infer_call_delta"],
                residual_call_delta=d["residual_call_delta"],
                model_execution=d["model_execution_delta"] > 0,
                ok=miss.get("status") == "OK" and miss.get("reason") != REASON_LEAK,
            )
            for field in DATA_BEARING_FUTURE_FIELDS:
                for value, kind in (*_data_bearing_values(), (NONEMPTY_BY_FIELD[field], "nonempty")):
                    body = deepcopy(syn_joint)
                    body[field] = value
                    out, d = _http_call(client, spies, "POST", route, body)
                    residual_forbidden += d["residual_call_delta"]
                    infer_forbidden += d["infer_call_delta"]
                    model_forbidden += d["model_execution_delta"]
                    add_case(
                        **ident,
                        field=field,
                        presence_kind="present",
                        value_kind=kind,
                        http_status=out.get("http_status"),
                        status=out.get("status"),
                        reason=out.get("reason"),
                        infer_call_delta=d["infer_call_delta"],
                        residual_call_delta=d["residual_call_delta"],
                        model_execution=d["model_execution_delta"] > 0,
                        ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS=out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
                        ok=out.get("http_status") == 400
                        and out.get("status") == "FAIL"
                        and out.get("reason") == REASON_LEAK
                        and out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS") == "FAIL"
                        and d["infer_call_delta"] == 0
                        and d["residual_call_delta"] == 0
                        and d["model_execution_delta"] == 0,
                    )
            hf_false = deepcopy(syn_joint)
            hf_false[HAS_FUTURE_FIELD] = False
            f_out, d = _http_call(client, spies, "POST", route, hf_false)
            residual_allowed_false += d["residual_call_delta"]
            add_case(
                **ident,
                field=HAS_FUTURE_FIELD,
                presence_kind="present",
                value_kind="false",
                http_status=f_out.get("http_status"),
                status=f_out.get("status"),
                reason=f_out.get("reason"),
                infer_call_delta=d["infer_call_delta"],
                residual_call_delta=d["residual_call_delta"],
                model_execution=d["model_execution_delta"] > 0,
                TEMPORAL_TIMESTAMP_VERIFICATION_STATUS=f_out.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"),
                ok=f_out.get("status") == "OK"
                and f_out.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") != "PASS",
            )
            hf_true = deepcopy(syn_joint)
            hf_true[HAS_FUTURE_FIELD] = True
            t_out, d = _http_call(client, spies, "POST", route, hf_true)
            residual_forbidden += d["residual_call_delta"]
            infer_forbidden += d["infer_call_delta"]
            model_forbidden += d["model_execution_delta"]
            add_case(
                **ident,
                field=HAS_FUTURE_FIELD,
                presence_kind="present",
                value_kind="true",
                http_status=t_out.get("http_status"),
                status=t_out.get("status"),
                reason=t_out.get("reason"),
                infer_call_delta=d["infer_call_delta"],
                residual_call_delta=d["residual_call_delta"],
                model_execution=d["model_execution_delta"] > 0,
                ok=t_out.get("http_status") == 400 and t_out.get("reason") == REASON_LEAK and d["residual_call_delta"] == 0,
            )
            for bad in HAS_FUTURE_INVALID:
                b = deepcopy(syn_joint)
                b[HAS_FUTURE_FIELD] = bad
                o, d = _http_call(client, spies, "POST", route, b)
                residual_forbidden += d["residual_call_delta"]
                model_forbidden += d["model_execution_delta"]
                add_case(
                    **ident,
                    field=HAS_FUTURE_FIELD,
                    presence_kind="present",
                    value_kind=value_kind(bad),
                    http_status=o.get("http_status"),
                    status=o.get("status"),
                    reason=o.get("reason"),
                    infer_call_delta=d["infer_call_delta"],
                    residual_call_delta=d["residual_call_delta"],
                    model_execution=d["model_execution_delta"] > 0,
                    ok=o.get("http_status") == 400 and o.get("reason") == REASON_SCHEMA and d["residual_call_delta"] == 0,
                )
            cancel = deepcopy(syn_joint)
            cancel[HAS_FUTURE_FIELD] = False
            cancel["t1"] = 0
            c_out, d = _http_call(client, spies, "POST", route, cancel)
            residual_forbidden += d["residual_call_delta"]
            infer_forbidden += d["infer_call_delta"]
            model_forbidden += d["model_execution_delta"]
            add_case(
                **ident,
                field="t1+has_future_values=false",
                presence_kind="present",
                value_kind="0",
                http_status=c_out.get("http_status"),
                status=c_out.get("status"),
                reason=c_out.get("reason"),
                infer_call_delta=d["infer_call_delta"],
                residual_call_delta=d["residual_call_delta"],
                model_execution=d["model_execution_delta"] > 0,
                ok=c_out.get("http_status") == 400 and c_out.get("reason") == REASON_LEAK and d["residual_call_delta"] == 0,
            )

        lep_scenarios = (
            ("/research/event-probability", "synthetic_ordinary_lep", syn_lep, "SYNTHETIC_FIXTURE", "ok_200"),
            ("/research/event-probability", "frozen_ordinary_lep", frozen_lep, "FROZEN_SOURCE_B", "abstain_422"),
            ("/research/event-probability/reference-probe", "frozen_reference_probe", frozen_lep, "FROZEN_SOURCE_B", "ok_200"),
        )
        for route, scenario, payload, provider, absent_mode in lep_scenarios:
            if payload is None:
                add_case(
                    route=route,
                    scenario_class=scenario,
                    namespace=NS_B if provider == "FROZEN_SOURCE_B" else NS_SYN,
                    source_system=SOURCE_B if provider == "FROZEN_SOURCE_B" else SYN_SOURCE,
                    provider_class=provider,
                    field=None,
                    presence_kind="absent",
                    value_kind="absent",
                    http_status=None,
                    status="FAIL",
                    reason="FROZEN_PROVIDER_UNAVAILABLE",
                    infer_call_delta=0,
                    residual_call_delta=0,
                    model_execution=False,
                    ok=False,
                )
                continue
            body_base = deepcopy(payload)
            body_base.pop("engine_eligible", None)
            body_base.setdefault("state_at_t0", {"history_depth": 2})
            ident = _identity(route, scenario, body_base, provider)
            miss, d = _http_call(client, spies, "POST", route, deepcopy(body_base))
            if absent_mode == "ok_200":
                absent_ok = miss.get("http_status") == 200 and miss.get("status") == "OK"
            else:
                absent_ok = (
                    miss.get("http_status") == 422
                    and miss.get("status") == "ABSTAIN"
                    and miss.get("STATE_CONDITIONED_LEP_STATUS") == "NOT_IMPLEMENTED"
                )
            add_case(
                **ident,
                field=None,
                presence_kind="absent",
                value_kind="absent",
                http_status=miss.get("http_status"),
                status=miss.get("status"),
                reason=miss.get("reason"),
                infer_call_delta=d["infer_call_delta"],
                residual_call_delta=d["residual_call_delta"],
                model_execution=d["model_execution_delta"] > 0,
                ok=absent_ok,
            )
            for field in DATA_BEARING_FUTURE_FIELDS:
                for value, kind in (*_data_bearing_values(), (NONEMPTY_BY_FIELD[field], "nonempty")):
                    body = deepcopy(body_base)
                    body[field] = value
                    out, d = _http_call(client, spies, "POST", route, body)
                    residual_forbidden += d["residual_call_delta"]
                    infer_forbidden += d["infer_call_delta"]
                    model_forbidden += d["model_execution_delta"]
                    add_case(
                        **ident,
                        field=field,
                        presence_kind="present",
                        value_kind=kind,
                        http_status=out.get("http_status"),
                        status=out.get("status"),
                        reason=out.get("reason"),
                        infer_call_delta=d["infer_call_delta"],
                        residual_call_delta=d["residual_call_delta"],
                        model_execution=d["model_execution_delta"] > 0,
                        ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS=out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS"),
                        ok=out.get("http_status") == 400
                        and out.get("status") == "FAIL"
                        and out.get("reason") == REASON_LEAK
                        and out.get("ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS") == "FAIL"
                        and d["infer_call_delta"] == 0
                        and d["residual_call_delta"] == 0
                        and d["model_execution_delta"] == 0,
                    )
            hf_false = deepcopy(body_base)
            hf_false[HAS_FUTURE_FIELD] = False
            f_out, d = _http_call(client, spies, "POST", route, hf_false)
            if absent_mode == "ok_200":
                false_ok = f_out.get("http_status") == 200 and f_out.get("status") == "OK"
            else:
                false_ok = (
                    f_out.get("http_status") == 422
                    and f_out.get("status") == "ABSTAIN"
                    and f_out.get("STATE_CONDITIONED_LEP_STATUS") == "NOT_IMPLEMENTED"
                )
            add_case(
                **ident,
                field=HAS_FUTURE_FIELD,
                presence_kind="present",
                value_kind="false",
                http_status=f_out.get("http_status"),
                status=f_out.get("status"),
                reason=f_out.get("reason"),
                infer_call_delta=d["infer_call_delta"],
                residual_call_delta=d["residual_call_delta"],
                model_execution=d["model_execution_delta"] > 0,
                TEMPORAL_TIMESTAMP_VERIFICATION_STATUS=f_out.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"),
                ok=false_ok and f_out.get("reason") != REASON_LEAK,
            )
            hf_true = deepcopy(body_base)
            hf_true[HAS_FUTURE_FIELD] = True
            t_out, d = _http_call(client, spies, "POST", route, hf_true)
            residual_forbidden += d["residual_call_delta"]
            infer_forbidden += d["infer_call_delta"]
            model_forbidden += d["model_execution_delta"]
            add_case(
                **ident,
                field=HAS_FUTURE_FIELD,
                presence_kind="present",
                value_kind="true",
                http_status=t_out.get("http_status"),
                status=t_out.get("status"),
                reason=t_out.get("reason"),
                infer_call_delta=d["infer_call_delta"],
                residual_call_delta=d["residual_call_delta"],
                model_execution=d["model_execution_delta"] > 0,
                ok=t_out.get("http_status") == 400 and t_out.get("reason") == REASON_LEAK and d["infer_call_delta"] == 0,
            )
            for bad in HAS_FUTURE_INVALID:
                b = deepcopy(body_base)
                b[HAS_FUTURE_FIELD] = bad
                o, d = _http_call(client, spies, "POST", route, b)
                residual_forbidden += d["residual_call_delta"]
                model_forbidden += d["model_execution_delta"]
                add_case(
                    **ident,
                    field=HAS_FUTURE_FIELD,
                    presence_kind="present",
                    value_kind=value_kind(bad),
                    http_status=o.get("http_status"),
                    status=o.get("status"),
                    reason=o.get("reason"),
                    infer_call_delta=d["infer_call_delta"],
                    residual_call_delta=d["residual_call_delta"],
                    model_execution=d["model_execution_delta"] > 0,
                    ok=o.get("http_status") == 400 and o.get("reason") == REASON_SCHEMA and d["residual_call_delta"] == 0,
                )
            cancel = deepcopy(body_base)
            cancel[HAS_FUTURE_FIELD] = False
            cancel["t1"] = 0
            c_out, d = _http_call(client, spies, "POST", route, cancel)
            residual_forbidden += d["residual_call_delta"]
            infer_forbidden += d["infer_call_delta"]
            model_forbidden += d["model_execution_delta"]
            add_case(
                **ident,
                field="t1+has_future_values=false",
                presence_kind="present",
                value_kind="0",
                http_status=c_out.get("http_status"),
                status=c_out.get("status"),
                reason=c_out.get("reason"),
                infer_call_delta=d["infer_call_delta"],
                residual_call_delta=d["residual_call_delta"],
                model_execution=d["model_execution_delta"] > 0,
                ok=c_out.get("http_status") == 400 and c_out.get("reason") == REASON_LEAK and d["residual_call_delta"] == 0,
            )

    identity_ok = all(all(c.get(k) not in (None, "") for k in SCENARIO_IDENTITY) for c in cases)
    scenario_set = {c.get("scenario_class") for c in cases}
    required_scenarios = {
        "nhr_forecast",
        "nhr_joint",
        "nhr_rollout",
        "nhr_replay",
        "synthetic_ordinary_lep",
        "frozen_ordinary_lep",
        "frozen_reference_probe",
    }
    frozen_rows = [c for c in cases if c.get("scenario_class") == "frozen_ordinary_lep" and c.get("presence_kind") == "present"]
    frozen_ok = (
        frozen_provider_available
        and bool((frozen_controls.get("reference_probe_control") or {}).get("ok"))
        and bool((frozen_controls.get("ordinary_adapter_abstention_control") or {}).get("ok"))
        and bool((frozen_controls.get("ordinary_future_field_pre_adapter") or {}).get("ok"))
        and bool(frozen_rows)
        and all(c.get("ok") for c in frozen_rows)
        and all(c.get("namespace") == NS_B and c.get("source_system") == SOURCE_B for c in frozen_rows)
    )
    zeros = residual_forbidden == 0 and infer_forbidden == 0 and model_forbidden == 0
    ok = (
        all(bool(c.get("ok")) for c in cases)
        and identity_ok
        and required_scenarios <= scenario_set
        and frozen_ok
        and zeros
        and residual_allowed_missing > 0
    )
    return {
        "ok": ok,
        "n_cases": len(cases),
        "n_pass": sum(1 for c in cases if c.get("ok")),
        "scenario_classes": sorted(scenario_set),
        "residual_calls_on_allowed_missing_control": residual_allowed_missing,
        "residual_calls_on_allowed_false_flag_control": residual_allowed_false,
        "residual_calls_on_forbidden": residual_forbidden,
        "infer_calls_on_forbidden": infer_forbidden,
        "model_execution_calls_on_forbidden": model_forbidden,
        "HTTP_EXPLICIT_FIELD_PRESENCE_STATUS": "PASS" if ok else "FAIL",
        "FALSEY_FUTURE_FIELD_REJECTION_STATUS": "PASS" if ok else "FAIL",
        "HTTP_FROZEN_ORDINARY_FUTURE_FIELD_MATRIX_STATUS": "PASS" if frozen_ok else "FAIL",
        "HTTP_PRESENCE_SCENARIO_IDENTITY_STATUS": "PASS" if identity_ok and required_scenarios <= scenario_set else "FAIL",
        "FORBIDDEN_REQUEST_MODEL_EXECUTION_AUDIT_STATUS": "PASS" if zeros else "FAIL",
        "frozen_controls": frozen_controls,
        "cases": cases,
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
