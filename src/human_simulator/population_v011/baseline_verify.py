"""Verify accepted v0.1 baseline before v0.1.1 work."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.population_v011.policy import (
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

    checks: dict[str, Any] = {}
    checks["zip_exists"] = zip_path.is_file()
    got = _sha(zip_path) if zip_path.is_file() else None
    checks["zip_sha256"] = got
    checks["zip_sha_matches_expected"] = got == ACCEPTED_V01_SHA256
    if sidecar.is_file():
        checks["sidecar_matches_zip"] = sidecar.read_text().split()[0] == got
    else:
        checks["sidecar_matches_zip"] = False

    if att_path.is_file():
        att = json.loads(att_path.read_text())
        checks["attestation_status"] = att.get("attestation_status")
        checks["attestation_sha_matches"] = att.get("review_zip_sha256") == got
        checks["attestation_members"] = att.get("members")
        checks["attestation_indexed"] = att.get("indexed_members")
    else:
        checks["attestation_status"] = None
        checks["attestation_sha_matches"] = False

    members_ok = False
    index_ok = False
    indexed_count = None
    internal_manifest_ok = False
    if zip_path.is_file():
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members_ok = len(names) == ACCEPTED_V01_MEMBERS and len(names) == len(set(names))
            checks["zip_member_count"] = len(names)
            checks["zip_members_unique"] = len(names) == len(set(names))
            index_ok = "REVIEW_INDEX.md" in names
            if index_ok:
                idx = zf.read("REVIEW_INDEX.md").decode()
                # count table rows with backticks paths
                indexed_count = sum(
                    1 for line in idx.splitlines() if line.startswith("| `") and "SHA-256" not in line
                )
                # header + separator don't count; paths look like | `path` | `sha` |
                indexed_count = sum(
                    1
                    for line in idx.splitlines()
                    if line.startswith("| `") and "|------" not in line and "Path" not in line
                )
            checks["indexed_member_count"] = indexed_count
            checks["indexed_matches_expected"] = indexed_count == ACCEPTED_V01_INDEXED

            man_names = [n for n in names if n.endswith("evidence-manifest.sha256")]
            mismatches = []
            if man_names:
                man_text = zf.read(man_names[0]).decode()
                base = Path(man_names[0]).parent.as_posix()
                for line in man_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    digest, _, name = line.partition("  ")
                    if not name:
                        digest, _, name = line.partition(" ")
                    name = name.strip()
                    candidates = [f"{base}/{name}" if base != "." else name, name]
                    found = next((c for c in candidates if c in names), None)
                    if not found:
                        bn = Path(name).name
                        hits = [n for n in names if n.endswith("/" + bn) or n == bn]
                        found = hits[0] if hits else None
                    if not found:
                        mismatches.append(name)
                        continue
                    if hashlib.sha256(zf.read(found)).hexdigest() != digest.strip():
                        mismatches.append(name)
                internal_manifest_ok = not mismatches
            checks["internal_manifest_mismatches"] = mismatches[:20]
            checks["internal_manifest_ok"] = internal_manifest_ok

    checks["members_ok"] = members_ok
    checks["review_index_present"] = index_ok

    prior_rows = []
    for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items():
        p = ext / name
        g = _sha(p) if p.is_file() else None
        prior_rows.append(
            {"label": label, "filename": name, "expected": exp, "got": g, "matches": g == exp}
        )
    checks["prior_immutable"] = prior_rows
    checks["prior_all_match"] = all(r["matches"] for r in prior_rows)

    ok = all(
        [
            checks["zip_sha_matches_expected"],
            checks["sidecar_matches_zip"],
            checks.get("attestation_status") == "PASS",
            checks["attestation_sha_matches"],
            checks["members_ok"],
            checks.get("indexed_matches_expected"),
            checks["review_index_present"],
            checks["internal_manifest_ok"],
            checks["prior_all_match"],
        ]
    )
    return {
        "baseline_verification_status": "PASS" if ok else "FAIL",
        "ok": ok,
        "checks": checks,
        "accepted_zip": ACCEPTED_V01_ZIP,
        "accepted_sha256": ACCEPTED_V01_SHA256,
        "expected_members": ACCEPTED_V01_MEMBERS,
        "expected_indexed": ACCEPTED_V01_INDEXED,
    }
