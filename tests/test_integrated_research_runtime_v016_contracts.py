"""Contract tests — Integrated Research Runtime Foundation v0.1.6."""

from __future__ import annotations

from pathlib import Path

from human_simulator.cross_source_lab_semantic_v021.publish import mutation_proof, verify_manifest, write_manifest
from human_simulator.integrated_research_runtime_v016.policy import (
    PRIOR_ZIPS,
    REVIEW_ZIP,
    V014_EXPECTED_INDEXED,
    V014_EXPECTED_MEMBERS,
    V014_EXPECTED_SHA256,
    V015_EXPECTED_INDEXED,
    V015_EXPECTED_MEMBERS,
    V015_EXPECTED_SHA256,
)
from human_simulator.integrated_research_runtime_v016.privacy import scan_public

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src/human_simulator/integrated_research_runtime_v016"


def test_v015_zip_not_rewritten_by_this_package():
    text = (SRC / "publish.py").read_text(encoding="utf-8")
    pol = (SRC / "policy.py").read_text(encoding="utf-8")
    assert "stage-04-uhbse-integrated-research-runtime-foundation-v0.1.5-review.zip" in pol
    assert "refuse overwrite" in text
    assert "testzip" in text
    assert "duplicate members" in text
    assert "unsafe member path" in text
    assert REVIEW_ZIP.endswith("v0.1.6-review.zip")
    assert V015_EXPECTED_SHA256 == PRIOR_ZIPS["irr_v015"][1]
    assert V015_EXPECTED_MEMBERS == 991
    assert V015_EXPECTED_INDEXED == 990
    assert V014_EXPECTED_SHA256 == PRIOR_ZIPS["irr_v014"][1]
    assert V014_EXPECTED_MEMBERS == 956
    assert V014_EXPECTED_INDEXED == 955
    assert "v0.1.5-review.zip" not in REVIEW_ZIP
    assert "v0.1.6-review.zip" not in pol.split("REVIEW_ZIP")[0]
    for frozen in ("v0.1.5-review.zip", "v0.1.4-review.zip", "v0.1.3-review.zip", "v0.1.2-review.zip", "v0.1.1-review.zip"):
        assert frozen not in REVIEW_ZIP


def test_open_test_does_not_reopen_heldout():
    pol = (SRC / "policy.py").read_text(encoding="utf-8")
    orch = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    assert "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED" in pol
    assert "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED" in orch
    assert "recomputed_joint_gates" in orch


def test_runtime_gates_are_not_string_presence_or_constants():
    for name in ("orchestrator.py", "http_app.py", "composition.py", "engine.py", "future_fields.py"):
        src = (SRC / name).read_text(encoding="utf-8")
        assert " or True" not in src
    orch = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    assert "browser_status == \"PASS\"" in orch
    assert "SOURCE_A_FROZEN_INFERENCE_STATUS\") == \"PASS\"" in orch
    assert "timestamp_verified_http" in orch
    assert "NHR_P0_D0_HTTP_WORKBENCH" in orch
    assert "STATE_CONDITIONED_LEP_STATUS\") == \"NOT_IMPLEMENTED\"" in orch
    assert "persist_stage_report" in orch
    assert 'report.replace("Report status: DRAFT", "Report status: FINAL")' not in orch
    presence = (SRC / "presence_audit.py").read_text(encoding="utf-8")
    assert "residual_calls_on_forbidden" in presence
    assert "residual_called_on_forbidden" not in presence
    assert "frozen_ordinary_lep" in presence
    assert "scenario_class" in presence
    recon = (SRC / "report_reconciliation.py").read_text(encoding="utf-8")
    assert "PENDING_SCAN" in recon
    assert "FINAL_REPORT_STATUS_RECONCILIATION_STATUS" in recon
    http = (SRC / "http_app.py").read_text(encoding="utf-8")
    assert "send_header(\"Access-Control-Allow-Origin\"" not in http
    assert "Access-Control-Allow-Origin: *" not in http
    assert "cors is None" in http
    wb_tests = (ROOT / "tests/test_integrated_research_runtime_v016_unit.py").read_text(encoding="utf-8")
    assert 'assert "fetch(" in html' in wb_tests
    assert "run_browser_audit" not in wb_tests


