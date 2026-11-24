"""Verify accepted medication-association v0.1 baseline."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v011.policy import (
    ACCEPTED_V01_INDEXED,
    ACCEPTED_V01_MEMBERS,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_accepted_v01(root: Path) -> dict[str, Any]:
    root = root.resolve()
    ext = root / "artifacts" / "external-review"
    zip_path = ext / ACCEPTED_V01_ZIP
    sidecar = ext / f"{ACCEPTED_V01_ZIP}.sha256"
    att_path = ext / ACCEPTED_V01_ZIP.replace(".zip", ".attestation.json")

    checks: dict[str, Any] = {
        "accepted_zip": ACCEPTED_V01_ZIP,
        "accepted_sha256_pin": ACCEPTED_V01_SHA256,
    }
    checks["zip_exists"] = zip_path.is_file()
    got = _sha(zip_path) if checks["zip_exists"] else None
    checks["zip_sha256"] = got
    checks["zip_sha_matches_pin"] = got == ACCEPTED_V01_SHA256
    if sidecar.is_file():
        side = sidecar.read_text(encoding="utf-8").strip().split()[0]
        checks["sidecar_matches_zip"] = side == got
    else:
        checks["sidecar_matches_zip"] = False

    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        checks["attestation_status"] = att.get("attestation_status")
        checks["attestation_sha_matches"] = att.get("review_zip_sha256") == got
        checks["attestation_members"] = att.get("members")
        checks["attestation_indexed"] = att.get("indexed_members")
    else:
        checks["attestation_status"] = None
        checks["attestation_sha_matches"] = False

    review_mm: list[str] = []
    man_mm: list[str] = []
    if checks["zip_exists"]:
        with zipfile.ZipFile(zip_path) as zf:
            members = [n for n in zf.namelist() if not n.endswith("/")]
            checks["members"] = len(members)
            checks["unique_members"] = len(set(members))
            checks["no_duplicates"] = len(members) == len(set(members))
            checks["members_match_pin"] = len(members) == ACCEPTED_V01_MEMBERS
            checks["members_eq_indexed_plus_1"] = len(members) == ACCEPTED_V01_INDEXED + 1
            idx = zf.read("REVIEW_INDEX.md").decode("utf-8")
            for line in idx.splitlines():
                if not line.startswith("| `"):
                    continue
                parts = [p.strip() for p in line.strip("|").split("|")]
                if len(parts) < 2:
                    continue
                name = parts[0].strip("`")
                expect = parts[1].strip("`")
                if len(expect) != 64:
                    continue
                if hashlib.sha256(zf.read(name)).hexdigest() != expect:
                    review_mm.append(name)
            art_prefix = (
                "artifacts/stage-03-first-medication-association-baseline-v0.1/"
            )
            man = zf.read(art_prefix + "evidence-manifest.sha256").decode()
            for line in man.splitlines():
                if not line.strip():
                    continue
                digest, _, name = line.partition("  ")
                if not name:
                    digest, _, name = line.partition(" ")
                path = art_prefix + name.strip()
                if hashlib.sha256(zf.read(path)).hexdigest() != digest.strip():
                    man_mm.append(name.strip())
            st = json.loads(zf.read(art_prefix + "status-contract.json"))
            checks["internal_publication_integrity_status"] = st.get(
                "PUBLICATION_INTEGRITY_STATUS"
            )
            checks["internal_vs_external_lifecycle_note"] = (
                "v0.1 internal status-contract had PENDING while external attestation PASS; "
                "v0.1.1 separates pre-pack vs post-pack fields."
            )

    checks["review_index_hash_mismatches"] = review_mm
    checks["evidence_manifest_mismatches"] = man_mm
    checks["review_index_ok"] = len(review_mm) == 0
    checks["evidence_manifest_ok"] = len(man_mm) == 0

    prior: dict[str, Any] = {}
    for label, (name, pin) in PRIOR_IMMUTABLE_ZIPS.items():
        p = ext / name
        if not p.is_file():
            prior[label] = {"exists": False, "unchanged": False}
            continue
        h = _sha(p)
        prior[label] = {"exists": True, "sha256": h, "unchanged": h == pin}
    checks["prior_immutable_zips"] = prior
    checks["all_priors_unchanged"] = all(v.get("unchanged") for v in prior.values())

    ok = bool(
        checks.get("zip_sha_matches_pin")
        and checks.get("sidecar_matches_zip")
        and checks.get("attestation_sha_matches")
        and checks.get("members_match_pin")
        and checks.get("no_duplicates")
        and checks.get("review_index_ok")
        and checks.get("evidence_manifest_ok")
        and checks.get("all_priors_unchanged")
    )
    checks["ok"] = ok
    checks["BASELINE_VERIFICATION_STATUS"] = "PASS" if ok else "FAIL"
    return checks
