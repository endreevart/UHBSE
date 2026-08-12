"""Validate external review bundle ZIP archives against REVIEW_INDEX.md."""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

INDEX_ENTRY_PATTERN = re.compile(r"^\|\s*`([a-f0-9]{64})`\s*\|\s*`([^`]+)`\s*\|")


@dataclass(frozen=True)
class ReviewIndexEntry:
    path: str
    sha256: str


def parse_review_index(text: str) -> tuple[ReviewIndexEntry, ...]:
    entries: list[ReviewIndexEntry] = []
    for line in text.splitlines():
        match = INDEX_ENTRY_PATTERN.match(line.strip())
        if match:
            entries.append(ReviewIndexEntry(path=match.group(2), sha256=match.group(1)))
    return tuple(entries)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_review_bundle_zip(zip_path: Path) -> tuple[bool, str]:
    if not zip_path.exists():
        return False, f"missing zip: {zip_path.name}"

    with zipfile.ZipFile(zip_path) as archive:
        members = frozenset(name for name in archive.namelist() if not name.endswith("/"))

        nested_zip = sorted(member for member in members if member.lower().endswith(".zip"))
        if nested_zip:
            return False, f"nested zip members: {nested_zip[:4]}"

        external_review = sorted(
            member for member in members if member.startswith("artifacts/external-review/")
        )
        if external_review:
            return False, f"artifacts/external-review members forbidden: {external_review[:4]}"

        if "REVIEW_INDEX.md" not in members:
            return False, "REVIEW_INDEX.md missing from zip"

        index_text = archive.read("REVIEW_INDEX.md").decode("utf-8")
        indexed_entries = parse_review_index(index_text)
        if not indexed_entries:
            return False, "REVIEW_INDEX.md contains no indexed members"

        indexed_paths = frozenset(entry.path for entry in indexed_entries)
        expected_members = indexed_paths | {"REVIEW_INDEX.md"}
        missing = sorted(expected_members - members)
        extra = sorted(members - expected_members)
        if missing or extra:
            return False, f"missing={missing[:6]}, extra={extra[:6]}"

        for entry in indexed_entries:
            payload = archive.read(entry.path)
            actual = sha256_bytes(payload)
            if actual != entry.sha256:
                return False, f"sha256 mismatch for {entry.path}: expected={entry.sha256}, actual={actual}"

        return True, f"validated {len(indexed_entries)} indexed members"
