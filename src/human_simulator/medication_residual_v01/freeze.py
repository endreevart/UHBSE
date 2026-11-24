"""Physical pre-test freeze. Test must remain unread."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.medication_residual_v01.policy import (
    FREEZE_MANIFEST,
    LANDMARK_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    TEST_OPENED_MARKER,
    TEST_PARQUET,
    VERSION,
    TestAccessError,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pretest_freeze(root: Path, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    models = root / MODELS_DIR
    runtime = root / RUNTIME_DIR
    models.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    if (runtime / TEST_OPENED_MARKER).is_file():
        raise TestAccessError("cannot rewrite freeze after test opened")
    if (root / LANDMARK_DIR / TEST_PARQUET).is_file():
        raise TestAccessError("test parquet exists at freeze time")
    members: dict[str, str] = {}
    for p in sorted(models.glob("frozen-*.json")):
        members[p.name] = _sha(p)
    for name in ("frozen-vocab.json", "frozen-r0-means.json"):
        p = models / name
        if p.is_file():
            members[name] = _sha(p)
    tv = root / LANDMARK_DIR / "residual_train_val.parquet"
    if tv.is_file():
        members["residual_train_val.parquet"] = _sha(tv)
    doc = {
        "version": VERSION,
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": "FROZEN",
        "test_opened": False,
        "test_unread": True,
        "n_frozen_payloads": sum(1 for k in members if k.startswith("frozen-")),
        "members": members,
        "ok": True,
    }
    if extra:
        doc["extra_sha256"] = hashlib.sha256(
            json.dumps(extra, sort_keys=True, default=str).encode()
        ).hexdigest()
    (models / FREEZE_MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (runtime / FREEZE_MANIFEST).write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    doc["manifest_sha256"] = _sha(models / FREEZE_MANIFEST)
    (models / FREEZE_MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (runtime / FREEZE_MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def verify_pretest_freeze(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / MODELS_DIR / FREEZE_MANIFEST
    if not path.is_file():
        return {"ok": False, "PRE_TEST_PHYSICAL_FREEZE_STATUS": "MISSING"}
    stored = json.loads(path.read_text(encoding="utf-8"))
    members = dict(stored.get("members") or {})
    after: dict[str, str] = {}
    mismatches = []
    for name, exp in members.items():
        if name.endswith(".parquet"):
            p = root / LANDMARK_DIR / name
        else:
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
        "test_unread_at_freeze": bool(stored.get("test_unread")),
    }


def mark_test_opened(root: Path) -> dict[str, Any]:
    verified = verify_pretest_freeze(root)
    if not verified.get("ok"):
        raise TestAccessError(f"freeze verification failed: {verified}")
    marker = {
        "version": VERSION,
        "test_opened": True,
        "freeze": verified,
    }
    path = root / RUNTIME_DIR / TEST_OPENED_MARKER
    path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    return marker


def assert_test_access_allowed(root: Path) -> None:
    if not (root / RUNTIME_DIR / TEST_OPENED_MARKER).is_file():
        raise TestAccessError("test not opened")
    verified = verify_pretest_freeze(root)
    if not verified.get("ok"):
        raise TestAccessError("freeze mutated")
