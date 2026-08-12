"""Inspect PostgreSQL custom-format dumps without connecting to a server."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class DumpInspectError(Exception):
    pass


@dataclass(frozen=True)
class DumpMetadata:
    path: Path
    size_bytes: int
    sha256: str
    format_label: str
    archive_version: str | None
    toc_entry_count: int
    toc_header_count: int | None
    toc_comment_lines: int
    dump_extensions: tuple[str, ...]
    pg_restore_version: str
    pg_restore_list_exit_code: int


@dataclass(frozen=True)
class TocAnalysis:
    header_toc_entries: int | None
    listed_active_entries: int
    comment_lines: int
    dump_extensions: tuple[str, ...]
    discrepancy: int | None
    explanation: str


_EXTENSION_LINE = re.compile(r"^\d+;\s+\d+\s+\d+\s+EXTENSION\s+-\s+(\S+)")
_TOC_HEADER = re.compile(r"TOC Entries:\s+(\d+)")
_ACTIVE_LINE = re.compile(r"^\d+;")


def analyze_toc_list(stdout: str) -> TocAnalysis:
    header_count: int | None = None
    extensions: list[str] = []
    comment_lines = 0
    active_lines = 0

    for line in stdout.splitlines():
        if not line.strip():
            continue
        if line.startswith(";"):
            comment_lines += 1
            match = _TOC_HEADER.search(line)
            if match:
                header_count = int(match.group(1))
            continue
        if _ACTIVE_LINE.match(line):
            active_lines += 1
        ext = _EXTENSION_LINE.match(line)
        if ext:
            name = ext.group(1)
            if name not in extensions:
                extensions.append(name)

    discrepancy = None
    explanation = "Header TOC count unavailable."
    if header_count is not None:
        discrepancy = header_count - active_lines
        explanation = (
            f"Archive header reports {header_count} embedded TOC entries. "
            f"pg_restore --list outputs {active_lines} active lines (matching '^\\\\d+;'). "
            f"Comment/semicolon lines in list output: {comment_lines}. "
            f"Delta {discrepancy}: header count includes archive metadata entries; "
            f"list output excludes semicolon-prefixed comment lines and may omit "
            f"non-restorable or duplicate-index entries present in the archive TOC."
        )

    return TocAnalysis(
        header_toc_entries=header_count,
        listed_active_entries=active_lines,
        comment_lines=comment_lines,
        dump_extensions=tuple(extensions),
        discrepancy=discrepancy,
        explanation=explanation,
    )


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_format(path: Path) -> tuple[str, str | None]:
    with path.open("rb") as f:
        header = f.read(5)
    if header != b"PGDMP":
        return ("unknown", None)
    # Optional: read archive version from dump header (bytes 5-7 little-endian)
    with path.open("rb") as f:
        f.seek(5)
        version_bytes = f.read(2)
    archive_version = None
    if len(version_bytes) == 2:
        major, minor = version_bytes[0], version_bytes[1]
        archive_version = f"{major}.{minor}"
    return ("postgresql_custom", archive_version)


def pg_restore_version() -> str:
    try:
        proc = subprocess.run(
            ["pg_restore", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DumpInspectError("pg_restore not found on PATH") from exc
    if proc.returncode != 0:
        raise DumpInspectError("pg_restore --version failed")
    return proc.stdout.strip()


def pg_restore_list(dump_path: Path) -> tuple[int, str, TocAnalysis]:
    """Run pg_restore --list (no DB connection)."""
    proc = subprocess.run(
        ["pg_restore", "--list", str(dump_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    analysis = analyze_toc_list(proc.stdout)
    return proc.returncode, proc.stdout, analysis


def inspect_dump(dump_path: Path) -> DumpMetadata:
    if not dump_path.is_file():
        raise DumpInspectError(f"dump not found: {dump_path}")

    fmt, archive_version = _detect_format(dump_path)
    if fmt != "postgresql_custom":
        raise DumpInspectError(f"unsupported dump format: {fmt}")

    restore_ver = pg_restore_version()
    list_rc, _, toc = pg_restore_list(dump_path)
    if list_rc != 0:
        raise DumpInspectError("pg_restore --list failed")

    return DumpMetadata(
        path=dump_path,
        size_bytes=dump_path.stat().st_size,
        sha256=_sha256_file(dump_path),
        format_label=fmt,
        archive_version=archive_version,
        toc_entry_count=toc.listed_active_entries,
        toc_header_count=toc.header_toc_entries,
        toc_comment_lines=toc.comment_lines,
        dump_extensions=toc.dump_extensions,
        pg_restore_version=restore_ver,
        pg_restore_list_exit_code=list_rc,
    )


def pg_restore_version_major(version_string: str) -> int | None:
    match = re.search(r"(\d+)", version_string)
    return int(match.group(1)) if match else None
