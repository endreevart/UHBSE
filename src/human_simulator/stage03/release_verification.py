"""Release evidence for Stage 03 implementation planning.

Every mandatory gate and test suite is executed once, with its literal command, counts,
exit code and duration recorded verbatim. ``overall_release_status`` is ``PASS`` only when
every mandatory entry reports zero failures and exit code 0.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RELEASE_VERIFICATION_NAME = "release-verification.json"

GATE_SUITE_EXCLUSIONS: tuple[str, ...] = (
    "test_published_verification_matches_final_report_bytes",
    "test_full_pytest_suite_preserves_publication_artifacts",
    "test_full_pytest_suite_does_not_mutate_prior_stage_artifacts",
    "test_implementation_plan_clean_extraction_gate",
    "test_unpacked_zip_pytest_preserves_publication_artifacts",
)

CLEAN_BUNDLE_SUITE_TARGETS: tuple[str, ...] = (
    "tests/test_verify_stage_03_design.py",
    "tests/test_verify_implementation_plan.py",
    "tests/test_stage03_contracts.py",
    "tests/test_review_bundle_validation.py",
    "tests/test_prior_stage_integrity.py",
)

CLEAN_BUNDLE_MARKER_EXPR = "not publisher_only"
FULL_REPOSITORY_MARKER_EXPR = "not verify_stage02_gate and not publisher_only"
INTEGRATION_MARKER_EXPR = "integration"

SUITE_KEY_ALIASES = "-k"
SUITE_MARKER_ALIASES = "-m"

# Every suite that must be present, executed and green before a bundle may be published.
# ``integration_migration_suite`` is mandatory from Changeset 01 v0.2: an overall PASS may
# only be claimed when the migrations were really applied to a disposable PostgreSQL 16.
MANDATORY_SUITE_NAMES: tuple[str, ...] = (
    "changeset_01_gate_suite",
    "clean_review_bundle_suite",
    "full_repository_suite",
    "integration_migration_suite",
)

# Suites where a skip means the evidence was never produced. A skipped integration suite
# looks green (exit 0, no failures) while proving nothing, so skips are failures there.
NO_SKIP_SUITE_NAMES: tuple[str, ...] = ("integration_migration_suite",)

# Changeset 01 (canonical storage foundation) suites.
CHANGESET_01_GATE_SUITE_TARGETS: tuple[str, ...] = (
    "tests/test_canonical_schema_contract.py",
    "tests/test_canonical_migrations_static.py",
    "tests/test_stage02_pre_live_load_gate.py",
    "tests/test_changeset_01_verifier.py",
    "tests/test_changeset_01_review_bundle.py",
)

CHANGESET_01_CLEAN_BUNDLE_SUITE_TARGETS: tuple[str, ...] = (
    *CLEAN_BUNDLE_SUITE_TARGETS,
    *CHANGESET_01_GATE_SUITE_TARGETS,
)

# Live-database suites are recorded separately, so the deterministic suites exclude them.
CHANGESET_01_STATIC_MARKER_EXPR = "not publisher_only and not integration"
CHANGESET_01_MIGRATION_MARKER_EXPR = "integration"


def changeset_01_gate_suite_command() -> list[str]:
    return [
        "uv",
        "run",
        "pytest",
        *CHANGESET_01_GATE_SUITE_TARGETS,
        "-q",
        SUITE_MARKER_ALIASES,
        CHANGESET_01_STATIC_MARKER_EXPR,
    ]


def changeset_01_clean_bundle_suite_command() -> list[str]:
    return [
        "uv",
        "run",
        "pytest",
        *CHANGESET_01_CLEAN_BUNDLE_SUITE_TARGETS,
        "-q",
        SUITE_MARKER_ALIASES,
        CHANGESET_01_STATIC_MARKER_EXPR,
        SUITE_KEY_ALIASES,
        _not_expression(GATE_SUITE_EXCLUSIONS),
    ]


def changeset_01_migration_suite_command() -> list[str]:
    return [
        "uv",
        "run",
        "pytest",
        "-q",
        SUITE_MARKER_ALIASES,
        CHANGESET_01_MIGRATION_MARKER_EXPR,
    ]


def clean_bundle_suite_command() -> list[str]:
    return [
        "uv",
        "run",
        "pytest",
        *CLEAN_BUNDLE_SUITE_TARGETS,
        "-q",
        SUITE_MARKER_ALIASES,
        CLEAN_BUNDLE_MARKER_EXPR,
        SUITE_KEY_ALIASES,
        _not_expression(GATE_SUITE_EXCLUSIONS),
    ]


def mandatory_release_suite_command() -> list[str]:
    return [
        "uv",
        "run",
        "pytest",
        "-q",
        SUITE_MARKER_ALIASES,
        FULL_REPOSITORY_MARKER_EXPR,
        SUITE_KEY_ALIASES,
        _not_expression(GATE_SUITE_EXCLUSIONS),
    ]


PUBLISHER_ONLY_MARKER_EXPR = "publisher_only"
VERIFY_STAGE02_GATE_MARKER_EXPR = "verify_stage02_gate"

MANDATORY_RELEASE_SUITE_DESELECTED: dict[str, Any] = {
    "marker_expression": FULL_REPOSITORY_MARKER_EXPR,
    "keyword_exclusions": list(GATE_SUITE_EXCLUSIONS),
    "deselected_markers": {
        "publisher_only": PUBLISHER_ONLY_MARKER_EXPR,
        "verify_stage02_gate": VERIFY_STAGE02_GATE_MARKER_EXPR,
    },
}


def collect_marker_deselected_tests(repo_root: Path, marker_expr: str) -> list[str]:
    """Return node ids collected under a marker expression."""
    completed = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "--collect-only",
            "-q",
            SUITE_MARKER_ALIASES,
            marker_expr,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return [
        line.strip()
        for line in output.splitlines()
        if "::" in line and not line.strip().startswith(("=", "-", " "))
    ]


def mandatory_release_suite_deselection(repo_root: Path) -> dict[str, Any]:
    """Describe every test/markers excluded from the mandatory release suite."""
    publisher_only = collect_marker_deselected_tests(repo_root, PUBLISHER_ONLY_MARKER_EXPR)
    verify_stage02_gate = collect_marker_deselected_tests(
        repo_root, VERIFY_STAGE02_GATE_MARKER_EXPR
    )
    keyword_excluded = list(GATE_SUITE_EXCLUSIONS)
    total = len(publisher_only) + len(verify_stage02_gate) + len(keyword_excluded)
    return {
        "marker_expression": FULL_REPOSITORY_MARKER_EXPR,
        "keyword_exclusions": keyword_excluded,
        "deselected_by_marker": {
            "publisher_only": publisher_only,
            "verify_stage02_gate": verify_stage02_gate,
        },
        "deselected_total_reported_by_pytest": total,
        "deselected_marker_counts": {
            "publisher_only": len(publisher_only),
            "verify_stage02_gate": len(verify_stage02_gate),
            "keyword_exclusions": len(keyword_excluded),
        },
    }


def full_repository_suite_command() -> list[str]:
    return [
        "uv",
        "run",
        "pytest",
        "-q",
        SUITE_MARKER_ALIASES,
        FULL_REPOSITORY_MARKER_EXPR,
        SUITE_KEY_ALIASES,
        _not_expression(("test_implementation_plan_clean_extraction_gate",)),
    ]


def integration_suite_command() -> list[str]:
    return ["uv", "run", "pytest", "-q", SUITE_MARKER_ALIASES, INTEGRATION_MARKER_EXPR]


def _not_expression(names: tuple[str, ...]) -> str:
    return " and ".join(f"not {name}" for name in names)


def shell_quote(command: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(part) for part in command)


@dataclass
class SuiteEvidence:
    name: str
    mandatory: bool
    command: str
    exit_code: int
    collected: int
    selected: int
    deselected: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration_seconds: float
    summary: str
    started_at: str
    finished_at: str
    allow_skips: bool = True

    @property
    def not_ok_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.exit_code != 0:
            reasons.append(f"exit code {self.exit_code}")
        if self.failed:
            reasons.append(f"{self.failed} failed")
        if self.errors:
            reasons.append(f"{self.errors} errors")
        if self.mandatory and self.selected == 0:
            reasons.append("nothing selected")
        if self.mandatory and self.passed == 0:
            reasons.append("no test passed")
        if not self.allow_skips and self.skipped:
            reasons.append(f"{self.skipped} skipped in a suite that may not skip")
        return reasons

    @property
    def ok(self) -> bool:
        return not self.not_ok_reasons


@dataclass
class GateEvidence:
    name: str
    mandatory: bool
    status: str
    checks_total: int
    checks_passed: int
    checks_failed: int
    verified_at: str

    @property
    def ok(self) -> bool:
        return self.status == "PASS" and self.checks_failed == 0


@dataclass
class ReleaseEvidence:
    gates: list[GateEvidence] = field(default_factory=list)
    suites: list[SuiteEvidence] = field(default_factory=list)

    @property
    def missing_mandatory_suites(self) -> list[str]:
        present = {suite.name for suite in self.suites}
        return [name for name in MANDATORY_SUITE_NAMES if name not in present]

    @property
    def non_mandatory_but_required_suites(self) -> list[str]:
        """Required suites that were recorded without the mandatory flag."""
        return sorted(
            suite.name
            for suite in self.suites
            if suite.name in MANDATORY_SUITE_NAMES and not suite.mandatory
        )

    @property
    def mandatory_failures(self) -> list[str]:
        failures = [
            f"{name} (not run)" for name in self.missing_mandatory_suites
        ]
        failures += [
            f"{name} (recorded as optional but is mandatory)"
            for name in self.non_mandatory_but_required_suites
        ]
        failures += [gate.name for gate in self.gates if gate.mandatory and not gate.ok]
        failures += [
            f"{suite.name} ({', '.join(suite.not_ok_reasons)})"
            for suite in self.suites
            if (suite.mandatory or suite.name in MANDATORY_SUITE_NAMES) and not suite.ok
        ]
        return failures

    @property
    def mandatory_ok(self) -> bool:
        return not self.mandatory_failures


def _parse_counts(output: str) -> dict[str, int | float | str | None]:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    summary = ""
    for line in reversed(lines):
        if re.search(r"\d+\s+(passed|failed|error|skipped|deselected)", line):
            summary = line.strip()
            break
    if not summary and lines:
        summary = lines[-1].strip()

    def count(label: str) -> int:
        match = re.search(rf"(\d+)\s+{label}", summary)
        return int(match.group(1)) if match else 0

    duration_match = re.search(r"in\s+([\d.]+)s", summary)
    return {
        "summary": summary or "no pytest output",
        "passed": count("passed"),
        "failed": count("failed"),
        "skipped": count("skipped"),
        "deselected": count("deselected"),
        "errors": count("error"),
        "reported_duration_seconds": float(duration_match.group(1)) if duration_match else None,
    }


def _collect_counts(repo_root: Path, command: list[str]) -> tuple[int, int]:
    """Return (collected_total, selected) using --collect-only for the same selection."""
    collect_command = [*command, "--collect-only"]
    completed = subprocess.run(collect_command, cwd=repo_root, capture_output=True, text=True)
    output = (completed.stdout or "") + (completed.stderr or "")
    match = re.search(r"(\d+)/(\d+)\s+tests collected", output)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.search(r"(\d+)\s+tests? collected", output)
    if match:
        total = int(match.group(1))
        return total, total
    return 0, 0


def run_suite(
    repo_root: Path,
    *,
    name: str,
    command: list[str],
    mandatory: bool,
    allow_skips: bool | None = None,
) -> SuiteEvidence:
    collected, selected = _collect_counts(repo_root, command)
    started = datetime.now(tz=UTC)
    monotonic_start = time.perf_counter()
    completed = subprocess.run(command, cwd=repo_root, capture_output=True, text=True)
    duration = round(time.perf_counter() - monotonic_start, 3)
    finished = datetime.now(tz=UTC)
    output = (completed.stdout or "") + (completed.stderr or "")
    parsed = _parse_counts(output)
    if selected == 0:
        selected = int(parsed["passed"]) + int(parsed["failed"]) + int(parsed["skipped"])
    return SuiteEvidence(
        name=name,
        mandatory=mandatory,
        command=shell_quote(command),
        exit_code=completed.returncode,
        collected=collected,
        selected=selected,
        deselected=int(parsed["deselected"]),
        passed=int(parsed["passed"]),
        failed=int(parsed["failed"]),
        skipped=int(parsed["skipped"]),
        errors=int(parsed["errors"]),
        duration_seconds=duration,
        summary=str(parsed["summary"]),
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        allow_skips=(name not in NO_SKIP_SUITE_NAMES) if allow_skips is None else allow_skips,
    )


def gate_evidence(name: str, result: dict[str, Any], *, mandatory: bool = True) -> GateEvidence:
    return GateEvidence(
        name=name,
        mandatory=mandatory,
        status=str(result.get("status", "FAIL")),
        checks_total=int(result.get("checks_total", 0)),
        checks_passed=int(result.get("checks_passed", 0)),
        checks_failed=int(result.get("checks_failed", 1)),
        verified_at=str(result.get("verified_at", "")),
    )


def build_release_document(
    *,
    evidence: ReleaseEvidence,
    gate_pytest: dict[str, Any],
    prior_stage_hashes_before: dict[str, str],
    prior_stage_hashes_after: dict[str, str],
    prior_stage_unchanged: bool,
    generated_at: str,
    design_version: str,
    plan_version: str,
) -> dict[str, Any]:
    mandatory_ok = evidence.mandatory_ok
    overall = "PASS" if mandatory_ok and prior_stage_unchanged else "FAIL"
    return {
        "generated_at": generated_at,
        "python_version": sys.version.split()[0],
        "design_baseline_version": design_version,
        "implementation_plan_version": plan_version,
        "gates": [asdict(gate) for gate in evidence.gates],
        "gate_pytest": {
            "name": "gate_pytest_implementation_plan_verifier",
            "mandatory": True,
            "command": gate_pytest.get("pytest_command", ""),
            "exit_code": gate_pytest.get("pytest_exit_code"),
            "collected": gate_pytest.get("pytest_collected"),
            "selected": gate_pytest.get("pytest_selected"),
            "deselected": gate_pytest.get("pytest_deselected"),
            "passed": gate_pytest.get("pytest_passed"),
            "failed": gate_pytest.get("pytest_failed"),
            "skipped": gate_pytest.get("pytest_skipped"),
            "duration_seconds": gate_pytest.get("pytest_duration_seconds"),
            "summary": gate_pytest.get("pytest_summary"),
        },
        "suites": [asdict(suite) for suite in evidence.suites],
        "prior_stage_integrity": {
            "hashes_before_test_suites": prior_stage_hashes_before,
            "hashes_after_test_suites": prior_stage_hashes_after,
            "unchanged": prior_stage_unchanged,
            "automatic_restore_performed": False,
        },
        "mandatory_suites": list(MANDATORY_SUITE_NAMES),
        "suites_that_may_not_skip": list(NO_SKIP_SUITE_NAMES),
        "mandatory_failures": evidence.mandatory_failures,
        "overall_release_status": overall,
    }


def write_release_verification(impl_dir: Path, document: dict[str, Any]) -> Path:
    impl_dir.mkdir(parents=True, exist_ok=True)
    path = impl_dir / RELEASE_VERIFICATION_NAME
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path
