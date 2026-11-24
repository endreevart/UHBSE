"""Publisher-workspace ZIP rehash and Stage 05 naming authority.

A clean extraction does not contain prior ZIP bytes. It may carry a snapshot of
the publisher rehash, and that snapshot is not an independent physical rehash.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.intervention_response_readiness_v01.hashes import sha256_file
from human_simulator.intervention_response_readiness_v011.policy import (
    ARTIFACT_DIR,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    V016_EXPECTED_INDEXED,
    V016_EXPECTED_MEMBERS,
    V01_INDEXED,
    V01_MEMBERS,
    V01_SHA256,
    V01_ZIP,
)

ALLOWED_SLUGS = (
    "stage-05-intervention-response-readiness-and-exposure-semantics-v0.1",
    "intervention_response_readiness_v011",
    "intervention_response_readiness_v01",
    "intervention-readiness",
)


def naming_authority(root: Path) -> dict[str, Any]:
    conflicts: list[str] = []
    artifacts = root / "artifacts"
    if artifacts.is_dir():
        for path in artifacts.iterdir():
            rel = path.relative_to(root).as_posix()
            if "stage-05" in path.name.lower() and not any(slug in path.name for slug in ALLOWED_SLUGS):
                conflicts.append(rel)
        external = artifacts / "external-review"
        if external.is_dir():
            for path in external.glob("stage-05*"):
                if not any(slug in path.name for slug in ALLOWED_SLUGS):
                    conflicts.append(path.relative_to(root).as_posix())
    for base in (root / "docs", root / "src", root / ".cursor", root / "tests"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".md", ".py", ".yml", ".yaml"}:
                continue
            rel = path.relative_to(root).as_posix()
            if "stage-05" in path.name.lower() and not any(slug in rel for slug in ALLOWED_SLUGS):
                conflicts.append(rel)
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "STAGE 05" in text or "stage-05" in text or "Stage 05" in text:
                if not any(slug in text or slug in rel for slug in ALLOWED_SLUGS):
                    if "stage-03" in rel or "stage-04" in rel:
                        continue
                    conflicts.append(rel)
    ok = not conflicts
    return {
        "ok": ok,
        "STAGE_NAMING_AUTHORITY_STATUS": "PASS_PUBLISHER_WORKSPACE" if ok else "STAGE_NAMING_CONFLICT",
        "scope": "publisher_workspace_contract_value",
        "conflicts": conflicts[:40],
    }


def _hash_named(root: Path, name: str, expected: str) -> dict[str, Any]:
    path = root / "artifacts" / "external-review" / name
    if not path.is_file():
        return {"ok": False, "present": False, "path": name, "expected_sha256": expected}
    digest = sha256_file(path)
    extra: dict[str, Any] = {}
    if name == PRIOR_ZIPS["irr_v016"][0]:
        with zipfile.ZipFile(path) as zf:
            names = [item for item in zf.namelist() if not item.endswith("/")]
            extra = {
                "members": len(names),
                "members_ok": len(names) == V016_EXPECTED_MEMBERS,
                "duplicate_members": len(names) != len(set(names)),
                "crc_ok": zf.testzip() is None,
                "indexed_expected": V016_EXPECTED_INDEXED,
            }
    if name == V01_ZIP:
        with zipfile.ZipFile(path) as zf:
            names = [item for item in zf.namelist() if not item.endswith("/")]
            extra = {
                "members": len(names),
                "members_ok": len(names) == V01_MEMBERS,
                "duplicate_members": len(names) != len(set(names)),
                "crc_ok": zf.testzip() is None,
                "indexed_expected": V01_INDEXED,
            }
    ok = digest == expected and extra.get("members_ok", True) and extra.get("crc_ok", True) and not extra.get("duplicate_members", False)
    return {"ok": ok, "present": True, "path": name, "sha256": digest, "expected_sha256": expected, **extra}


def _snapshot_matches_pins(snapshot: dict[str, Any]) -> bool:
    zips = snapshot.get("zips") or {}
    if set(zips) != set(PRIOR_ZIPS):
        return False
    for label, (name, expected) in PRIOR_ZIPS.items():
        row = zips.get(label) or {}
        if row.get("sha256") != expected or row.get("path") != name or row.get("ok") is not True:
            return False
    v01 = snapshot.get("v01_review_zip") or {}
    return v01.get("sha256") == V01_SHA256 and v01.get("ok") is True


def verify_baseline(root: Path) -> dict[str, Any]:
    root = root.resolve()
    naming = naming_authority(root)
    existing = None
    existing_path = root / ARTIFACT_DIR / "baseline-verification.json"
    if existing_path.is_file():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = None
    hashed: dict[str, Any] = {}
    missing: list[str] = []
    for label, (name, expected) in PRIOR_ZIPS.items():
        row = _hash_named(root, name, expected)
        if row.get("present"):
            hashed[label] = row
        else:
            missing.append(name)
    v01_row = _hash_named(root, V01_ZIP, V01_SHA256)
    physical_ok = bool(hashed) and not missing and all(row.get("ok") for row in hashed.values()) and v01_row.get("ok")
    if physical_ok:
        snapshot = {
            "PRIOR_ZIP_PHYSICAL_REHASH_STATUS": "PASS_PUBLISHER_WORKSPACE",
            "scope": "publisher_workspace",
            "independent_clean_extraction_rehash": False,
            "zips": hashed,
            "v01_review_zip": v01_row,
        }
        return {
            "ok": naming["ok"],
            "BASELINE_VERIFICATION_STATUS": "PASS" if naming["ok"] else "FAIL",
            "PRIOR_ZIP_PHYSICAL_REHASH_STATUS": "PASS_PUBLISHER_WORKSPACE",
            "PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS": "NOT_RUN_PRIOR_BYTES_NOT_PACKED",
            "rehash_performed_this_run": True,
            "independent_clean_extraction_rehash": False,
            "publisher_workspace_prior_zip_rehash": snapshot,
            "naming": naming,
            "stage05_v011_zip_exists": (root / "artifacts" / "external-review" / REVIEW_ZIP).exists(),
            "note": "Physical rehash ran in the publisher workspace. The packed snapshot is not an independent clean-extraction rehash.",
        }
    if not hashed and not v01_row.get("present"):
        snapshot = None if not isinstance(existing, dict) else existing.get("publisher_workspace_prior_zip_rehash")
        if isinstance(snapshot, dict) and _snapshot_matches_pins(snapshot) and naming["ok"]:
            return {
                "ok": True,
                "BASELINE_VERIFICATION_STATUS": "PASS",
                "PRIOR_ZIP_PHYSICAL_REHASH_STATUS": "PASS_PUBLISHER_WORKSPACE",
                "PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS": "NOT_RUN_PRIOR_BYTES_NOT_PACKED",
                "rehash_performed_this_run": False,
                "independent_clean_extraction_rehash": False,
                "publisher_workspace_prior_zip_rehash": snapshot,
                "naming": naming,
                "note": "Prior ZIP bytes are not in this tree. Status repeats the publisher-workspace snapshot and does not rehash it.",
            }
    return {
        "ok": False,
        "BASELINE_VERIFICATION_STATUS": "FAIL",
        "PRIOR_ZIP_PHYSICAL_REHASH_STATUS": "FAIL",
        "PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS": "NOT_RUN_PRIOR_BYTES_NOT_PACKED",
        "rehash_performed_this_run": bool(hashed),
        "missing": missing,
        "v01_review_zip": v01_row,
        "naming": naming,
    }
