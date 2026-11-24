"""Physical ZIP verification and Stage 05 naming-authority check."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.intervention_response_readiness_v01.hashes import sha256_file
from human_simulator.intervention_response_readiness_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    V016_EXPECTED_INDEXED,
    V016_EXPECTED_MEMBERS,
)

OUR_SLUG = "stage-05-intervention-response-readiness-and-exposure-semantics-v0.1"
OUR_PACKAGE = "intervention_response_readiness_v01"
OUR_CLI = "intervention-readiness"


def _zip_members(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return [name for name in zf.namelist() if not name.endswith("/")]


def verify_zip(path: Path, expected_sha: str, *, members: int | None = None, indexed: int | None = None) -> dict[str, Any]:
    if not path.is_file():
        return {"ok": False, "reason": "missing", "path": path.name}
    digest = sha256_file(path)
    sidecar = path.with_name(path.name + ".sha256")
    sidecar_sha = None
    sidecar_ok = False
    if sidecar.is_file():
        sidecar_sha = sidecar.read_text(encoding="utf-8").split()[0]
        sidecar_ok = sidecar_sha == expected_sha
    names = _zip_members(path)
    dup = len(names) != len(set(names))
    with zipfile.ZipFile(path) as zf:
        crc = zf.testzip()
    att_path = path.with_name(path.name.replace(".zip", ".attestation.json"))
    attestation: dict[str, Any] | None = None
    att_ok = True
    if att_path.is_file():
        attestation = json.loads(att_path.read_text(encoding="utf-8"))
        att_ok = attestation.get("sha256") == expected_sha
        if indexed is not None:
            att_ok = att_ok and attestation.get("indexed_members") == indexed
        if members is not None:
            att_ok = att_ok and attestation.get("members") == members
    member_ok = True if members is None else len(names) == members
    indexed_ok = True
    if indexed is not None and attestation is not None:
        indexed_ok = attestation.get("indexed_members") == indexed
    ok = (
        digest == expected_sha
        and sidecar_ok
        and crc is None
        and not dup
        and member_ok
        and indexed_ok
        and att_ok
    )
    return {
        "ok": ok,
        "path": path.name,
        "sha256": digest,
        "expected_sha256": expected_sha,
        "sha_ok": digest == expected_sha,
        "sidecar_ok": sidecar_ok,
        "sidecar_sha256": sidecar_sha,
        "crc_fail": crc,
        "duplicate_members": dup,
        "members": len(names),
        "members_ok": member_ok,
        "indexed_ok": indexed_ok,
        "attestation_ok": att_ok,
        "attestation_sha256": None if attestation is None else attestation.get("sha256"),
        "attestation_members": None if attestation is None else attestation.get("members"),
        "attestation_indexed": None if attestation is None else attestation.get("indexed_members"),
    }


def naming_authority(root: Path) -> dict[str, Any]:
    conflicts: list[str] = []
    search_roots = [
        root / "docs",
        root / "src",
        root / ".cursor",
        root / "tests",
    ]
    allowed_needles = (OUR_SLUG, OUR_PACKAGE, OUR_CLI, ARTIFACT_DIR, REVIEW_ZIP)
    artifacts = root / "artifacts"
    if artifacts.is_dir():
        for path in artifacts.iterdir():
            rel = path.relative_to(root).as_posix()
            if "stage-05" in path.name.lower() and OUR_SLUG not in rel:
                conflicts.append(rel)
        ext = artifacts / "external-review"
        if ext.is_dir():
            for path in ext.glob("stage-05*"):
                rel = path.relative_to(root).as_posix()
                if OUR_SLUG not in rel:
                    conflicts.append(rel)
    for base in search_roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(root).as_posix()
            name = path.name
            if "stage-05" in name.lower() or "stage_05" in name.lower():
                if OUR_SLUG not in rel and OUR_PACKAGE not in rel:
                    conflicts.append(rel)
                    continue
            if path.is_file() and path.suffix.lower() in {".md", ".py", ".yml", ".yaml"}:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "STAGE 05" in text or "stage-05" in text or "Stage 05" in text:
                    if not any(needle in rel or needle in text for needle in allowed_needles):
                        if "stage-03" in rel or "stage-04" in rel:
                            continue
                        conflicts.append(rel)
    status = "PASS" if not conflicts else "STAGE_NAMING_CONFLICT"
    return {
        "STAGE_NAMING_AUTHORITY_STATUS": status,
        "ok": not conflicts,
        "reserved_slug": OUR_SLUG,
        "conflicts": conflicts[:40],
        "note": "Stage 05 is reserved for intervention-response readiness and exposure semantics v0.1.",
    }


def verify_baseline(root: Path) -> dict[str, Any]:
    external = root / "artifacts" / "external-review"
    naming = naming_authority(root)
    if not naming["ok"]:
        return {
            "ok": False,
            "BASELINE_VERIFICATION_STATUS": "STAGE_NAMING_CONFLICT",
            "naming": naming,
            "zips": {},
        }
    zips: dict[str, Any] = {}
    all_ok = True
    for label, (name, expected) in PRIOR_ZIPS.items():
        extra = {}
        if label == "irr_v016":
            extra = {"members": V016_EXPECTED_MEMBERS, "indexed": V016_EXPECTED_INDEXED}
        result = verify_zip(external / name, expected, **extra)
        zips[label] = result
        all_ok = all_ok and bool(result.get("ok"))
    stage05 = external / REVIEW_ZIP
    return {
        "ok": all_ok,
        "BASELINE_VERIFICATION_STATUS": "PASS" if all_ok else "FAIL",
        "naming": naming,
        "zips": zips,
        "stage05_zip_exists": stage05.exists(),
        "v016_members_indexed": f"{V016_EXPECTED_MEMBERS}/{V016_EXPECTED_INDEXED}",
    }
