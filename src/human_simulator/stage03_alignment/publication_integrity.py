"""Publication integrity helpers for runtime-auth review ZIPs."""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_sha256_manifest(
    directory: Path,
    *,
    exclude_names: set[str] | None = None,
    include_names: set[str] | list[str] | None = None,
) -> Path:
    """Write manifest.sha256 over files currently in directory (excluding the manifest itself).

    If include_names is set, only those filenames are hashed (must exist).
    """
    exclude = set(exclude_names or set())
    exclude.add("manifest.sha256")
    if include_names is not None:
        files = []
        for name in sorted(include_names):
            if name in exclude:
                continue
            path = directory / name
            if not path.is_file():
                raise FileNotFoundError(f"manifest include missing: {name}")
            files.append(path)
    else:
        files = sorted(
            p for p in directory.iterdir() if p.is_file() and p.name not in exclude
        )
    lines = [f"{sha256_file(p)}  {p.name}" for p in files]
    manifest = directory / "manifest.sha256"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def verify_sha256_manifest(manifest_path: Path, *, base_dir: Path | None = None) -> dict[str, Any]:
    base = base_dir or manifest_path.parent
    if not manifest_path.is_file():
        return {"verified": False, "detail": "manifest missing", "mismatches": ["missing"]}
    mismatches: list[str] = []
    entries = 0
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.strip()
        entries += 1
        target = base / name
        if not target.is_file():
            mismatches.append(f"missing:{name}")
            continue
        actual = sha256_file(target)
        if actual != digest:
            mismatches.append(f"mismatch:{name}")
    return {
        "verified": not mismatches,
        "entry_count": entries,
        "mismatches": mismatches,
    }


def parse_review_index(text: str) -> dict[str, str]:
    indexed: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", line)
        if m:
            indexed[m.group(1)] = m.group(2)
    return indexed


def verify_review_index_against_zip(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        nested = [n for n in names if n.endswith(".zip")]
        if "REVIEW_INDEX.md" not in names:
            return {
                "verified": False,
                "detail": "REVIEW_INDEX.md missing",
                "no_duplicate_members": not duplicates,
                "no_nested_archives": not nested,
            }
        indexed = parse_review_index(zf.read("REVIEW_INDEX.md").decode("utf-8"))
        members = [n for n in names if n != "REVIEW_INDEX.md"]
        missing = sorted(set(indexed) - set(members))
        unindexed = sorted(set(members) - set(indexed))
        hash_mismatches: list[str] = []
        for arc, expected in indexed.items():
            if arc not in members:
                continue
            actual = sha256_bytes(zf.read(arc))
            if actual != expected:
                hash_mismatches.append(arc)
        verified = (
            not missing
            and not unindexed
            and not hash_mismatches
            and not duplicates
            and not nested
        )
        return {
            "verified": verified,
            "members": len(names),
            "indexed_members": len(indexed),
            "no_missing_members": not missing,
            "no_unindexed_members": not unindexed,
            "no_duplicate_members": not duplicates,
            "no_nested_archives": not nested,
            "hash_mismatches": hash_mismatches,
            "missing_members": missing,
            "unindexed_members": unindexed,
        }


def verify_extracted_bundle(extract_root: Path, *, evidence_subdir: str) -> dict[str, Any]:
    evidence = extract_root / evidence_subdir
    manifest = evidence / "manifest.sha256"
    manifest_result = verify_sha256_manifest(manifest, base_dir=evidence)
    index_path = extract_root / "REVIEW_INDEX.md"
    if not index_path.is_file():
        return {
            "internal_manifest_verified_after_extract": False,
            "review_index_present": False,
            **manifest_result,
        }
    indexed = parse_review_index(index_path.read_text(encoding="utf-8"))
    present = {
        p.relative_to(extract_root).as_posix()
        for p in extract_root.rglob("*")
        if p.is_file() and p.name != "REVIEW_INDEX.md"
    }
    missing = sorted(set(indexed) - present)
    unindexed = sorted(present - set(indexed))
    hash_mismatches = []
    for arc, expected in indexed.items():
        path = extract_root / arc
        if path.is_file() and sha256_file(path) != expected:
            hash_mismatches.append(arc)
    return {
        "internal_manifest_verified_after_extract": manifest_result["verified"],
        "review_index_verified_after_extract": not missing
        and not unindexed
        and not hash_mismatches,
        "manifest_mismatches": manifest_result.get("mismatches", []),
        "index_missing_members": missing,
        "index_unindexed_members": unindexed,
        "index_hash_mismatches": hash_mismatches,
    }
