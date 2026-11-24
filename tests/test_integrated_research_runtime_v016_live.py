"""Live tests — Integrated Research Runtime Foundation v0.1.6 (after run)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from human_simulator.integrated_research_runtime_v016.connectors import SourceAConnector, SourceBConnector, build_registry
from human_simulator.integrated_research_runtime_v016.hashes import sha256_file
from human_simulator.integrated_research_runtime_v016.policy import ARTIFACT_DIR, PRIOR_ZIPS, V031_MATERIALIZED
from human_simulator.integrated_research_runtime_v016.privacy import scan_public
from human_simulator.integrated_research_runtime_v016.report_reconciliation import assert_artifact_dir_reconciled

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ARTIFACT_DIR


def _st() -> dict:
    p = ART / "status-contract.json"
    if not p.is_file():
        pytest.skip("runtime artifacts not built")
    return json.loads(p.read_text(encoding="utf-8"))


def test_prior_zips_byte_for_byte():
    external = ROOT / "artifacts/external-review"
    for _label, (name, exp) in PRIOR_ZIPS.items():
        p = external / name
        assert p.is_file()
        assert sha256_file(p) == exp


def test_phase0_artifacts_exist():
    if not ART.is_dir():
        pytest.skip("not run")
    for name in (
        "v015-evidence-accounting-defect-reproduction.json",
        "v015-forbidden-execution-audit-defect.json",
        "v015-http-frozen-ordinary-matrix-defect.json",
        "v015-final-report-status-reconciliation-defect.json",
        "v016-runtime-acceptance-matrix.json",
        "final-report-status-reconciliation.json",
        "field-presence-contract-matrix.json",
        "direct-api-future-field-presence-audit.json",
        "live-http-future-field-presence-audit.json",
        "frozen-provider-identities.json",
        "prior-zip-sha-before.json",
        "prior-zip-sha-after.json",
        "tests-report.json",
        "baseline-verification.json",
    ):
        assert (ART / name).is_file()


def test_status_non_claims_and_required_keys():
    st = _st()
    assert st["SCIENTIFIC_CROSS_SOURCE_PASS"] is False
    assert st["DOMAIN_ACCEPTED_MAPPING_COUNT"] == 0
    assert st["JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT"] == 0
    assert st["D1_JOINT_DEPENDENCE_STATUS"] == "NOT_ACCEPTED"
    assert st["CROSS_HORIZON_DEPENDENCE_STATUS"] == "NOT_ESTABLISHED"
    assert st["PRODUCTION_READINESS"] == "NOT_CLAIMED"
    assert st["SECURITY_STAGE_STATUS"] == "PAUSED_NOT_ACCEPTED_BY_OWNER"
    assert st["AUTOMATED_EXTERNAL_CONTACT_STATUS"] == "NOT_RUN"
    assert st["IROS_PROVIDER_COMMITMENT_STATUS"] == "NOT_ESTABLISHED"
    assert st["CLINICAL_SOURCE_SYSTEM_COUNT"] == 2
    assert st["PUBLICATION_INTEGRITY_STATUS"] == "DETACHED_SIDECAR_AUTHORITATIVE"
    assert st["TEST_ACCESS_LIFECYCLE_STATUS"] == "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED"
    assert st["e2e_scope"] == "NHR_P0_D0_HTTP_WORKBENCH"
    assert st["STATE_CONDITIONED_LEP_STATUS"] == "NOT_IMPLEMENTED"
    assert st["LEP_ROUTE_BOUNDARY_STATUS"] == "PASS"
    assert st["V015_RUNTIME_FUTURE_FIELD_CONTRACT_STATUS"] == "PASS"
    assert st["V015_REVIEW_EVIDENCE_STATUS"] == "CORRECTION_REQUIRED"
    assert st["FORBIDDEN_REQUEST_MODEL_EXECUTION_AUDIT_STATUS"] == "PASS"
    assert st["HTTP_FROZEN_ORDINARY_FUTURE_FIELD_MATRIX_STATUS"] == "PASS"
    assert st["HTTP_PRESENCE_SCENARIO_IDENTITY_STATUS"] == "PASS"
    assert st["FALSEY_FUTURE_FIELD_REJECTION_STATUS"] == "PASS"
    assert st["FUTURE_FIELD_PRESENCE_CONTRACT_STATUS"] == "PASS"
    assert st["HTTP_EXPLICIT_FIELD_PRESENCE_STATUS"] == "PASS"
    for key in (
        "TEMPORAL_TIMESTAMP_VERIFICATION_STATUS",
        "DECLARED_PRE_T0_SUMMARY_STATUS",
        "ENGINE_FUTURE_INFORMATION_LEAKAGE_STATUS",
        "SOURCE_NAMESPACE_BINDING_STATUS",
        "PER_OUTCOME_IDENTITY_COMPLETENESS_STATUS",
        "SOURCE_A_FROZEN_INFERENCE_STATUS",
        "SOURCE_B_FROZEN_INFERENCE_STATUS",
        "FROZEN_LEP_REFERENCE_PROBE_STATUS",
        "STATE_CONDITIONED_LEP_STATUS",
        "LEP_ROUTE_BOUNDARY_STATUS",
        "JOINT_PANEL_ROW_ACCOUNTING_STATUS",
        "JOINT_PANEL_COUNT_BRIDGE_STATUS",
        "WORKBENCH_BROWSER_INTEGRATION_STATUS",
        "END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS",
        "PUBLIC_DATA_MINIMIZATION_STATUS",
        "PUBLICATION_INTEGRITY_STATUS",
        "FORBIDDEN_REQUEST_MODEL_EXECUTION_AUDIT_STATUS",
        "HTTP_FROZEN_ORDINARY_FUTURE_FIELD_MATRIX_STATUS",
        "HTTP_PRESENCE_SCENARIO_IDENTITY_STATUS",
        "FINAL_REPORT_STATUS_RECONCILIATION_STATUS",
        "V015_RUNTIME_FUTURE_FIELD_CONTRACT_STATUS",
        "V015_REVIEW_EVIDENCE_STATUS",
    ):
        assert key in st
    if st["WORKBENCH_BROWSER_INTEGRATION_STATUS"] != "PASS":
        assert st["END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS"] == "NOT_ACCEPTED"
    if st["TEMPORAL_TIMESTAMP_VERIFICATION_STATUS"] != "PASS":
        assert st["END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS"] == "NOT_ACCEPTED"
    if st["SOURCE_A_FROZEN_INFERENCE_STATUS"] != "PASS" or st["SOURCE_B_FROZEN_INFERENCE_STATUS"] != "PASS":
        assert st["END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS"] == "NOT_ACCEPTED"


def test_source_connectors_are_filtered():
    parquet = ROOT / V031_MATERIALIZED / "research_observation_component.parquet"
    if not parquet.is_file():
        pytest.skip("materialized layer absent")
    a = SourceAConnector(ROOT).probe()
    b = SourceBConnector(ROOT).probe()
    assert a.get("availability_status") == "CONNECTED_MATERIALIZED_READ_ONLY"
    assert b.get("availability_status") == "CONNECTED_MATERIALIZED_READ_ONLY"
    assert a["health"]["read_is_source_filtered"] is True
    assert b["health"]["read_is_source_filtered"] is True
    assert a["health"]["foreign_source_not_returned_as_this_connector"] is True
    assert b["health"]["foreign_source_not_returned_as_this_connector"] is True
    assert a["health"]["n_rows_expected_source"] > 0
    assert b["health"]["n_rows_expected_source"] > 0
    reg = build_registry(ROOT)
    assert reg["CLINICAL_SOURCE_SYSTEM_COUNT"] == 2
    assert reg["unified_layer_not_a_third_clinical_source"]
    assert reg["SOURCE_CONNECTOR_FILTERED_READ_STATUS"] == "PASS"


def test_privacy_scan_pass():
    if not ART.is_dir():
        pytest.skip("not run")
    scan = scan_public(ART)
    assert scan["ok"], scan
    assert scan["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"


def test_http_matrix_seven_scenario_classes_and_zero_forbidden_counters():
    if not ART.is_dir():
        pytest.skip("not run")
    matrix = json.loads((ART / "live-http-future-field-presence-matrix.json").read_text(encoding="utf-8"))
    required = {
        "nhr_forecast",
        "nhr_joint",
        "nhr_rollout",
        "nhr_replay",
        "synthetic_ordinary_lep",
        "frozen_ordinary_lep",
        "frozen_reference_probe",
    }
    assert required <= set(matrix.get("scenario_classes") or [])
    assert matrix.get("n_cases") == len(matrix.get("cases") or [])
    assert matrix.get("n_cases") == matrix.get("n_pass")
    assert matrix.get("residual_calls_on_forbidden") == 0
    assert matrix.get("infer_calls_on_forbidden") == 0
    assert matrix.get("model_execution_calls_on_forbidden") == 0
    assert matrix.get("HTTP_FROZEN_ORDINARY_FUTURE_FIELD_MATRIX_STATUS") == "PASS"
    assert matrix.get("HTTP_PRESENCE_SCENARIO_IDENTITY_STATUS") == "PASS"
    frozen = [
        c
        for c in matrix.get("cases") or []
        if c.get("scenario_class") == "frozen_ordinary_lep" and c.get("presence_kind") == "present"
    ]
    assert frozen
    assert all(c.get("namespace") == "SOURCE_B" and c.get("source_system") == "kgz_raw" for c in frozen)


def test_final_report_status_reconciliation():
    if not ART.is_dir():
        pytest.skip("not run")
    recon = assert_artifact_dir_reconciled(ART)
    assert recon["ok"], recon
    assert recon["FINAL_REPORT_STATUS_RECONCILIATION_STATUS"] == "PASS"
    report = (ART / "stage-report.md").read_text(encoding="utf-8")
    if "Report status: FINAL" in report:
        assert "PENDING_SCAN" not in report
        assert "PENDING_PUBLISH" not in report
        assert "Report status: DRAFT" not in report
    st = _st()
    assert st["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
    assert st["PUBLICATION_INTEGRITY_STATUS"] == "DETACHED_SIDECAR_AUTHORITATIVE"
