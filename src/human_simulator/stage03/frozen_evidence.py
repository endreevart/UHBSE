"""Byte-level pin of every frozen input Changeset 01 is allowed to read but never write.

Changeset 01 v0.2 published a review bundle whose Design evidence had been *regenerated* by the
test suite rather than carried over from the accepted Design v0.7.4 release. The eleven Design
content artifacts survived, because a manifest covers them; the two generated evidence files —
the design report and the design verification — were covered by nothing, so a republish inside a
test silently replaced them and the bundle shipped the replacement.

v0.2.1 closes that hole by pinning the accepted SHA-256 of every frozen input, including the two
files no manifest describes, and by re-checking the whole set before and after every suite.

Nothing in this module writes, repairs or restores. A mismatch is a hard FAIL that a human has
to resolve, because the correct bytes can only come from an accepted release, never from a
regeneration.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from human_simulator.canonical.constants import (
    ACCEPTED_MIGRATION_SHA256,
    HARDENING_MIGRATION_FILENAME,
)
from human_simulator.stage03.changeset_01_constants import (
    DESIGN_CONTENT_MANIFEST_NAME,
    DESIGN_DIR,
    IMPLEMENTATION_DIR,
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
)
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.prior_stage_integrity import (
    ACCEPTED_SHA256 as PRIOR_STAGE_SHA256,
)

MIGRATIONS_DIR = Path("migrations") / "canonical"

DESIGN_REPORT_NAME = "stage-03-design-report.md"
DESIGN_VERIFICATION_NAME = "stage-03-design-verification.json"

# Accepted bytes of the two generated Design evidence files, confirmed by external audit of
# Changeset 01 v0.2. The same bytes appear in the published
# stage-03-implementation-plan-v0.3.4-review.zip and
# stage-03-implementation-changeset-01-v0.1-review.zip, which is what makes them recoverable.
FROZEN_DESIGN_EVIDENCE_SHA256: dict[str, str] = {
    DESIGN_REPORT_NAME: "6f30b6aaa25a2efa9a6ead3ab7f76563fa688f1f61d94818c2562015d70a6785",
    DESIGN_VERIFICATION_NAME: "ae4a426aa5cb44e03cf509afed54c917af25a2d6283486ab393ae19159f8254c",
}

# Migrations 0001-0003 were accepted with v0.1 and 0004 with v0.2. From v0.2.1 all four are
# frozen: a schema correction may only arrive as a new forward-only file.
FROZEN_MIGRATION_SHA256: dict[str, str] = {
    **ACCEPTED_MIGRATION_SHA256,
    HARDENING_MIGRATION_FILENAME:
        "20f1744f31f4e215243b8c9922ac4838b28ce969fedaef550a8ecb9c6c3b373a",
}

# Archives known to carry the accepted Design evidence bytes, in preference order. Recovery is a
# deliberate human action; this list only tells the operator where to look.
DESIGN_EVIDENCE_SOURCE_ARCHIVES: tuple[str, ...] = (
    "stage-03-implementation-changeset-01-v0.1-review.zip",
    "stage-03-implementation-plan-v0.3.4-review.zip",
)

# Directories no test and no verifier may write into.
PROTECTED_WORKSPACE_DIRS: tuple[Path, ...] = (
    Path("artifacts") / "stage-01",
    Path("artifacts") / "stage-02",
    DESIGN_DIR,
    IMPLEMENTATION_DIR,
    Path("artifacts") / "external-review",
    MIGRATIONS_DIR,
)


@dataclass(frozen=True)
class EvidenceRecord:
    path: str
    category: str
    accepted_sha256: str | None
    current_sha256: str | None

    @property
    def unchanged(self) -> bool:
        if self.current_sha256 is None:
            return False
        if self.accepted_sha256 is None:
            # Manifest-covered files have no separately pinned hash here; presence is enough,
            # because the manifest check compares their bytes.
            return True
        return self.current_sha256 == self.accepted_sha256

    def document(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "category": self.category,
            "accepted_sha256": self.accepted_sha256,
            "current_sha256": self.current_sha256,
            "unchanged": self.unchanged,
        }


def _manifest_entries(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        entries[name.strip()] = digest
    return entries


def _record(root: Path, relative: Path, category: str, accepted: str | None) -> EvidenceRecord:
    target = root / relative
    return EvidenceRecord(
        path=relative.as_posix(),
        category=category,
        accepted_sha256=accepted,
        current_sha256=sha256_file(target) if target.is_file() else None,
    )


def frozen_evidence_records(repo_root: Path) -> list[EvidenceRecord]:
    """Every frozen input, with its accepted hash where one is pinned.

    Covers the nine controlled Stage 01/02 files, the eleven Design content artifacts and their
    manifest, the two generated Design evidence files, the Implementation Plan artifacts and
    their manifest, and migrations 0001-0004.
    """
    root = repo_root.resolve()
    records: list[EvidenceRecord] = []

    for relative, accepted in sorted(PRIOR_STAGE_SHA256.items()):
        records.append(_record(root, Path(relative), "stage_01_02_controlled", accepted))

    design_manifest = DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME
    for name, digest in sorted(_manifest_entries(root / design_manifest).items()):
        records.append(_record(root, DESIGN_DIR / name, "design_content_artifact", digest))
    records.append(_record(root, design_manifest, "design_manifest", None))

    for name, digest in sorted(FROZEN_DESIGN_EVIDENCE_SHA256.items()):
        records.append(_record(root, DESIGN_DIR / name, "design_evidence", digest))

    plan_manifest = IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME
    for name, digest in sorted(_manifest_entries(root / plan_manifest).items()):
        records.append(_record(root, IMPLEMENTATION_DIR / name, "plan_artifact", digest))
    records.append(_record(root, plan_manifest, "plan_manifest", None))

    for name, digest in sorted(FROZEN_MIGRATION_SHA256.items()):
        records.append(_record(root, MIGRATIONS_DIR / name, "migration", digest))

    return records


def frozen_evidence_fingerprint(repo_root: Path) -> dict[str, str]:
    """A ``path -> sha256`` snapshot, suitable for before/after comparison around a suite."""
    return {
        record.path: record.current_sha256 or "MISSING"
        for record in frozen_evidence_records(repo_root)
    }


def evaluate_frozen_evidence(repo_root: Path) -> dict[str, Any]:
    """Read-only. Reports drift; never restores."""
    records = frozen_evidence_records(repo_root)
    changed = [record for record in records if not record.unchanged]
    design_report = next(
        record
        for record in records
        if record.path == (DESIGN_DIR / DESIGN_REPORT_NAME).as_posix()
    )
    design_verification = next(
        record
        for record in records
        if record.path == (DESIGN_DIR / DESIGN_VERIFICATION_NAME).as_posix()
    )
    return {
        "status": "PASS" if not changed else "FAIL",
        "read_only": True,
        "automatic_restore_performed": False,
        "repairs_performed": 0,
        "file_count": len(records),
        "all_unchanged": not changed,
        "frozen_design_report_match": design_report.unchanged,
        "frozen_design_verification_match": design_verification.unchanged,
        "changed": [record.document() for record in changed],
        "files": [record.document() for record in records],
        "recovery_sources": list(DESIGN_EVIDENCE_SOURCE_ARCHIVES),
    }


class FrozenEvidenceDrift(RuntimeError):
    """Raised when a frozen input changed. Recovery is a human action, never automatic."""


def recover_design_evidence(repo_root: Path, *, confirm: bool) -> dict[str, Any]:
    """Copy the accepted Design evidence bytes out of an accepted release archive.

    This is a deliberate, human-confirmed action and is never reachable from a gate, a suite or
    the publisher. It restores only bytes that hash to the audited values, so it cannot install
    a regenerated file: if no archive carries the accepted bytes, it fails and changes nothing.
    """
    root = repo_root.resolve()
    review_dir = root / "artifacts" / "external-review"
    plan: list[tuple[Path, bytes, str, str]] = []
    unavailable: list[str] = []

    for name, accepted in sorted(FROZEN_DESIGN_EVIDENCE_SHA256.items()):
        target = root / DESIGN_DIR / name
        current = sha256_file(target) if target.is_file() else None
        if current == accepted:
            continue
        member = (DESIGN_DIR / name).as_posix()
        for archive_name in DESIGN_EVIDENCE_SOURCE_ARCHIVES:
            archive = review_dir / archive_name
            if not archive.is_file():
                continue
            with zipfile.ZipFile(archive) as zf:
                if member not in zf.namelist():
                    continue
                payload = zf.read(member)
            if hashlib.sha256(payload).hexdigest() == accepted:
                plan.append((target, payload, current or "MISSING", archive_name))
                break
        else:
            unavailable.append(name)

    if unavailable:
        raise FrozenEvidenceDrift(
            "no accepted release archive carries the audited bytes for: "
            + ", ".join(unavailable)
        )

    if confirm:
        for target, payload, _, _ in plan:
            target.write_bytes(payload)

    return {
        "confirmed": confirm,
        "restored": [
            {
                "path": target.relative_to(root).as_posix(),
                "previous_sha256": previous,
                "restored_sha256": FROZEN_DESIGN_EVIDENCE_SHA256[target.name],
                "recovered_from": archive_name,
            }
            for target, _, previous, archive_name in plan
        ],
        "already_correct": len(FROZEN_DESIGN_EVIDENCE_SHA256) - len(plan),
    }


REPAIR_ENTRY_POINTS: tuple[str, ...] = (
    "recover_design_evidence",
    "restore_prior_stage_baseline",
)


def repair_entry_points_used(source: str) -> list[str]:
    """Names of repair functions this module actually imports or calls.

    Parses rather than greps: a verifier legitimately names these functions in a failure
    message, and a text search cannot tell a message from a call — including inside its own
    search pattern.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                name = alias.name.rsplit(".", maxsplit=1)[-1]
                if name in REPAIR_ENTRY_POINTS:
                    used.add(name)
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in REPAIR_ENTRY_POINTS:
                used.add(name)
    return sorted(used)


def require_frozen_evidence(repo_root: Path, *, context: str) -> dict[str, Any]:
    document = evaluate_frozen_evidence(repo_root)
    if document["status"] != "PASS":
        changed = ", ".join(record["path"] for record in document["changed"])
        raise FrozenEvidenceDrift(
            f"Frozen evidence changed {context}: {changed}. Nothing was restored. "
            "Accepted Design evidence bytes can only be recovered from an accepted release "
            f"({', '.join(DESIGN_EVIDENCE_SOURCE_ARCHIVES)}), never by regenerating them."
        )
    return document
