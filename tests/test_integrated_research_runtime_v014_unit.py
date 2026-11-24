"""Unit tests — Integrated Research Runtime Foundation v0.1.4."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from human_simulator.integrated_research_runtime_v014.accounting import reconcile, recount_origins, synthetic_accounting
from human_simulator.integrated_research_runtime_v014.composition import compose_joint_distribution, parse_aware_datetime
from human_simulator.integrated_research_runtime_v014.connectors import _filtered_source_counts
from human_simulator.integrated_research_runtime_v014.defects import run_phase0
from human_simulator.integrated_research_runtime_v014.fixtures import (
    synthetic_request,
    synthetic_runtime_bundle,
    timestamp_verified_request,
)
from human_simulator.integrated_research_runtime_v014.http_app import LocalServer, ResearchApp
from human_simulator.integrated_research_runtime_v014.http_client import HttpClient
from human_simulator.integrated_research_runtime_v014.labels import append_label, technical_cannot_become_clinical
from human_simulator.integrated_research_runtime_v014.policy import HTTP_HOST, PRIOR_ZIPS, SOURCE_A, SYN_OUTCOMES, VERSION
from human_simulator.integrated_research_runtime_v014.privacy import scan_public
from human_simulator.integrated_research_runtime_v014.probability import (
    HTTP_ROUTE_PROBE,
    HTTP_ROUTE_STATE,
    REASON_ADAPTER,
    REASON_CLIENT_VECTOR,
    REASON_PROBE_URL,
    SYN_FEATURE_ORDER_SHA256,
    SYN_MODEL_ID,
    execute_event_probability,
)
from human_simulator.integrated_research_runtime_v014.qsp import execute_qsp
from human_simulator.integrated_research_runtime_v014.scale import ScaleMissingError, scale_value
from human_simulator.integrated_research_runtime_v014.workbench import render_workbench
from human_simulator.longitudinal_event_probability_v0211.estimators import feature_order_hash
from human_simulator.longitudinal_event_probability_v0211.policy import FEATURE_ORDER

ROOT = Path(__file__).resolve().parents[1]


def _clinical(mid: str = "c" * 64) -> dict:
    return {
        "namespace": "SOURCE_B",
        "source_system": "kgz_raw",
        "endpoint": "TIME_TO_NEXT_LAB_PANEL",
        "requested_horizon_days": 90,
        "model_id": mid,
        "feature_order_sha256": feature_order_hash(list(FEATURE_ORDER)),
        "cutoff_t0": "2000-01-01T00:00:00Z",
        "state_at_t0": {"history_depth": 2},
    }


def test_version_and_prior_pins():
    assert VERSION == "0.1.4"
    assert PRIOR_ZIPS["irr_v013"][1] == "351febd77c018dacf1f04117d2a9a11d6022749d8c34b9f1f4a0c3514eaafa65"
    assert PRIOR_ZIPS["irr_v012"][1] == "2e0e7e8efa6b563c4363b34e4b040738c7d8e58de864c1ee83a819cd57ead7e3"


def test_phase0_v013_lep_defects_reproduced():
    p0 = run_phase0(ROOT)
    assert p0["n_defects"] == 2
    assert p0["n_reproduced"] == 2
    assert p0["ok"]
    ids = [d["id"] for d in p0["defects"]]
    assert ids == [1, 2]
    assert all(d["reproduced"] for d in p0["defects"])
    d1 = p0["defects"][0]
    assert d1["routing_status_REFERENCE_FEATURE_PROBE"]["check"] == "routing_status_not_frozen_model_execution"
    assert d1["routing_status_lep_input_mode"]["check"] == "routing_status_not_frozen_model_execution"


def test_timezone_aware_timestamps():
    bundle = synthetic_runtime_bundle()
    ok0, ok1 = SYN_OUTCOMES
    assert parse_aware_datetime("2019-12-31T23:00:00-02:00").isoformat().startswith("2020-01-01T01:00:00")
    same = timestamp_verified_request(
        history_timestamps={ok0: ["2020-01-01T03:00:00+03:00"], ok1: ["2019-12-31T21:00:00-03:00"]}
    )
    out_same = compose_joint_distribution(same, bundle)
    assert out_same["status"] == "OK"
    assert out_same["TEMPORAL_EVIDENCE_TIER"] == "TIMESTAMP_VERIFIED"
    after = timestamp_verified_request(
        history_timestamps={ok0: ["2020-01-01T00:00:01Z"], ok1: ["2020-01-01T00:00:01Z"]}
    )
    assert compose_joint_distribution(after, bundle)["reason"] == "HISTORY_TIMESTAMP_AFTER_CUTOFF_T0"
    offset_future = timestamp_verified_request(
        history_timestamps={ok0: ["2019-12-31T23:00:00-02:00"], ok1: ["2019-12-31T23:00:00-02:00"]}
    )
    fut = compose_joint_distribution(offset_future, bundle)
    assert fut["reason"] == "HISTORY_TIMESTAMP_AFTER_CUTOFF_T0"
    naive = timestamp_verified_request(history_timestamps={ok0: ["2019-12-31T23:00:00"], ok1: ["2019-12-31T23:00:00"]})
    assert compose_joint_distribution(naive, bundle)["reason"] == "TIMESTAMP_NAIVE_TIMEZONE_REQUIRED"
    declared = compose_joint_distribution(synthetic_request(), bundle)
    assert declared["TEMPORAL_EVIDENCE_TIER"] == "DECLARED_PRE_T0_SUMMARY"
    verified = compose_joint_distribution(timestamp_verified_request(), bundle)
    assert verified["TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"] == "PASS"


def test_source_namespace_and_identity_completeness():
    bundle = synthetic_runtime_bundle()
    req = synthetic_request()
    bad_ns = deepcopy(req)
    bad_ns["namespace"] = "SOURCE_B"
    assert compose_joint_distribution(bad_ns, bundle)["reason"] == "SOURCE_NAMESPACE_MISMATCH"
    ok0 = SYN_OUTCOMES[0]
    no_unit = deepcopy(req)
    no_unit["cell_identities"][ok0].pop("unit")
    assert compose_joint_distribution(no_unit, bundle)["reason"] == "MISSING_UNIT"
    src = deepcopy(req)
    src["source_system"] = SOURCE_A
    src["namespace"] = "SOURCE_A"
    assert compose_joint_distribution(src, bundle)["reason"] == "SYNTHETIC_PROVIDER_FORBIDDEN_FOR_CLINICAL_SOURCE"


def test_v014_rejects_identity_mutations():
    bundle = synthetic_runtime_bundle()
    req = synthetic_request()
    ok0 = SYN_OUTCOMES[0]
    for field, reason in (
        ("active_payload_sha256", "MODEL_HASH_MISMATCH"),
        ("feature_order_sha256", "FEATURE_ORDER_HASH_MISMATCH"),
        ("scaler_sha256", "SCALER_HASH_MISMATCH"),
        ("residual_distribution_sha256", "RESIDUAL_HASH_MISMATCH"),
    ):
        mut = deepcopy(req)
        mut["cell_identities"][ok0][field] = "0" * 64
        out = compose_joint_distribution(mut, bundle)
        assert out["status"] == "FAIL"
        assert out["reason"] == reason


def test_v014_no_silent_p0_and_requires_cutoff():
    bundle = synthetic_runtime_bundle()
    p1 = deepcopy(bundle)
    p1["cells"][SYN_OUTCOMES[0]]["active_provider"] = "P1"
    p1["cells"][SYN_OUTCOMES[0]]["p1_payload"] = None
    assert compose_joint_distribution(synthetic_request(), p1)["reason"] == "P1_PAYLOAD_MISSING"
    no_cut = dict(synthetic_request())
    no_cut.pop("cutoff_t0")
    assert compose_joint_distribution(no_cut, bundle)["reason"] == "CUTOFF_T0_REQUIRED"
    assert compose_joint_distribution(synthetic_request(t1=True), bundle)["reason"] == "FUTURE_INFORMATION_LEAKAGE"
    assert compose_joint_distribution(synthetic_request(force_d1=True), bundle)["reason"] == "D1_NOT_ACCEPTED"


def test_synthetic_event_probability_still_works():
    out = execute_event_probability(
        {
            "namespace": "SYNTHETIC_FIXTURE",
            "source_system": "synthetic",
            "endpoint": "TIME_TO_NEXT_LAB_PANEL",
            "requested_horizon_days": 90,
            "model_id": SYN_MODEL_ID,
            "feature_order_sha256": SYN_FEATURE_ORDER_SHA256,
            "cutoff_t0": "2000-01-01T00:00:00Z",
            "state_at_t0": {"history_depth": 2},
        }
    )
    assert out["executed"] is True
    assert out["route"] == "SYNTHETIC_FIXTURE"


def test_ordinary_lep_abstains_without_verified_adapter():
    infer = MagicMock()
    with patch("human_simulator.longitudinal_event_probability_v0211.engine.infer", infer):
        out = execute_event_probability(_clinical(), root=ROOT, http_route=HTTP_ROUTE_STATE)
    assert out["status"] == "ABSTAIN"
    assert out["reason"] == REASON_ADAPTER
    assert out["STATE_CONDITIONED_LEP_STATUS"] == "NOT_IMPLEMENTED"
    assert out["state_conditioned"] is False
    assert out["infer_called"] is False
    infer.assert_not_called()


def test_client_feature_vector_is_not_state_conditioned_pass():
    infer = MagicMock()
    dummy = [float(i + 1) for i in range(len(FEATURE_ORDER))]
    keys = {k: float(i + 1) for i, k in enumerate(FEATURE_ORDER)}
    with patch("human_simulator.longitudinal_event_probability_v0211.engine.infer", infer):
        feat = execute_event_probability({**_clinical(), "features": dummy}, root=ROOT, http_route=HTTP_ROUTE_STATE)
        keyed = execute_event_probability({**_clinical(), "state_at_t0": keys}, root=ROOT, http_route=HTTP_ROUTE_STATE)
    for out in (feat, keyed):
        assert out["status"] == "ABSTAIN"
        assert out["reason"] == REASON_CLIENT_VECTOR
        assert out["STATE_CONDITIONED_LEP_STATUS"] == "NOT_IMPLEMENTED"
        assert out["state_conditioned"] is not True
        assert out.get("infer_called") is not True
    infer.assert_not_called()


def test_body_cannot_select_reference_probe_on_ordinary_route():
    infer = MagicMock()
    with patch("human_simulator.longitudinal_event_probability_v0211.engine.infer", infer):
        flag = execute_event_probability(
            {**_clinical(), "REFERENCE_FEATURE_PROBE": True},
            root=ROOT,
            http_route=HTTP_ROUTE_STATE,
        )
        mode = execute_event_probability(
            {**_clinical(), "lep_input_mode": "REFERENCE_FEATURE_PROBE"},
            root=ROOT,
            http_route=HTTP_ROUTE_STATE,
        )
    assert flag["status"] == "FAIL" and flag["reason"] == REASON_PROBE_URL
    assert mode["status"] == "FAIL" and mode["reason"] == REASON_PROBE_URL
    infer.assert_not_called()


def test_ordinary_lep_cutoff_rejects_future_and_naive():
    future = execute_event_probability({**_clinical(), "t1": "2020-01-02T00:00:00Z"}, root=ROOT, http_route=HTTP_ROUTE_STATE)
    t2 = execute_event_probability({**_clinical(), "t2": True}, root=ROOT, http_route=HTTP_ROUTE_STATE)
    naive = execute_event_probability({**_clinical(), "cutoff_t0": "2000-01-01T00:00:00"}, root=ROOT, http_route=HTTP_ROUTE_STATE)
    assert future["reason"] == "FUTURE_INFORMATION_LEAKAGE"
    assert t2["reason"] == "FUTURE_INFORMATION_LEAKAGE"
    assert naive["reason"] == "TIMESTAMP_NAIVE_TIMEZONE_REQUIRED"
    assert future.get("TEMPORAL_TIMESTAMP_VERIFICATION_STATUS") != "PASS"


def test_http_4xx_fail_vs_422_abstain_and_url_selected_probe():
    with LocalServer(ResearchApp(root=ROOT)) as srv:
        c = HttpClient(HTTP_HOST, srv.port)
        req = synthetic_request(include_paths=True)
        joint = c.request("POST", "/research/joint-outcome-distribution", req)
        assert joint["status"] == "OK"
        body = c.request("POST", "/research/event-probability", {**_clinical(), "REFERENCE_FEATURE_PROBE": True})
        mode = c.request("POST", "/research/event-probability", {**_clinical(), "lep_input_mode": "REFERENCE_FEATURE_PROBE"})
        feats = c.request(
            "POST",
            "/research/event-probability",
            {**_clinical(), "features": [float(i + 1) for i in range(len(FEATURE_ORDER))]},
        )
        keys = c.request(
            "POST",
            "/research/event-probability",
            {**_clinical(), "state_at_t0": {k: float(i + 1) for i, k in enumerate(FEATURE_ORDER)}},
        )
        abs_out = c.request("POST", "/research/event-probability", _clinical())
        assert body["http_status"] == 400 and body["status"] == "FAIL" and body["reason"] == REASON_PROBE_URL
        assert mode["http_status"] == 400 and mode["reason"] == REASON_PROBE_URL
        assert feats["http_status"] == 422 and feats["status"] == "ABSTAIN" and feats["reason"] == REASON_CLIENT_VECTOR
        assert keys["http_status"] == 422 and keys["reason"] == REASON_CLIENT_VECTOR
        assert abs_out["http_status"] == 422 and abs_out["reason"] == REASON_ADAPTER
        assert abs_out["STATE_CONDITIONED_LEP_STATUS"] == "NOT_IMPLEMENTED"
        syn = c.request(
            "POST",
            "/research/event-probability",
            {
                "namespace": "SYNTHETIC_FIXTURE",
                "source_system": "synthetic",
                "endpoint": "TIME_TO_NEXT_LAB_PANEL",
                "requested_horizon_days": 90,
                "model_id": SYN_MODEL_ID,
                "feature_order_sha256": SYN_FEATURE_ORDER_SHA256,
                "cutoff_t0": "2000-01-01T00:00:00Z",
                "state_at_t0": {"history_depth": 2},
            },
        )
        assert syn["route"] == "SYNTHETIC_FIXTURE"
        probe = c.request("POST", "/research/event-probability/reference-probe", _clinical())
        assert probe.get("http_route") == HTTP_ROUTE_PROBE or probe.get("route") == "FROZEN_LEP_REFERENCE_PROBE" or probe.get("reason") in {
            "LEP_PROVIDER_UNAVAILABLE",
            "MODEL_HASH_MISMATCH",
            "FEATURE_ORDER_HASH_MISMATCH",
            "CELL_NOT_FOUND",
        }


def test_qsp_real_intervention_unavailable():
    ok = execute_qsp({"model_id": "SYNTHETIC_REFERENCE_COMPOUND_X_PKPD"})
    assert ok["synthetic_only"] is True
    blocked = execute_qsp({"medication": "real", "dose": 4})
    assert blocked["reason"] == "INTERVENTION_EFFECT_UNAVAILABLE"


def test_workbench_distinguishes_probe_and_abstention_and_is_not_the_browser_gate():
    html = render_workbench()
    assert "fetch(" in html
    assert "btn-lep-probe" in html
    assert "btn-lep-abstain" in html
    assert "btn-lep-body-probe" in html
    assert "reference-probe" in html
    assert "TEMPORAL_EVIDENCE_TIER" in html


def test_panel_unexplained_computed_not_leftover():
    syn = synthetic_accounting()
    assert syn["unexplained"] == 0
    broken = reconcile({**syn["row_counts"], "excluded_invalid_rows": 0, "deterministic_selected_rows": 14})
    assert broken["unexplained"] != 0


def test_panel_skip_row_classification_breaks_conservation(tmp_path: Path):
    table = pa.table(
        {
            "source_system": ["synthetic", "synthetic", "synthetic", "synthetic"],
            "outcome_key": ["SYN::alpha::au", "SYN::beta::au", "SYN::alpha::au", "SYN::gamma::au"],
            "requested_horizon_days": [90, 90, 90, 90],
            "source_scoped_subject_id": ["s1", "s1", "s2", "s2"],
            "t0_iso": ["t", "t", "t", "t"],
            "target_id": ["a", "b", "c", "d"],
            "split_role": ["train", "train", "train", "train"],
            "actual_recorded_label_offset_days": [90.0, 90.0, 90.0, 90.0],
        }
    )
    path = tmp_path / "origins.parquet"
    pq.write_table(table, path)
    vocab = {("synthetic", "SYN::alpha::au", 90), ("synthetic", "SYN::beta::au", 90), ("synthetic", "SYN::gamma::au", 90)}
    live = recount_origins(path, vocab)
    assert live["exclusive_classification"] is True
    counts = live["row_counts"]
    tagged = (
        counts["strict_panel_membership_rows"]
        + counts["asynchronous_vector_membership_rows"]
        + counts["single_outcome_group_membership_rows"]
        + counts["excluded_invalid_rows"]
    )
    assert tagged == counts["deterministic_selected_rows"]


def test_filtered_connector_excludes_foreign_source(tmp_path: Path):
    table = pa.table({"source_system": ["magerya_api", "magerya_api", "kgz_raw"]})
    path = tmp_path / "obs.parquet"
    pq.write_table(table, path)
    a = _filtered_source_counts(path, "magerya_api")
    assert a["n_rows_returned"] == 2
    assert a["foreign_source_not_returned_as_this_connector"] is True


def test_label_append_only_not_clinical():
    reg = append_label([], {"label_id": "x", "status": "CANDIDATE_TECHNICAL_LABEL", "clinical": True, "technical": True})
    assert reg[0]["clinical"] is False
    assert technical_cannot_become_clinical(reg)


def test_scale_missing_hard_fail():
    with pytest.raises(ScaleMissingError):
        scale_value({"train_scales": {}}, "synthetic", SYN_OUTCOMES[0], 1.0)


def test_privacy_scan_empty_dir(tmp_path: Path):
    assert scan_public(tmp_path)["ok"]
