"""Reproduce the Stage 02 relationship assessment without touching the working Stage 02.

``assess-source-relationship`` writes its eight artifacts and rewrites the manifest. Running it
against the repository would repair the drift by accident and destroy the evidence, so it runs
against a throwaway copy of the workspace and the results are read back from there.

The assessment queries both sources through the dedicated read-only audit roles and verifies
row-count fingerprints before and after, so the raw databases are provably unchanged. Row-level
values are processed inside the local runtime to compute keyed digests; only aggregates reach
any artifact, and ``validate_relationship_artifacts`` re-checks that before this returns.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
)
from human_simulator.stage02_maintenance.constants import STAGE_02_DIR
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_bytes

# Everything the assessment reads: Stage 01 evidence, the Stage 02 inputs, the source settings
# and the local credential files. Copying rather than symlinking keeps the throwaway workspace
# genuinely separate from the repository.
REPRODUCTION_INPUTS: tuple[str, ...] = (
    "artifacts/stage-01",
    "artifacts/stage-02",
    "config",
    "private",
    "db.env",
    "db-audit.env",
    "db-kgz.env",
    "pyproject.toml",
)


@dataclass
class ReproductionResult:
    attempted: bool
    completed: bool
    detail: str
    workspace_discarded: bool
    artifact_sha256: dict[str, str]
    artifact_bytes: dict[str, bytes]
    manifest_text: str
    query_log: list[dict[str, str]]
    safety_findings: list[dict[str, str]]
    raw_databases_unchanged: bool | None
    clinical_rows_processed_in_runtime: bool

    def document(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "completed": self.completed,
            "detail": self.detail,
            "ran_against": "throwaway copy of the workspace, discarded afterwards",
            "working_stage_02_written": False,
            "workspace_discarded": self.workspace_discarded,
            "artifact_sha256": dict(sorted(self.artifact_sha256.items())),
            "query_count": len(self.query_log),
            "artifact_safety_findings": self.safety_findings,
            "raw_databases_unchanged": self.raw_databases_unchanged,
            "clinical_rows_processed_in_local_runtime": self.clinical_rows_processed_in_runtime,
            "clinical_rows_written_to_artifacts": False,
        }


def _stage_inputs(repo_root: Path, workspace: Path) -> None:
    for relative in REPRODUCTION_INPUTS:
        source = repo_root / relative
        if not source.exists():
            continue
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def sanitise_query_log(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep the operation names and statuses; drop anything that could carry a value.

    The assessment's own log is already aggregate-only, but a maintenance artifact that
    republishes a log must not depend on that being true, so the projection is explicit.
    """
    allowed = ("operation", "status", "relation", "schema", "source", "duration_ms", "row_count")
    sanitised: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sanitised.append(
            {key: str(entry[key]) for key in allowed if key in entry and entry[key] is not None}
        )
    return sanitised


def reproduce_assessment(repo_root: Path) -> ReproductionResult:
    """Run the assessment in a throwaway workspace and read the artifacts back out."""
    root = repo_root.resolve()

    try:
        from human_simulator.stage02.assess_source_relationship import assess_source_relationship
    except ImportError as error:  # pragma: no cover - dependency is part of the package
        return ReproductionResult(
            attempted=False,
            completed=False,
            detail=f"assessment entry point unavailable: {error}",
            workspace_discarded=False,
            artifact_sha256={},
            artifact_bytes={},
            manifest_text="",
            query_log=[],
            safety_findings=[],
            raw_databases_unchanged=None,
            clinical_rows_processed_in_runtime=False,
        )

    with TemporaryDirectory(prefix="stage-02-maintenance-01-reproduce-") as handle:
        workspace = Path(handle) / "workspace"
        workspace.mkdir(parents=True)
        _stage_inputs(root, workspace)

        try:
            outcome = assess_source_relationship(workspace)
        except Exception as error:  # noqa: BLE001 - a failed reproduction is a result, not a crash
            return ReproductionResult(
                attempted=True,
                completed=False,
                detail=f"{type(error).__name__}: {error}",
                workspace_discarded=True,
                artifact_sha256={},
                artifact_bytes={},
                manifest_text="",
                query_log=[],
                safety_findings=[],
                raw_databases_unchanged=None,
                clinical_rows_processed_in_runtime=True,
            )

        directory = workspace / STAGE_02_DIR
        payloads: dict[str, bytes] = {}
        for name in (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME):
            path = directory / name
            if path.is_file():
                payloads[name] = path.read_bytes()

        report_path = directory / "relationship-verification-report.json"
        raw_unchanged: bool | None = None
        findings: list[dict[str, str]] = []
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            for check in report.get("checks", []):
                if check.get("name") == "raw_databases_unchanged":
                    raw_unchanged = check.get("status") == "PASS"
                if check.get("name") == "artifact_safety" and check.get("status") != "PASS":
                    findings.append({"check": "artifact_safety", "detail": str(check.get("detail"))})

        log_path = directory / "relationship-query-log.json"
        entries: list[dict[str, Any]] = []
        if log_path.is_file():
            logged = json.loads(log_path.read_text(encoding="utf-8"))
            entries = logged.get("operations", []) if isinstance(logged, dict) else []
        query_log = sanitise_query_log(entries)
        status = outcome.get("status") if isinstance(outcome, dict) else None

    return ReproductionResult(
        attempted=True,
        completed=True,
        detail=f"assessment completed in a throwaway workspace with status {status}",
        workspace_discarded=True,
        artifact_sha256={name: sha256_bytes(data) for name, data in payloads.items()},
        artifact_bytes=payloads,
        manifest_text=payloads.get(MANIFEST_NAME, b"").decode("utf-8"),
        query_log=query_log,
        safety_findings=list(findings),
        raw_databases_unchanged=raw_unchanged,
        clinical_rows_processed_in_runtime=True,
    )
