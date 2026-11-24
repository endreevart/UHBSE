"""Reproduce v0.1 publication defects (immutable baseline)."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v011.policy import (
    ACCEPTED_PRIVACY_XS_INDEXED,
    ACCEPTED_PRIVACY_XS_MEMBERS,
    ACCEPTED_PRIVACY_XS_SHA256,
    ACCEPTED_PRIVACY_XS_ZIP,
    ACCEPTED_V01_ARTIFACT_DIR,
    ACCEPTED_V01_INDEXED,
    ACCEPTED_V01_MEMBERS,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    VERSION,
)

_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")


def _sha(p: Path | bytes) -> str:
    if isinstance(p, bytes):
        return hashlib.sha256(p).hexdigest()
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_zip_manifest(zf: zipfile.ZipFile, art_prefix: str) -> dict[str, Any]:
    man_name = f"{art_prefix}/evidence-manifest.sha256"
    man = zf.read(man_name).decode("utf-8")
    mismatches: list[str] = []
    checked = 0
    expected_tests = actual_tests = None
    for line in man.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        name = name.strip()
        member = f"{art_prefix}/{name}"
        if member not in zf.namelist():
            mismatches.append(f"missing:{name}")
            continue
        data = zf.read(member)
        checked += 1
        got = _sha(data)
        if got != digest.strip():
            mismatches.append(name)
        if name == "tests.json":
            expected_tests = digest.strip()
            actual_tests = got
    return {
        "ok": not mismatches,
        "checked": checked,
        "mismatches": mismatches,
        "expected_tests_json_sha256": expected_tests,
        "actual_tests_json_sha256": actual_tests,
        "tests_json_match": expected_tests == actual_tests and expected_tests is not None,
    }


def reproduce_v01_defects(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    zpath = external / ACCEPTED_V01_ZIP
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    digest = _sha(zpath) if zpath.is_file() else None
    add("v01_zip_present", zpath.is_file())
    add("v01_sha256", digest == ACCEPTED_V01_SHA256, digest)

    members = indexed = None
    cache_n = pytest_n = pycache_n = pyc_n = 0
    man = None
    att_pass_despite_fail = False
    if zpath.is_file():
        with zipfile.ZipFile(zpath) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            indexed = members - (
                1 if any(n.endswith("REVIEW_INDEX.md") for n in names) else 0
            )
            cache = [n for n in names if _CACHE_RE.search(n)]
            cache_n = len(cache)
            pytest_n = sum(1 for n in cache if ".pytest_cache" in n)
            pycache_n = sum(1 for n in cache if "__pycache__" in n)
            pyc_n = sum(1 for n in cache if n.endswith(".pyc"))
            man = verify_zip_manifest(zf, ACCEPTED_V01_ARTIFACT_DIR)

        add("members_600", members == ACCEPTED_V01_MEMBERS, members)
        add("indexed_599", indexed == ACCEPTED_V01_INDEXED, indexed)
        add("evidence_manifest_fail_for_tests_json", man and not man["tests_json_match"], man)
        add("cache_members_present", cache_n > 0, cache_n)

        att = external / ACCEPTED_V01_ZIP.replace(".zip", ".attestation.json")
        if att.is_file():
            a = json.loads(att.read_text(encoding="utf-8"))
            att_pass_despite_fail = (
                a.get("attestation_status") == "PASS" and man is not None and not man["ok"]
            )
            add(
                "attestation_pass_despite_manifest_fail",
                att_pass_despite_fail,
                {
                    "attestation_status": a.get("attestation_status"),
                    "manifest_ok": man["ok"] if man else None,
                },
            )

    # Privacy 540/539 is a different ZIP
    pz = external / ACCEPTED_PRIVACY_XS_ZIP
    privacy_sha = _sha(pz) if pz.is_file() else None
    privacy_members = None
    if pz.is_file():
        with zipfile.ZipFile(pz) as zf:
            privacy_members = len([n for n in zf.namelist() if not n.endswith("/")])
    add("privacy_sha_unchanged", privacy_sha == ACCEPTED_PRIVACY_XS_SHA256, privacy_sha)
    add(
        "privacy_540_539_is_not_semantic_review_zip",
        privacy_members == ACCEPTED_PRIVACY_XS_MEMBERS
        and members == ACCEPTED_V01_MEMBERS
        and privacy_members != members,
        {
            "privacy_members": privacy_members,
            "privacy_indexed": ACCEPTED_PRIVACY_XS_INDEXED,
            "semantic_v01_members": members,
            "semantic_v01_indexed": indexed,
        },
    )

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "V01_PUBLICATION_DEFECT_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "v01_sha256": digest,
        "v01_members": members,
        "v01_indexed": indexed,
        "expected_tests_json_sha256": (man or {}).get("expected_tests_json_sha256"),
        "actual_tests_json_sha256": (man or {}).get("actual_tests_json_sha256"),
        "manifest_mismatches": (man or {}).get("mismatches"),
        "cache_member_count": cache_n,
        "pytest_cache_members": pytest_n,
        "pycache_members": pycache_n,
        "pyc_members": pyc_n,
        "attestation_pass_despite_manifest_fail": att_pass_despite_fail,
        "privacy_baseline_sha256": privacy_sha,
        "privacy_members_indexed": {
            "members": privacy_members,
            "indexed": ACCEPTED_PRIVACY_XS_INDEXED,
        },
        "note": (
            "540/539 is the privacy-cross-source baseline ZIP, "
            "not the semantic-review v0.1 ZIP (600/599)."
        ),
        "checks": checks,
        "ok": ok,
    }
