"""Baseline verification — immutable lab semantic v0.2.1."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import (
    reconcile_review_index,
    verify_manifest,
)
from human_simulator.cross_source_lab_semantic_v0211.policy import (
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
    ACCEPTED_V021_ARTIFACT_DIR,
    ACCEPTED_V021_INDEXED,
    ACCEPTED_V021_MEMBERS,
    ACCEPTED_V021_SHA256,
    ACCEPTED_V021_ZIP,
    VERSION,
)

_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    priors = {
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
        add(f"{label}_sha", dig == exp, dig)

    z = external / ACCEPTED_V021_ZIP
    members = indexed = cache_n = None
    man_ok = tests_in = False
    recon_ok = False
    mut_ok = False
    if z.is_file():
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            cache_n = sum(1 for n in names if _CACHE_RE.search(n))
            idx_text = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx_text, payloads_on_disk=payloads)
            recon_ok = bool(recon.get("ok"))
            indexed = recon.get("indexed_members")
            add("review_index_recon", recon_ok, recon)
            art = ACCEPTED_V021_ARTIFACT_DIR
            man = zf.read(f"{art}/evidence-manifest.sha256").decode()
            mism: list[str] = []
            for line in man.splitlines():
                line = line.strip()
                if not line:
                    continue
                digest, _, name = line.partition("  ")
                if not name:
                    digest, _, name = line.partition(" ")
                name = name.strip()
                if name == "tests.json":
                    tests_in = True
                data = zf.read(f"{art}/{name}")
                if hashlib.sha256(data).hexdigest() != digest.strip():
                    mism.append(name)
            man_ok = not mism and tests_in

            # mutation proof on extracted art
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                art_path = Path(tmp) / art
                from human_simulator.cross_source_lab_semantic_v021.publish import (
                    mutation_proof,
                )

                mut = mutation_proof(art_path)
                mut_ok = bool(mut.get("ok"))
                add("mutation_proof", mut_ok, mut)

        add("members_590", members == ACCEPTED_V021_MEMBERS, members)
        add("indexed_589", indexed == ACCEPTED_V021_INDEXED, indexed)
        add("cache_zero", cache_n == 0, cache_n)
        add("manifest_ok", man_ok)
        add("tests_json_in_manifest", tests_in)
        side = external / f"{ACCEPTED_V021_ZIP}.sha256"
        add(
            "sidecar",
            side.is_file() and side.read_text().split()[0] == ACCEPTED_V021_SHA256,
        )
        att = external / ACCEPTED_V021_ZIP.replace(".zip", ".attestation.json")
        if att.is_file():
            a = json.loads(att.read_text(encoding="utf-8"))
            add("attestation_pass", a.get("attestation_status") == "PASS")
            add("attestation_sha", a.get("sha256") == ACCEPTED_V021_SHA256)

    after = {label: _sha(external / name) for label, (name, _) in priors.items()}
    add("prior_before_equals_after", before == after)

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "v021_members": members,
        "v021_indexed": indexed,
        "cache_members": cache_n,
        "prior_before": before,
        "prior_after": after,
        "checks": checks,
        "ok": ok,
    }
