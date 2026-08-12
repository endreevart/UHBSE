"""Regression tests for Stage 03 alignment candidate publication and baseline recovery."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from human_simulator.stage03_alignment.baseline import evaluate_baseline
from human_simulator.stage03_alignment.constants import (
    ACCEPTED_PLAN_V035_ZIP_SHA256,
    ALIGNMENT_EXPECTED_CHANGED_FILES,
    BUNDLE_SHA256_NAME,
    BUNDLE_ZIP_NAME,
    DESIGN_VERSION,
    EXTERNAL_REVIEW_DIR,
    FROZEN_DESIGN_VERSION,
    FROZEN_DESIGN_ZIP_RECOVERED,
    FROZEN_PLAN_VERSION,
    FROZEN_PLAN_ZIP_RECOVERED,
    PLAN_VERSION,
)
from human_simulator.stage03_alignment.recovery import (
    FROZEN_DESIGN_ZIP_INVALID,
    FROZEN_PLAN_ZIP_INVALID,
    INVALID_BASELINE_STATUS,
    audit_baseline_recovery,
    create_recovery_bundles,
)


@pytest.fixture
def recovery_ready(repo_root: Path) -> dict:
    return create_recovery_bundles(repo_root)


def test_recovery_audit_marks_invalid_baselines(repo_root: Path, recovery_ready: dict) -> None:
    audit = audit_baseline_recovery(repo_root)
    assert audit["invalid_archives"]["design"]["status"] == INVALID_BASELINE_STATUS
    assert audit["invalid_archives"]["plan"]["status"] == INVALID_BASELINE_STATUS
    assert audit["recovery_source_complete"] is True


def test_recovered_design_bundle_contains_frozen_version(repo_root: Path, recovery_ready: dict) -> None:
    zip_path = repo_root / FROZEN_DESIGN_ZIP_RECOVERED
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as archive:
        payload = archive.read("artifacts/stage-03/canonical-id-contract.yaml")
    assert f'document_version: "{FROZEN_DESIGN_VERSION}"'.encode() in payload


def test_recovered_plan_bundle_contains_frozen_version(repo_root: Path, recovery_ready: dict) -> None:
    zip_path = repo_root / FROZEN_PLAN_ZIP_RECOVERED
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as archive:
        payload = archive.read("artifacts/stage-03-implementation/implementation-plan.yaml")
    assert f'document_version: "{FROZEN_PLAN_VERSION}"'.encode() in payload


def test_invalid_design_archive_rejected_for_wrong_version(repo_root: Path) -> None:
    zip_path = repo_root / FROZEN_DESIGN_ZIP_INVALID
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as archive:
        payload = archive.read("artifacts/stage-03/canonical-id-contract.yaml")
    assert f'document_version: "{DESIGN_VERSION}"'.encode() in payload


def test_invalid_plan_archive_rejected_for_wrong_version(repo_root: Path) -> None:
    zip_path = repo_root / FROZEN_PLAN_ZIP_INVALID
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as archive:
        payload = archive.read("artifacts/stage-03-implementation/implementation-plan.yaml")
    assert f'document_version: "{PLAN_VERSION}"'.encode() in payload


def test_before_after_matrix_uses_recovered_baselines(repo_root: Path, recovery_ready: dict) -> None:
    from human_simulator.stage03_alignment.publish_alignment import _before_after_matrix

    matrix = _before_after_matrix(repo_root)
    assert matrix["frozen_design_zip"].endswith(FROZEN_DESIGN_ZIP_RECOVERED.name)
    assert matrix["frozen_plan_zip"].endswith(FROZEN_PLAN_ZIP_RECOVERED.name)
    assert matrix["alignment_change_check_pass"] is True
    changed = set(matrix["expected_alignment_files_changed"])
    assert changed & set(ALIGNMENT_EXPECTED_CHANGED_FILES)


def test_before_after_cannot_compare_same_snapshot(repo_root: Path, recovery_ready: dict) -> None:
    from human_simulator.stage03_alignment.publish_alignment import _before_after_matrix

    matrix = _before_after_matrix(repo_root)
    same = all(
        entry.get("before_sha256") == entry.get("after_sha256")
        for entry in matrix["design_content_files"] + matrix["plan_content_files"]
        if entry.get("before_sha256")
    )
    assert same is False


def test_baseline_db_exception_does_not_pass(repo_root: Path, recovery_ready: dict) -> None:
    with patch(
        "human_simulator.stage03_alignment.canonical_db_baseline.canonical_connection",
        side_effect=AttributeError("broken"),
    ), patch(
        "human_simulator.stage03_alignment.canonical_db_baseline.canonical_settings_available",
        return_value=True,
    ), patch(
        "human_simulator.stage03_alignment.canonical_db_baseline.load_canonical_settings",
    ) as load_settings:
        load_settings.return_value.user = "canonical_admin"
        baseline = evaluate_baseline(repo_root)
    db_check = next(item for item in baseline["checks"] if item["name"] == "canonical_db_row_counts_zero")
    assert db_check["passed"] is False
    assert db_check["status"] == "EVALUATED"
    assert baseline["canonical_db"]["exception"]["type"] == "AttributeError"
    assert baseline["status"] == "FAIL"


def test_baseline_unavailable_db_is_not_evaluated(repo_root: Path, recovery_ready: dict) -> None:
    with patch(
        "human_simulator.stage03_alignment.canonical_db_baseline.canonical_settings_available",
        return_value=False,
    ):
        baseline = evaluate_baseline(repo_root)
    db_check = next(item for item in baseline["checks"] if item["name"] == "canonical_db_row_counts_zero")
    assert db_check["status"] == "NOT_EVALUATED"
    assert baseline["status"] == "FAIL"


def test_false_baseline_forbids_pass_attestation(repo_root: Path, recovery_ready: dict) -> None:
    attestation_path = repo_root / EXTERNAL_REVIEW_DIR / BUNDLE_ZIP_NAME.replace(".zip", ".attestation.json")
    if not attestation_path.is_file():
        pytest.skip("alignment bundle not yet published")
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    baseline = json.loads(
        (repo_root / "artifacts/stage-03-alignment-candidate/baseline-verification.json").read_text()
    )
    if baseline["status"] != "PASS":
        assert attestation["baseline_status"] == "FAIL"
        assert attestation["checks"]["baseline_pass"] is False
    else:
        assert attestation["baseline_status"] == "PASS"
        assert attestation["checks"]["baseline_pass"] is True
    assert attestation["publication_integrity_status"] == "PASS"
    assert attestation["candidate_status"] == "PARTIAL"
    assert attestation["pre_live_load_gate_status"] == "FAIL"


def test_published_alignment_bundle_has_single_review_index(repo_root: Path, recovery_ready: dict) -> None:
    zip_path = repo_root / EXTERNAL_REVIEW_DIR / BUNDLE_ZIP_NAME
    if not zip_path.is_file():
        pytest.skip("alignment bundle not yet published")
    with zipfile.ZipFile(zip_path) as archive:
        review_indexes = [name for name in archive.namelist() if name.endswith("REVIEW_INDEX.md")]
        assert review_indexes == ["REVIEW_INDEX.md"]
        assert "placeholder" not in archive.read("REVIEW_INDEX.md").decode("utf-8")


def test_sidecar_matches_final_archive_sha(repo_root: Path, recovery_ready: dict) -> None:
    zip_path = repo_root / EXTERNAL_REVIEW_DIR / BUNDLE_ZIP_NAME
    sidecar = repo_root / EXTERNAL_REVIEW_DIR / BUNDLE_SHA256_NAME
    if not zip_path.is_file():
        pytest.skip("alignment bundle not yet published")
    archive_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sidecar_sha = sidecar.read_text(encoding="utf-8").split()[0]
    assert archive_sha == sidecar_sha


def test_zip_immutable_after_sha_sidecar(repo_root: Path, recovery_ready: dict) -> None:
    zip_path = repo_root / EXTERNAL_REVIEW_DIR / BUNDLE_ZIP_NAME
    sidecar = repo_root / EXTERNAL_REVIEW_DIR / BUNDLE_SHA256_NAME
    if not zip_path.is_file():
        pytest.skip("alignment bundle not yet published")
    before = sidecar.read_text(encoding="utf-8")
    after_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert before.startswith(after_sha)


def test_duplicate_zip_member_forbidden() -> None:
    from human_simulator.stage03_alignment.publish_alignment import _assert_unique_arcnames

    with pytest.raises(RuntimeError, match="duplicate zip member"):
        _assert_unique_arcnames([(Path("a"), "same"), (Path("b"), "same")])


def test_canonical_settings_use_dsn_not_admin_dsn() -> None:
    from human_simulator.canonical.settings import CanonicalConnectionSettings

    settings = CanonicalConnectionSettings(
        host="localhost",
        port=5436,
        database="uhbse_canonical_dev",
        user="canonical_admin",
        password="secret",
    )
    assert hasattr(settings, "dsn")
    assert not hasattr(settings, "admin_dsn")


def test_canonical_db_row_counts_executed_when_reachable() -> None:
    from human_simulator.canonical.settings import canonical_settings_available
    from human_simulator.stage03_alignment.canonical_db_baseline import evaluate_canonical_db_baseline

    if not canonical_settings_available():
        pytest.skip("canonical-db.env not configured")
    result = evaluate_canonical_db_baseline()
    assert result.check_status == "EVALUATED"
    assert result.document["connection_user"] == "canonical_admin"
    assert result.document["raw_db_connections"] == 0
    assert result.document["clinical_source_rows_read"] == 0
    assert set(result.document["row_counts"] or {}) == {
        "source_system",
        "source_record",
        "subject",
        "subject_characteristic",
        "encounter",
        "observation",
        "observation_component",
    }


def test_before_after_marks_added_conflict_file(repo_root: Path, recovery_ready: dict) -> None:
    from human_simulator.stage03_alignment.publish_alignment import _before_after_matrix

    matrix = _before_after_matrix(repo_root)
    entry = next(
        item for item in matrix["design_content_files"] if item["file"] == "artifact-conflict-resolutions.yaml"
    )
    assert entry["before_sha256"] is None
    assert entry["changed"] is True
    assert entry["change_type"] == "ADDED"


def test_all_design_manifest_members_in_published_zip(repo_root: Path, recovery_ready: dict) -> None:
    from human_simulator.stage03.changeset_01_constants import DESIGN_CONTENT_MANIFEST_NAME, DESIGN_DIR

    zip_path = repo_root / EXTERNAL_REVIEW_DIR / BUNDLE_ZIP_NAME
    if not zip_path.is_file():
        pytest.skip("alignment bundle not yet published")
    manifest = (repo_root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME).read_text(encoding="utf-8")
    expected = [line.split(maxsplit=1)[1].strip() for line in manifest.splitlines() if line.strip()]
    with zipfile.ZipFile(zip_path) as archive:
        members = set(archive.namelist())
    for name in expected:
        assert f"design/{name}" in members


def test_all_plan_manifest_members_in_published_zip(repo_root: Path, recovery_ready: dict) -> None:
    from human_simulator.stage03.changeset_01_constants import (
        IMPLEMENTATION_DIR,
        IMPLEMENTATION_PLAN_MANIFEST_NAME,
    )

    zip_path = repo_root / EXTERNAL_REVIEW_DIR / BUNDLE_ZIP_NAME
    if not zip_path.is_file():
        pytest.skip("alignment bundle not yet published")
    manifest = (repo_root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME).read_text(encoding="utf-8")
    expected = [line.split(maxsplit=1)[1].strip() for line in manifest.splitlines() if line.strip()]
    with zipfile.ZipFile(zip_path) as archive:
        members = set(archive.namelist())
    for name in expected:
        assert f"plan/{name}" in members


def test_reports_do_not_reference_invalid_plan_archive_sha(repo_root: Path) -> None:
    report = (repo_root / "artifacts/stage-03-implementation/implementation-plan-report.md").read_text()
    assert "7a4ddbad" not in report
    assert "SourceRecord construction patch" not in report
    assert "RECONSTRUCTED_FROM_ACCEPTED_MEMBERS" in report
    assert "33bc3daa253b5587963185f4e3552dd426abdcbbc1e47a2cd4466a4cca6035ee" in report


def test_design_report_describes_v075_alignment(repo_root: Path) -> None:
    report = (repo_root / "artifacts/stage-03/stage-03-design-report.md").read_text()
    assert "v0.7.5" in report
    assert "alignment candidate" in report.lower()


def test_accepted_plan_zip_not_found_uses_reconstructed_recovery(repo_root: Path, recovery_ready: dict) -> None:
    audit = audit_baseline_recovery(repo_root)
    assert audit["accepted_plan_zip_found"] is False
    attestation = json.loads(
        (repo_root / EXTERNAL_REVIEW_DIR / f"{FROZEN_PLAN_ZIP_RECOVERED.name}.attestation.json").read_text()
    )
    assert attestation["recovery_method"] == "RECONSTRUCTED_FROM_ACCEPTED_MEMBERS"
    assert attestation["accepted_zip_sha256"] == ACCEPTED_PLAN_V035_ZIP_SHA256
