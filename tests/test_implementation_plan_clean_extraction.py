"""Mandatory clean-extraction gate for Stage 03 implementation planning v0.3.5."""

from __future__ import annotations

import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

from human_simulator.stage03.implementation_constants import IMPLEMENTATION_PLAN_VERIFICATION_NAME
from human_simulator.stage03.implementation_review_bundle import BUNDLE_PYTEST_TARGETS, BUNDLE_ZIP_NAME
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.review_bundle_validation import validate_review_bundle_zip
from human_simulator.stage03.verify_implementation_plan import verify_implementation_plan
from human_simulator.stage03.verify_stage_03_design import verify_stage_03_design

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPL_DIR = REPO_ROOT / "artifacts" / "stage-03-implementation"


def _prior_stages_ready() -> bool:
    stage01 = REPO_ROOT / "artifacts" / "stage-01" / "stage-01-report.md"
    stage02_verify = REPO_ROOT / "artifacts" / "stage-02" / "verify-stage-02.json"
    if not stage01.exists() or not stage02_verify.exists():
        return False
    verify = json.loads(stage02_verify.read_text(encoding="utf-8"))
    report = stage01.read_text(encoding="utf-8")
    return ("**Report status:** FINAL" in report or "Report status: FINAL" in report) and verify.get("status") == "PASS"


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


@pytest.mark.publisher_only
def test_implementation_plan_clean_extraction_gate(isolated_workspace: Path) -> None:
    """A freshly published plan bundle must verify on its own after a clean extraction.

    Publishing happens in a throwaway copy. Republishing into the working tree is what let a
    test regenerate Stage 03 Design evidence that then travelled into a review bundle.
    """
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")

    publish = verify_implementation_plan(isolated_workspace, run_pytest=True, publish_artifacts=True)
    assert publish["status"] == "PASS", publish.get("failures")

    zip_path = isolated_workspace / "artifacts" / "external-review" / BUNDLE_ZIP_NAME
    assert zip_path.exists(), "review bundle ZIP was not published"
    zip_sha256 = sha256_file(zip_path)
    ok, detail = validate_review_bundle_zip(zip_path)
    assert ok, detail

    with tempfile.TemporaryDirectory(prefix="impl-plan-clean-extract-") as tmp:
        extract_root = Path(tmp)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_root)

        sync = _run(["uv", "sync", "--frozen", "--extra", "dev"], cwd=extract_root)
        assert sync.returncode == 0, sync.stderr

        design = verify_stage_03_design(extract_root, run_pytest=False, publish_artifacts=False)
        plan = verify_implementation_plan(extract_root, run_pytest=False, publish_artifacts=False)
        assert design["status"] == "PASS", design.get("failures")
        assert plan["status"] == "PASS", plan.get("failures")
        assert design["checks_failed"] == 0
        assert plan["checks_failed"] == 0

        pytest_targets = " ".join(BUNDLE_PYTEST_TARGETS)
        pytest_one = _run(["uv", "run", "pytest", *BUNDLE_PYTEST_TARGETS, "-q"], cwd=extract_root)
        assert pytest_one.returncode == 0, pytest_one.stdout + pytest_one.stderr

        # A reviewer only ever runs the read-only gate form; the archive deliberately omits
        # artifacts/external-review, so publishing from an extraction is not a supported path.
        design_gate = _run(
            ["uv", "run", "audit", "--root", ".", "stage-03-check", "--no-publish"], cwd=extract_root
        )
        assert design_gate.returncode == 0, design_gate.stdout + design_gate.stderr
        impl_gate = _run(
            ["uv", "run", "audit", "--root", ".", "stage-03-implementation-plan-check", "--no-publish"],
            cwd=extract_root,
        )
        assert impl_gate.returncode == 0, impl_gate.stdout + impl_gate.stderr

        gate_before = _impl_artifact_hashes_from(extract_root)
        _run(
            ["uv", "run", "audit", "--root", ".", "stage-03-implementation-plan-check", "--no-publish"],
            cwd=extract_root,
        )
        assert _impl_artifact_hashes_from(extract_root) == gate_before, (
            "--no-publish gate must not write Stage 03 artifacts"
        )

        verification_path = extract_root / "artifacts" / "stage-03-implementation" / IMPLEMENTATION_PLAN_VERIFICATION_NAME
        design_verification_path = extract_root / "artifacts" / "stage-03" / "stage-03-design-verification.json"
        on_disk_plan = json.loads(verification_path.read_text(encoding="utf-8"))
        on_disk_design = json.loads(design_verification_path.read_text(encoding="utf-8"))
        gate_design = verify_stage_03_design(extract_root, run_pytest=False, publish_artifacts=False)
        gate_plan = verify_implementation_plan(extract_root, run_pytest=False, publish_artifacts=False)
        assert gate_design["status"] == on_disk_design["overall_status"]
        assert gate_design["checks_total"] == on_disk_design["checks_total"]
        assert gate_design["checks_passed"] == on_disk_design["checks_passed"]
        assert gate_design["checks_failed"] == on_disk_design["checks_failed"]
        assert gate_plan["status"] == on_disk_plan["overall_status"]
        assert gate_plan["checks_total"] == on_disk_plan["checks_total"]
        assert gate_plan["checks_passed"] == on_disk_plan["checks_passed"]
        assert gate_plan["checks_failed"] == on_disk_plan["checks_failed"]

        extract_before = _impl_artifact_hashes_from(extract_root)
        pytest_two = _run(["uv", "run", "pytest", *BUNDLE_PYTEST_TARGETS, "-q"], cwd=extract_root)
        assert pytest_two.returncode == 0, pytest_two.stdout + pytest_two.stderr
        extract_after = _impl_artifact_hashes_from(extract_root)
        assert extract_before == extract_after, "publication artifacts changed during extracted pytest rerun"

    with zipfile.ZipFile(zip_path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
    assert zip_sha256 and len(members) > 0


def _impl_artifact_hashes_from(root: Path) -> dict[str, str]:
    impl = root / "artifacts" / "stage-03-implementation"
    return {
        str(path.relative_to(impl)): sha256_file(path)
        for path in sorted(impl.rglob("*"))
        if path.is_file()
    }


def test_fresh_bundle_no_publish_verification_passes() -> None:
    bundle = REPO_ROOT / "artifacts" / "external-review" / BUNDLE_ZIP_NAME
    if not bundle.exists():
        pytest.skip("review bundle missing")

    with tempfile.TemporaryDirectory(prefix="impl-plan-fresh-no-publish-") as tmp:
        extract_root = Path(tmp)
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(extract_root)
        result = verify_implementation_plan(extract_root, run_pytest=False, publish_artifacts=False)
        assert result["status"] == "PASS", result.get("failures")
        assert result["checks_failed"] == 0
