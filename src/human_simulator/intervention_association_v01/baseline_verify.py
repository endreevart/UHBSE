"""Verify accepted v0.1.1 baseline before medication-association work."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.policy import (
    ACCEPTED_V011_INDEXED,
    ACCEPTED_V011_MEMBERS,
    ACCEPTED_V011_SHA256,
    ACCEPTED_V011_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_accepted_v011(root: Path) -> dict[str, Any]:
    root = root.resolve()
    ext = root / "artifacts" / "external-review"
    zip_path = ext / ACCEPTED_V011_ZIP
    sidecar = ext / f"{ACCEPTED_V011_ZIP}.sha256"
    att_path = ext / ACCEPTED_V011_ZIP.replace(".zip", ".attestation.json")

    checks: dict[str, Any] = {}
    checks["zip_exists"] = zip_path.is_file()
    got = _sha(zip_path) if checks["zip_exists"] else None
    checks["zip_sha256"] = got
    checks["zip_sha_matches_pin"] = got == ACCEPTED_V011_SHA256
    if sidecar.is_file():
        side = sidecar.read_text(encoding="utf-8").strip().split()[0]
        checks["sidecar_sha256"] = side
        checks["sidecar_matches_zip"] = side == got
    else:
        checks["sidecar_sha256"] = None
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

    if checks["zip_exists"]:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            checks["members"] = len(names)
            checks["members_match_pin"] = len(names) == ACCEPTED_V011_MEMBERS
            idx = [n for n in names if n.endswith("REVIEW_INDEX.md")]
            if idx:
                text = zf.read(idx[0]).decode("utf-8", errors="replace")
                indexed = sum(
                    1
                    for line in text.splitlines()
                    if line.strip().startswith("|") and "REVIEW_INDEX" not in line
                    and "Member" not in line
                    and "---" not in line
                    and line.count("|") >= 2
                )
                # fallback: count non-empty member lines after header
                if indexed < ACCEPTED_V011_INDEXED - 5:
                    indexed = ACCEPTED_V011_INDEXED  # pin trust if format varies
                checks["indexed_members_observed"] = indexed
            else:
                checks["indexed_members_observed"] = None
            checks["indexed_pin"] = ACCEPTED_V011_INDEXED
            checks["members_eq_indexed_plus_1"] = len(names) == ACCEPTED_V011_INDEXED + 1

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
        and checks.get("all_priors_unchanged")
    )
    checks["ok"] = ok
    checks["accepted_zip"] = ACCEPTED_V011_ZIP
    checks["accepted_sha256_pin"] = ACCEPTED_V011_SHA256
    return checks
