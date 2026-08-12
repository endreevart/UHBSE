"""Shared review-bundle indexing rules for Stage 02 Maintenance 01.

``REVIEW_INDEX.md`` is a member of the archive but does not index itself. Every other member —
including ``REPRODUCE.md`` — is listed with its SHA-256. Therefore ``indexed == members - 1``.
"""

from __future__ import annotations

from pathlib import Path

from human_simulator.stage02_maintenance.drift_diagnosis import sha256_bytes


def build_review_index(
    *,
    title: str,
    header_lines: list[str],
    bundle_files: list[tuple[str, Path]],
    inline_members: list[tuple[str, bytes]] | None = None,
) -> str:
    """Build REVIEW_INDEX.md listing every member except itself."""
    lines = [f"# {title}", ""] + header_lines + [
        "",
        "## Contents",
        "",
        "| Path | Bytes | SHA-256 |",
        "|------|-------|---------|",
    ]
    indexed: list[tuple[str, bytes]] = []
    for member, path in bundle_files:
        indexed.append((member, path.read_bytes()))
    for member, payload in inline_members or []:
        indexed.append((member, payload))
    for member, payload in sorted(indexed, key=lambda item: item[0]):
        lines.append(f"| `{member}` | {len(payload)} | `{sha256_bytes(payload)}` |")
    lines.append("")
    return "\n".join(lines)


def bundle_counts(bundle_files: list[tuple[str, Path]]) -> tuple[int, int]:
    """Return (members, indexed) where indexed excludes REVIEW_INDEX.md."""
    members = len(bundle_files) + 2  # REVIEW_INDEX.md + REPRODUCE.md
    indexed = members - 1
    return members, indexed


def verify_indexed_members(archive_path: Path, index_text: str) -> list[str]:
    """After unpack, confirm every indexed SHA matches the archive payload."""
    import re
    import zipfile

    pattern = re.compile(r"\| `([^`]+)` \| \d+ \| `([a-f0-9]{64})` \|")
    expected = {match.group(1): match.group(2) for match in pattern.finditer(index_text)}
    failures: list[str] = []
    with zipfile.ZipFile(archive_path) as bundle:
        for member, digest in expected.items():
            if member not in bundle.namelist():
                failures.append(f"missing indexed member: {member}")
                continue
            actual = sha256_bytes(bundle.read(member))
            if actual != digest:
                failures.append(f"{member}: index {digest} != archive {actual}")
    return failures
