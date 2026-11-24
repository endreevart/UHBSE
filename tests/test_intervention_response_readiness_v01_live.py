"""Live tests — require Stage 05 artifacts after run-v0.1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from human_simulator.intervention_response_readiness_v01.policy import ARTIFACT_DIR, PRIOR_ZIPS, REQUIRED_ARTIFACTS
from human_simulator.intervention_response_readiness_v01.privacy import scan_public
from human_simulator.intervention_response_readiness_v01.reconciliation import assert_artifact_dir_reconciled

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ARTIFACT_DIR


def test_required_artifacts_and_statuses() -> None:
    assert ART.is_dir()
    for name in REQUIRED_ARTIFACTS:
        assert (ART / name).is_file(), name
    status = json.loads((ART / "status-contract.json").read_text(encoding="utf-8"))
    assert status["DOMAIN_ACCEPTED_MAPPING_COUNT"] == 0
    assert status["CONFIRMED_ADMINISTRATION_MAPPING_COUNT"] == 0
    assert status["TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT"] == 0
    assert status["ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0
    assert status["ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0
    assert status["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
    assert status["INTERVENTION_RESPONSE_MODEL_STATUS"] == "NOT_STARTED"
    assert status["TREATMENT_EFFECT_STATUS"] == "NOT_STARTED"
    assert status["CAUSAL_EFFECT_STATUS"] == "NOT_STARTED"
    assert status["SCIENTIFIC_CROSS_SOURCE_PASS"] is False
    assert status["CLINICAL_VALIDATION_STATUS"] == "NOT_STARTED"
    assert status["PRODUCTION_READINESS"] == "NOT_CLAIMED"
    assert status["SECURITY_STAGE_STATUS"] == "PAUSED_NOT_ACCEPTED_BY_OWNER"
    assert status["MEDICATION_RESIDUAL_CONSUMPTION_STATUS"] == "NOT_CONSUMED"
    assert status["TECHNICAL_AUDIT_STATUS"] == "PASS"
    assert status["PUBLICATION_INTEGRITY_STATUS"] in {
        "NOT_PACKED",
        "DETACHED_SIDECAR_AUTHORITATIVE",
    }
    assert status["HELD_OUT_REOPENED"] is False
    report = (ART / "stage-report.md").read_text(encoding="utf-8")
    assert "Report status: FINAL" in report
    assert "PENDING_SCAN" not in report
    assert "PENDING_PUBLISH" not in report
    ver = json.loads((ART / "verification.json").read_text(encoding="utf-8"))
    assert ver["ok"] is True


def test_privacy_and_full_reconciliation() -> None:
    scan = scan_public(ART)
    assert scan["ok"] is True
    assert scan["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
    recon = assert_artifact_dir_reconciled(ART)
    assert recon["ok"] is True
    assert recon["comparison_mode"] == "ALL_COMMON_UPPERCASE_STATUS_KEYS"
    assert recon["compared_key_count"] >= 20


def test_negative_controls_passed() -> None:
    nc = json.loads((ART / "negative-control-results.json").read_text(encoding="utf-8"))
    assert nc["ok"] is True
    assert nc["n_cases"] == 11
    assert nc["n_rejected"] == 11


def test_prior_zips_unmutated() -> None:
    external = ROOT / "artifacts" / "external-review"
    for _label, (name, expected) in PRIOR_ZIPS.items():
        path = external / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected, name
