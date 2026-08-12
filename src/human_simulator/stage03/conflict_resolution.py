"""Gate logic for artifact conflict resolutions in new Design/Plan releases.

The historical ``accepted-artifact-conflicts.yaml`` in Changeset 01 stays immutable and OPEN.
A separate resolution artifact in a new design release records how each conflict was resolved.
The pre-live-load gate closes a conflict-derived blocker only when every gate condition is met:

* ``resolution_status`` is exactly ``RESOLVED``;
* the owning release report is FINAL;
* release verification status is PASS;
* the design content manifest verifies and lists the resolution artifact.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from human_simulator.audit.report import REPORT_STATUS_FINAL
from human_simulator.stage03.changeset_01_baseline import verify_sha256_manifest
from human_simulator.stage03.changeset_01_constants import DESIGN_CONTENT_MANIFEST_NAME, DESIGN_DIR
from human_simulator.stage03.constants import STAGE03_CONTENT_ARTIFACTS
from human_simulator.stage03.frozen_evidence import DESIGN_REPORT_NAME, DESIGN_VERIFICATION_NAME
from human_simulator.stage03.preconditions import sha256_file

CONFLICT_RESOLUTIONS_NAME = "artifact-conflict-resolutions.yaml"
RESOLUTION_STATUS_RESOLVED = "RESOLVED"
RESOLUTION_STATUS_PENDING = "RESOLVED_PENDING_FINAL_RELEASE"

REPORT_STATUS_PATTERN = re.compile(
    r"\*\*Report status:\*\*\s*(?P<status>[A-Z]+)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ResolutionGate:
    conflict_id: str
    effective: bool
    resolution_status: str | None
    owning_release: str | None
    report_final: bool
    verification_pass: bool
    manifest_verified: bool
    resolution_in_manifest: bool
    detail: str

    def document(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "effective": self.effective,
            "resolution_status": self.resolution_status,
            "owning_release": self.owning_release,
            "report_final": self.report_final,
            "verification_pass": self.verification_pass,
            "manifest_verified": self.manifest_verified,
            "resolution_in_manifest": self.resolution_in_manifest,
            "detail": self.detail,
        }


def _load_resolutions_document(repo_root: Path) -> dict[str, Any] | None:
    path = repo_root / DESIGN_DIR / CONFLICT_RESOLUTIONS_NAME
    if not path.is_file():
        return None
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return document if isinstance(document, dict) else None


def _resolution_entries(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw = document.get("resolutions")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def _design_report_final(repo_root: Path) -> bool:
    report_path = repo_root / DESIGN_DIR / DESIGN_REPORT_NAME
    if not report_path.is_file():
        return False
    match = REPORT_STATUS_PATTERN.search(report_path.read_text(encoding="utf-8"))
    return bool(match and match.group("status") == REPORT_STATUS_FINAL)


def _design_verification_pass(repo_root: Path) -> bool:
    path = repo_root / DESIGN_DIR / DESIGN_VERIFICATION_NAME
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return str(payload.get("status", "")).upper() == "PASS"


def _resolution_listed_in_manifest(repo_root: Path) -> bool:
    if CONFLICT_RESOLUTIONS_NAME not in STAGE03_CONTENT_ARTIFACTS:
        return False
    manifest = repo_root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME
    if not manifest.is_file():
        return False
    for line in manifest.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        _, name = stripped.split(maxsplit=1)
        if name.strip() == CONFLICT_RESOLUTIONS_NAME:
            return True
    return False


def evaluate_resolution_gate(repo_root: Path, conflict_id: str) -> ResolutionGate:
    document = _load_resolutions_document(repo_root)
    if document is None:
        return ResolutionGate(
            conflict_id=conflict_id,
            effective=False,
            resolution_status=None,
            owning_release=None,
            report_final=False,
            verification_pass=False,
            manifest_verified=False,
            resolution_in_manifest=False,
            detail=f"{CONFLICT_RESOLUTIONS_NAME} is absent or unparsable",
        )

    entry = next(
        (item for item in _resolution_entries(document) if str(item.get("conflict_id", "")).strip() == conflict_id),
        None,
    )
    if entry is None:
        return ResolutionGate(
            conflict_id=conflict_id,
            effective=False,
            resolution_status=None,
            owning_release=None,
            report_final=False,
            verification_pass=False,
            manifest_verified=False,
            resolution_in_manifest=False,
            detail=f"no resolution entry for {conflict_id}",
        )

    status = str(entry.get("resolution_status", "")).strip().upper()
    owning_release = str(entry.get("owning_release", "")).strip() or None
    report_final = _design_report_final(repo_root)
    verification_pass = _design_verification_pass(repo_root)
    manifest = verify_sha256_manifest(repo_root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME)
    resolution_in_manifest = _resolution_listed_in_manifest(repo_root)

    effective = (
        status == RESOLUTION_STATUS_RESOLVED
        and report_final
        and verification_pass
        and manifest.verified
        and resolution_in_manifest
    )

    if effective:
        detail = "resolution effective: owning release FINAL, verification PASS, manifest verifies"
    elif status == RESOLUTION_STATUS_PENDING:
        detail = (
            "resolution recorded but pending FINAL release; DRAFT or manifest alone does not close blocker"
        )
    elif status != RESOLUTION_STATUS_RESOLVED:
        detail = f"resolution_status {status!r} is not {RESOLUTION_STATUS_RESOLVED!r}"
    else:
        missing = []
        if not report_final:
            missing.append("report not FINAL")
        if not verification_pass:
            missing.append("verification not PASS")
        if not manifest.verified:
            missing.append("manifest does not verify")
        if not resolution_in_manifest:
            missing.append("resolution artifact not in manifest")
        detail = "resolution not yet effective: " + ", ".join(missing)

    return ResolutionGate(
        conflict_id=conflict_id,
        effective=effective,
        resolution_status=status,
        owning_release=owning_release,
        report_final=report_final,
        verification_pass=verification_pass,
        manifest_verified=manifest.verified,
        resolution_in_manifest=resolution_in_manifest,
        detail=detail,
    )


def conflict_resolution_supersedes_open_blocker(repo_root: Path, conflict_id: str) -> bool:
    """True when the gate may treat a historical OPEN conflict as resolved."""
    return evaluate_resolution_gate(repo_root, conflict_id).effective


def populate_confirming_hashes(repo_root: Path) -> dict[str, str]:
    """Return sha256 for files named in the resolution artifact confirming_file_sha256 maps."""
    document = _load_resolutions_document(repo_root)
    if document is None:
        return {}
    updated: dict[str, str] = {}
    for entry in _resolution_entries(document):
        confirming = entry.get("confirming_file_sha256")
        if not isinstance(confirming, dict):
            continue
        for name in confirming:
            path = repo_root / DESIGN_DIR / str(name)
            if path.is_file():
                updated[str(name)] = sha256_file(path)
    return updated
