"""Publication index counting — never copy members into indexed_members."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_review_index_entries(index_text: str) -> list[str]:
    """Parse REVIEW_INDEX.md table paths (excludes header / self)."""
    entries: list[str] = []
    for line in index_text.splitlines():
        if not line.startswith("| `"):
            continue
        if "SHA-256" in line or line.startswith("|------"):
            continue
        # | `path` | `sha` |
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        path = parts[0].strip("`")
        if path in ("Path", "REVIEW_INDEX.md"):
            continue
        entries.append(path)
    return entries


def compute_zip_index_counts(zip_path: Path) -> dict[str, Any]:
    """Independently compute zip vs index membership invariants."""
    with zipfile.ZipFile(zip_path) as zf:
        members = sorted(n for n in zf.namelist() if not n.endswith("/"))
        zip_member_count = len(members)
        has_index = "REVIEW_INDEX.md" in members
        if has_index:
            index_text = zf.read("REVIEW_INDEX.md").decode("utf-8", errors="replace")
            indexed = parse_review_index_entries(index_text)
        else:
            indexed = []

    review_index_entry_count = len(indexed)
    member_set = set(members)
    indexed_set = set(indexed)
    # Unindexed = zip members not listed in index and not REVIEW_INDEX itself
    unindexed = sorted(m for m in members if m != "REVIEW_INDEX.md" and m not in indexed_set)
    # Duplicate index entries
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in indexed:
        if name in seen:
            duplicates.append(name)
        seen.add(name)

    self_excluded = "REVIEW_INDEX.md" not in indexed_set
    members_equals_indexed_plus_one = zip_member_count == review_index_entry_count + (
        1 if has_index else 0
    )

    return {
        "zip_path": zip_path.name,
        "zip_sha256": _sha256_file(zip_path) if zip_path.is_file() else None,
        "zip_member_count": zip_member_count,
        "review_index_entry_count": review_index_entry_count,
        "self_excluded": self_excluded,
        "members_equals_indexed_plus_one": members_equals_indexed_plus_one,
        "unindexed_members": unindexed,
        "duplicate_members": duplicates,
        "review_index_present": has_index,
        # Correct attestation fields (indexed excludes REVIEW_INDEX)
        "correct_indexed_members": review_index_entry_count,
        "correct_members": zip_member_count,
    }


def analyze_v011_publication_defect(repo_root: Path) -> dict[str, Any]:
    """Document v0.1.1 attestation indexed_members == members defect."""
    external = repo_root / "artifacts" / "external-review"
    zip_path = external / "stage-03-unified-source-expansion-v0.1.1-review.zip"
    att_path = external / "stage-03-unified-source-expansion-v0.1.1-review.attestation.json"
    if not zip_path.is_file():
        return {"status": "MISSING_ZIP", "ok": False}

    counts = compute_zip_index_counts(zip_path)
    att: dict[str, Any] = {}
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))

    att_members = att.get("members")
    att_indexed = att.get("indexed_members")
    defect = att_members is not None and att_members == att_indexed
    # Never copy members → indexed
    corrected_indexed = counts["correct_indexed_members"]
    corrected_members = counts["correct_members"]

    return {
        "status": "CORRECTED_EVIDENCE",
        "v011_zip_counts": counts,
        "v011_attestation": {
            "members": att_members,
            "indexed_members": att_indexed,
            "defect_members_copied_to_indexed": defect,
        },
        "correction": {
            "members": corrected_members,
            "indexed_members": corrected_indexed,
            "rule": "indexed_members = zip_member_count - 1 when REVIEW_INDEX present; never copy members",
            "members_equals_indexed_plus_one": corrected_members == corrected_indexed + 1,
        },
        "required_invariants": {
            "members_equals_indexed_plus_one": True,
            "self_excluded": True,
            "unindexed_members": [],
            "duplicate_members": [],
        },
        "invariants_hold_on_zip": bool(
            counts["members_equals_indexed_plus_one"]
            and counts["self_excluded"]
            and not counts["unindexed_members"]
            and not counts["duplicate_members"]
        ),
        "ok": True,
    }


def assert_attestation_index_fields(*, members: int, indexed_members: int) -> dict[str, Any]:
    """Reject the previous 256/256 attestation pattern."""
    ok = members == indexed_members + 1
    return {
        "members": members,
        "indexed_members": indexed_members,
        "members_equals_indexed_plus_one": ok,
        "defect_members_equals_indexed": members == indexed_members,
        "accepted": ok and members != indexed_members,
    }
