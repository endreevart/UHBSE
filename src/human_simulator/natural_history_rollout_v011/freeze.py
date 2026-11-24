"""Complete physical freeze with detached manifest digest. No invalid self-hash."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.natural_history_rollout_v011.hashes import sha256_file
from human_simulator.natural_history_rollout_v011.policy import (
    FREEZE_MANIFEST,
    FREEZE_SIDECAR,
    MODELS_DIR,
    RUNTIME_DIR,
    SEQ_DIR,
    TEST_OPENED_MARKER,
    TEST_PARQUET,
    TRAIN_VAL_PARQUET,
    VERSION,
    TestAccessError,
)

MEMBER_FILES = (
    "pre-test-cells.json",
    "residual-payload.json",
    "registry.json",
    "policy-snapshot.json",
    "target-alignment-contract.json",
    "engine-eligibility.json",
    "code-policy-hashes.json",
)


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
    for name in MEMBER_FILES:
        p = models / name
        if p.is_file():
            members[name] = sha256_file(p)
    for p in sorted(models.glob("frozen-payload-*.json")):
        members[p.name] = sha256_file(p)
    tv = root / SEQ_DIR / TRAIN_VAL_PARQUET
    if tv.is_file():
        members[TRAIN_VAL_PARQUET] = sha256_file(tv)
    required = {
        "pre-test-cells.json",
        "residual-payload.json",
        "registry.json",
        "policy-snapshot.json",
        "target-alignment-contract.json",
        "engine-eligibility.json",
        "code-policy-hashes.json",
        TRAIN_VAL_PARQUET,
    }
    missing = [n for n in required if n not in members]
    doc = {
        "version": VERSION,
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": "FROZEN" if not missing else "INCOMPLETE",
        "test_opened": False,
        "test_unread": True,
        "self_hash_inside_manifest": False,
        "detached_sidecar": FREEZE_SIDECAR,
        "members": members,
        "missing_required": missing,
        "ok": not missing,
    }
    man_path = models / FREEZE_MANIFEST
    payload = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    man_path.write_text(payload, encoding="utf-8")
    (runtime / FREEZE_MANIFEST).write_text(payload, encoding="utf-8")
    digest = sha256_file(man_path)
    (models / FREEZE_SIDECAR).write_text(f"{digest}  {FREEZE_MANIFEST}\n", encoding="utf-8")
    (runtime / FREEZE_SIDECAR).write_text(f"{digest}  {FREEZE_MANIFEST}\n", encoding="utf-8")
    doc["manifest_digest_detached"] = digest
    return doc


def _member_path(root: Path, name: str) -> Path:
    if name.endswith(".parquet"):
        return root / SEQ_DIR / name
    return root / MODELS_DIR / name


def verify_pretest_freeze(root: Path) -> dict[str, Any]:
    path = root / MODELS_DIR / FREEZE_MANIFEST
    side = root / MODELS_DIR / FREEZE_SIDECAR
    if not path.is_file() or not side.is_file():
        return {"ok": False, "PRE_TEST_PHYSICAL_FREEZE_STATUS": "MISSING"}
    stored = json.loads(path.read_text(encoding="utf-8"))
    got_man = sha256_file(path)
    exp_man = side.read_text(encoding="utf-8").split()[0]
    mismatches = []
    if got_man != exp_man:
        mismatches.append({"name": FREEZE_MANIFEST, "error": "sidecar_mismatch"})
    after = {}
    for name, exp in (stored.get("members") or {}).items():
        p = _member_path(root, name)
        if not p.is_file():
            mismatches.append({"name": name, "error": "missing"})
            continue
        got = sha256_file(p)
        after[name] = got
        if got != exp:
            mismatches.append({"name": name})
    ok = not mismatches
    return {
        "ok": ok,
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": "VERIFIED" if ok else "MUTATED",
        "ACTIVE_RUNTIME_PAYLOAD_IDENTITY_STATUS": "VERIFIED" if ok else "MUTATED",
        "test_unread_at_freeze": bool(stored.get("test_unread")),
        "sidecar_ok": got_man == exp_man,
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


def assert_members_unmutated(root: Path) -> None:
    v = verify_pretest_freeze(root)
    if not v.get("ok"):
        raise TestAccessError(f"active payload mutated: {v.get('mismatches')}")
