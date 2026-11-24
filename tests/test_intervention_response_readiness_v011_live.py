"""Publisher-workspace checks for the Stage 05 v0.1.1 correction."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from human_simulator.cross_source_lab_semantic_v021.publish import reconcile_review_index
from human_simulator.intervention_response_readiness_v01.hashes import sha256_file
from human_simulator.intervention_response_readiness_v01.privacy import scan_public
from human_simulator.intervention_response_readiness_v01.reconciliation import assert_artifact_dir_reconciled
from human_simulator.intervention_response_readiness_v011.defects import reproduce_v01_defect
from human_simulator.intervention_response_readiness_v011.policy import (
    ARTIFACT_DIR,
    EVIDENCE_CATALOG,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    V01_SHA256,
    V01_ZIP,
)
from human_simulator.intervention_response_readiness_v011.snapshots import verify_snapshots

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ARTIFACT_DIR
EXTERNAL = ROOT / "artifacts" / "external-review"
ZIP_PATH = EXTERNAL / REVIEW_ZIP


def _load(name: str) -> dict:
    return json.loads((ART / name).read_text(encoding="utf-8"))


def test_phase0_v01_reproduction_from_immutable_zip() -> None:
    defect = reproduce_v01_defect(ROOT)
    assert defect["measurement_ok"] is True
    assert defect["V01_CORE_NEGATIVE_READINESS_STATUS"] == "PASS"
    assert defect["V01_UPSTREAM_EVIDENCE_PROVENANCE_STATUS"] == "NOT_SELF_CONTAINED"
    assert defect["V01_CLEAN_REPLAY_STATUS"] == "FAIL"
    assert defect["V01_SELF_CONTAINMENT_CLAIM_STATUS"] == "CORRECTION_REQUIRED"
    assert defect["not_ready_conclusion_overturned"] is False
    assert defect["evidence_files_missing_count"] == 10
    assert defect["negative_controls_are_11_of_11"] is False
    assert defect["audit_exit_code"] == 1
    assert defect["TECHNICAL_AUDIT_STATUS"] == "FAIL"
    assert defect["unit_contract_passed"] == 11
    assert defect["packed_computed_from_published_artifacts"] is True
    assert defect["packed_evidence_files_missing"] == []
    assert defect["packed_REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] == "PACKED_CONTENTS_VERIFIED"
    with zipfile.ZipFile(EXTERNAL / V01_ZIP) as zf:
        names = set(zf.namelist())
        assert zf.testzip() is None
    missing = [spec["canonical_source_path"] for spec in EVIDENCE_CATALOG if spec["canonical_source_path"] not in names]
    assert len(missing) == 10
    assert sha256_file(EXTERNAL / V01_ZIP) == V01_SHA256


def test_upstream_snapshots_match_sources_and_fail_closed_verification() -> None:
    verified = verify_snapshots(ROOT)
    assert verified["ok"] is True
    assert verified["snapshot_count_label"] == "10/10"
    manifest = _load("upstream-evidence-manifest.json")
    assert manifest["patient_rows_included"] is False
    assert manifest["parquet_included"] is False
    assert manifest["raw_db_exports_included"] is False
    assert manifest["snapshot_count"] == 10
    for entry in manifest["snapshots"]:
        snap = ART / entry["snapshot_relpath"]
        source = ROOT / entry["canonical_source_path"]
        assert snap.read_bytes() == source.read_bytes()
        assert entry["source_bytes_equal_snapshot"] is True
        assert entry["source_sha256"] == entry["snapshot_sha256"]
        assert sha256_file(snap) == entry["snapshot_sha256"]
    medres = next(item for item in manifest["snapshots"] if item["key"] == "medres_status")
    assert medres["source_bytes_equal_originating_bundle_member"] is False
    assert set(medres["bundle_member_divergence_keys"]) <= {
        "PUBLICATION_INTEGRITY_STATUS",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS",
    }
    others = [item for item in manifest["snapshots"] if item["key"] != "medres_status"]
    assert all(item["source_bytes_equal_originating_bundle_member"] is True for item in others)


def test_registry_negative_controls_and_reconciliation() -> None:
    registry = _load("intervention-evidence-registry.json")
    status = _load("status-contract.json")
    nc = _load("negative-control-results.json")
    gaps = _load("phase0-readiness-gaps.json")
    assert registry["n_cells"] == 49
    assert status["SOURCE_A_INVENTORY_CELL_COUNT"] == 48
    assert status["SOURCE_B_ABSENCE_CELL_COUNT"] == 1
    assert status["INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT"] == 0
    assert status["DOMAIN_ACCEPTED_MAPPING_COUNT"] == 0
    assert status["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
    assert status["TECHNICAL_AUDIT_STATUS"] == "PASS"
    assert nc["n_cases"] == 11 and nc["n_rejected"] == 11
    assert gaps["evidence_files_missing"] == []
    assert gaps["computed_from_published_artifacts"] is True
    assert gaps["handwritten_literals"] is False
    assert gaps["appointment_date_not_administration"] is True
    recon = assert_artifact_dir_reconciled(ART)
    assert recon["ok"] is True
    assert recon["comparison_mode"] == "ALL_COMMON_UPPERCASE_STATUS_KEYS"


def test_privacy_scan_of_packed_snapshots_has_no_patient_rows_or_parquet() -> None:
    scan = scan_public(ART)
    assert scan["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
    assert scan["parquet"] == []
    assert scan["patient_level_publication"] is False
    snapshots = list((ART / "upstream-evidence").glob("*.json"))
    assert len(snapshots) == 10
    assert not list(ART.rglob("*.parquet"))
    blob = "\n".join(path.read_text(encoding="utf-8") for path in snapshots)
    for marker in ("sklearn", "train_model", "xgboost", ".parquet"):
        assert marker not in blob


def test_prior_zip_hashes_unchanged() -> None:
    for _label, (name, expected) in PRIOR_ZIPS.items():
        assert sha256_file(EXTERNAL / name) == expected
    assert sha256_file(EXTERNAL / V01_ZIP) == V01_SHA256


def test_clean_extraction_core_readiness_replay_status_pass() -> None:
    assert ZIP_PATH.is_file()
    attestation_path = EXTERNAL / REVIEW_ZIP.replace(".zip", ".attestation.json")
    sidecar = (EXTERNAL / f"{REVIEW_ZIP}.sha256").read_text(encoding="utf-8").split()[0]
    assert sha256_file(ZIP_PATH) == sidecar
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    assert attestation["PUBLICATION_INTEGRITY_STATUS"] == "PASS"
    assert attestation["ZIP_INNER_PUBLICATION_INTEGRITY_STATUS"] == "DETACHED_SIDECAR_AUTHORITATIVE"
    replay = attestation["clean_core_replay"]
    assert replay["CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS"] == "PASS"
    assert replay["exit_code"] == 0
    assert replay["TECHNICAL_AUDIT_STATUS"] == "PASS"
    assert replay["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
    assert replay["evidence_files_missing"] == []
    assert replay["negative_controls"] == "11/11"
    assert replay["registry_cells"] == 49
    assert replay["source_a_inventory_cells"] == 48
    assert replay["source_b_absence_cells"] == 1
    assert replay["eligible_cells"] == 0
    assert attestation["upstream_evidence_snapshot_count"] == "10/10"
    assert attestation["prior_zip_rehash_scope"] == "publisher_workspace"
    assert attestation["PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS"] == "NOT_RUN_PRIOR_BYTES_NOT_PACKED"
    assert attestation["v01_sha256_before"] == attestation["v01_sha256_after"] == V01_SHA256
    assert attestation["stage04_prior_sha_before"] == attestation["stage04_prior_sha_after"]
    assert attestation["clean_unit_contract"]["failed"] == 0
    assert attestation["clean_unit_contract"]["passed"]
    with zipfile.ZipFile(ZIP_PATH) as zf:
        crc = zf.testzip()
        names = [name for name in zf.namelist() if not name.endswith("/")]
        assert crc is None
        assert len(names) == len(set(names))
        assert not any(name.endswith(".parquet") or name.endswith(V01_ZIP) for name in names)
        assert not any(Path(name).name in {item[0] for item in PRIOR_ZIPS.values()} for name in names)
        status = json.loads(zf.read(f"{ARTIFACT_DIR}/status-contract.json"))
        index = zf.read("REVIEW_INDEX.md").decode("utf-8")
        payloads = {name: zf.read(name) for name in names if name != "REVIEW_INDEX.md"}
    assert status["PUBLICATION_INTEGRITY_STATUS"] == "DETACHED_SIDECAR_AUTHORITATIVE"
    assert status["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] == "PASS_CORE_READINESS_REPLAY_PRIOR_ZIPS_EXTERNAL"
    assert status["CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS"] == "PASS"
    assert status["CORE_READINESS_REPLAY_STATUS"] == "PASS"
    assert status["UPSTREAM_EVIDENCE_SNAPSHOT_STATUS"] == "PASS"
    assert status["PRIOR_ZIP_PHYSICAL_REHASH_STATUS"] == "PASS_PUBLISHER_WORKSPACE"
    assert status["PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS"] == "NOT_RUN_PRIOR_BYTES_NOT_PACKED"
    assert status["STAGE_NAMING_AUTHORITY_STATUS"] == "PASS_PUBLISHER_WORKSPACE"
    assert status["INTERVENTION_RESPONSE_MODEL_STATUS"] == "NOT_STARTED"
    review = reconcile_review_index(names, index, payloads)
    assert review["ok"] is True
    assert attestation["members"] == len(names)
    assert attestation["indexed_members"] == review["indexed_members"] == len(names) - 1
