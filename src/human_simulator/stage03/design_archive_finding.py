"""Evidence-bound finding about the Design v0.7.4 review archive.

Changeset 01 v0.2.1 stated that the published Design archive "does not carry the audited bytes".
The statement was true of the file inspected, but it was recorded without the archive's own
SHA-256, which makes it unverifiable and indistinguishable from a claim about some other copy.
A finding about integrity that carries no hash is not evidence.

This module recomputes the finding from the artifact present now and states only what the bytes
support. It cannot and does not claim what the archive contained when it was first published:
no sidecar was ever written for it, so no accepted archive hash exists to compare against.

Read-only.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.stage03.frozen_evidence import (
    DESIGN_EVIDENCE_SOURCE_ARCHIVES,
    DESIGN_REPORT_NAME,
    DESIGN_VERIFICATION_NAME,
    FROZEN_DESIGN_EVIDENCE_SHA256,
)

DESIGN_ARCHIVE_NAME = "stage-03-design-v0.7.4-review.zip"
REVIEW_DIR = Path("artifacts") / "external-review"
FINDING_ID = "design_v0_7_4_archive_evidence_mismatch"


def evaluate_design_archive_finding(repo_root: Path) -> dict[str, Any]:
    """State the finding strictly from the bytes of the archive as it exists now."""
    archive = repo_root.resolve() / REVIEW_DIR / DESIGN_ARCHIVE_NAME
    sidecar = Path(str(archive) + ".sha256")

    if not archive.is_file():
        return {
            "finding_id": FINDING_ID,
            "status": "NOT_ASSESSABLE_ARTIFACT_ABSENT",
            "archive": DESIGN_ARCHIVE_NAME,
            "archive_present": False,
            "archive_sha256": None,
            "archive_source": f"{REVIEW_DIR.as_posix()}/{DESIGN_ARCHIVE_NAME}",
            "accepted_archive_sha256": None,
            "accepted_archive_sha256_recorded": False,
            "embedded_design_evidence_sha256": {},
            "audited_design_evidence_sha256": dict(FROZEN_DESIGN_EVIDENCE_SHA256),
            "embedded_matches_audited": None,
            "claim": (
                "The archive is not present in this workspace, so no statement about its "
                "contents is supported by evidence here."
            ),
            "historical_corruption_claimed": False,
            "why_no_historical_claim": (
                "No archive was available to hash, so nothing is asserted about it."
            ),
            "audited_bytes_recovered_from": list(DESIGN_EVIDENCE_SOURCE_ARCHIVES),
            "republishing_design_archive": "out of scope; Design v0.7.4 is a frozen input",
        }

    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    embedded: dict[str, str] = {}
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        for name in (DESIGN_REPORT_NAME, DESIGN_VERIFICATION_NAME):
            member = f"artifacts/stage-03/{name}"
            embedded[name] = (
                hashlib.sha256(zf.read(member)).hexdigest() if member in names else "MEMBER_ABSENT"
            )

    matches = embedded == dict(FROZEN_DESIGN_EVIDENCE_SHA256)
    accepted_archive_hash_recorded = sidecar.is_file()

    if matches:
        status = "NOT_REPRODUCED_CURRENT_ARTIFACT"
        claim = (
            f"The archive present now, SHA-256 {archive_sha256}, carries both audited Design "
            "evidence files. The v0.2.1 finding does not reproduce against this artifact."
        )
    else:
        status = "REPRODUCED_CURRENT_ARTIFACT"
        claim = (
            f"The archive present now, SHA-256 {archive_sha256}, does not carry the audited "
            "Design evidence bytes. This is a statement about this artifact only."
        )

    return {
        "finding_id": FINDING_ID,
        "status": status,
        "archive": DESIGN_ARCHIVE_NAME,
        "archive_present": True,
        "archive_sha256": archive_sha256,
        "archive_source": f"{REVIEW_DIR.as_posix()}/{DESIGN_ARCHIVE_NAME}",
        "accepted_archive_sha256": (
            sidecar.read_text(encoding="utf-8").split()[0] if accepted_archive_hash_recorded else None
        ),
        "accepted_archive_sha256_recorded": accepted_archive_hash_recorded,
        "embedded_design_evidence_sha256": embedded,
        "audited_design_evidence_sha256": dict(FROZEN_DESIGN_EVIDENCE_SHA256),
        "embedded_matches_audited": matches,
        "claim": claim,
        "historical_corruption_claimed": False,
        "why_no_historical_claim": (
            "No sidecar was ever published for this archive, so no accepted hash exists for it. "
            "What the archive contained at first publication therefore cannot be established, "
            "and this finding does not assert it."
        ),
        "audited_bytes_recovered_from": list(DESIGN_EVIDENCE_SOURCE_ARCHIVES),
        "republishing_design_archive": "out of scope; Design v0.7.4 is a frozen input",
    }
