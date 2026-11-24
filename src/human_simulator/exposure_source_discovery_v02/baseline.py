"""Verify the frozen v0.1 discovery baseline. Never writes into it."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.policy import BASELINE_SHA256


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    files: list[dict[str, Any]] = []
    ok = True
    for rel, expected in BASELINE_SHA256.items():
        path = root / rel
        actual = sha256_file(path) if path.is_file() else None
        match = actual == expected
        ok = ok and match
        files.append({"path": rel, "expected_sha256": expected, "actual_sha256": actual, "ok": match})
    return {
        "ok": ok,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "files": files,
        "writes_into_v01": False,
    }
