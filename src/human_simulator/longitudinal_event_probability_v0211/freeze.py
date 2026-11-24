"""Physical pre-test freeze: persist payloads, registry, hashes; then stop."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.longitudinal_event_probability_v0211.policy import (
    FREEZE_MANIFEST,
    MODELS_DIR,
    PRETEST_REGISTRY,
    RUNTIME_DIR,
    TEST_OPENED_MARKER,
    VERSION,
)

from human_simulator.longitudinal_event_probability_v0211.survival import TestAccessError


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pretest_freeze(
    root: Path,
    *,
    registry: dict[str, Any],
    results_public: list[dict[str, Any]],
    extra_files: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    models = root / MODELS_DIR
    runtime = root / RUNTIME_DIR
    models.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    if (runtime / TEST_OPENED_MARKER).is_file():
        raise TestAccessError("cannot rewrite freeze after test opened")
    pretest_path = models / PRETEST_REGISTRY
    pretest_path.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    members: dict[str, str] = {}
    for p in sorted(models.glob("frozen-*.json")):
        members[p.name] = _sha(p)
    members[PRETEST_REGISTRY] = _sha(pretest_path)
    ood = models / "ood-reference.json"
    if ood.is_file():
        members["ood-reference.json"] = _sha(ood)
    for name in extra_files or []:
        p = models / name
        if p.is_file():
            members[name] = _sha(p)
    doc = {
        "version": VERSION,
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": "FROZEN",
        "test_opened": False,
        "n_frozen_payloads": sum(1 for k in members if k.startswith("frozen-")),
        "members": members,
        "results_public_sha256": hashlib.sha256(
            json.dumps(results_public, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "ok": True,
    }
    (models / FREEZE_MANIFEST).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (runtime / FREEZE_MANIFEST).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    doc["manifest_sha256"] = _sha(models / FREEZE_MANIFEST)
    (models / FREEZE_MANIFEST).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (runtime / FREEZE_MANIFEST).write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return doc


def verify_pretest_freeze(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / MODELS_DIR / FREEZE_MANIFEST
    if not path.is_file():
        return {
            "ok": False,
            "PRE_TEST_PHYSICAL_FREEZE_STATUS": "MISSING",
            "error": "FREEZE_MANIFEST_MISSING",
        }
    stored = json.loads(path.read_text(encoding="utf-8"))
    members = dict(stored.get("members") or {})
    after: dict[str, str] = {}
    mismatches = []
    for name, exp in members.items():
        p = root / MODELS_DIR / name
        if not p.is_file():
            mismatches.append({"name": name, "error": "missing"})
            continue
        got = _sha(p)
        after[name] = got
        if got != exp:
            mismatches.append({"name": name, "before": exp, "after": got})
    ok = not mismatches
    return {
        "ok": ok,
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": "VERIFIED" if ok else "MUTATED",
        "before": members,
        "after": after,
        "before_equals_after": ok,
        "mismatches": mismatches,
    }


def mark_test_opened(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    verified = verify_pretest_freeze(root)
    if not verified.get("ok"):
        raise TestAccessError(f"freeze verification failed: {verified}")
    marker = {
        "version": VERSION,
        "TEST_ACCESS_LIFECYCLE_STATUS": "OPENED",
        "freeze": verified,
    }
    (root / RUNTIME_DIR / TEST_OPENED_MARKER).write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )
    (root / MODELS_DIR / TEST_OPENED_MARKER).write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )
    return marker


def assert_test_access_allowed(root: Path) -> None:
    root = Path(root).resolve()
    freeze = root / MODELS_DIR / FREEZE_MANIFEST
    opened = root / RUNTIME_DIR / TEST_OPENED_MARKER
    if not freeze.is_file():
        raise TestAccessError("test evaluation before persisted pre-test freeze")
    if not opened.is_file():
        raise TestAccessError("test evaluation requires open-test process")
    verified = verify_pretest_freeze(root)
    if not verified.get("ok"):
        raise TestAccessError("freeze hashes mutated before test")


def freeze_status(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    freeze_path = root / MODELS_DIR / FREEZE_MANIFEST
    opened = (root / RUNTIME_DIR / TEST_OPENED_MARKER).is_file()
    if not freeze_path.is_file():
        return {
            "PRE_TEST_PHYSICAL_FREEZE_STATUS": "MISSING",
            "TEST_ACCESS_LIFECYCLE_STATUS": "BLOCKED",
            "ok": False,
        }
    verified = verify_pretest_freeze(root)
    return {
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": (
            "FROZEN" if verified.get("ok") and not opened else verified.get("PRE_TEST_PHYSICAL_FREEZE_STATUS")
        ),
        "TEST_ACCESS_LIFECYCLE_STATUS": "OPENED" if opened else "FROZEN_CLOSED",
        "freeze_verified": verified.get("ok"),
        "ok": bool(verified.get("ok")),
    }
