"""Verify immutable Unified v0.1.2 + prior review ZIPs (fail closed)."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.unified_v0121.policy import (
    ACCEPTED_UNIFIED_V012_INDEXED,
    ACCEPTED_UNIFIED_V012_MEMBERS,
    ACCEPTED_UNIFIED_V012_SHA256,
    ACCEPTED_UNIFIED_V012_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
    policy_snapshot,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_baselines(repo_root: Path) -> dict[str, Any]:
    """Read-only baseline gate — refuse further work if v0.1.2 or priors drift."""
    external = repo_root / "artifacts" / "external-review"
    result: dict[str, Any] = {
        "check_name": "unified_source_expansion_baselines_v0.1.2.1",
        "expected_unified_v012_sha256": ACCEPTED_UNIFIED_V012_SHA256,
        "expected_unified_v012_members": ACCEPTED_UNIFIED_V012_MEMBERS,
        "expected_unified_v012_indexed": ACCEPTED_UNIFIED_V012_INDEXED,
        "baseline_verification_status": "FAIL",
    }

    v012 = external / ACCEPTED_UNIFIED_V012_ZIP
    result["unified_v012_present"] = v012.is_file()
    if not v012.is_file():
        result["ok"] = False
        result["refuse_reason"] = "Unified Source Expansion v0.1.2 ZIP missing; refuse"
        result["policy"] = policy_snapshot()
        return result

    got = _sha256_file(v012)
    result["computed_unified_v012_sha256"] = got
    result["unified_v012_sha_matches"] = got == ACCEPTED_UNIFIED_V012_SHA256
    if not result["unified_v012_sha_matches"]:
        result["ok"] = False
        result["refuse_reason"] = "Unified Source Expansion v0.1.2 SHA mismatch; refuse"
        result["policy"] = policy_snapshot()
        return result

    with zipfile.ZipFile(v012) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        result["unified_v012_zip_member_count"] = len(names)
        result["unified_v012_members_match"] = len(names) == ACCEPTED_UNIFIED_V012_MEMBERS
        result["unified_v012_review_index_present"] = "REVIEW_INDEX.md" in names
        if "REVIEW_INDEX.md" in names:
            idx = zf.read("REVIEW_INDEX.md").decode("utf-8", errors="replace")
            entry_count = sum(
                1
                for line in idx.splitlines()
                if line.startswith("| `") and "SHA-256" not in line and line.count("|") >= 3
            )
            result["unified_v012_review_index_entry_count"] = entry_count
            result["unified_v012_indexed_match"] = entry_count == ACCEPTED_UNIFIED_V012_INDEXED
            result["members_equals_indexed_plus_one"] = len(names) == entry_count + 1

    priors: dict[str, Any] = {}
    all_ok = bool(
        result.get("unified_v012_sha_matches")
        and result.get("unified_v012_members_match")
        and result.get("members_equals_indexed_plus_one")
    )
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
    result["ok"] = all_ok
    result["baseline_verification_status"] = "PASS" if all_ok else "FAIL"
    result["policy"] = policy_snapshot()
    result["security_stage_paused"] = True
    result["clinical_validation"] = "NOT_STARTED"
    result["refuse_if_exists_target"] = (
        "stage-03-unified-source-expansion-v0.1.2.1-review.zip"
    )
    return result


def before_after_hash_matrix(repo_root: Path) -> dict[str, Any]:
    """Record prior ZIP hashes for post-publish immutability proof."""
    external = repo_root / "artifacts" / "external-review"
    rows = []
    for label, (name, expected) in PRIOR_IMMUTABLE_ZIPS.items():
        p = external / name
        got = _sha256_file(p) if p.is_file() else None
        rows.append(
            {
                "label": label,
                "filename": name,
                "expected_sha256": expected,
                "computed_sha256": got,
                "matches": got == expected,
            }
        )
    return {
        "phase": "before_v0121_publish",
        "rows": rows,
        "all_match": all(r["matches"] for r in rows),
    }
