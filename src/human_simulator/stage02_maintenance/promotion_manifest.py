"""Promotion manifest helpers for Stage 02 Maintenance 01.

``promotion-manifest.sha256`` seals every promotion content artifact except itself.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from human_simulator.stage02_maintenance.constants import (
    PROMOTION_CONTENT_ARTIFACTS,
    PROMOTION_MANIFEST_NAME,
)
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_file

_MANIFEST_LINE = re.compile(r"^([a-f0-9]{64})\s+(.+)$")


def promotion_content_paths(directory: Path) -> dict[str, Path]:
    """Map each sealed promotion content artifact to its path."""
    return {
        name: directory / name
        for name in PROMOTION_CONTENT_ARTIFACTS
        if (directory / name).is_file()
    }


def read_promotion_manifest(manifest_path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not manifest_path.is_file():
        return entries
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _MANIFEST_LINE.match(stripped)
        if not match:
            continue
        entries[match.group(2).strip()] = match.group(1)
    return entries


def manifest_lists_itself(entries: dict[str, str]) -> bool:
    return PROMOTION_MANIFEST_NAME in entries


def write_promotion_manifest(directory: Path) -> Path:
    """Seal promotion content artifacts. The manifest file must not list itself."""
    lines: list[str] = []
    for name in PROMOTION_CONTENT_ARTIFACTS:
        path = directory / name
        if path.is_file():
            lines.append(f"{sha256_file(path)}  {name}")
    manifest_path = directory / PROMOTION_MANIFEST_NAME
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


def verify_promotion_manifest_entries(directory: Path) -> tuple[bool, list[str]]:
    """Verify every manifest entry against on-disk bytes under ``directory``."""
    manifest_path = directory / PROMOTION_MANIFEST_NAME
    failures: list[str] = []
    if not manifest_path.is_file():
        return False, [f"missing {PROMOTION_MANIFEST_NAME}"]

    entries = read_promotion_manifest(manifest_path)
    if manifest_lists_itself(entries):
        failures.append(f"{PROMOTION_MANIFEST_NAME} must not list itself")

    expected_names = [name for name in PROMOTION_CONTENT_ARTIFACTS if (directory / name).is_file()]
    missing_entries = sorted(set(expected_names) - set(entries))
    if missing_entries:
        failures.extend(f"missing manifest entry: {name}" for name in missing_entries)

    extra_entries = sorted(set(entries) - set(expected_names))
    if extra_entries:
        failures.extend(f"unexpected manifest entry: {name}" for name in extra_entries)

    for name, recorded in entries.items():
        path = directory / name
        if not path.is_file():
            failures.append(f"missing file for manifest entry: {name}")
            continue
        actual = sha256_file(path)
        if actual != recorded:
            failures.append(f"{name}: recorded {recorded} != actual {actual}")

    return not failures, failures


def verify_promotion_manifest_with_shasum(directory: Path) -> tuple[bool, str]:
    """Independent check using the platform ``shasum`` / ``sha256sum`` tool."""
    manifest_path = directory / PROMOTION_MANIFEST_NAME
    if not manifest_path.is_file():
        return False, f"missing {PROMOTION_MANIFEST_NAME}"

    for tool in ("shasum", "sha256sum"):
        completed = subprocess.run(
            [tool, "-a", "256", "-c", PROMOTION_MANIFEST_NAME],
            cwd=directory,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return True, (completed.stdout or "").strip()
        if "command not found" not in (completed.stderr or "").lower():
            output = ((completed.stdout or "") + (completed.stderr or "")).strip()
            return False, output or f"{tool} exit {completed.returncode}"
    return False, "neither shasum nor sha256sum is available"
