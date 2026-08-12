"""Review bundle safety for Stage 03 Implementation Changeset 01.

The static tests below never build an archive. The clean-extraction gate is publisher-only
because it republishes the workspace bundle and therefore changes its SHA-256.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pytest

from human_simulator.stage02.relationship_manifest import MANIFEST_NAME
from human_simulator.stage02_maintenance.constants import EXPECTED_MANIFEST_SHA_AFTER
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_file
from human_simulator.stage03.changeset_01_constants import (
    CANONICAL_ENV_FILE,
    CHANGESET_DIR,
    CHANGESET_REPORT_NAME,
    CHANGESET_VERIFICATION_NAME,
    GATE_RESULT_NAME,
    RELEASE_VERIFICATION_NAME,
)
from human_simulator.stage03.changeset_01_review_bundle import (
    BUNDLE_SHA256_SIDECAR_NAME,
    BUNDLE_ZIP_NAME,
    ChangesetBundleError,
    _assert_no_forbidden_files,
    _has_concrete_dsn,
    _is_forbidden_member,
    validate_changeset_snapshot,
)
from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.release_verification import (
    CHANGESET_01_CLEAN_BUNDLE_SUITE_TARGETS,
    CHANGESET_01_GATE_SUITE_TARGETS,
    changeset_01_gate_suite_command,
)
from human_simulator.stage03.review_bundle_validation import validate_review_bundle_zip
from human_simulator.stage03.review_dependencies import (
    get_changeset_01_review_bundle_paths,
    get_changeset_01_review_dependencies,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = REPO_ROOT / "artifacts" / "external-review" / BUNDLE_ZIP_NAME


# --------------------------------------------------------------------------------------
# Bundle composition, evaluated without building anything
# --------------------------------------------------------------------------------------


def test_bundle_paths_cover_every_required_category() -> None:
    paths = set(get_changeset_01_review_bundle_paths())
    required = {
        CHANGESET_DIR.as_posix(),
        "migrations/canonical",
        "docker-compose.yml",
        "config/canonical-db.env.template",
        "src/human_simulator",
        "artifacts/stage-03",
        "artifacts/stage-03-implementation",
        "docs/stage-03-implementation-changeset-01.md",
        ".cursor/rules/08-canonical-implementation.mdc",
        ".cursor/commands/stage-03-changeset-01-check.md",
        "pyproject.toml",
        "uv.lock",
    }
    assert required <= paths


def test_bundle_paths_include_all_nine_controlled_prior_stage_files() -> None:
    from human_simulator.stage03.prior_stage_integrity import CONTROLLED_PRIOR_STAGE_PATHS

    paths = set(get_changeset_01_review_bundle_paths())
    assert len(CONTROLLED_PRIOR_STAGE_PATHS) == 9
    for controlled in CONTROLLED_PRIOR_STAGE_PATHS:
        assert controlled in paths, controlled


def test_bundle_paths_include_every_new_and_changed_test() -> None:
    paths = set(get_changeset_01_review_bundle_paths())
    for target in (
        "tests/test_canonical_schema_contract.py",
        "tests/test_canonical_migrations_static.py",
        "tests/test_canonical_migration_integration.py",
        "tests/test_stage02_pre_live_load_gate.py",
        "tests/test_changeset_01_verifier.py",
    ):
        assert target in paths, target


def test_bundle_paths_never_reference_secrets_or_dumps() -> None:
    for rel in get_changeset_01_review_bundle_paths():
        assert rel != CANONICAL_ENV_FILE
        assert not rel.endswith(".env")
        assert not rel.startswith("dumps")
        assert not rel.startswith("private")
        assert not rel.startswith("artifacts/external-review")


def test_every_declared_bundle_path_exists() -> None:
    for rel in get_changeset_01_review_bundle_paths():
        assert (REPO_ROOT / rel).exists(), rel


def test_changeset_dependencies_are_all_used_by_the_bundle() -> None:
    assert set(get_changeset_01_review_dependencies()) <= set(
        get_changeset_01_review_bundle_paths()
    )


# --------------------------------------------------------------------------------------
# Forbidden member classification is fail-closed
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "canonical-db.env",
        "db.env",
        ".env",
        "nested/inner.zip",
        "dumps/stage_magerya_api.dump",
        "backup.tar.gz",
        "backup.tgz",
        "snapshot.pgdump",
        "artifacts/stage-03/whatever.sql.gz",
    ],
)
def test_forbidden_members_are_detected(name: str) -> None:
    assert _is_forbidden_member(name)


@pytest.mark.parametrize(
    "name",
    [
        "migrations/canonical/0001_roles_and_schema.sql",
        "config/canonical-db.env.template",
        "REVIEW_INDEX.md",
        "artifacts/stage-03/canonical-model.yaml",
    ],
)
def test_allowed_members_are_not_flagged(name: str) -> None:
    assert not _is_forbidden_member(name)


def test_forbidden_file_scan_rejects_a_leaked_env_file(tmp_path: Path) -> None:
    (tmp_path / CANONICAL_ENV_FILE).write_text("CANONICAL_DB_ADMIN_USER=x\n", encoding="utf-8")
    with pytest.raises(ChangesetBundleError, match="forbidden members"):
        _assert_no_forbidden_files(tmp_path)


def test_forbidden_file_scan_rejects_a_leaked_dsn(tmp_path: Path) -> None:
    # Assembled at runtime so this test file itself carries no credential-bearing DSN.
    leaked = "postgres" + "ql://" + "someone" + ":" + "a-secret" + "@localhost:5436/db"
    (tmp_path / "notes.md").write_text(f"connect with {leaked}\n", encoding="utf-8")
    with pytest.raises(ChangesetBundleError, match="credential_bearing"):
        _assert_no_forbidden_files(tmp_path)


def test_forbidden_file_scan_accepts_a_clean_tree(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("host:port/database only, no credentials\n", encoding="utf-8")
    _assert_no_forbidden_files(tmp_path)


def test_dsn_format_templates_are_not_treated_as_credentials() -> None:
    assert not _has_concrete_dsn(
        'return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{db}"'
    )
    assert not _has_concrete_dsn('f"postgresql://{user}:***@{host}:{port}/{database}"')
    assert not _has_concrete_dsn("postgresql://user:<password>@host/db")


def test_literal_credentials_are_treated_as_a_leak() -> None:
    literal = "postgres" + "ql://" + "someone" + ":" + "a-secret" + "@localhost:5436/db"
    assert _has_concrete_dsn(literal)


# --------------------------------------------------------------------------------------
# Snapshot validation is fail-closed
# --------------------------------------------------------------------------------------


def test_published_changeset_snapshot_is_consistent() -> None:
    if not (REPO_ROOT / CHANGESET_DIR / CHANGESET_VERIFICATION_NAME).exists():
        pytest.skip("changeset artifacts not published in this workspace")
    ok, detail = validate_changeset_snapshot(REPO_ROOT / CHANGESET_DIR)
    assert ok, detail


def _snapshot_copy(tmp_path: Path) -> Path:
    source = REPO_ROOT / CHANGESET_DIR
    if not (source / CHANGESET_VERIFICATION_NAME).exists():
        pytest.skip("changeset artifacts not published in this workspace")
    target = tmp_path / "changeset"
    shutil.copytree(source, target)
    return target


def test_snapshot_validation_rejects_a_tampered_report(tmp_path: Path) -> None:
    target = _snapshot_copy(tmp_path)
    report = target / CHANGESET_REPORT_NAME
    report.write_text(report.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
    ok, detail = validate_changeset_snapshot(target)
    assert not ok
    assert "report_sha256" in detail


def test_snapshot_validation_rejects_a_final_report(tmp_path: Path) -> None:
    target = _snapshot_copy(tmp_path)
    document = json.loads((target / CHANGESET_VERIFICATION_NAME).read_text(encoding="utf-8"))
    document["report_status"] = "FINAL"
    (target / CHANGESET_VERIFICATION_NAME).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    ok, detail = validate_changeset_snapshot(target)
    assert not ok
    assert "report_status=FINAL" in detail


def test_snapshot_validation_requires_the_stage02_gate_to_stay_failing(tmp_path: Path) -> None:
    target = _snapshot_copy(tmp_path)
    gate = json.loads((target / GATE_RESULT_NAME).read_text(encoding="utf-8"))
    gate["status"] = "PASS"
    (target / GATE_RESULT_NAME).write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
    ok, detail = validate_changeset_snapshot(target)
    assert not ok
    assert "pre-live-load gate" in detail


def test_snapshot_validation_rejects_a_missing_manifest_entry(tmp_path: Path) -> None:
    target = _snapshot_copy(tmp_path)
    plan = target / "changeset-01-plan.yaml"
    plan.write_text(plan.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    ok, detail = validate_changeset_snapshot(target)
    assert not ok
    assert "manifest" in detail


# --------------------------------------------------------------------------------------
# Suite declarations
# --------------------------------------------------------------------------------------


def test_gate_suite_targets_all_exist() -> None:
    for target in CHANGESET_01_GATE_SUITE_TARGETS:
        assert (REPO_ROOT / target).exists(), target


def test_clean_bundle_suite_targets_are_all_inside_the_bundle() -> None:
    bundle_paths = set(get_changeset_01_review_bundle_paths())
    for target in CHANGESET_01_CLEAN_BUNDLE_SUITE_TARGETS:
        assert target in bundle_paths, target


def test_gate_suite_command_excludes_live_and_publisher_tests() -> None:
    command = changeset_01_gate_suite_command()
    assert "-m" in command
    marker = command[command.index("-m") + 1]
    assert "not publisher_only" in marker
    assert "not integration" in marker


# --------------------------------------------------------------------------------------
# Published archive. These assert on publication output, which exists only in the publisher
# workspace after publication, so they are excluded from the gate and repository suites that
# run *during* publication.
# --------------------------------------------------------------------------------------


@pytest.mark.publisher_only
def test_published_bundle_matches_its_index_and_sidecar() -> None:
    if not BUNDLE_PATH.exists():
        pytest.skip("review bundle not published in this workspace")
    ok, detail = validate_review_bundle_zip(BUNDLE_PATH)
    assert ok, detail

    sidecar = BUNDLE_PATH.with_name(BUNDLE_SHA256_SIDECAR_NAME)
    assert sidecar.exists()
    recorded = sidecar.read_text(encoding="utf-8").split()[0]
    assert recorded == sha256_file(BUNDLE_PATH)


@pytest.mark.publisher_only
def test_published_bundle_contains_no_forbidden_member() -> None:
    if not BUNDLE_PATH.exists():
        pytest.skip("review bundle not published in this workspace")
    with zipfile.ZipFile(BUNDLE_PATH) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
    assert members
    assert not [name for name in members if _is_forbidden_member(name)]
    assert not [name for name in members if name.startswith("artifacts/external-review/")]


@pytest.mark.publisher_only
def test_published_bundle_carries_the_required_evidence() -> None:
    if not BUNDLE_PATH.exists():
        pytest.skip("review bundle not published in this workspace")
    changeset = CHANGESET_DIR.as_posix()
    with zipfile.ZipFile(BUNDLE_PATH) as archive:
        members = set(archive.namelist())
    for required in (
        "REVIEW_INDEX.md",
        "REPRODUCE.md",
        f"{changeset}/changeset-01-plan.yaml",
        f"{changeset}/{CHANGESET_REPORT_NAME}",
        f"{changeset}/{CHANGESET_VERIFICATION_NAME}",
        f"{changeset}/{RELEASE_VERIFICATION_NAME}",
        f"{changeset}/{GATE_RESULT_NAME}",
        f"{changeset}/prior-stage-integrity.json",
        f"{changeset}/unresolved-changeset-01-decisions.yaml",
        f"{changeset}/migration-result.json",
        f"{changeset}/permission-report.json",
        "migrations/canonical/0001_roles_and_schema.sql",
        "migrations/canonical/0002_pilot_evidence_tables.sql",
        "migrations/canonical/0003_pilot_grants.sql",
        "docker-compose.yml",
        "config/canonical-db.env.template",
        "artifacts/stage-03/design-content-manifest.sha256",
        "artifacts/stage-03-implementation/implementation-plan-manifest.sha256",
    ):
        assert required in members, required


@pytest.mark.publisher_only
def test_changeset_01_clean_extraction_gate() -> None:
    """Publisher-only: the extracted archive must verify on its own."""
    if not BUNDLE_PATH.exists():
        pytest.skip("review bundle not published in this workspace")

    with tempfile.TemporaryDirectory(prefix="changeset-01-clean-extract-") as tmp:
        extract_root = Path(tmp)
        with zipfile.ZipFile(BUNDLE_PATH) as archive:
            archive.extractall(extract_root)

        sync = subprocess.run(  # noqa: S603
            ["uv", "sync", "--frozen", "--extra", "dev"],  # noqa: S607
            cwd=extract_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert sync.returncode == 0, sync.stderr

        before = _changeset_hashes(extract_root)
        gate = subprocess.run(  # noqa: S603
            ["uv", "run", "audit", "--root", ".", "changeset-01-check", "--no-publish"],  # noqa: S607
            cwd=extract_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert gate.returncode == 0, gate.stdout[-4000:] + gate.stderr[-2000:]
        assert _changeset_hashes(extract_root) == before

        blocker = subprocess.run(  # noqa: S603
            ["uv", "run", "audit", "--root", ".", "stage-02-pre-live-load-gate"],  # noqa: S607
            cwd=extract_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert blocker.returncode == 1
        extracted_gate = json.loads(blocker.stdout)
        assert extracted_gate["status"] == "FAIL"
        publisher_root = Path.cwd()
        publisher_gate = evaluate_pre_live_load_gate(publisher_root)
        manifest_sha = sha256_file(publisher_root / "artifacts" / "stage-02" / MANIFEST_NAME)
        if manifest_sha == EXPECTED_MANIFEST_SHA_AFTER:
            # The published bundle predates Maintenance 01. Extraction must reproduce the
            # publication-time gate from the frozen gate artifact, not the repaired workspace.
            bundled_gate = json.loads(
                (publisher_root / CHANGESET_DIR / GATE_RESULT_NAME).read_text(encoding="utf-8")
            )
            assert sorted(extracted_gate["failed_checks"]) == sorted(
                bundled_gate["failed_checks"]
            )
            assert "relationship_manifest_hashes_match" in extracted_gate["failed_checks"]
            assert "stage02_relationship_manifest_drift" in extracted_gate["failed_checks"]
            assert "relationship_manifest_hashes_match" not in publisher_gate.failed_checks
            assert "stage02_relationship_manifest_drift" not in publisher_gate.failed_checks
        else:
            # The clean extraction must reproduce the publisher's failure reason exactly.
            # "manifest missing" would mean the archive lacks a gate input, not that the
            # Stage 02 defect is real.
            assert sorted(extracted_gate["failed_checks"]) == sorted(publisher_gate.failed_checks)
            assert "relationship_manifest_hashes_match" not in extracted_gate["failed_checks"]
        assert "relationship_manifest_present" not in extracted_gate["failed_checks"]

        suite = subprocess.run(  # noqa: S603
            [
                "uv",
                "run",
                "pytest",
                *CHANGESET_01_GATE_SUITE_TARGETS,
                "-q",
                "-m",
                "not publisher_only and not integration",
            ],
            cwd=extract_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert suite.returncode == 0, suite.stdout[-4000:] + suite.stderr[-2000:]
        assert _changeset_hashes(extract_root) == before


def _changeset_hashes(root: Path) -> dict[str, str]:
    changeset = root / CHANGESET_DIR
    return {
        path.relative_to(changeset).as_posix(): sha256_file(path)
        for path in sorted(changeset.rglob("*"))
        if path.is_file()
    }
