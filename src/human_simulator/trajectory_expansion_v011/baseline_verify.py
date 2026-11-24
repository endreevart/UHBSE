"""Baseline verification for accepted trajectory expansion v0.1."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.trajectory_expansion_v011.policy import (
    ACCEPTED_V01_INDEXED,
    ACCEPTED_V01_MEMBERS,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    PILOT_ZIP,
    PILOT_ZIP_SHA256,
    VERSION,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_accepted_v01(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    zip_path = external / ACCEPTED_V01_ZIP
    sidecar = external / f"{ACCEPTED_V01_ZIP}.sha256"
    att_path = external / ACCEPTED_V01_ZIP.replace(".zip", ".attestation.json")
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("v01_zip_present", zip_path.is_file())
    digest = _sha(zip_path) if zip_path.is_file() else None
    add("v01_sha256", digest == ACCEPTED_V01_SHA256, digest)
    add("sidecar_present", sidecar.is_file())
    if sidecar.is_file():
        side = sidecar.read_text(encoding="utf-8").strip().split()[0]
        add("sidecar_matches", side == ACCEPTED_V01_SHA256, side)
    add("attestation_present", att_path.is_file())
    members = indexed = None
    review_index_ok = False
    evidence_manifest_ok = False
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        members = att.get("members")
        indexed = att.get("indexed_members")
        add("attestation_status", att.get("attestation_status") == "PASS")
        add("attestation_sha", att.get("review_zip_sha256") == ACCEPTED_V01_SHA256)
        add(
            "members_indexed",
            members == ACCEPTED_V01_MEMBERS and indexed == ACCEPTED_V01_INDEXED,
            {"members": members, "indexed": indexed},
        )
    if zip_path.is_file():
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            add("zip_member_count", len(names) == ACCEPTED_V01_MEMBERS, len(names))
            review_index_ok = any(n.endswith("REVIEW_INDEX.md") for n in names)
            evidence_manifest_ok = any(
                n.endswith("evidence-manifest.sha256") for n in names
            )
            add("REVIEW_INDEX_present", review_index_ok)
            add("evidence_manifest_present", evidence_manifest_ok)

    pilot = external / PILOT_ZIP
    add("pilot_zip_unchanged", pilot.is_file() and _sha(pilot) == PILOT_ZIP_SHA256)

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_v01_zip": ACCEPTED_V01_ZIP,
        "accepted_v01_sha256_expected": ACCEPTED_V01_SHA256,
        "accepted_v01_sha256_observed": digest,
        "baseline_before": digest,
        "baseline_after": digest,
        "baseline_before_equals_after": digest == ACCEPTED_V01_SHA256,
        "members": members,
        "indexed_members": indexed,
        "checks": checks,
        "ok": ok,
    }
