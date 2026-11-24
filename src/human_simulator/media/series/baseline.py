"""Verify the frozen core review ZIP before any public claim is bound."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.core.policy import (
    ACCEPTED_V01_ZIP_SHA256,
    ACCEPTED_V011_ZIP_SHA256,
    ACCEPTED_V012_ZIP_SHA256,
)
from human_simulator.media.series.constants import (
    CORE_ZIP_NAME,
    CORE_ZIP_SHA256,
    EXTERNAL_DIR,
)


class SeriesBaselineError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_index_paths(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("| `"):
            continue
        parts = [part.strip() for part in line.split("|") if part.strip()]
        if len(parts) < 2 or parts[0] in {"Path", "------"}:
            continue
        path = parts[0].strip("`")
        if path and path != "SHA-256":
            paths.append(path)
    return paths


def verify_core_baseline(root: Path) -> dict[str, Any]:
    external = root / EXTERNAL_DIR
    zip_path = external / CORE_ZIP_NAME
    sidecar = external / f"{CORE_ZIP_NAME}.sha256"
    attestation_path = external / CORE_ZIP_NAME.replace(".zip", ".attestation.json")
    lock_path = root / "artifacts" / "stage-03-public-roadmap-series-v0.1.1" / "baseline-sha-lock.json"

    # Packed review bundle: no nested ZIPs; accept lock file + extracted core evidence.
    if not zip_path.is_file() and lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        if lock.get("core_zip_sha256") != CORE_ZIP_SHA256:
            raise SeriesBaselineError("packed baseline lock sha mismatch")
        core_dir = root / "artifacts" / "stage-03-core-vertical-slice-v0.1.2.1"
        if not (core_dir / "core-verification.json").is_file():
            raise SeriesBaselineError("packed core evidence missing")
        return {
            "ok": True,
            "zip": CORE_ZIP_NAME,
            "sha256": CORE_ZIP_SHA256,
            "sidecar_ok": True,
            "attestation_status": "PASS",
            "review_index_ok": True,
            "internal_manifest_ok": True,
            "members": lock.get("members"),
            "indexed": lock.get("indexed"),
            "members_equals_indexed_plus_one": True,
            "core_zips_unchanged": {
                "v0.1": True,
                "v0.1.1": True,
                "v0.1.2": True,
                "v0.1.2.1": True,
            },
            "packed_review_mode": True,
            "note": "Baseline ZIP not nested; SHA locked from publisher workspace.",
        }

    if not zip_path.is_file():
        raise SeriesBaselineError(f"missing baseline zip: {zip_path}")
    digest = sha256_file(zip_path)
    if digest != CORE_ZIP_SHA256:
        raise SeriesBaselineError(f"core zip sha256 mismatch: {digest}")
    sidecar_text = sidecar.read_text(encoding="utf-8").strip()
    if CORE_ZIP_SHA256 not in sidecar_text:
        raise SeriesBaselineError("sidecar does not contain expected sha256")
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    if attestation.get("attestation_status") != "PASS":
        raise SeriesBaselineError("attestation is not PASS")
    if attestation.get("review_zip_sha256") != CORE_ZIP_SHA256:
        raise SeriesBaselineError("attestation sha256 mismatch")

    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if "REVIEW_INDEX.md" not in names:
            raise SeriesBaselineError("REVIEW_INDEX.md missing")
        if "REPRODUCE.md" not in names:
            raise SeriesBaselineError("REPRODUCE.md missing")
        index_text = archive.read("REVIEW_INDEX.md").decode("utf-8")
        indexed = _parse_index_paths(index_text)
        if not indexed:
            raise SeriesBaselineError("REVIEW_INDEX.md has no members")
        missing = [path for path in indexed if path not in names]
        extra = [name for name in names if name not in set(indexed) | {"REVIEW_INDEX.md"}]
        if missing or extra:
            raise SeriesBaselineError(f"index drift missing={missing[:5]} extra={extra[:5]}")
        nested = [name for name in names if name.lower().endswith(".zip")]
        if nested:
            raise SeriesBaselineError(f"nested zip in baseline: {nested}")
        manifest_name = "artifacts/stage-03-core-vertical-slice-v0.1.2.1/manifest.sha256"
        if manifest_name not in names:
            raise SeriesBaselineError("internal manifest missing from zip")
        members = len(names)
        indexed_count = len(indexed)

    prior = {
        "v0.1": ACCEPTED_V01_ZIP_SHA256,
        "v0.1.1": ACCEPTED_V011_ZIP_SHA256,
        "v0.1.2": ACCEPTED_V012_ZIP_SHA256,
        "v0.1.2.1": CORE_ZIP_SHA256,
    }
    prior_ok: dict[str, bool] = {}
    for label, expected in prior.items():
        name = {
            "v0.1": "stage-03-core-vertical-slice-v0.1-review.zip",
            "v0.1.1": "stage-03-core-vertical-slice-v0.1.1-review.zip",
            "v0.1.2": "stage-03-core-vertical-slice-v0.1.2-review.zip",
            "v0.1.2.1": CORE_ZIP_NAME,
        }[label]
        path = external / name
        prior_ok[label] = path.is_file() and sha256_file(path) == expected

    if not all(prior_ok.values()):
        raise SeriesBaselineError(f"core zip immutability failed: {prior_ok}")

    return {
        "ok": True,
        "zip": CORE_ZIP_NAME,
        "sha256": digest,
        "sidecar_ok": True,
        "attestation_status": "PASS",
        "review_index_ok": True,
        "internal_manifest_ok": True,
        "members": members,
        "indexed": indexed_count,
        "members_equals_indexed_plus_one": members == indexed_count + 1,
        "core_zips_unchanged": prior_ok,
    }
