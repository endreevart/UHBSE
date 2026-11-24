"""Complete freeze with detached sidecar. No self-hash rewrite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v01.hashes import sha256_file
from human_simulator.integrated_research_runtime_v01.policy import (
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
    "joint-payload.json",
    "train-scales.json",
    "residual-oof.json",
    "source-registry.json",
    "policy-snapshot.json",
    "gates.json",
    "classifier-public.json",
    "qsp-sandbox.json",
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
    tv = root / SEQ_DIR / TRAIN_VAL_PARQUET
    if tv.is_file():
        members[TRAIN_VAL_PARQUET] = sha256_file(tv)
    required = {"joint-payload.json", "gates.json", "source-registry.json", TRAIN_VAL_PARQUET}
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
    payload = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    man = models / FREEZE_MANIFEST
    man.write_text(payload, encoding="utf-8")
    sidecar = models / FREEZE_SIDECAR
    sidecar.write_text(sha256_file(man) + "  " + FREEZE_MANIFEST + "\n", encoding="utf-8")
    (runtime / FREEZE_MANIFEST).write_text(payload, encoding="utf-8")
    (runtime / FREEZE_SIDECAR).write_text(sidecar.read_text(encoding="utf-8"), encoding="utf-8")
    return doc


def verify_pretest_freeze(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    man = root / MODELS_DIR / FREEZE_MANIFEST
    sidecar = root / MODELS_DIR / FREEZE_SIDECAR
    if not man.is_file() or not sidecar.is_file():
        return {"ok": False, "reason": "missing freeze"}
    if sha256_file(man) != sidecar.read_text(encoding="utf-8").split()[0]:
        return {"ok": False, "reason": "sidecar mismatch"}
    doc = json.loads(man.read_text(encoding="utf-8"))
    for name, exp in (doc.get("members") or {}).items():
        p = root / MODELS_DIR / name
        if name == TRAIN_VAL_PARQUET:
            p = root / SEQ_DIR / TRAIN_VAL_PARQUET
        if not p.is_file() or sha256_file(p) != exp:
            return {"ok": False, "reason": f"member changed: {name}"}
    return {"ok": True, "PRE_TEST_PHYSICAL_FREEZE_STATUS": "VERIFIED", **doc}


def mark_test_opened(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    v = verify_pretest_freeze(root)
    if not v.get("ok"):
        raise TestAccessError(f"freeze not verified: {v}")
    marker = root / RUNTIME_DIR / TEST_OPENED_MARKER
    doc = {"version": VERSION, "test_opened": True}
    marker.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc
