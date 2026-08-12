"""Build the candidate repair and prove it works without applying it.

The candidate is deliberately the smallest change that can be justified from evidence: the eight
relationship artifacts keep the bytes an accepted release published, and only the manifest is
re-sealed over them. Nothing is regenerated, because a regenerated artifact would carry a new
timestamp and would therefore be a set of bytes no release has ever accepted.

The candidate is written to ``artifacts/stage-02-maintenance-01/candidate/`` and validated by
overlaying it onto a throwaway copy of the workspace. ``artifacts/stage-02/`` is never written.
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
    verify_relationship_manifest,
)
from human_simulator.stage02_maintenance.constants import CANDIDATE_DIR, STAGE_02_DIR
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_file

# Everything the isolated validation needs to run the three checks end to end.
VALIDATION_INPUTS: tuple[str, ...] = (
    "artifacts",
    "migrations",
    "src",
    "config",
    "pyproject.toml",
)


@dataclass
class CandidateSet:
    directory: Path
    artifact_sha256: dict[str, str]
    manifest_sha256: str
    manifest_text: str
    changed_relative_to_stage_02: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "directory": CANDIDATE_DIR.as_posix(),
            "artifact_count": len(self.artifact_sha256),
            "artifact_sha256": dict(sorted(self.artifact_sha256.items())),
            "candidate_manifest_sha256": self.manifest_sha256,
            "files_whose_bytes_differ_from_working_stage_02": list(
                self.changed_relative_to_stage_02
            ),
            "regenerated_artifacts": 0,
            "working_stage_02_written": False,
        }


def build_candidate(repo_root: Path) -> CandidateSet:
    """Copy the eight accepted artifacts and seal a manifest over exactly those bytes."""
    root = repo_root.resolve()
    source = root / STAGE_02_DIR
    target = root / CANDIDATE_DIR
    target.mkdir(parents=True, exist_ok=True)

    hashes: dict[str, str] = {}
    changed: list[str] = []
    for name in RELATIONSHIP_MANIFEST_ARTIFACTS:
        origin = source / name
        destination = target / name
        shutil.copy2(origin, destination)
        digest = sha256_file(destination)
        hashes[name] = digest
        if digest != sha256_file(origin):  # pragma: no cover - copy2 preserves content
            changed.append(name)

    # Written directly rather than via write_relationship_manifest, because that helper takes a
    # Stage 02 directory and this must never be pointed at the working one by accident.
    manifest_text = "\n".join(f"{hashes[name]}  {name}" for name in RELATIONSHIP_MANIFEST_ARTIFACTS)
    manifest_path = target / MANIFEST_NAME
    manifest_path.write_text(manifest_text + "\n", encoding="utf-8")

    return CandidateSet(
        directory=target,
        artifact_sha256=hashes,
        manifest_sha256=sha256_file(manifest_path),
        manifest_text=manifest_text + "\n",
        changed_relative_to_stage_02=tuple(changed),
    )


# verify-stage-02 runs the whole pytest suite as one of its checks. Inside a throwaway copy that
# would re-enter the publication pipeline, so the suite is not run here and the two checks that
# depend on it are reported as not evaluated rather than silently counted as failures.
TEST_GATE_CHECKS: tuple[str, ...] = ("full_test_suite", "test_result_not_skipped")


@dataclass
class IsolatedValidation:
    applied: bool
    manifest_verified: bool
    manifest_detail: str
    verify_stage_02_status: str
    verify_stage_02_checks: tuple[tuple[str, str], ...]
    gate_status: str
    gate_failed_checks: tuple[str, ...]
    gate_open_blockers: tuple[str, ...]
    drift_blocker_cleared: bool
    working_stage_02_sha256_before: dict[str, str]
    working_stage_02_sha256_after: dict[str, str]

    @property
    def working_stage_02_unchanged(self) -> bool:
        return self.working_stage_02_sha256_before == self.working_stage_02_sha256_after

    @property
    def evaluated_failures(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, status in self.verify_stage_02_checks
            if status != "PASS" and name not in TEST_GATE_CHECKS
        )

    @property
    def relationship_manifest_check(self) -> str:
        for name, status in self.verify_stage_02_checks:
            if name == "relationship_manifest":
                return status
        return "NOT_PRESENT"

    @property
    def verify_stage_02_status_excluding_test_gate(self) -> str:
        return "PASS" if not self.evaluated_failures else "FAIL"

    def document(self) -> dict[str, Any]:
        return {
            "applied_in": "throwaway copy of the workspace, discarded afterwards",
            "candidate_applied": self.applied,
            "relationship_manifest_verified": self.manifest_verified,
            "relationship_manifest_detail": self.manifest_detail,
            "verify_stage_02": {
                "raw_status": self.verify_stage_02_status,
                "status_excluding_test_gate": self.verify_stage_02_status_excluding_test_gate,
                "relationship_manifest_check": self.relationship_manifest_check,
                "checks_evaluated": len(self.verify_stage_02_checks) - len(TEST_GATE_CHECKS),
                "failed_evaluated_checks": list(self.evaluated_failures),
                "checks_not_evaluated": list(TEST_GATE_CHECKS),
                "why_not_evaluated": (
                    "verify-stage-02 runs the full pytest suite as a check; inside a throwaway "
                    "copy that would re-enter the publication pipeline, so it was not run"
                ),
                "all_checks": [{"name": n, "status": s} for n, s in self.verify_stage_02_checks],
            },
            "pre_live_load_gate_status": self.gate_status,
            "pre_live_load_gate_failed_checks": list(self.gate_failed_checks),
            "pre_live_load_gate_open_blockers": list(self.gate_open_blockers),
            "manifest_drift_blocker_cleared": self.drift_blocker_cleared,
            "gate_still_fails_on_remaining_blockers": self.gate_status == "FAIL",
            "working_stage_02_sha256_before": dict(sorted(self.working_stage_02_sha256_before.items())),
            "working_stage_02_sha256_after": dict(sorted(self.working_stage_02_sha256_after.items())),
            "working_stage_02_unchanged": self.working_stage_02_unchanged,
        }


def _stage_02_fingerprint(repo_root: Path) -> dict[str, str]:
    directory = repo_root / STAGE_02_DIR
    names = (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME)
    return {name: sha256_file(directory / name) for name in names if (directory / name).is_file()}


def validate_candidate(repo_root: Path, candidate: CandidateSet) -> IsolatedValidation:
    """Overlay the candidate in a throwaway copy and run the three checks that must change."""
    from human_simulator.stage02.verify_stage_02 import verify_stage_02
    from human_simulator.stage03.pre_live_load_blockers import MANIFEST_DRIFT_BLOCKER
    from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate

    root = repo_root.resolve()
    before = _stage_02_fingerprint(root)

    with TemporaryDirectory(prefix="stage-02-maintenance-01-validate-") as handle:
        workspace = Path(handle) / "workspace"
        workspace.mkdir(parents=True)
        for relative in VALIDATION_INPUTS:
            origin = root / relative
            if not origin.exists():
                continue
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if origin.is_dir():
                shutil.copytree(origin, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(origin, destination)

        isolated_stage_02 = workspace / STAGE_02_DIR
        for name in (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME):
            shutil.copy2(candidate.directory / name, isolated_stage_02 / name)

        manifest_ok, manifest_detail = verify_relationship_manifest(isolated_stage_02)

        verification = verify_stage_02(workspace, run_tests=False, publish_artifacts=False)
        checks = tuple(
            (str(check.get("name")), str(check.get("status")))
            for check in verification.get("checks", [])
        )

        gate = evaluate_pre_live_load_gate(workspace)
        open_blockers = tuple(gate.blockers.get("open_blocker_ids", []))

    return IsolatedValidation(
        applied=True,
        manifest_verified=manifest_ok,
        manifest_detail=manifest_detail,
        verify_stage_02_status=str(verification.get("status")),
        verify_stage_02_checks=checks,
        gate_status=gate.status,
        gate_failed_checks=tuple(gate.failed_checks),
        gate_open_blockers=open_blockers,
        drift_blocker_cleared=MANIFEST_DRIFT_BLOCKER not in gate.failed_checks,
        working_stage_02_sha256_before=before,
        working_stage_02_sha256_after=_stage_02_fingerprint(root),
    )


def load_candidate(repo_root: Path) -> CandidateSet | None:
    """Read a previously built candidate without rebuilding it."""
    target = repo_root.resolve() / CANDIDATE_DIR
    manifest = target / MANIFEST_NAME
    if not manifest.is_file():
        return None
    hashes = {
        name: sha256_file(target / name)
        for name in RELATIONSHIP_MANIFEST_ARTIFACTS
        if (target / name).is_file()
    }
    return CandidateSet(
        directory=target,
        artifact_sha256=hashes,
        manifest_sha256=sha256_file(manifest),
        manifest_text=manifest.read_text(encoding="utf-8"),
        changed_relative_to_stage_02=(),
    )


def write_json(path: Path, document: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
