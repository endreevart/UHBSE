"""Mandatory precondition baseline for Stage 03 Implementation Changeset 01.

Read-only. The baseline check proves, before any change is made, that:

* the nine controlled Stage 01/02 files still carry their accepted bytes;
* the frozen Design baseline v0.7.4 content manifest verifies;
* the accepted Implementation Plan v0.3.5 manifest verifies.

Nothing here restores or rewrites a prior stage. A mismatch is a hard FAIL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage03.changeset_01_constants import (
    BASELINE_VERIFICATION_NAME,
    CHANGESET_DIR,
    CHANGESET_ID,
    CHANGESET_VERSION,
    DESIGN_CONTENT_MANIFEST_NAME,
    DESIGN_DIR,
    IMPLEMENTATION_DIR,
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
)
from human_simulator.stage03.implementation_gate import (
    FROZEN_DESIGN_VERSION,
    FROZEN_IMPLEMENTATION_PLAN_VERSION,
)
from human_simulator.stage03.frozen_evidence import evaluate_frozen_evidence
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.prior_stage_integrity import (
    ACCEPTED_SHA256,
    CONTROLLED_PRIOR_STAGE_PATHS,
    evaluate_prior_stage_integrity,
)


class BaselineMismatch(RuntimeError):
    """Raised when the recorded baseline does not match the workspace."""


@dataclass(frozen=True)
class ManifestVerification:
    manifest: str
    verified: bool
    entry_count: int
    detail: str


def verify_sha256_manifest(manifest_path: Path) -> ManifestVerification:
    """Verify a ``<sha256>  <name>`` manifest against sibling files. Never rewrites it."""
    relative = manifest_path.name
    if not manifest_path.exists():
        return ManifestVerification(relative, False, 0, f"missing {relative}")

    directory = manifest_path.parent
    entries = 0
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        target = directory / name.strip()
        if not target.exists():
            return ManifestVerification(relative, False, entries, f"missing file {name.strip()}")
        if sha256_file(target) != digest:
            return ManifestVerification(relative, False, entries, f"hash mismatch {name.strip()}")
        entries += 1
    if entries == 0:
        return ManifestVerification(relative, False, 0, f"{relative} has no entries")
    return ManifestVerification(relative, True, entries, f"verified {entries} entries")


def evaluate_baseline(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    prior_unchanged, records = evaluate_prior_stage_integrity(root)

    design = verify_sha256_manifest(root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME)
    plan = verify_sha256_manifest(root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME)

    # A manifest only covers the files it lists. The two generated Design evidence files are
    # listed by nothing, which is how v0.2 shipped regenerated copies of them, so they are
    # pinned by hash here instead.
    frozen = evaluate_frozen_evidence(root)

    checks = {
        "controlled_prior_stage_files_unchanged": prior_unchanged,
        "controlled_prior_stage_file_count": len(CONTROLLED_PRIOR_STAGE_PATHS) == len(ACCEPTED_SHA256),
        "design_content_manifest_verified": design.verified,
        "implementation_plan_manifest_verified": plan.verified,
        "frozen_design_report_match": frozen["frozen_design_report_match"],
        "frozen_design_verification_match": frozen["frozen_design_verification_match"],
        "all_frozen_evidence_unchanged": frozen["all_unchanged"],
    }
    status = "PASS" if all(checks.values()) else "FAIL"

    return {
        "changeset": CHANGESET_ID,
        "changeset_version": CHANGESET_VERSION,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "read_only": True,
        "auto_restore_performed": False,
        "design_baseline_version": FROZEN_DESIGN_VERSION,
        "implementation_plan_version": FROZEN_IMPLEMENTATION_PLAN_VERSION,
        "controlled_prior_stage": {
            "file_count": len(records),
            "all_unchanged": prior_unchanged,
            "files": [
                {
                    "path": record.path,
                    "accepted_sha256": record.accepted_sha256,
                    "current_sha256": record.current_sha256,
                    "unchanged": record.unchanged,
                }
                for record in records
            ],
        },
        "frozen_manifests": {
            "design": {
                "manifest": design.manifest,
                "verified": design.verified,
                "entry_count": design.entry_count,
                "detail": design.detail,
                "manifest_sha256": sha256_file(root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME)
                if (root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME).exists()
                else None,
            },
            "implementation_plan": {
                "manifest": plan.manifest,
                "verified": plan.verified,
                "entry_count": plan.entry_count,
                "detail": plan.detail,
                "manifest_sha256": sha256_file(
                    root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME
                )
                if (root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME).exists()
                else None,
            },
        },
        "frozen_evidence": frozen,
        "checks": checks,
        "failures": sorted(name for name, ok in checks.items() if not ok),
    }


def write_baseline_verification(repo_root: Path, document: dict[str, Any]) -> Path:
    target_dir = repo_root / CHANGESET_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / BASELINE_VERIFICATION_NAME
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def require_baseline(repo_root: Path) -> dict[str, Any]:
    """Fail closed before any Changeset 01 change is made."""
    document = evaluate_baseline(repo_root)
    if document["status"] != "PASS":
        failed = sorted(name for name, ok in document["checks"].items() if not ok)
        raise BaselineMismatch(
            "Changeset 01 baseline does not match the accepted checkpoint; "
            f"failed checks: {', '.join(failed)}. Nothing was restored or modified."
        )
    return document
