"""The release pipeline must fail closed when the integration migration suite is not green.

Changeset 01 v0.1 recorded ``integration_migration_suite`` as optional, so a release could
report PASS while the migrations had never touched a real PostgreSQL 16. These tests pin the
v0.2 behaviour: absent, skipped, failing or errored, the suite blocks publication.

No database and no subprocess is required: the tests drive the evidence model directly and
then drive the publisher with a stubbed suite runner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from human_simulator.stage03 import publish_changeset_01 as publisher
from human_simulator.stage03.release_verification import (
    MANDATORY_SUITE_NAMES,
    NO_SKIP_SUITE_NAMES,
    ReleaseEvidence,
    SuiteEvidence,
    build_release_document,
)

INTEGRATION_SUITE = "integration_migration_suite"


def _suite(name: str, **overrides: Any) -> SuiteEvidence:
    values: dict[str, Any] = {
        "name": name,
        "mandatory": True,
        "command": f"uv run pytest -q -m {name}",
        "exit_code": 0,
        "collected": 10,
        "selected": 10,
        "deselected": 0,
        "passed": 10,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "duration_seconds": 1.0,
        "summary": "10 passed",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00",
        "allow_skips": name not in NO_SKIP_SUITE_NAMES,
    }
    values.update(overrides)
    return SuiteEvidence(**values)


def _evidence(*suites: SuiteEvidence) -> ReleaseEvidence:
    evidence = ReleaseEvidence()
    evidence.suites.extend(suites)
    return evidence


def _document(evidence: ReleaseEvidence) -> dict[str, Any]:
    return build_release_document(
        evidence=evidence,
        gate_pytest={},
        prior_stage_hashes_before={"a": "1"},
        prior_stage_hashes_after={"a": "1"},
        prior_stage_unchanged=True,
        generated_at="2026-01-01T00:00:00+00:00",
        design_version="0.7.4",
        plan_version="0.3.5",
    )


def test_the_integration_migration_suite_is_declared_mandatory() -> None:
    assert INTEGRATION_SUITE in MANDATORY_SUITE_NAMES
    assert INTEGRATION_SUITE in NO_SKIP_SUITE_NAMES


def test_all_mandatory_suites_green_gives_an_overall_pass() -> None:
    document = _document(_evidence(*(_suite(name) for name in MANDATORY_SUITE_NAMES)))
    assert document["mandatory_failures"] == []
    assert document["overall_release_status"] == "PASS"


def test_an_absent_integration_suite_fails_the_release() -> None:
    others = [name for name in MANDATORY_SUITE_NAMES if name != INTEGRATION_SUITE]
    document = _document(_evidence(*(_suite(name) for name in others)))
    assert document["overall_release_status"] == "FAIL"
    assert any(INTEGRATION_SUITE in entry for entry in document["mandatory_failures"])


def test_a_skipped_integration_suite_fails_the_release() -> None:
    """A skip looks green — exit 0, nothing failed — while proving nothing."""
    suites = [
        _suite(name) if name != INTEGRATION_SUITE else _suite(name, passed=0, skipped=10)
        for name in MANDATORY_SUITE_NAMES
    ]
    document = _document(_evidence(*suites))
    assert document["overall_release_status"] == "FAIL"
    assert any(INTEGRATION_SUITE in entry for entry in document["mandatory_failures"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"exit_code": 1},
        {"failed": 1},
        {"errors": 1},
        {"selected": 0, "passed": 0},
    ],
    ids=["nonzero_exit", "one_failed", "one_error", "nothing_selected"],
)
def test_a_broken_integration_suite_fails_the_release(overrides: dict[str, Any]) -> None:
    suites = [
        _suite(name) if name != INTEGRATION_SUITE else _suite(name, **overrides)
        for name in MANDATORY_SUITE_NAMES
    ]
    document = _document(_evidence(*suites))
    assert document["overall_release_status"] == "FAIL"
    assert any(INTEGRATION_SUITE in entry for entry in document["mandatory_failures"])


def test_recording_the_integration_suite_as_optional_does_not_hide_a_failure() -> None:
    """The v0.1 hole: marking the suite optional must no longer buy an overall PASS."""
    suites = [
        _suite(name)
        if name != INTEGRATION_SUITE
        else _suite(name, mandatory=False, exit_code=1, failed=3)
        for name in MANDATORY_SUITE_NAMES
    ]
    document = _document(_evidence(*suites))
    assert document["overall_release_status"] == "FAIL"
    assert any(INTEGRATION_SUITE in entry for entry in document["mandatory_failures"])


IGNORED_IN_SANDBOX = (
    ".git",
    ".venv",
    "dumps",
    "external-review",
    # Local runtime credentials are never part of a publication workspace.
    "canonical-db.env",
    "db.env",
    "private",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".DS_Store",
)


@pytest.fixture
def sandbox_repo(repo_root: Path, tmp_path: Path) -> Path:
    """A throwaway copy of the workspace, so a publish attempt cannot touch real artifacts."""
    import shutil

    destination = tmp_path / "workspace"
    shutil.copytree(
        repo_root,
        destination,
        ignore=shutil.ignore_patterns(*IGNORED_IN_SANDBOX, ".tmp-*"),
        symlinks=True,
    )
    (destination / "artifacts" / "external-review").mkdir(parents=True, exist_ok=True)
    return destination


def test_publication_is_refused_and_no_bundle_is_written_when_integration_fails(
    sandbox_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the real publisher with an artificially failing integration suite."""
    built: list[str] = []

    def fake_run_suite(
        root: Path, *, name: str, command: list[str], mandatory: bool
    ) -> SuiteEvidence:
        if name == INTEGRATION_SUITE:
            return _suite(
                name,
                mandatory=mandatory,
                exit_code=1,
                passed=7,
                failed=3,
                summary="3 failed, 7 passed",
            )
        return _suite(name, mandatory=mandatory)

    def fake_build_bundle(*args: Any, **kwargs: Any) -> Any:
        built.append("bundle")
        raise AssertionError("the review bundle must not be built after a mandatory failure")

    monkeypatch.setattr(publisher, "run_suite", fake_run_suite)
    monkeypatch.setattr(publisher, "build_changeset_01_review_bundle", fake_build_bundle)

    with pytest.raises(publisher.ChangesetPublicationBlocked) as excinfo:
        publisher.publish_changeset_01(sandbox_repo)

    assert INTEGRATION_SUITE in str(excinfo.value)
    assert built == []
    assert list((sandbox_repo / "artifacts" / "external-review").glob("*.zip")) == []


def test_publication_proceeds_past_the_release_gate_when_every_suite_is_green(
    sandbox_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal above must come from the failing suite, not from the sandbox itself."""
    reached: list[str] = []

    def fake_run_suite(
        root: Path, *, name: str, command: list[str], mandatory: bool
    ) -> SuiteEvidence:
        return _suite(name, mandatory=mandatory)

    def fake_build_bundle(*args: Any, **kwargs: Any) -> Any:
        reached.append("bundle")
        raise RuntimeError("stop after the release gate")

    monkeypatch.setattr(publisher, "run_suite", fake_run_suite)
    monkeypatch.setattr(publisher, "build_changeset_01_review_bundle", fake_build_bundle)

    with pytest.raises(RuntimeError, match="stop after the release gate"):
        publisher.publish_changeset_01(sandbox_repo)

    assert reached == ["bundle"]
