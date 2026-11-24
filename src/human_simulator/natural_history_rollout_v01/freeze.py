"""Physical pre-test freeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.natural_history_rollout_v01.policy import (
    FREEZE_MANIFEST,
    MODELS_DIR,
    RUNTIME_DIR,
    SEQ_DIR,
    TEST_OPENED_MARKER,
    TEST_PARQUET,
    VERSION,
    TestAccessError,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pretest_freeze(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    models = root / MODELS_DIR
    runtime = root / RUNTIME_DIR
    models.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    if (runtime / TEST_OPENED_MARKER).is_file():
        raise TestAccessError("cannot rewrite freeze after test opened")
    if (root / SEQ_DIR / TEST_PARQUET).is_file():
        raise TestAccessError("test parquet exists at freeze time")
    members: dict[str, str] = {}
    for p in sorted(models.glob("frozen-*.json")):
        members[p.name] = _sha(p)
    tv = root / SEQ_DIR / "sequences_train_val.parquet"
    if tv.is_file():
        members["sequences_train_val.parquet"] = _sha(tv)
    doc = {
        "version": VERSION,
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": "FROZEN",
        "test_opened": False,
        "test_unread": True,
        "members": members,
        "ok": True,
    }
    (models / FREEZE_MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (runtime / FREEZE_MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    doc["manifest_sha256"] = _sha(models / FREEZE_MANIFEST)
    (models / FREEZE_MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (runtime / FREEZE_MANIFEST).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def verify_pretest_freeze(root: Path) -> dict[str, Any]:
    path = root / MODELS_DIR / FREEZE_MANIFEST
    if not path.is_file():
        return {"ok": False, "PRE_TEST_PHYSICAL_FREEZE_STATUS": "MISSING"}
    stored = json.loads(path.read_text(encoding="utf-8"))
    members = dict(stored.get("members") or {})
    mismatches = []
    after = {}
    for name, exp in members.items():
        p = (root / SEQ_DIR / name) if name.endswith(".parquet") else (root / MODELS_DIR / name)
        if not p.is_file():
            mismatches.append({"name": name, "error": "missing"})
            continue
        got = _sha(p)
        after[name] = got
        if got != exp:
            mismatches.append({"name": name})
    ok = not mismatches
    return {
        "ok": ok,
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": "VERIFIED" if ok else "MUTATED",
        "test_unread_at_freeze": bool(stored.get("test_unread")),
        "before_equals_after": ok,
        "mismatches": mismatches,
    }


def mark_test_opened(root: Path) -> dict[str, Any]:
    verified = verify_pretest_freeze(root)
    if not verified.get("ok"):
        raise TestAccessError(f"freeze verification failed: {verified}")
    marker = {"version": VERSION, "test_opened": True, "freeze": verified}
    (root / RUNTIME_DIR / TEST_OPENED_MARKER).write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )
    return marker
