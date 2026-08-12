"""Regression tests for Stage 02 Maintenance 01 promotion publication."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

from human_simulator.stage02.relationship_manifest import MANIFEST_NAME
from human_simulator.stage02_maintenance.constants import (
    EXPECTED_MANIFEST_SHA_AFTER,
    MAINTENANCE_DIR,
    PROMOTION_CONTENT_ARTIFACTS,
    PROMOTION_MANIFEST_NAME,
    PROMOTION_REPORT_JSON,
    PROMOTION_VERIFICATION_JSON,
)
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_file
from human_simulator.stage02_maintenance.promotion_manifest import (
    manifest_lists_itself,
    read_promotion_manifest,
    verify_promotion_manifest_entries,
    write_promotion_manifest,
)
from human_simulator.stage02_maintenance.publish_promotion import (
    PromotionPublicationBlocked,
    _evaluate_publication_checks,
    publish_promotion,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def promotion_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    shutil.copytree(REPO_ROOT / "artifacts" / "stage-02", workspace / "artifacts" / "stage-02")
    shutil.copytree(REPO_ROOT / MAINTENANCE_DIR, workspace / MAINTENANCE_DIR)
    return workspace


def test_promotion_manifest_excludes_itself(promotion_workspace: Path) -> None:
    directory = promotion_workspace / MAINTENANCE_DIR
    write_promotion_manifest(directory)
    entries = read_promotion_manifest(directory / PROMOTION_MANIFEST_NAME)
    assert PROMOTION_MANIFEST_NAME not in entries
    assert PROMOTION_MANIFEST_NAME not in PROMOTION_CONTENT_ARTIFACTS
    assert not manifest_lists_itself(entries)
    ok, failures = verify_promotion_manifest_entries(directory)
    assert ok, failures


def test_self_hash_entry_blocks_verification(promotion_workspace: Path) -> None:
    directory = promotion_workspace / MAINTENANCE_DIR
    write_promotion_manifest(directory)
    manifest_path = directory / PROMOTION_MANIFEST_NAME
    digest = read_promotion_manifest(manifest_path)[PROMOTION_REPORT_JSON]
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8")
        + f"{digest}  {PROMOTION_MANIFEST_NAME}\n",
        encoding="utf-8",
    )
    ok, failures = verify_promotion_manifest_entries(directory)
    assert not ok
    assert any("must not list itself" in item for item in failures)


def test_manifest_verifies_after_clean_extraction(promotion_workspace: Path) -> None:
    directory = promotion_workspace / MAINTENANCE_DIR
    write_promotion_manifest(directory)
    with tempfile.TemporaryDirectory() as tmp:
        extract_root = Path(tmp)
        for name in (*PROMOTION_CONTENT_ARTIFACTS, PROMOTION_MANIFEST_NAME):
            shutil.copy2(directory / name, extract_root / name)
        ok, failures = verify_promotion_manifest_entries(extract_root)
        assert ok, failures


def test_tampered_artifact_blocks_publication_checks(promotion_workspace: Path) -> None:
    directory = promotion_workspace / MAINTENANCE_DIR
    write_promotion_manifest(directory)
    tampered = directory / PROMOTION_REPORT_JSON
    tampered.write_text(tampered.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
        archive_path = Path(tmp.name)
        with zipfile.ZipFile(archive_path, "w") as bundle:
            for name in (*PROMOTION_CONTENT_ARTIFACTS, PROMOTION_MANIFEST_NAME):
                bundle.write(directory / name, f"{MAINTENANCE_DIR.as_posix()}/{name}")

        publication = _evaluate_publication_checks(
            promotion_workspace,
            archive_path=archive_path,
            archive_sha="0" * 64,
            sidecar_sha="0" * 64,
            index_text="| `x` | 1 | `" + ("a" * 64) + "` |",
            indexed_count=0,
            member_names=["x"],
        )
        assert not publication["passed"]
        assert publication["checks"]["promotion_manifest_hashes_match"] is False


def test_attestation_cannot_pass_with_invalid_manifest(promotion_workspace: Path) -> None:
    directory = promotion_workspace / MAINTENANCE_DIR
    write_promotion_manifest(directory)
    (directory / PROMOTION_REPORT_JSON).write_text("{}", encoding="utf-8")
    ok, _ = verify_promotion_manifest_entries(directory)
    assert not ok


def test_report_and_verification_have_different_roles() -> None:
    from human_simulator.stage02_maintenance.promotion_evidence import (
        build_promotion_report,
        build_promotion_verification,
    )

    mandatory = {"status": "PASS", "passed": 1, "failed": 0, "exit_code": 0, "summary": "1 passed"}
    publisher = {"status": "PASS", "executed": True, "passed": 1, "failed": 0, "summary": "1 passed"}
    report = build_promotion_report(
        repair_applied=True,
        rolled_back=False,
        manifest_sha256_after=EXPECTED_MANIFEST_SHA_AFTER,
        manifest_verified_8_of_8=True,
        mandatory_release_suite=mandatory,
        publisher_only_suite=publisher,
        gate_failed_checks=["canonical_loader_runtime_principal_undefined"],
    )
    verification = build_promotion_verification(
        repair_applied=True,
        rolled_back=False,
        preconditions={},
        before_after_matrix={},
        post_apply_core={"detail": "evidence"},
        mandatory_release_suite=mandatory,
        publisher_only_suite=publisher,
        verify_stage_02_summary={"status": "FAIL"},
        gate_document={"status": "FAIL"},
    )
    assert "post_apply" not in report
    assert "evidence_location" in report
    assert "post_apply_core" in verification or "post_apply" in str(verification)
    assert len(verification) > len(report)


@pytest.mark.publisher_only
def test_publish_v011_refuses_to_overwrite_existing_archive(repo_root: Path) -> None:
    from human_simulator.stage02_maintenance.constants import PROMOTION_BUNDLE_V011_ZIP_NAME

    manifest_sha = sha256_file(repo_root / "artifacts" / "stage-02" / MANIFEST_NAME)
    if manifest_sha != EXPECTED_MANIFEST_SHA_AFTER:
        pytest.skip("repair not applied in workspace")

    destination = repo_root / "artifacts" / "external-review" / PROMOTION_BUNDLE_V011_ZIP_NAME
    if not destination.is_file():
        pytest.skip("v0.1.1 bundle not yet published")

    with pytest.raises(PromotionPublicationBlocked, match="refusing to overwrite"):
        publish_promotion(repo_root, refresh_evidence=False)
