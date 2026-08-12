"""Tests for the Changeset 01 verifier and its immutability guarantees."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from human_simulator.audit.report import REPORT_STATUS_DRAFT
from human_simulator.stage03.changeset_01_baseline import (
    BaselineMismatch,
    evaluate_baseline,
    require_baseline,
)
from human_simulator.stage03.changeset_01_constants import (
    ARTIFACT_CONFLICTS_NAME,
    CHANGESET_CONTENT_ARTIFACTS,
    CHANGESET_DIR,
    CHANGESET_MANIFEST_NAME,
    CHANGESET_REPORT_NAME,
    CHANGESET_VERIFICATION_NAME,
    FORBIDDEN_IN_CHANGESET_MANIFEST,
    GATE_RESULT_NAME,
    UNRESOLVED_DECISIONS_NAME,
)
from human_simulator.stage03.implementation_gate import (
    AUTHORIZED_CHANGESET_ID,
    CHANGESET_01_AUTHORIZED_PATHS,
    FROZEN_DESIGN_VERSION,
    FROZEN_IMPLEMENTATION_PLAN_VERSION,
    IMPLEMENTATION_GATE_OPEN,
    is_authorized_changeset_path,
    unauthorized_paths,
)
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.prior_stage_integrity import (
    ACCEPTED_SHA256,
    CONTROLLED_PRIOR_STAGE_PATHS,
    evaluate_prior_stage_integrity,
)
from human_simulator.stage03.verify_changeset_01 import verify_changeset_01

DESIGN_DIR = Path("artifacts") / "stage-03"
IMPL_DIR = Path("artifacts") / "stage-03-implementation"


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path): sha256_file(path) for path in paths if path.is_file()}


def _frozen_inputs(root: Path) -> dict[str, str]:
    controlled = [root / rel for rel in CONTROLLED_PRIOR_STAGE_PATHS]
    design = sorted((root / DESIGN_DIR).rglob("*"))
    plan = sorted((root / IMPL_DIR).rglob("*"))
    return _hashes(controlled + design + plan)


# --------------------------------------------------------------------------------------
# Baseline precondition
# --------------------------------------------------------------------------------------


def test_baseline_passes_on_the_current_checkpoint(repo_root: Path) -> None:
    document = evaluate_baseline(repo_root)
    assert document["status"] == "PASS"
    assert document["controlled_prior_stage"]["file_count"] == 9
    assert document["controlled_prior_stage"]["all_unchanged"] is True
    assert document["frozen_manifests"]["design"]["verified"] is True
    assert document["frozen_manifests"]["implementation_plan"]["verified"] is True
    assert document["auto_restore_performed"] is False


def test_baseline_covers_exactly_nine_controlled_files() -> None:
    assert len(CONTROLLED_PRIOR_STAGE_PATHS) == 9
    assert len(ACCEPTED_SHA256) == 9


def test_baseline_evaluation_writes_nothing(repo_root: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    shutil.copytree(repo_root / "artifacts", workspace / "artifacts")
    before = _hashes(sorted(workspace.rglob("*")))
    evaluate_baseline(workspace)
    assert _hashes(sorted(workspace.rglob("*"))) == before


def test_baseline_fails_closed_on_a_mutated_stage_02_file(repo_root: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    shutil.copytree(repo_root / "artifacts", workspace / "artifacts")
    target = workspace / "artifacts" / "stage-02" / "entity-crosswalk.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# mutated\n", encoding="utf-8")

    document = evaluate_baseline(workspace)
    assert document["status"] == "FAIL"
    assert document["checks"]["controlled_prior_stage_files_unchanged"] is False
    with pytest.raises(BaselineMismatch, match="Nothing was restored"):
        require_baseline(workspace)
    # the mutation is reported, never repaired
    assert "# mutated" in target.read_text(encoding="utf-8")


def test_baseline_fails_closed_on_a_mutated_design_artifact(repo_root: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    shutil.copytree(repo_root / "artifacts", workspace / "artifacts")
    target = workspace / DESIGN_DIR / "canonical-model.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# mutated\n", encoding="utf-8")

    document = evaluate_baseline(workspace)
    assert document["status"] == "FAIL"
    assert document["checks"]["design_content_manifest_verified"] is False


def test_baseline_fails_closed_on_a_mutated_plan_artifact(repo_root: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    shutil.copytree(repo_root / "artifacts", workspace / "artifacts")
    target = workspace / IMPL_DIR / "pilot-slice.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "\n# mutated\n", encoding="utf-8")

    document = evaluate_baseline(workspace)
    assert document["status"] == "FAIL"
    assert document["checks"]["implementation_plan_manifest_verified"] is False


# --------------------------------------------------------------------------------------
# Verifier behaviour
# --------------------------------------------------------------------------------------


def test_verifier_passes_on_the_published_workspace(repo_root: Path) -> None:
    result = verify_changeset_01(repo_root, publish_artifacts=False)
    failed = [check for check in result["checks"] if check["status"] != "PASS"]
    assert failed == []
    assert result["overall_status"] == "PASS"


def test_no_publish_verification_writes_nothing(repo_root: Path) -> None:
    tracked = sorted((repo_root / CHANGESET_DIR).rglob("*"))
    before = _hashes(tracked)
    frozen_before = _frozen_inputs(repo_root)

    verify_changeset_01(repo_root, publish_artifacts=False)

    assert _hashes(sorted((repo_root / CHANGESET_DIR).rglob("*"))) == before
    assert _frozen_inputs(repo_root) == frozen_before


def test_verification_never_touches_stage_01_02_design_or_plan(repo_root: Path) -> None:
    before = _frozen_inputs(repo_root)
    verify_changeset_01(repo_root, publish_artifacts=False)
    assert _frozen_inputs(repo_root) == before


def test_verifier_performs_no_repair(repo_root: Path) -> None:
    source = Path("src/human_simulator/stage03/verify_changeset_01.py").read_text(encoding="utf-8")
    assert "restore_prior_stage_baseline" not in source
    assert "write_relationship_manifest" not in source
    baseline_source = Path("src/human_simulator/stage03/changeset_01_baseline.py").read_text(
        encoding="utf-8"
    )
    assert "restore_prior_stage_baseline" not in baseline_source


def test_verifier_reports_a_mutated_stage_02_without_repairing(repo_root: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    for item in ("artifacts", "migrations", "config", "src", "docker-compose.yml", ".gitignore"):
        source = repo_root / item
        target = workspace / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

    victim = workspace / "artifacts" / "stage-02" / "subject-root-analysis.json"
    mutated = victim.read_text(encoding="utf-8") + "\n"
    victim.write_text(mutated, encoding="utf-8")

    result = verify_changeset_01(workspace, publish_artifacts=False)
    assert result["overall_status"] == "FAIL"
    names = {check["name"] for check in result["checks"] if check["status"] == "FAIL"}
    assert "controlled_prior_stage_nine_files_unchanged" in names
    assert victim.read_text(encoding="utf-8") == mutated

    unchanged, _ = evaluate_prior_stage_integrity(repo_root)
    assert unchanged is True


def test_check_count_is_identical_in_both_publish_modes(isolated_workspace: Path) -> None:
    """Publishing must not add or drop a check. Runs in a copy so it writes nothing real."""
    read_only = verify_changeset_01(isolated_workspace, publish_artifacts=False)
    published = verify_changeset_01(isolated_workspace, publish_artifacts=True)
    assert read_only["checks_total"] == published["checks_total"]
    assert [check["name"] for check in read_only["checks"]] == [
        check["name"] for check in published["checks"]
    ]


# --------------------------------------------------------------------------------------
# Published artifacts
# --------------------------------------------------------------------------------------


def test_report_remains_draft(repo_root: Path) -> None:
    report = (repo_root / CHANGESET_DIR / CHANGESET_REPORT_NAME).read_text(encoding="utf-8")
    assert f"Report status: {REPORT_STATUS_DRAFT}" in report
    assert "Report status: FINAL" not in report
    assert "not promoted to FINAL" in report


def test_verification_matches_the_published_report(repo_root: Path) -> None:
    payload = json.loads(
        (repo_root / CHANGESET_DIR / CHANGESET_VERIFICATION_NAME).read_text(encoding="utf-8")
    )
    report_path = repo_root / CHANGESET_DIR / CHANGESET_REPORT_NAME
    assert payload["report_sha256"] == sha256_file(report_path)
    assert payload["report_status"] == REPORT_STATUS_DRAFT
    assert payload["overall_status"] == "PASS"


def test_content_manifest_matches_and_excludes_generated_evidence(repo_root: Path) -> None:
    directory = repo_root / CHANGESET_DIR
    lines = [
        line
        for line in (directory / CHANGESET_MANIFEST_NAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    names = []
    for line in lines:
        digest, name = line.split(maxsplit=1)
        names.append(name.strip())
        assert sha256_file(directory / name.strip()) == digest
    assert names == list(CHANGESET_CONTENT_ARTIFACTS)
    assert not set(names) & FORBIDDEN_IN_CHANGESET_MANIFEST


def test_gate_result_is_published_as_a_separate_artifact(repo_root: Path) -> None:
    document = json.loads((repo_root / CHANGESET_DIR / GATE_RESULT_NAME).read_text(encoding="utf-8"))
    assert document["gate_id"] == "stage02_relationship_integrity_pre_live_load"
    assert document["status"] == "FAIL"
    assert document["repairs_performed"] == 0


def test_recorded_conflicts_are_not_silently_resolved(repo_root: Path) -> None:
    document = yaml.safe_load(
        (repo_root / CHANGESET_DIR / ARTIFACT_CONFLICTS_NAME).read_text(encoding="utf-8")
    )
    assert document["open_conflict_count"] == len(document["conflicts"])
    assert document["conflicts_repaired_automatically"] == 0
    assert document["design_or_plan_artifacts_modified"] == 0
    ids = {conflict["id"] for conflict in document["conflicts"]}
    assert ids == {
        "temporal_precision_field_absent_from_model",
        "encounter_provider_id_population_disagreement",
    }
    for conflict in document["conflicts"]:
        assert conflict["status"] == "OPEN"
        assert conflict["severity"] == "BLOCKS_LIVE_LOAD"


def test_blocking_decisions_include_every_open_conflict(repo_root: Path) -> None:
    decisions = yaml.safe_load(
        (repo_root / CHANGESET_DIR / UNRESOLVED_DECISIONS_NAME).read_text(encoding="utf-8")
    )
    blocking = {
        item["id"] for item in decisions["decisions"] if item["blocking_for_next_phase"]
    }
    assert blocking == set(decisions["blocking_ids"])
    assert "stage02_relationship_manifest_drift" in blocking
    assert decisions["open_blocking_count"] == len(blocking)


def test_plan_artifact_v035_unresolved_decisions_untouched(repo_root: Path) -> None:
    """Changeset decisions live in their own file; the accepted plan file is immutable."""
    plan_decisions = yaml.safe_load(
        (repo_root / IMPL_DIR / "unresolved-implementation-decisions.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert plan_decisions["document_version"] == FROZEN_IMPLEMENTATION_PLAN_VERSION
    assert plan_decisions["implementation_status"] == "planning_only_not_started"


def test_changeset_artifacts_contain_no_secret_or_dsn(repo_root: Path) -> None:
    for path in sorted((repo_root / CHANGESET_DIR).rglob("*")):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        assert "postgresql://" not in content
        assert "postgres://" not in content
        lowered = content.lower()
        for token in ("hmac_secret", "password=", "admin_password="):
            assert token not in lowered, f"{path.name} contains {token}"


def test_changeset_artifacts_contain_no_clinical_values(repo_root: Path) -> None:
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    phone = re.compile(r"\+\d{7,}")
    for path in sorted((repo_root / CHANGESET_DIR).rglob("*")):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        assert not email.search(content), f"{path.name} contains an email-like value"
        assert not phone.search(content), f"{path.name} contains a phone-like value"
        assert "patient_name" not in content
        # Column names from the design may appear; concrete key values may not.
        assert not re.search(r"source_subject_key\s*[:=]\s*['\"]?[\w-]+", content)


# --------------------------------------------------------------------------------------
# Implementation gate state
# --------------------------------------------------------------------------------------


def test_implementation_gate_is_open_only_for_this_changeset() -> None:
    assert IMPLEMENTATION_GATE_OPEN is True
    assert AUTHORIZED_CHANGESET_ID == "stage-03-implementation-changeset-01"
    assert FROZEN_DESIGN_VERSION == "0.7.4"
    assert FROZEN_IMPLEMENTATION_PLAN_VERSION == "0.3.5"


def test_authorized_path_allowlist_is_narrow() -> None:
    assert is_authorized_changeset_path("migrations/canonical/0001_roles_and_schema.sql")
    assert is_authorized_changeset_path("src/human_simulator/canonical/migrations.py")
    assert not is_authorized_changeset_path("etl")
    assert not is_authorized_changeset_path("ddl/canonical.sql")
    assert unauthorized_paths(["migrations", "etl", "alembic"]) == ["alembic", "etl"]


def test_authorized_paths_all_exist(repo_root: Path) -> None:
    for path in CHANGESET_01_AUTHORIZED_PATHS:
        assert (repo_root / path).exists(), path


def test_plan_gate_still_rejects_unauthorized_implementation_paths(
    repo_root: Path, tmp_path: Path
) -> None:
    from human_simulator.stage03.verify_implementation_plan import verify_implementation_plan

    workspace = tmp_path / "workspace"
    for item in ("artifacts", "migrations", "config", "src", "docker-compose.yml", ".gitignore"):
        source = repo_root / item
        target = workspace / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    (workspace / "etl").mkdir()

    result = verify_implementation_plan(workspace, run_pytest=False, publish_artifacts=False)
    failed = {check["name"] for check in result["checks"] if check["status"] == "FAIL"}
    assert "no_ddl_etl_or_database_creation_artifacts" in failed


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def test_cli_no_publish_is_read_only(repo_root: Path) -> None:
    before = _hashes(sorted((repo_root / CHANGESET_DIR).rglob("*")))
    frozen_before = _frozen_inputs(repo_root)

    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "human_simulator.cli", "--root", str(repo_root),
         "changeset-01-check", "--no-publish"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert _hashes(sorted((repo_root / CHANGESET_DIR).rglob("*"))) == before
    assert _frozen_inputs(repo_root) == frozen_before


def test_cli_gate_command_returns_nonzero_while_blocked(repo_root: Path) -> None:
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "human_simulator.cli", "--root", str(repo_root),
         "stage-02-pre-live-load-gate"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    assert completed.returncode == 1
    document = json.loads(completed.stdout)
    assert document["status"] == "FAIL"


def test_cli_baseline_command_is_read_only(repo_root: Path) -> None:
    frozen_before = _frozen_inputs(repo_root)
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "human_simulator.cli", "--root", str(repo_root),
         "changeset-01-baseline"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert json.loads(completed.stdout)["status"] == "PASS"
    assert _frozen_inputs(repo_root) == frozen_before
