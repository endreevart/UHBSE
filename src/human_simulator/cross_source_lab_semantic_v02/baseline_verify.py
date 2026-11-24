"""Baseline verification for lab semantic discovery v0.2."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v02.policy import (
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_PRIVACY_XS_SHA256,
    ACCEPTED_PRIVACY_XS_ZIP,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ACCEPTED_V011_INDEXED,
    ACCEPTED_V011_MEMBERS,
    ACCEPTED_V011_SHA256,
    ACCEPTED_V011_ZIP,
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

    z = external / ACCEPTED_V011_ZIP
    members = indexed = cache_n = None
    man_ok = tests_in = False
    if z.is_file():
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            indexed = members - (
                1 if any(n.endswith("REVIEW_INDEX.md") for n in names) else 0
            )
            cache_n = sum(1 for n in names if _CACHE_RE.search(n))
            art = (
                "artifacts/stage-03-cross-source-outcome-semantic-review-v0.1.1"
            )
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
                if name == "tests.json":
                    tests_in = True
                member = f"{art}/{name}"
                data = zf.read(member)
                if hashlib.sha256(data).hexdigest() != digest.strip():
                    mism.append(name)
            man_ok = not mism and tests_in
        add("members_557", members == ACCEPTED_V011_MEMBERS, members)
        add("indexed_556", indexed == ACCEPTED_V011_INDEXED, indexed)
        add("cache_zero", cache_n == 0, cache_n)
        add("manifest_ok", man_ok)
        add("tests_json_in_manifest", tests_in)
        side = external / f"{ACCEPTED_V011_ZIP}.sha256"
        add(
            "sidecar",
            side.is_file() and side.read_text().split()[0] == ACCEPTED_V011_SHA256,
        )
        att = external / ACCEPTED_V011_ZIP.replace(".zip", ".attestation.json")
        if att.is_file():
            a = json.loads(att.read_text(encoding="utf-8"))
            add("attestation_pass", a.get("attestation_status") == "PASS")

    after = {label: _sha(external / name) for label, (name, _) in priors.items()}
    add("prior_before_equals_after", before == after)

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "v011_members": members,
        "v011_indexed": indexed,
        "cache_members": cache_n,
        "prior_before": before,
        "prior_after": after,
        "checks": checks,
        "ok": ok,
    }
