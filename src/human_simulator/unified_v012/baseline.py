"""Verify immutable prior review ZIPs for Unified Source Expansion v0.1.2."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.unified_v012.policy import (
    ACCEPTED_UNIFIED_V011_INDEX_ROWS,
    ACCEPTED_UNIFIED_V011_MEMBERS,
    ACCEPTED_UNIFIED_V011_SHA256,
    ACCEPTED_UNIFIED_V011_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
    policy_snapshot,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_baselines(repo_root: Path) -> dict[str, Any]:
    """Read-only: refuse DB mutation if Unified v0.1.1 or priors drift."""
    external = repo_root / "artifacts" / "external-review"
    result: dict[str, Any] = {
        "check_name": "unified_source_expansion_baselines_v0.1.2",
        "expected_unified_v011_sha256": ACCEPTED_UNIFIED_V011_SHA256,
        "expected_unified_v011_members": ACCEPTED_UNIFIED_V011_MEMBERS,
        "expected_unified_v011_index_rows": ACCEPTED_UNIFIED_V011_INDEX_ROWS,
    }

    v011 = external / ACCEPTED_UNIFIED_V011_ZIP
    result["unified_v011_present"] = v011.is_file()
    if not v011.is_file():
        result["ok"] = False
        result["refuse_reason"] = "Unified Source Expansion v0.1.1 ZIP missing; refuse DB mutation"
        result["policy"] = policy_snapshot()
        return result

    got = _sha256_file(v011)
    result["computed_unified_v011_sha256"] = got
    result["unified_v011_sha_matches"] = got == ACCEPTED_UNIFIED_V011_SHA256
    if not result["unified_v011_sha_matches"]:
        result["ok"] = False
        result["refuse_reason"] = "Unified Source Expansion v0.1.1 SHA mismatch; refuse DB mutation"
        result["policy"] = policy_snapshot()
        return result

    with zipfile.ZipFile(v011) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        result["unified_v011_zip_member_count"] = len(names)
        result["unified_v011_review_index_present"] = "REVIEW_INDEX.md" in names
        if "REVIEW_INDEX.md" in names:
            idx = zf.read("REVIEW_INDEX.md").decode("utf-8", errors="replace")
            # Count table rows that look like `| `path` | `sha` |`
            entry_count = sum(
                1
                for line in idx.splitlines()
                if line.startswith("| `") and "SHA-256" not in line and line.count("|") >= 3
            )
            result["unified_v011_review_index_entry_count"] = entry_count
            result["unified_v011_attestation_indexed_members_defect"] = (
                ACCEPTED_UNIFIED_V011_MEMBERS == entry_count + 1
                and entry_count == ACCEPTED_UNIFIED_V011_INDEX_ROWS
            )

    att = external / "stage-03-unified-source-expansion-v0.1.1-review.attestation.json"
    result["unified_v011_attestation_present"] = att.is_file()
    if att.is_file():
        doc = json.loads(att.read_text(encoding="utf-8"))
        result["unified_v011_attestation_members"] = doc.get("members")
        result["unified_v011_attestation_indexed_members"] = doc.get("indexed_members")
        result["unified_v011_indexed_copied_from_members"] = doc.get("members") == doc.get(
            "indexed_members"
        )

    priors: dict[str, Any] = {}
    all_ok = True
    for label, (name, expected) in PRIOR_IMMUTABLE_ZIPS.items():
        p = external / name
        if not p.is_file():
            priors[label] = {"present": False, "untouched": False}
            all_ok = False
            continue
        got_p = _sha256_file(p)
        ok = got_p == expected
        priors[label] = {"present": True, "sha256": got_p, "untouched": ok}
        if not ok:
            all_ok = False
    result["prior_zips"] = priors
    result["ok"] = bool(result.get("unified_v011_sha_matches") and all_ok)
    result["policy"] = policy_snapshot()
    result["security_stage_paused"] = True
    result["clinical_validation"] = "NOT_STARTED"
    return result
