"""Tests for Stage 01/02 byte integrity during implementation planning."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from human_simulator.stage03.prior_stage_integrity import (
    ACCEPTED_SHA256,
    CONTROLLED_PRIOR_STAGE_PATHS,
    PRIOR_STAGE_INTEGRITY_NAME,
    baseline_source_descriptor,
    build_prior_stage_integrity_document,
    evaluate_prior_stage_integrity,
    restore_prior_stage_baseline,
    snapshot_prior_stage_hashes,
    write_prior_stage_integrity,
)
from human_simulator.stage03.verify_implementation_plan import verify_implementation_plan

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPL_DIR = REPO_ROOT / "artifacts" / "stage-03-implementation"


def test_prior_stage_files_match_accepted_sha256() -> None:
    ok, records = evaluate_prior_stage_integrity(REPO_ROOT)
    assert ok, [
        (record.path, record.current_sha256, record.accepted_sha256)
        for record in records
        if not record.unchanged
    ]
    assert len(records) == len(CONTROLLED_PRIOR_STAGE_PATHS)


def test_stage02_kgz_schema_profile_is_controlled() -> None:
    rel = "artifacts/stage-02/schema-profile-kgz.json"
    assert rel in CONTROLLED_PRIOR_STAGE_PATHS
    assert ACCEPTED_SHA256[rel] == "1065db5d00edcabb0fe714cedf6cd80c1a7d19890c34d277bdb6c4694c4238ce"


def test_all_stage03_prior_stage_dependencies_are_controlled() -> None:
    from human_simulator.stage03.review_dependencies import get_implementation_review_bundle_paths

    bundled_prior_stage = {
        rel
        for rel in get_implementation_review_bundle_paths()
        if rel.startswith("artifacts/stage-01/") or rel.startswith("artifacts/stage-02/")
    }
    assert bundled_prior_stage <= set(CONTROLLED_PRIOR_STAGE_PATHS)


def test_integrity_document_claims_no_git_provenance() -> None:
    document = build_prior_stage_integrity_document(REPO_ROOT)
    assert "baseline_git_commit" not in document
    assert "baseline_git_note" not in document
    source = document["baseline_source"]
    assert source["kind"] == "accepted_review_bundle"
    assert source["path"] == "stage-03-design-v0.7.1-review.zip"
    assert source["bundle_sha256"] == source["bundle_sha256_expected"]
    assert document["automatic_restore_performed"] is False


def test_baseline_source_descriptor_verifies_member_hashes_when_bundle_available() -> None:
    """Review bundles deliberately exclude artifacts/external-review, so verification is conditional."""
    source = baseline_source_descriptor(REPO_ROOT)
    if not source["bundle_present_in_workspace"]:
        assert source["member_hashes_verified"] is False
        assert source["bundle_sha256"] == source["bundle_sha256_expected"]
        return
    assert source["member_hashes_verified"] is True
    assert source["bundle_sha256"] == source["bundle_sha256_expected"]


def test_published_document_recorded_verified_member_hashes() -> None:
    path = IMPL_DIR / PRIOR_STAGE_INTEGRITY_NAME
    if not path.exists():
        pytest.skip("integrity document not published yet")
    source = json.loads(path.read_text(encoding="utf-8"))["baseline_source"]
    assert source["kind"] == "accepted_review_bundle"
    assert source["member_hashes_verified"] is True
    assert source["bundle_sha256"] == source["bundle_sha256_expected"]


def test_prior_stage_integrity_document_on_disk_is_current() -> None:
    path = IMPL_DIR / PRIOR_STAGE_INTEGRITY_NAME
    if not path.exists():
        pytest.skip("integrity document not published yet")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["unchanged"] is True
    assert loaded["controlled_file_count"] == len(CONTROLLED_PRIOR_STAGE_PATHS)
    assert set(loaded["hashes_before_test_suite"]) == set(CONTROLLED_PRIOR_STAGE_PATHS)


def test_prior_stage_integrity_document_written_to_tmp(tmp_path: Path) -> None:
    document = build_prior_stage_integrity_document(REPO_ROOT)
    path = write_prior_stage_integrity(tmp_path, document)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["unchanged"] is True
    assert loaded["baseline_source"]["kind"] == "accepted_review_bundle"
    assert loaded["controlled_files"]


def test_restore_requires_explicit_confirmation(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        restore_prior_stage_baseline(tmp_path)


def test_verifier_never_calls_restore() -> None:
    source = (
        REPO_ROOT / "src" / "human_simulator" / "stage03" / "verify_implementation_plan.py"
    ).read_text(encoding="utf-8")
    assert "restore_prior_stage_baseline" not in source
    assert "ensure_prior_stage_baseline" not in source


def test_no_test_calls_restore_prior_stage_baseline() -> None:
    for path in sorted((REPO_ROOT / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "restore_prior_stage_baseline(" not in line:
                continue
            assert "pytest.raises" in text, path.name
            assert "confirm=True" not in line, f"{path.name}: {line.strip()}"


def _clone_workspace(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for rel in (
        "artifacts/stage-01",
        "artifacts/stage-02",
        "artifacts/stage-03",
        "artifacts/stage-03-implementation",
        "src",
        "tests",
        "docs",
        "config",
        "pyproject.toml",
        "README.md",
    ):
        source = REPO_ROOT / rel
        if source.is_dir():
            shutil.copytree(source, destination / rel, dirs_exist_ok=True)
        elif source.exists():
            (destination / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination / rel)
    baseline = REPO_ROOT / "artifacts/external-review/stage-03-design-v0.7.1-review.zip"
    if baseline.exists():
        (destination / "artifacts" / "external-review").mkdir(parents=True, exist_ok=True)
        shutil.copy2(baseline, destination / "artifacts" / "external-review" / baseline.name)
    return destination


def test_verifier_fails_on_mutated_stage02_and_does_not_repair(tmp_path: Path) -> None:
    repo_before = snapshot_prior_stage_hashes(REPO_ROOT)
    workspace = _clone_workspace(tmp_path / "workspace")

    target = workspace / "artifacts" / "stage-02" / "entity-crosswalk.yaml"
    original = target.read_bytes()
    tampered = original + b"\n# tampered by integrity regression test\n"
    target.write_bytes(tampered)

    result = verify_implementation_plan(workspace, run_pytest=False, publish_artifacts=False)

    assert result["status"] == "FAIL"
    failure_names = {failure["name"] for failure in result["failures"]}
    assert "prior_stage_integrity_bytes" in failure_names

    assert target.read_bytes() == tampered, "verifier must not repair a detected change"
    assert snapshot_prior_stage_hashes(REPO_ROOT) == repo_before


def test_no_publish_verification_writes_nothing(tmp_path: Path) -> None:
    workspace = _clone_workspace(tmp_path / "readonly-workspace")

    def snapshot(root: Path) -> dict[str, str]:
        from human_simulator.stage03.preconditions import sha256_file

        return {
            str(path.relative_to(root)): sha256_file(path)
            for path in sorted((root / "artifacts").rglob("*"))
            if path.is_file()
        }

    before = snapshot(workspace)
    verify_implementation_plan(workspace, run_pytest=False, publish_artifacts=False)
    assert snapshot(workspace) == before


@pytest.mark.publisher_only
def test_full_pytest_suite_does_not_mutate_prior_stage_artifacts() -> None:
    before = snapshot_prior_stage_hashes(REPO_ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-m",
            "not verify_stage02_gate and not publisher_only",
            "-k",
            "not test_implementation_plan_clean_extraction_gate",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    after = snapshot_prior_stage_hashes(REPO_ROOT)
    document = build_prior_stage_integrity_document(
        REPO_ROOT,
        hashes_before_test_suite=before,
        hashes_after_test_suite=after,
        test_suite_unchanged_prior_stages=before == after,
    )
    assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-2000:]
    assert document["test_suite_unchanged_prior_stages"] is True
    assert document["unchanged"] is True
    for rel, accepted in ACCEPTED_SHA256.items():
        assert before[rel] == accepted
        assert after[rel] == accepted
