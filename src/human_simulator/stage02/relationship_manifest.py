"""SHA-256 manifest for Stage 02 relationship assessment artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

RELATIONSHIP_MANIFEST_ARTIFACTS: tuple[str, ...] = (
    "subject-root-analysis.json",
    "subject-root-analysis.md",
    "source-relationship-assessment.json",
    "source-relationship-assessment.md",
    "identity-linkage-assessment.json",
    "identity-linkage-assessment.md",
    "relationship-verification-report.json",
    "relationship-query-log.json",
)

MANIFEST_NAME = "relationship-manifest.sha256"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_relationship_manifest(artifacts_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    lines: list[str] = []
    for name in RELATIONSHIP_MANIFEST_ARTIFACTS:
        path = artifacts_dir / name
        if not path.exists():
            continue
        digest = sha256_file(path)
        hashes[name] = digest
        lines.append(f"{digest}  {name}")
    (artifacts_dir / MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashes


def verify_relationship_manifest(artifacts_dir: Path) -> tuple[bool, str]:
    manifest_path = artifacts_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return False, f"missing {MANIFEST_NAME}"
    verified = 0
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        path = artifacts_dir / name.strip()
        if not path.exists():
            return False, f"manifest entry missing file: {name.strip()}"
        if sha256_file(path) != digest:
            return False, f"hash mismatch: {name.strip()}"
        verified += 1
    return True, f"verified {verified} entries in {MANIFEST_NAME}"
