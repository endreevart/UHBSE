"""Freeze synthetic runtime identity. Upstream held-out is consumed, not reopened."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v013.fixtures import synthetic_runtime_bundle
from human_simulator.integrated_research_runtime_v013.hashes import sha256_file, sha_obj
from human_simulator.integrated_research_runtime_v013.policy import FREEZE_MANIFEST, FREEZE_SIDECAR, MODELS_DIR, VERSION


def write_pretest_freeze(root: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    models = root / MODELS_DIR
    models.mkdir(parents=True, exist_ok=True)
    bundle = synthetic_runtime_bundle()
    public_cells = {
        ok: {k: v for k, v in c.items() if k not in {"ecdf", "residual_blocks", "p1_payload"}}
        for ok, c in bundle["cells"].items()
    }
    (models / "synthetic-runtime-bundle.json").write_text(
        json.dumps({**{k: v for k, v in bundle.items() if k != "cells"}, "cells": public_cells}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    members: dict[str, str] = {}
    for name in ("synthetic-runtime-bundle.json", "source-registry.json", "policy-snapshot.json", "gates.json"):
        p = models / name
        if p.is_file():
            members[name] = sha256_file(p)
    members["bundle_identity"] = sha_obj(
        {k: bundle[k] for k in ("source_system", "outcomes", "feature_order_sha256", "horizon_days") if k in bundle}
    )
    if extra:
        members["extra"] = sha_obj(extra)
    doc = {
        "version": VERSION,
        "PRE_TEST_PHYSICAL_FREEZE_STATUS": "FROZEN",
        "TEST_ACCESS_LIFECYCLE_STATUS": "CONSUMED_UPSTREAM_V01_HELDOUT_NOT_REOPENED",
        "open_test_does_not_recompute_joint_gates": True,
        "self_hash_inside_manifest": False,
        "detached_sidecar": FREEZE_SIDECAR,
        "members": members,
        "ok": True,
    }
    payload = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    man = models / FREEZE_MANIFEST
    man.write_text(payload, encoding="utf-8")
    (models / FREEZE_SIDECAR).write_text(sha256_file(man) + "  " + FREEZE_MANIFEST + "\n", encoding="utf-8")
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
        if name in {"bundle_identity", "extra"}:
            continue
        p = root / MODELS_DIR / name
        if not p.is_file() or sha256_file(p) != exp:
            return {"ok": False, "reason": f"member changed: {name}"}
    return {"ok": True, "PRE_TEST_PHYSICAL_FREEZE_STATUS": "VERIFIED", **doc}
