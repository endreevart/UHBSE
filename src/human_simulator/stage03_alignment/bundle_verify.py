"""Self-contained verification for alignment review bundles."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from human_simulator.stage03.changeset_01_baseline import verify_sha256_manifest
from human_simulator.stage03.changeset_01_constants import (
    DESIGN_CONTENT_MANIFEST_NAME,
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
)
from human_simulator.stage03.review_bundle_validation import parse_review_index, validate_review_bundle_zip


def _manifest_member_paths(extract_root: Path, *, prefix: str, manifest_name: str) -> list[str]:
    manifest_path = extract_root / prefix / manifest_name
    members: list[str] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, name = line.split(maxsplit=1)
        members.append(f"{prefix}/{name.strip()}")
    return members


def verify_extracted_alignment_bundle(extract_root: Path) -> dict[str, Any]:
    """Verify manifests and members from a clean extraction only."""
    design_manifest = extract_root / "design" / DESIGN_CONTENT_MANIFEST_NAME
    plan_manifest = extract_root / "plan" / IMPLEMENTATION_PLAN_MANIFEST_NAME
    design_result = verify_sha256_manifest(design_manifest)
    plan_result = verify_sha256_manifest(plan_manifest)

    design_members = _manifest_member_paths(
        extract_root, prefix="design", manifest_name=DESIGN_CONTENT_MANIFEST_NAME
    )
    plan_members = _manifest_member_paths(
        extract_root, prefix="plan", manifest_name=IMPLEMENTATION_PLAN_MANIFEST_NAME
    )
    required_members = set(design_members + plan_members)
    present_members = {
        path.relative_to(extract_root).as_posix()
        for path in extract_root.rglob("*")
        if path.is_file() and path.name not in {"REVIEW_INDEX.md", "REPRODUCE.md"}
    }
    missing_members = sorted(required_members - present_members)
    extra_members = sorted(
        member
        for member in present_members
        if member.startswith(("design/", "plan/")) and member not in required_members
    )

    return {
        "extracted_design_manifest_verified": design_result.verified,
        "extracted_plan_manifest_verified": plan_result.verified,
        "all_manifest_members_present": not missing_members,
        "missing_manifest_members": missing_members,
        "extra_manifest_members": extra_members,
        "design_manifest_entry_count": design_result.entry_count,
        "plan_manifest_entry_count": plan_result.entry_count,
    }


def verify_alignment_bundle_zip(zip_path: Path, extract_root: Path) -> dict[str, Any]:
    ok, detail = validate_review_bundle_zip(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.namelist()
        duplicate_members = sorted({name for name in members if members.count(name) > 1})
        index_entries = parse_review_index(archive.read("REVIEW_INDEX.md").decode("utf-8"))
        indexed_paths = {entry.path for entry in index_entries}
        bundle_files = {
            name
            for name in members
            if not name.endswith("/") and name != "REVIEW_INDEX.md"
        }
        unindexed_members = sorted(bundle_files - indexed_paths)

    extracted = verify_extracted_alignment_bundle(extract_root)
    return {
        "zip_valid": ok,
        "zip_validation_detail": detail,
        "no_duplicate_members": not duplicate_members,
        "duplicate_members": duplicate_members,
        "no_unindexed_members": not unindexed_members,
        "unindexed_members": unindexed_members,
        **extracted,
        "publication_integrity_pass": (
            ok
            and not duplicate_members
            and not unindexed_members
            and extracted["extracted_design_manifest_verified"]
            and extracted["extracted_plan_manifest_verified"]
            and extracted["all_manifest_members_present"]
        ),
    }
