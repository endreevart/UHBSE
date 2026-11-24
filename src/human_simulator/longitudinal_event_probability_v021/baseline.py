"""Baseline verification — v0.2 + traj + CSR + v0.1.1.1 remain immutable."""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import (
    mutation_proof,
    reconcile_review_index,
)
from human_simulator.longitudinal_event_probability_v021.policy import (
    ACCEPTED_TRAJ_ARTIFACT_DIR,
    ACCEPTED_TRAJ_INDEXED,
    ACCEPTED_TRAJ_MEMBERS,
    ACCEPTED_TRAJ_SHA256,
    ACCEPTED_TRAJ_ZIP,
    ACCEPTED_V02_SHA256,
    ACCEPTED_V02_ZIP,
    PRIOR_ZIPS,
    TRAJ_TRANSITIONS,
    VERSION,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    external = root / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []
    before: dict[str, str] = {}
    for label, (name, exp) in PRIOR_ZIPS.items():
        p = external / name
        dig = _sha(p) if p.is_file() else None
        before[label] = dig or ""
        checks.append({"name": f"{label}_sha", "ok": dig == exp, "detail": dig})

    z02 = external / ACCEPTED_V02_ZIP
    if z02.is_file():
        sc = external / f"{ACCEPTED_V02_ZIP}.sha256"
        sidecar_ok = sc.is_file() and sc.read_text(encoding="utf-8").split()[0] == ACCEPTED_V02_SHA256
        checks.append({"name": "lep_v02_sidecar", "ok": sidecar_ok})
        with zipfile.ZipFile(z02) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            checks.append({"name": "lep_v02_no_parquet", "ok": not any(n.endswith(".parquet") for n in names)})
            idx = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
            checks.append({"name": "lep_v02_review_index", "ok": bool(recon.get("ok"))})

    z = external / ACCEPTED_TRAJ_ZIP
    members = indexed = None
    if z.is_file():
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            checks.append({"name": "traj_members", "ok": members == ACCEPTED_TRAJ_MEMBERS, "detail": members})
            checks.append({"name": "traj_no_parquet", "ok": not any(n.endswith(".parquet") for n in names)})
            idx = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
            indexed = recon.get("indexed_members")
            checks.append(
                {
                    "name": "traj_indexed",
                    "ok": indexed == ACCEPTED_TRAJ_INDEXED and bool(recon.get("ok")),
                    "detail": indexed,
                }
            )
            art = ACCEPTED_TRAJ_ARTIFACT_DIR
            man = zf.read(f"{art}/evidence-manifest.sha256").decode()
            mism = []
            for line in man.splitlines():
                line = line.strip()
                if not line:
                    continue
                digest, _, name = line.partition("  ")
                if not name:
                    digest, _, name = line.partition(" ")
                name = name.strip()
                data = zf.read(f"{art}/{name}")
                if hashlib.sha256(data).hexdigest() != digest.strip():
                    mism.append(name)
            checks.append({"name": "traj_manifest", "ok": not mism})
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                checks.append(
                    {
                        "name": "traj_mutation",
                        "ok": bool(mutation_proof(Path(tmp) / art).get("ok")),
                    }
                )

    checks.append(
        {
            "name": "private_transitions",
            "ok": (root / TRAJ_TRANSITIONS / "transitions.parquet").is_file(),
        }
    )
    after = {
        label: _sha(external / name) if (external / name).is_file() else ""
        for label, (name, _) in PRIOR_ZIPS.items()
    }
    checks.append({"name": "prior_before_after", "ok": before == after})
    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_lep_v02_sha256": ACCEPTED_V02_SHA256,
        "accepted_traj_sha256": ACCEPTED_TRAJ_SHA256,
        "members": members,
        "indexed": indexed,
        "prior_sha_before": before,
        "prior_sha_after": after,
        "prior_zips_immutable": before == after,
        "checks": checks,
        "ok": ok,
    }
