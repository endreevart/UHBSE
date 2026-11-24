"""Live tests — Integrated Research Runtime Foundation v0.1.4 (after run)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from human_simulator.integrated_research_runtime_v014.connectors import SourceAConnector, SourceBConnector, build_registry
from human_simulator.integrated_research_runtime_v014.hashes import sha256_file
from human_simulator.integrated_research_runtime_v014.policy import ARTIFACT_DIR, PRIOR_ZIPS, V031_MATERIALIZED
from human_simulator.integrated_research_runtime_v014.privacy import scan_public

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
        "v013-lep-route-defect-reproduction.json",
        "v013-body-selects-reference-probe-defect.json",
        "v013-client-vector-state-conditioned-pass-defect.json",
        "v013-runtime-acceptance-matrix.json",
        "frozen-provider-identities.json",
        "prior-zip-sha-before.json",
        "prior-zip-sha-after.json",
    ):
        assert (ART / name).is_file()


def test_status_non_claims_and_required_keys():
    st = _st()
    assert st["SCIENTIFIC_CROSS_SOURCE_PASS"] is False
    assert st["DOMAIN_ACCEPTED_MAPPING_COUNT"] == 0
    assert st["JOINT_VALIDATION_ACCEPTED_ROUTE_COUNT"] == 0
    assert st["D1_JOINT_DEPENDENCE_STATUS"] == "NOT_ACCEPTED"
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
