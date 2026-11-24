"""Normalized comparison between a packed reference and a clean-extraction replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.intervention_response_readiness_v011.policy import (
    COMPARE_FILES,
    STATUS_COMPARE_IGNORE,
    UNSTABLE_KEYS,
)


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize(item)
            for key, item in value.items()
            if key not in UNSTABLE_KEYS
        }
    if isinstance(value, list):
        normalized = [normalize(item) for item in value]
        if normalized and all(isinstance(item, dict) and "cell_id" in item for item in normalized):
            return sorted(normalized, key=lambda item: str(item.get("cell_id")))
        return normalized
    return value


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_artifact_dirs(reference: Path, candidate: Path) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    compared: list[str] = []
    for name in COMPARE_FILES:
        left_path = reference / name
        right_path = candidate / name
        if not left_path.is_file() or not right_path.is_file():
            mismatches.append({"file": name, "reason": "MISSING"})
            continue
        left = normalize(_load(left_path))
        right = normalize(_load(right_path))
        if name == "status-contract.json":
            left = {key: value for key, value in left.items() if key not in STATUS_COMPARE_IGNORE}
            right = {key: value for key, value in right.items() if key not in STATUS_COMPARE_IGNORE}
        compared.append(name)
        if left != right:
            mismatches.append({"file": name, "reason": "NORMALIZED_MISMATCH", "diff": _brief(left, right)})
    return {
        "ok": not mismatches,
        "compared_files": compared,
        "ignored_status_keys": sorted(STATUS_COMPARE_IGNORE),
        "ignored_unstable_keys": sorted(UNSTABLE_KEYS),
        "mismatches": mismatches,
    }


def _brief(left: Any, right: Any, prefix: str = "") -> list[str]:
    lines: list[str] = []
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                lines.append(f"{prefix}{key}: presence")
                continue
            if left[key] != right[key]:
                nested = _brief(left[key], right[key], prefix + key + ".")
                if nested:
                    lines.extend(nested[:8])
                else:
                    lines.append(f"{prefix}{key}")
            if len(lines) > 12:
                break
        return lines[:12]
    if left != right:
        return [prefix[:-1] or "value"]
    return []
