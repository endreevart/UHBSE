"""Baseline verification — v0.3 + v0.2.1.1 immutable priors."""

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
from human_simulator.unified_research_layer_v031.policy import (
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
    ACCEPTED_V0211_ARTIFACT_DIR,
    ACCEPTED_V0211_INDEXED,
    ACCEPTED_V0211_MEMBERS,
    ACCEPTED_V0211_SHA256,
    ACCEPTED_V0211_ZIP,
    ACCEPTED_V03_ARTIFACT_DIR,
    ACCEPTED_V03_INDEXED,
    ACCEPTED_V03_MEMBERS,
    ACCEPTED_V03_SHA256,
    ACCEPTED_V03_ZIP,
    VERSION,
)

_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _verify_zip(
    *,
    external: Path,
    zip_name: str,
    exp_sha: str,
    exp_members: int | None,
    exp_indexed: int | None,
    artifact_dir: str | None,
    label: str,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    z = external / zip_name
    dig = _sha(z) if z.is_file() else None
    checks.append({"name": f"{label}_sha", "ok": dig == exp_sha, "detail": dig})
    members = indexed = cache_n = None
    mut_ok = True
    if z.is_file():
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            cache_n = sum(1 for n in names if _CACHE_RE.search(n))
            idx = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
            indexed = recon.get("indexed_members")
            checks.append({"name": f"{label}_review_index", "ok": bool(recon.get("ok")), "detail": recon})
            if exp_members is not None:
                checks.append(
                    {
                        "name": f"{label}_members",
                        "ok": members == exp_members,
                        "detail": members,
                    }
                )
            if exp_indexed is not None:
                checks.append(
                    {
                        "name": f"{label}_indexed",
                        "ok": indexed == exp_indexed,
                        "detail": indexed,
                    }
                )
            if artifact_dir:
                man = zf.read(f"{artifact_dir}/evidence-manifest.sha256").decode()
                mism = []
                for line in man.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    digest, _, name = line.partition("  ")
                    if not name:
                        digest, _, name = line.partition(" ")
                    name = name.strip()
                    data = zf.read(f"{artifact_dir}/{name}")
                    if hashlib.sha256(data).hexdigest() != digest.strip():
                        mism.append(name)
                checks.append({"name": f"{label}_manifest", "ok": not mism, "detail": mism[:10]})
                with tempfile.TemporaryDirectory() as tmp:
                    zf.extractall(tmp)
                    mut = mutation_proof(Path(tmp) / artifact_dir)
                    mut_ok = bool(mut.get("ok"))
                    checks.append({"name": f"{label}_mutation", "ok": mut_ok, "detail": mut})
    return {
        "label": label,
        "sha256": dig,
        "members": members,
        "indexed": indexed,
        "cache_entries": cache_n,
        "checks": checks,
        "ok": all(c["ok"] for c in checks),
    }


def verify_baseline(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    priors = {
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
    checks: list[dict[str, Any]] = []
    for label, (name, exp) in priors.items():
        p = external / name
        dig = _sha(p) if p.is_file() else None
        before[label] = dig or ""
        checks.append({"name": f"{label}_sha_before", "ok": dig == exp, "detail": dig})

    v03 = _verify_zip(
        external=external,
        zip_name=ACCEPTED_V03_ZIP,
        exp_sha=ACCEPTED_V03_SHA256,
        exp_members=ACCEPTED_V03_MEMBERS,
        exp_indexed=ACCEPTED_V03_INDEXED,
        artifact_dir=ACCEPTED_V03_ARTIFACT_DIR,
        label="v03",
    )
    v0211 = _verify_zip(
        external=external,
        zip_name=ACCEPTED_V0211_ZIP,
        exp_sha=ACCEPTED_V0211_SHA256,
        exp_members=ACCEPTED_V0211_MEMBERS,
        exp_indexed=ACCEPTED_V0211_INDEXED,
        artifact_dir=ACCEPTED_V0211_ARTIFACT_DIR,
        label="v0211",
    )
    checks.extend(v03["checks"])
    checks.extend(v0211["checks"])

    # attestation presence for v0.3
    att = external / ACCEPTED_V03_ZIP.replace(".zip", ".attestation.json")
    att_ok = False
    if att.is_file():
        try:
            doc = json.loads(att.read_text(encoding="utf-8"))
            att_ok = doc.get("status") == "PASS" or doc.get("ok") is True or "PASS" in str(doc)
        except json.JSONDecodeError:
            att_ok = False
    checks.append({"name": "v03_attestation", "ok": att_ok, "detail": att.name if att.is_file() else None})

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "prior_sha_before": before,
        "prior_sha_after": before,  # filled again at publish
        "v03": v03,
        "v0211": v0211,
        "checks": checks,
        "ok": ok,
    }