def test_presence_contract_is_shared_and_not_truthiness():
    fut = (SRC / "future_fields.py").read_text(encoding="utf-8")
    comp = (SRC / "composition.py").read_text(encoding="utf-8")
    prob = (SRC / "probability.py").read_text(encoding="utf-8")
    http = (SRC / "http_app.py").read_text(encoding="utf-8")
    schemas = (SRC / "schemas.py").read_text(encoding="utf-8")
    assert "def future_information_contract" in fut
    assert "if name in keys" in fut
    assert "request.get(\"t1\")" not in comp
    assert "request.get(\"t2\")" not in prob.split("def _cutoff_contract")[1].split("def synthetic_event_probability")[0]
    assert "future_information_contract(body, present=set(body.keys()))" in http
    assert "model_dump(exclude_unset=True)" in schemas
    assert "model_dump(exclude_none=False)" not in schemas
    assert "_provided_fields" not in http
    assert "value is True" in fut
    assert "value is False" in fut


def test_lep_route_is_url_selected_and_client_vector_is_not_an_adapter():
    prob = (SRC / "probability.py").read_text(encoding="utf-8")
    http = (SRC / "http_app.py").read_text(encoding="utf-8")
    assert "http_route" in prob
    assert "HTTP_ROUTE_PROBE" in prob
    assert "REASON_PROBE_URL" in prob
    assert "LEP_CLIENT_VECTOR_IS_NOT_VERIFIED_STATE_ADAPTER" in prob
    assert "LEP_STATE_ADAPTER_NOT_IMPLEMENTED" in prob
    assert "execute_event_probability(parsed, root=self.root, http_route=HTTP_ROUTE_STATE)" in http
    assert "execute_event_probability(parsed, root=self.root, http_route=HTTP_ROUTE_PROBE)" in http
    assert '{**body, "REFERENCE_FEATURE_PROBE": True' not in http
    state_fn = prob.split("def execute_state_conditioned_lep")[1].split("def execute_event_probability")[0]
    assert "feats = _in_support_features" not in state_fn
    assert "_run_infer" not in state_fn
    assert "STATE_CONDITIONED_LEP_STATUS\": \"PASS\"" not in state_fn


def test_composition_is_timezone_aware_with_bound_identity():
    comp = (SRC / "composition.py").read_text(encoding="utf-8")
    assert "parse_aware_datetime" in comp
    assert "SOURCE_NAMESPACE_MISMATCH" in comp
    assert "HISTORY_TIMESTAMP_AFTER_CUTOFF_T0" in comp
    assert "TIMESTAMP_NAIVE_TIMEZONE_REQUIRED" in comp
    assert "str(t) > str(cutoff)" not in comp
    assert "IDENTITY_REQUIRED_FIELDS" in comp
    acc = (SRC / "accounting.py").read_text(encoding="utf-8")
    assert "EXPLAINED_DEFINITION_AND_UNIVERSE" not in acc
    assert "n_gained_panel_keys" in acc


def test_connectors_and_accounting_contracts():
    conn = (SRC / "connectors.py").read_text(encoding="utf-8")
    acc = (SRC / "accounting.py").read_text(encoding="utf-8")
    assert "CLINICAL_SOURCE_SYSTEM_COUNT" in conn
    assert "read_is_source_filtered" in conn
    assert "invalid = leftover" not in acc
    pub = (SRC / "publish.py").read_text(encoding="utf-8")
    assert "DETACHED_SIDECAR_AUTHORITATIVE" in pub
    assert "PUBLICATION_INTEGRITY_STATUS\"] = \"PASS\"" not in (SRC / "orchestrator.py").read_text(encoding="utf-8")


def test_indexed_file_mutation_is_detected(tmp_path: Path):
    art = tmp_path / "art"
    art.mkdir()
    (art / "status-contract.json").write_text('{"ok": true}\n', encoding="utf-8")
    (art / "tests.json").write_text('{"passed": 1}\n', encoding="utf-8")
    write_manifest(art)
    assert verify_manifest(art)["ok"]
    proof = mutation_proof(art)
    assert proof["ok"] is True
    assert proof["after_mutation_ok"] is False


def test_public_artifact_dir_scan_when_present():
    art = ROOT / "artifacts/stage-04-uhbse-integrated-research-runtime-foundation-v0.1.6"
    if art.is_dir() and any(art.iterdir()):
        scan = scan_public(art)
        assert scan["ok"], scan
