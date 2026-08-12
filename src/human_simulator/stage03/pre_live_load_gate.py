"""Executable pre-live-load gate for Stage 02 relationship integrity.

Gate id: ``stage02_relationship_integrity_pre_live_load``.

The gate is strictly read-only. It never repairs a manifest, never rewrites a Stage 02
artifact and never restores a baseline. It blocks future live extraction, load and ETL
operations while Stage 02 relationship integrity is unproven, and it deliberately does not
block creation of an empty canonical database or application of canonical migrations.

The gate currently returns FAIL because four pre-live-load blockers remain open after
Stage 02 Maintenance 01 repaired the relationship manifest drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
    sha256_file,
    verify_relationship_manifest,
)
from human_simulator.stage03.conflict_registry import validate_conflict_registry
from human_simulator.stage03.frozen_evidence import frozen_evidence_fingerprint
from human_simulator.stage03.live_load_contracts import contract_authority_document
from human_simulator.stage03.pre_live_load_blockers import (
    REQUIRED_BLOCKER_IDS,
    blockers_document,
    evaluate_blockers,
)
from human_simulator.stage03.prior_stage_integrity import evaluate_prior_stage_integrity

GATE_ID = "stage02_relationship_integrity_pre_live_load"
GATE_RESULT_NAME = "stage02-pre-live-load-gate.json"
STAGE_02_DIR = Path("artifacts") / "stage-02"

# Operations that must consult the gate before touching a live source or loading rows.
# Changeset 01 implements none of them; the registry exists so that the guard is wired in
# before any of them can be added.
BLOCKED_LIVE_OPERATIONS: tuple[str, ...] = (
    "source_a_live_extract",
    "source_b_live_extract",
    "pilot_cohort_selection",
    "canonical_transform_run",
    "canonical_staging_load",
    "canonical_promotion",
    "etl_pipeline_run",
)

# Operations that the gate must never block: empty storage creation is authorised by
# Changeset 01 and touches no source data.
ALLOWED_WHILE_BLOCKED: tuple[str, ...] = (
    "canonical_database_create",
    "canonical_migration_apply",
    "canonical_schema_verify",
    "canonical_permission_verify",
)


class LiveLoadBlocked(RuntimeError):
    """Raised when a live extraction, load or ETL operation is attempted while blocked."""


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: str
    checks: tuple[GateCheck, ...]
    blocked_operations: tuple[str, ...] = field(default=BLOCKED_LIVE_OPERATIONS)
    allowed_operations: tuple[str, ...] = field(default=ALLOWED_WHILE_BLOCKED)
    blockers: dict[str, Any] = field(default_factory=dict)
    manifest_mismatches: tuple[dict[str, str], ...] = field(default=())
    frozen_inputs_before: dict[str, str] = field(default_factory=dict)
    frozen_inputs_after: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks if not check.passed)

    @property
    def check_names(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks)

    def document(self) -> dict[str, Any]:
        open_blockers = sorted(
            blocker["blocker_id"]
            for blocker in self.blockers.get("blockers", [])
            if blocker.get("status") == "OPEN"
        )
        known_open_defect = open_blockers[0] if len(open_blockers) == 1 else open_blockers
        return {
            "gate_id": self.gate_id,
            "evaluated_at": datetime.now(UTC).isoformat(),
            "status": self.status,
            "read_only": True,
            "repairs_performed": 0,
            "stage_02_modified": False,
            "checks_total": len(self.checks),
            "checks_passed": sum(1 for check in self.checks if check.passed),
            "failed_checks": list(self.failed_checks),
            "checks": [
                {"name": check.name, "status": "PASS" if check.passed else "FAIL", "detail": check.detail}
                for check in self.checks
            ],
            "blocks_live_operations": list(self.blocked_operations),
            "does_not_block": list(self.allowed_operations),
            "known_open_defect": known_open_defect,
            "relationship_manifest_mismatch_count": len(self.manifest_mismatches),
            "relationship_manifest_mismatches": [dict(item) for item in self.manifest_mismatches],
            "pre_live_load_blockers": self.blockers,
            "database_connections_opened": 0,
            "clinical_rows_read": 0,
            "manifests_created": 0,
            "frozen_evidence_restored": 0,
            "frozen_inputs": {
                "count": len(self.frozen_inputs_after),
                "unchanged": self.frozen_inputs_before == self.frozen_inputs_after,
                "sha256_before": dict(self.frozen_inputs_before),
                "sha256_after": dict(self.frozen_inputs_after),
            },
        }


def relationship_manifest_mismatches(repo_root: Path) -> list[dict[str, str]]:
    """Every artifact whose bytes disagree with the recorded manifest, not just the first.

    ``verify_relationship_manifest`` returns on the first mismatch, which understated the defect:
    an independent check finds two. This enumerates them so the report names both. It reads only
    and rewrites nothing in Stage 02.
    """
    directory = repo_root / STAGE_02_DIR
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        return []

    recorded: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        digest, name = stripped.split(maxsplit=1)
        recorded[name.strip()] = digest

    mismatches: list[dict[str, str]] = []
    for name in RELATIONSHIP_MANIFEST_ARTIFACTS:
        path = directory / name
        current = sha256_file(path) if path.is_file() else "MISSING"
        expected = recorded.get(name, "NOT_LISTED")
        if current != expected:
            mismatches.append(
                {"artifact": name, "recorded_sha256": expected, "current_sha256": current}
            )
    return mismatches


def _stage_02_snapshot(repo_root: Path) -> dict[str, str]:
    """Hashes of every relationship artifact plus the manifest, for a no-mutation proof."""
    directory = repo_root / STAGE_02_DIR
    names = (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME)
    snapshot: dict[str, str] = {}
    for name in names:
        path = directory / name
        if path.exists():
            snapshot[name] = sha256_file(path)
    return snapshot


def evaluate_pre_live_load_gate(repo_root: Path) -> GateResult:
    """Read-only evaluation. Performs no repair and writes nothing."""
    directory = repo_root / STAGE_02_DIR
    before = _stage_02_snapshot(repo_root)
    frozen_before = frozen_evidence_fingerprint(repo_root)
    checks: list[GateCheck] = []

    manifest_path = directory / MANIFEST_NAME
    checks.append(
        GateCheck(
            "relationship_manifest_present",
            manifest_path.exists(),
            f"{MANIFEST_NAME} present" if manifest_path.exists() else f"{MANIFEST_NAME} missing",
        )
    )

    mismatches = relationship_manifest_mismatches(repo_root)
    if manifest_path.exists():
        matches, _ = verify_relationship_manifest(directory)
        detail = (
            f"{len(mismatches)} manifest mismatches: "
            + ", ".join(item["artifact"] for item in mismatches)
            if mismatches
            else "all recorded hashes match"
        )
    else:
        matches, detail = False, f"missing {MANIFEST_NAME}"
    checks.append(GateCheck("relationship_manifest_hashes_match", matches, detail))

    unchanged, records = evaluate_prior_stage_integrity(repo_root)
    changed = [record.path for record in records if not record.unchanged]
    checks.append(
        GateCheck(
            "controlled_stage_01_02_files_unchanged",
            unchanged,
            f"{len(records)} controlled files verified"
            if unchanged
            else f"changed: {sorted(changed)}",
        )
    )

    # The registry is a source of checks, so damage to it must not shrink the check set. This is
    # deliberately independent of whether any conflict it lists is open.
    registry = validate_conflict_registry(repo_root)
    checks.append(
        GateCheck(
            "accepted_artifact_conflict_registry_valid",
            registry.valid,
            registry.detail,
        )
    )

    blockers = evaluate_blockers(repo_root)
    for blocker in blockers:
        checks.append(
            GateCheck(
                blocker.blocker_id,
                blocker.status != "OPEN",
                blocker.evidence,
            )
        )

    # A blocker that vanished because its source artifact was deleted or edited would be a
    # silent unblocking, which is exactly the failure mode a fail-closed gate exists to prevent.
    present = {blocker.blocker_id for blocker in blockers}
    missing_required = sorted(REQUIRED_BLOCKER_IDS - present)
    unenforced = sorted(set(registry.blocking_ids) - present)
    checks.append(
        GateCheck(
            "required_blocker_checks_present",
            not missing_required and not unenforced,
            f"{len(blockers)} blockers registered from manifest, contracts and conflicts"
            if not missing_required and not unenforced
            else f"blocker checks disappeared from the registry: {missing_required + unenforced}",
        )
    )

    # A contract that exists twice is a contract nobody owns. Reporting it as merely "absent"
    # would understate a governance failure, so ambiguity is its own check.
    authority = contract_authority_document(repo_root)
    ambiguous = authority["ambiguous_definitions"]
    checks.append(
        GateCheck(
            "contract_definitions_are_unambiguous",
            not ambiguous,
            "each contract has at most one definition in scope"
            if not ambiguous
            else f"multiple definitions found for {ambiguous}",
        )
    )

    after = _stage_02_snapshot(repo_root)
    checks.append(
        GateCheck(
            "gate_evaluation_did_not_modify_stage_02",
            before == after,
            "stage 02 bytes identical before and after gate evaluation"
            if before == after
            else "gate evaluation changed stage 02 bytes",
        )
    )

    frozen_after = frozen_evidence_fingerprint(repo_root)
    checks.append(
        GateCheck(
            "gate_evaluation_did_not_modify_frozen_inputs",
            frozen_before == frozen_after,
            f"{len(frozen_after)} frozen inputs identical before and after gate evaluation"
            if frozen_before == frozen_after
            else "gate evaluation changed frozen inputs: "
            + str(sorted(p for p in set(frozen_before) | set(frozen_after)
                         if frozen_before.get(p) != frozen_after.get(p))),
        )
    )

    status = "PASS" if all(check.passed for check in checks) else "FAIL"
    return GateResult(
        gate_id=GATE_ID,
        status=status,
        checks=tuple(checks),
        blockers=blockers_document(repo_root),
        manifest_mismatches=tuple(mismatches),
        frozen_inputs_before=frozen_before,
        frozen_inputs_after=frozen_after,
    )


def require_live_load_authorized(repo_root: Path, operation: str) -> GateResult:
    """Fail closed before any live extraction, load or ETL operation."""
    if operation in ALLOWED_WHILE_BLOCKED:
        raise ValueError(
            f"{operation!r} does not touch source data and must not consult the live-load gate"
        )
    if operation not in BLOCKED_LIVE_OPERATIONS:
        raise ValueError(f"unknown live operation {operation!r}; register it before use")

    result = evaluate_pre_live_load_gate(repo_root)
    if not result.passed:
        raise LiveLoadBlocked(
            f"{GATE_ID} status {result.status}; {operation} blocked. "
            f"Failed checks: {', '.join(result.failed_checks)}. "
            "Resolve every open pre-live-load blocker before live extraction, load or ETL. "
            "This gate never repairs Stage 02 automatically."
        )
    return result
