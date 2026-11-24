"""Baseline verification — immutable v0.3.1 accepted bundle."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import (
    mutation_proof,
    reconcile_review_index,
)
from human_simulator.unified_individual_state_v01.policy import (
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_PRIVACY_XS_SHA256,
    ACCEPTED_PRIVACY_XS_ZIP,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ACCEPTED_V011_SHA256,
    ACCEPTED_V011_ZIP,
    ACCEPTED_V02_SHA256,
    ACCEPTED_V02_ZIP,
    ACCEPTED_V021_SHA256,
    ACCEPTED_V021_ZIP,
    ACCEPTED_V0211_SHA256,
    ACCEPTED_V0211_ZIP,
    ACCEPTED_V03_SHA256,
    ACCEPTED_V03_ZIP,
    ACCEPTED_V031_ARTIFACT_DIR,
    ACCEPTED_V031_INDEXED,
    ACCEPTED_V031_MEMBERS,
    ACCEPTED_V031_SHA256,
    ACCEPTED_V031_ZIP,
    VERSION,
)

_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []
    priors = {
        "v031": (ACCEPTED_V031_ZIP, ACCEPTED_V031_SHA256),
        "v03": (ACCEPTED_V03_ZIP, ACCEPTED_V03_SHA256),
        "v0211": (ACCEPTED_V0211_ZIP, ACCEPTED_V0211_SHA256),
        "v021": (ACCEPTED_V021_ZIP, ACCEPTED_V021_SHA256),
        "v02": (ACCEPTED_V02_ZIP, ACCEPTED_V02_SHA256),
        "v011": (ACCEPTED_V011_ZIP, ACCEPTED_V011_SHA256),
        "v01": (ACCEPTED_V01_ZIP, ACCEPTED_V01_SHA256),
        "privacy": (ACCEPTED_PRIVACY_XS_ZIP, ACCEPTED_PRIVACY_XS_SHA256),
        "gs011": (ACCEPTED_GS011_ZIP, ACCEPTED_GS011_SHA256),
    }
    before: dict[str, str] = {}
    for label, (name, exp) in priors.items():
        p = external / name
        dig = _sha(p) if p.is_file() else None
        before[label] = dig or ""
        checks.append({"name": f"{label}_sha", "ok": dig == exp, "detail": dig})

    z = external / ACCEPTED_V031_ZIP
    members = indexed = None
    parquet_in_zip = []
    mut_ok = False
    att_ok = False
    sidecar_ok = False
    if z.is_file():
        sidecar = external / f"{ACCEPTED_V031_ZIP}.sha256"
        if sidecar.is_file():
            sc = sidecar.read_text(encoding="utf-8").split()[0]
            sidecar_ok = sc == ACCEPTED_V031_SHA256
        checks.append({"name": "sidecar", "ok": sidecar_ok})
        att = external / ACCEPTED_V031_ZIP.replace(".zip", ".attestation.json")
        if att.is_file():
            doc = json.loads(att.read_text(encoding="utf-8"))
            att_ok = doc.get("status") == "PASS" or doc.get("ok") is True
        checks.append({"name": "attestation", "ok": att_ok})

        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            parquet_in_zip = [n for n in names if n.endswith(".parquet")]
            cache_n = sum(1 for n in names if _CACHE_RE.search(n))
            checks.append({"name": "members", "ok": members == ACCEPTED_V031_MEMBERS, "detail": members})
            checks.append({"name": "no_parquet", "ok": not parquet_in_zip, "detail": parquet_in_zip[:5]})
            checks.append({"name": "no_cache", "ok": cache_n == 0, "detail": cache_n})
            idx = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
            indexed = recon.get("indexed_members")
            checks.append(
                {
                    "name": "indexed",
                    "ok": indexed == ACCEPTED_V031_INDEXED and bool(recon.get("ok")),
                    "detail": indexed,
                }
            )
            art = ACCEPTED_V031_ARTIFACT_DIR
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
            checks.append({"name": "manifest", "ok": not mism, "detail": mism[:10]})
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                mut = mutation_proof(Path(tmp) / art)
                mut_ok = bool(mut.get("ok"))
                checks.append({"name": "mutation", "ok": mut_ok, "detail": mut})

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_v031_sha256": ACCEPTED_V031_SHA256,
        "members": members,
        "indexed": indexed,
        "prior_sha_before": before,
        "checks": checks,
        "ok": ok,
    }
