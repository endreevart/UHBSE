"""Baseline verification — v0.2.1 ZIP members/indexed, plus immutable priors."""

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
from human_simulator.longitudinal_event_probability_v0211.policy import (
    ACCEPTED_V021_ARTIFACT_DIR,
    ACCEPTED_V021_INDEXED,
    ACCEPTED_V021_MEMBERS,
    ACCEPTED_V021_SHA256,
    ACCEPTED_V021_ZIP,
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

    z021 = external / ACCEPTED_V021_ZIP
    members = indexed = None
    if z021.is_file():
        sc = external / f"{ACCEPTED_V021_ZIP}.sha256"
        sidecar_ok = (
            sc.is_file() and sc.read_text(encoding="utf-8").split()[0] == ACCEPTED_V021_SHA256
        )
        checks.append({"name": "lep_v021_sidecar", "ok": sidecar_ok})
        with zipfile.ZipFile(z021) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            checks.append(
                {
                    "name": "lep_v021_members",
                    "ok": members == ACCEPTED_V021_MEMBERS,
                    "detail": members,
                }
            )
            checks.append(
                {"name": "lep_v021_no_parquet", "ok": not any(n.endswith(".parquet") for n in names)}
            )
            idx = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
            indexed = recon.get("indexed_members")
            checks.append(
                {
                    "name": "lep_v021_indexed",
                    "ok": indexed == ACCEPTED_V021_INDEXED and bool(recon.get("ok")),
                    "detail": indexed,
                }
            )
            art = ACCEPTED_V021_ARTIFACT_DIR
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
            checks.append({"name": "lep_v021_manifest", "ok": not mism})
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                checks.append(
                    {
                        "name": "lep_v021_mutation",
                        "ok": bool(mutation_proof(Path(tmp) / art).get("ok")),
                    }
                )

    z02 = external / ACCEPTED_V02_ZIP
    if z02.is_file():
        sc = external / f"{ACCEPTED_V02_ZIP}.sha256"
        sidecar_ok = sc.is_file() and sc.read_text(encoding="utf-8").split()[0] == ACCEPTED_V02_SHA256
        checks.append({"name": "lep_v02_sidecar", "ok": sidecar_ok})

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
    # Must not publish trajectory v0.1 703/702 as the verified ZIP accounting.
    checks.append(
        {
            "name": "not_traj_member_accounting",
            "ok": members == ACCEPTED_V021_MEMBERS and indexed == ACCEPTED_V021_INDEXED,
            "detail": {"members": members, "indexed": indexed},
        }
    )
    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_lep_v021_sha256": ACCEPTED_V021_SHA256,
        "accepted_lep_v02_sha256": ACCEPTED_V02_SHA256,
        "verified_zip": ACCEPTED_V021_ZIP,
        "members": members,
        "indexed": indexed,
        "not_traj_v01_member_counts": True,
        "prior_sha_before": before,
        "prior_sha_after": after,
        "prior_zips_immutable": before == after,
        "checks": checks,
        "ok": ok,
    }
