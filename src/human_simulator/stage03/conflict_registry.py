"""Fail-closed validation of the accepted-artifact conflict registry.

v0.2.2 made every conflict that is ``OPEN`` and ``BLOCKS_LIVE_LOAD`` an automatic gate check,
which removed the risk of two hand-maintained lists drifting apart. It introduced a quieter one
in its place: the checks are derived from a file, so damaging the file removes checks. Deleting
the registry made two blockers vanish and the gate reported *fewer* failures than before —
fail-open behaviour dressed as a smaller problem.

The registry is therefore validated as an artifact in its own right. Anything that would make it
an unreliable source of blockers — absent, unparsable, malformed, self-inconsistent, or not the
bytes the changeset manifest accepted — is a failure by itself, independent of the conflicts it
happens to contain.

No conflict identifier is written here. The registry is the only place they exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from human_simulator.stage03.changeset_01_constants import (
    ARTIFACT_CONFLICTS_NAME,
    CHANGESET_DIR,
    CHANGESET_MANIFEST_NAME,
)
from human_simulator.stage03.preconditions import sha256_file

CONFLICTS_ARTIFACT = CHANGESET_DIR / ARTIFACT_CONFLICTS_NAME

BLOCKING_SEVERITY = "BLOCKS_LIVE_LOAD"
OPEN_STATUS = "OPEN"

KNOWN_SEVERITIES: frozenset[str] = frozenset({BLOCKING_SEVERITY, "BLOCKS_PILOT_SCOPE", "ADVISORY"})
KNOWN_STATUSES: frozenset[str] = frozenset({OPEN_STATUS, "RESOLVED", "SUPERSEDED", "WITHDRAWN"})

REQUIRED_CONFLICT_FIELDS: tuple[str, ...] = ("id", "severity", "status")


@dataclass(frozen=True)
class RegistryValidation:
    valid: bool
    problems: tuple[str, ...]
    conflicts: tuple[dict[str, Any], ...]
    blocking_ids: tuple[str, ...]
    open_conflict_count_recorded: int | None
    open_conflict_count_actual: int
    manifest_match: bool
    sha256: str | None

    @property
    def detail(self) -> str:
        if self.valid:
            return (
                f"{len(self.conflicts)} conflicts, {len(self.blocking_ids)} open and blocking, "
                f"registry sha256 {self.sha256}"
            )
        return "; ".join(self.problems)

    def document(self) -> dict[str, Any]:
        return {
            "artifact": CONFLICTS_ARTIFACT.as_posix(),
            "valid": self.valid,
            "problems": list(self.problems),
            "sha256": self.sha256,
            "matches_changeset_manifest": self.manifest_match,
            "conflict_count": len(self.conflicts),
            "open_conflict_count_recorded": self.open_conflict_count_recorded,
            "open_conflict_count_actual": self.open_conflict_count_actual,
            "open_blocking_conflict_ids": list(self.blocking_ids),
        }


def _manifest_records_registry(repo_root: Path, digest: str | None) -> tuple[bool, str | None]:
    """Does the accepted changeset manifest record exactly these bytes?"""
    manifest = repo_root / CHANGESET_DIR / CHANGESET_MANIFEST_NAME
    if not manifest.is_file():
        return False, f"missing {CHANGESET_MANIFEST_NAME}"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip() == ARTIFACT_CONFLICTS_NAME:
            if parts[0] == digest:
                return True, None
            return False, (
                f"{ARTIFACT_CONFLICTS_NAME} does not match the hash recorded in "
                f"{CHANGESET_MANIFEST_NAME}"
            )
    return False, f"{ARTIFACT_CONFLICTS_NAME} is not listed in {CHANGESET_MANIFEST_NAME}"


def validate_conflict_registry(repo_root: Path) -> RegistryValidation:
    """Validate the registry itself. Every failure mode is a failure, never a smaller gate."""
    path = repo_root / CONFLICTS_ARTIFACT
    problems: list[str] = []

    if not path.is_file():
        return RegistryValidation(
            valid=False,
            problems=(
                f"{CONFLICTS_ARTIFACT.as_posix()} is absent; a missing registry removes blocker "
                "checks and must fail loudly instead",
            ),
            conflicts=(),
            blocking_ids=(),
            open_conflict_count_recorded=None,
            open_conflict_count_actual=0,
            manifest_match=False,
            sha256=None,
        )

    digest = sha256_file(path)
    manifest_match, manifest_problem = _manifest_records_registry(repo_root, digest)
    if manifest_problem:
        problems.append(manifest_problem)

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        first_line = str(error).splitlines()[0] if str(error) else "unparsable"
        return RegistryValidation(
            valid=False,
            problems=(f"{CONFLICTS_ARTIFACT.name} is not valid YAML: {first_line}",),
            conflicts=(),
            blocking_ids=(),
            open_conflict_count_recorded=None,
            open_conflict_count_actual=0,
            manifest_match=manifest_match,
            sha256=digest,
        )

    if not isinstance(document, dict):
        return RegistryValidation(
            valid=False,
            problems=(f"{CONFLICTS_ARTIFACT.name} does not parse to a mapping",),
            conflicts=(),
            blocking_ids=(),
            open_conflict_count_recorded=None,
            open_conflict_count_actual=0,
            manifest_match=manifest_match,
            sha256=digest,
        )

    raw = document.get("conflicts")
    if raw is None:
        problems.append("the conflicts key is absent")
        raw = []
    elif not isinstance(raw, list):
        problems.append(f"conflicts is a {type(raw).__name__}, not a list")
        raw = []
    elif not raw:
        problems.append(
            "conflicts is empty; an empty registry silently removes every conflict-derived "
            "blocker check"
        )

    conflicts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            problems.append(f"conflict at index {index} is not a mapping")
            continue
        absent = [name for name in REQUIRED_CONFLICT_FIELDS if not str(entry.get(name, "")).strip()]
        if absent:
            problems.append(f"conflict at index {index} is missing {absent}")
            continue
        identifier = str(entry["id"]).strip()
        severity = str(entry["severity"]).strip().upper()
        status = str(entry["status"]).strip().upper()
        if identifier in seen_ids:
            problems.append(f"duplicate conflict id {identifier!r}")
            continue
        seen_ids.add(identifier)
        if severity not in KNOWN_SEVERITIES:
            problems.append(
                f"conflict {identifier!r} has unknown severity {severity!r}; known values are "
                f"{sorted(KNOWN_SEVERITIES)}"
            )
        if status not in KNOWN_STATUSES:
            problems.append(
                f"conflict {identifier!r} has unknown status {status!r}; known values are "
                f"{sorted(KNOWN_STATUSES)}"
            )
        conflicts.append({**entry, "id": identifier, "severity": severity, "status": status})

    open_actual = sum(1 for entry in conflicts if entry["status"] == OPEN_STATUS)
    recorded = document.get("open_conflict_count")
    if not isinstance(recorded, int) or isinstance(recorded, bool):
        problems.append("open_conflict_count is absent or not an integer")
        recorded = None
    elif recorded != open_actual:
        problems.append(f"open_conflict_count records {recorded} but {open_actual} conflicts are OPEN")

    blocking = tuple(
        entry["id"]
        for entry in conflicts
        if entry["severity"] == BLOCKING_SEVERITY and entry["status"] == OPEN_STATUS
    )

    return RegistryValidation(
        valid=not problems,
        problems=tuple(problems),
        conflicts=tuple(conflicts),
        blocking_ids=blocking,
        open_conflict_count_recorded=recorded,
        open_conflict_count_actual=open_actual,
        manifest_match=manifest_match,
        sha256=digest,
    )
