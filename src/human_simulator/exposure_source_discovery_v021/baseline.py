"""Hash frozen discovery trees and Stage 05 bundles. This module does not write them."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v021.policy import (
    STAGE05_SHA256,
    V01_DIR,
    V01_SOURCE,
    V02_DIR,
    V02_SOURCE,
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_tree(root: Path, relative: str) -> list[dict[str, Any]]:
    base = root / relative
    if not base.exists():
        return [{"path": relative, "ok": False, "reason": "MISSING"}]
    files = sorted(path for path in base.rglob("*") if path.is_file())
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in files
    ]


def _tree_status(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    if any(not item.get("sha256") for item in before):
        return "FAIL"
    return "PASS" if before == after else "FAIL"


def stage05_status(root: Path) -> dict[str, Any]:
    files = []
    for relative, expected in STAGE05_SHA256.items():
        path = root / relative
        actual = sha256_file(path) if path.is_file() else None
        files.append({
            "path": relative,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "ok": actual == expected,
        })
    return {
        "STAGE05_BASELINE_VERIFICATION_STATUS": "PASS" if all(item["ok"] for item in files) else "FAIL",
        "files": files,
    }


def snapshot(root: Path) -> dict[str, Any]:
    root = Path(root)
    return {
        "v01_artifacts": hash_tree(root, V01_DIR),
        "v01_source": hash_tree(root, V01_SOURCE),
        "v02_artifacts": hash_tree(root, V02_DIR),
        "v02_source": hash_tree(root, V02_SOURCE),
        "stage05": stage05_status(root),
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "V01_BASELINE_VERIFICATION_STATUS": _tree_status(before["v01_artifacts"], after["v01_artifacts"])
        if _tree_status(before["v01_source"], after["v01_source"]) == "PASS"
        else "FAIL",
        "V02_BASELINE_VERIFICATION_STATUS": _tree_status(before["v02_artifacts"], after["v02_artifacts"])
        if _tree_status(before["v02_source"], after["v02_source"]) == "PASS"
        else "FAIL",
        "STAGE05_BASELINE_VERIFICATION_STATUS": after["stage05"]["STAGE05_BASELINE_VERIFICATION_STATUS"]
        if before["stage05"] == after["stage05"]
        else "FAIL",
        "before": before,
        "after": after,
        "writes_into_v01": False,
        "writes_into_v02": False,
        "external_review_zip_created": False,
    }
