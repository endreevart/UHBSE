"""Tests for the authorised Stage 02 Maintenance 01 repair application."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
    verify_relationship_manifest,
)
from human_simulator.stage02_maintenance.apply_maintenance_01 import (
    MaintenanceApplyBlocked,
    apply_maintenance_01,
    apply_manifest,
    evaluate_preconditions,
)
from human_simulator.stage02_maintenance.constants import (
    CANDIDATE_DIR,
    EXPECTED_MANIFEST_SHA_AFTER,
    EXPECTED_MANIFEST_SHA_BEFORE,
    EXPECTED_REMAINING_GATE_FAILURES,
    FORBIDDEN_STAGE_02_CHANGES,
    MAINTENANCE_DIR,
    PROMOTION_REPORT_JSON,
    STAGE_02_DIR,
)
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_apply_refuses_without_confirm():
    with pytest.raises(MaintenanceApplyBlocked, match="--confirm"):
        apply_maintenance_01(REPO_ROOT, confirm=False)


def test_preconditions_pass_when_the_repair_is_already_on_disk(repo_root: Path) -> None:
    pre = evaluate_preconditions(repo_root)
    assert pre.passed, pre.detail
    assert pre.current_manifest_sha256 == EXPECTED_MANIFEST_SHA_AFTER
    assert pre.candidate_manifest_sha256 == EXPECTED_MANIFEST_SHA_AFTER


def test_cli_refuses_without_confirm():
    proc = subprocess.run(
        [sys.executable, "-m", "human_simulator.cli", "--root", str(REPO_ROOT),
         "stage-02-maintenance-01-apply"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "confirm" in proc.stdout.lower() or "confirm" in proc.stderr.lower()


@pytest.mark.maintenance_apply
def test_authorised_apply_and_publish_end_to_end():
    """Apply the real repair once; this test is idempotent only if already applied."""
    manifest = REPO_ROOT / STAGE_02_DIR / MANIFEST_NAME
    current = sha256_file(manifest) if manifest.is_file() else ""
    if current == EXPECTED_MANIFEST_SHA_AFTER:
        pytest.skip("repair already applied in this workspace")

    proc = subprocess.run(
        [sys.executable, "-m", "human_simulator.cli", "--root", str(REPO_ROOT),
         "stage-02-maintenance-01-apply", "--confirm"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "PASS"
    assert result["repair_applied"] is True
    assert result["rolled_back"] is False
    assert result["report_status"] == "FINAL"
    assert sha256_file(manifest) == EXPECTED_MANIFEST_SHA_AFTER
    verified, detail = verify_relationship_manifest(REPO_ROOT / STAGE_02_DIR)
    assert verified, detail
    assert (REPO_ROOT / MAINTENANCE_DIR / PROMOTION_REPORT_JSON).is_file()


def test_atomic_apply_in_a_throwaway_copy(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / STAGE_02_DIR).mkdir(parents=True)
    (workspace / CANDIDATE_DIR).mkdir(parents=True)

    for name in (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME):
        shutil.copy2(REPO_ROOT / STAGE_02_DIR / name, workspace / STAGE_02_DIR / name)
    for name in (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME):
        shutil.copy2(REPO_ROOT / CANDIDATE_DIR / name, workspace / CANDIDATE_DIR / name)
    for rel in (
        "artifacts/stage-01/schema-profile.json",
        "artifacts/stage-01/stage-01-report.md",
        "artifacts/stage-02/verify-stage-02.json",
        "artifacts/stage-02/stage-02-report.md",
        "artifacts/stage-02/stage-02-final-manifest.sha256",
        "artifacts/stage-02/entity-crosswalk.yaml",
        "artifacts/stage-02/identity-linkage-assessment.json",
        "artifacts/stage-02/subject-root-analysis.json",
        "artifacts/stage-02/schema-profile-kgz.json",
    ):
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, target)

    (workspace / STAGE_02_DIR / MANIFEST_NAME).write_text("deadbeef  broken-manifest\n", encoding="utf-8")
    apply_manifest(workspace)
    assert sha256_file(workspace / STAGE_02_DIR / MANIFEST_NAME) == EXPECTED_MANIFEST_SHA_AFTER
    verified, _ = verify_relationship_manifest(workspace / STAGE_02_DIR)
    assert verified
    for name in FORBIDDEN_STAGE_02_CHANGES:
        assert sha256_file(workspace / STAGE_02_DIR / name) == sha256_file(
            REPO_ROOT / STAGE_02_DIR / name
        )


def test_gate_expectation_after_apply():
    """If repair is applied, gate must fail only on the four remaining blockers."""
    manifest_sha = sha256_file(REPO_ROOT / STAGE_02_DIR / MANIFEST_NAME)
    if manifest_sha != EXPECTED_MANIFEST_SHA_AFTER:
        pytest.skip("repair not yet applied")

    from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate

    gate = evaluate_pre_live_load_gate(REPO_ROOT)
    assert gate.status == "FAIL"
    assert set(gate.failed_checks) == set(EXPECTED_REMAINING_GATE_FAILURES)
    assert "relationship_manifest_hashes_match" not in gate.failed_checks
    assert "stage02_relationship_manifest_drift" not in gate.failed_checks
