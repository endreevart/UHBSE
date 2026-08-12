"""The single registry of everything that blocks the first live load.

Changeset 01 v0.2 kept two lists: blockers computed here, and conflicts recorded in
``accepted-artifact-conflicts.yaml``. The gate consulted only the first, so two conflicts marked
``severity: BLOCKS_LIVE_LOAD`` and ``status: OPEN`` were documented as blocking while the
executable guard ignored them entirely. A guard that disagrees with its own documentation is
worse than no guard, because it invites trust it has not earned.

v0.2.2 makes this module the only producer of blockers. Conflicts become blockers automatically:
any conflict that is OPEN and BLOCKS_LIVE_LOAD is a FAIL check, without being restated here.
Adding a conflict to the artifact is therefore sufficient to block a live load.

Blocker sources:

* Stage 02 relationship manifest integrity;
* the subject key transformation contract, resolved from its authoritative Design path;
* the loader runtime security contract, resolved from its authoritative Plan path;
* every OPEN, BLOCKS_LIVE_LOAD entry in a *valid* ``accepted-artifact-conflicts.yaml``.

v0.2.3 closed the remaining fail-open path in that last source. Deriving checks from a file means
damaging the file removes checks, so the registry is validated as an artifact in its own right by
``conflict_registry.py`` and its validity is a gate check separate from the conflicts it lists.

Nothing here repairs an artifact, fills a gap by guessing, or reads a database. A blocker stays
OPEN until an accepted release resolves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from human_simulator.canonical.constants import ROLE_LOADER
from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
    sha256_file,
)
from human_simulator.stage03.changeset_01_constants import DESIGN_DIR
from human_simulator.stage03.conflict_registry import (
    BLOCKING_SEVERITY,
    CONFLICTS_ARTIFACT,
    OPEN_STATUS,
    validate_conflict_registry,
)
from human_simulator.stage03.conflict_resolution import (
    conflict_resolution_supersedes_open_blocker,
    evaluate_resolution_gate,
)
from human_simulator.stage03.live_load_contracts import (
    RUNTIME_CONTRACT_KEY,
    SUBJECT_KEY_CONTRACT_KEY,
    ContractValidation,
    contract_authority_document,
    validate_runtime_contract,
    validate_subject_key_contract,
)

SUBJECT_KEY_TRANSFORMATION = "subject_key_from_id"
SUBJECT_KEY_SOURCE_COLUMN = "account_patient.id"

STAGE_02_DIR = Path("artifacts") / "stage-02"

MANIFEST_DRIFT_BLOCKER = "stage02_relationship_manifest_drift"
SUBJECT_KEY_BLOCKER = "source_subject_key_opacity_undefined"
LOADER_PRINCIPAL_BLOCKER = "canonical_loader_runtime_principal_undefined"

# Blockers that must exist regardless of what any artifact says. A blocker disappearing because
# its source file vanished would be a silent unblocking, so the gate asserts this set is present.
REQUIRED_BLOCKER_IDS: frozenset[str] = frozenset(
    {MANIFEST_DRIFT_BLOCKER, SUBJECT_KEY_BLOCKER, LOADER_PRINCIPAL_BLOCKER}
)


@dataclass(frozen=True)
class Blocker:
    blocker_id: str
    status: str
    question: str
    evidence: str
    blocks_live_load: bool
    blocks_schema_migration: bool
    source: str

    def document(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "status": self.status,
            "question": self.question,
            "evidence": self.evidence,
            "blocks_live_load": self.blocks_live_load,
            "blocks_schema_only_migration_0004": self.blocks_schema_migration,
            "source": self.source,
        }


def _manifest_mismatches(repo_root: Path) -> list[str]:
    directory = repo_root / STAGE_02_DIR
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"missing {MANIFEST_NAME}"]

    recorded: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        digest, name = stripped.split(maxsplit=1)
        recorded[name.strip()] = digest

    mismatched: list[str] = []
    for name in RELATIONSHIP_MANIFEST_ARTIFACTS:
        path = directory / name
        current = sha256_file(path) if path.is_file() else "MISSING"
        if current != recorded.get(name, "NOT_LISTED"):
            mismatched.append(name)
    return mismatched


def _manifest_blocker(repo_root: Path) -> Blocker:
    mismatched = _manifest_mismatches(repo_root)
    resolved = not mismatched
    return Blocker(
        blocker_id=MANIFEST_DRIFT_BLOCKER,
        status="RESOLVED" if resolved else OPEN_STATUS,
        question=(
            "Do the Stage 02 relationship artifacts still carry the bytes their manifest "
            "records?"
        ),
        evidence=(
            "all recorded hashes match"
            if resolved
            else f"{len(mismatched)} artifacts disagree with the manifest: {mismatched}"
        ),
        blocks_live_load=not resolved,
        blocks_schema_migration=False,
        source=f"{STAGE_02_DIR.as_posix()}/{MANIFEST_NAME}",
    )


def _contract_blocker(
    blocker_id: str, question: str, validation: ContractValidation, unresolved_evidence: str
) -> Blocker:
    return Blocker(
        blocker_id=blocker_id,
        status="RESOLVED" if validation.satisfied else OPEN_STATUS,
        question=question,
        evidence=validation.summary if validation.satisfied else unresolved_evidence,
        blocks_live_load=not validation.satisfied,
        blocks_schema_migration=False,
        source=validation.found_in or f"no artifact defines {validation.contract_key}",
    )


def load_artifact_conflicts(repo_root: Path) -> list[dict[str, Any]]:
    """Every well-formed conflict entry. Read-only; the artifact is never rewritten."""
    return list(validate_conflict_registry(repo_root).conflicts)


def blocking_conflicts(repo_root: Path) -> list[dict[str, Any]]:
    """Conflicts that are OPEN and declared to block live load."""
    return [
        conflict
        for conflict in load_artifact_conflicts(repo_root)
        if conflict.get("severity") == BLOCKING_SEVERITY and conflict.get("status") == OPEN_STATUS
    ]


def _conflict_blockers(repo_root: Path) -> list[Blocker]:
    blockers: list[Blocker] = []
    for conflict in blocking_conflicts(repo_root):
        identifier = str(conflict.get("id", "")).strip()
        if not identifier:
            continue
        if conflict_resolution_supersedes_open_blocker(repo_root, identifier):
            gate = evaluate_resolution_gate(repo_root, identifier)
            blockers.append(
                Blocker(
                    blocker_id=identifier,
                    status="RESOLVED",
                    question=f"Has the accepted-artifact conflict {identifier} been resolved?",
                    evidence=gate.detail,
                    blocks_live_load=False,
                    blocks_schema_migration=False,
                    source=f"{DESIGN_DIR.as_posix()}/artifact-conflict-resolutions.yaml",
                )
            )
            continue
        contradiction = str(conflict.get("exact_contradiction", "")).strip() or "no detail recorded"
        blockers.append(
            Blocker(
                blocker_id=identifier,
                status=OPEN_STATUS,
                question=f"Has the accepted-artifact conflict {identifier} been resolved?",
                evidence=" ".join(contradiction.split()),
                blocks_live_load=True,
                blocks_schema_migration=False,
                source=CONFLICTS_ARTIFACT.as_posix(),
            )
        )
    return blockers


def evaluate_blockers(repo_root: Path) -> tuple[Blocker, ...]:
    """Every blocker, from every source, with no manually duplicated list."""
    subject_key = validate_subject_key_contract(repo_root)
    runtime = validate_runtime_contract(repo_root)

    blockers: list[Blocker] = [
        _manifest_blocker(repo_root),
        _contract_blocker(
            LOADER_PRINCIPAL_BLOCKER,
            (
                f"Which login principal connects and assumes {ROLE_LOADER}, from which "
                "credential source, by which connection path and SET ROLE flow, with which "
                "minimal grants, audit identity and rotation procedure?"
            ),
            runtime,
            (
                f"{ROLE_LOADER} is created NOLOGIN by migration 0001 and no accepted artifact "
                f"carries a complete {RUNTIME_CONTRACT_KEY}. {runtime.summary}"
            ),
        ),
        _contract_blocker(
            SUBJECT_KEY_BLOCKER,
            (
                f"Does an accepted artifact define {SUBJECT_KEY_TRANSFORMATION} as a keyed "
                "pseudorandom transformation with a key reference, key version, namespace, "
                "encodings, rotation policy and collision handling?"
            ),
            subject_key,
            (
                f"{SUBJECT_KEY_TRANSFORMATION} has no complete {SUBJECT_KEY_CONTRACT_KEY}, so "
                f"the opacity of Subject.source_subject_key is unspecified and "
                f"{SUBJECT_KEY_SOURCE_COLUMN} could be stored in the clear. "
                f"{subject_key.summary}"
            ),
        ),
        *_conflict_blockers(repo_root),
    ]
    return tuple(blockers)


def blockers_document(repo_root: Path) -> dict[str, Any]:
    blockers = evaluate_blockers(repo_root)
    present = {blocker.blocker_id for blocker in blockers}
    registry = validate_conflict_registry(repo_root)
    return {
        "blockers": [blocker.document() for blocker in blockers],
        "blocker_count": len(blockers),
        "open_blocker_ids": sorted(b.blocker_id for b in blockers if b.status == OPEN_STATUS),
        "blocks_first_live_load": any(b.blocks_live_load for b in blockers),
        "blocks_schema_only_migration_0004": any(b.blocks_schema_migration for b in blockers),
        "required_blockers_present": sorted(REQUIRED_BLOCKER_IDS - present) == [],
        "missing_required_blockers": sorted(REQUIRED_BLOCKER_IDS - present),
        "conflict_derived_blocker_ids": sorted(registry.blocking_ids),
        "conflict_registry": registry.document(),
        "contract_authority": contract_authority_document(repo_root),
        "subject_key_contract": validate_subject_key_contract(repo_root).document(),
        "loader_runtime_contract": validate_runtime_contract(repo_root).document(),
        "validation_method": (
            "authoritative-path resolution, release manifest verification and semantic field "
            "validation; no recursive search, no substring matching"
        ),
    }
