"""Baseline verification for v0.1.2.1.1 correction release."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.unified_v01211.policy import (
    ACCEPTED_UNIFIED_V0121_INDEXED,
    ACCEPTED_UNIFIED_V0121_MEMBERS,
    ACCEPTED_UNIFIED_V0121_SHA256,
    ACCEPTED_UNIFIED_V0121_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
    policy_snapshot,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_baselines(repo_root: Path) -> dict[str, Any]:
    """Recompute all accepted baseline ZIP hashes (never trust prompt values)."""
    external = repo_root / "artifacts" / "external-review"
    result: dict[str, Any] = {
        "check_name": "unified_source_expansion_v0.1.2.1.1_baseline",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "primary_baseline": "unified_v0.1.2.1",
        "expected_unified_v0121_sha256": ACCEPTED_UNIFIED_V0121_SHA256,
        "expected_unified_v0121_members": ACCEPTED_UNIFIED_V0121_MEMBERS,
        "expected_unified_v0121_indexed": ACCEPTED_UNIFIED_V0121_INDEXED,
        "baseline_verification_status": "FAIL",
        "ok": False,
    }

    baselines: dict[str, Any] = {}
    all_ok = True
    for label, (name, expected) in PRIOR_IMMUTABLE_ZIPS.items():
        p = external / name
        entry: dict[str, Any] = {"filename": name, "present": p.is_file()}
        if not p.is_file():
            entry["ok"] = False
            all_ok = False
            baselines[label] = entry
            continue
        got = _sha256_file(p)
        entry["computed_sha256"] = got
        entry["expected_sha256"] = expected
        entry["sha_matches"] = got == expected
        if not entry["sha_matches"]:
            all_ok = False
        side = external / f"{name}.sha256"
        if side.is_file():
            side_sha = side.read_text(encoding="utf-8").split()[0]
            entry["sidecar_sha256"] = side_sha
            entry["sidecar_matches_zip"] = side_sha == got
            if not entry["sidecar_matches_zip"]:
                all_ok = False
        att = external / name.replace(".zip", ".attestation.json")
        if att.is_file():
            att_doc = json.loads(att.read_text(encoding="utf-8"))
            entry["attestation_status"] = att_doc.get("attestation_status")
            entry["attestation_zip_sha256"] = att_doc.get("review_zip_sha256")
            entry["attestation_sha_matches"] = att_doc.get("review_zip_sha256") == got
        baselines[label] = entry

    v0121 = external / ACCEPTED_UNIFIED_V0121_ZIP
    structure: dict[str, Any] = {}
    if v0121.is_file():
        with zipfile.ZipFile(v0121) as zf:
            members = [n for n in zf.namelist() if not n.endswith("/")]
            structure["members"] = len(members)
            structure["review_index_present"] = "REVIEW_INDEX.md" in members
            structure["zip_integrity"] = "PASS"
            if "REVIEW_INDEX.md" in members:
                idx = zf.read("REVIEW_INDEX.md").decode("utf-8", errors="replace")
                indexed_paths: list[str] = []
                for line in idx.splitlines():
                    if line.startswith("| `"):
                        m = re.search(r"`([^`]+)`", line)
                        if m and "SHA-256" not in line and line.count("|") >= 3:
                            indexed_paths.append(m.group(1))
                structure["indexed"] = len(indexed_paths)
                structure["review_index_in_indexed_paths"] = "REVIEW_INDEX.md" in indexed_paths
                structure["members_equals_indexed_plus_one"] = (
                    len(members) == len(indexed_paths) + 1
                )
            # sample sidecar frozen model defect confirmation
            fm = next((n for n in members if n.endswith("frozen-source-a-model.json")), None)
            fm_side = next(
                (n for n in members if n.endswith("frozen-source-a-model.json.sha256")), None
            )
            if fm and fm_side:
                file_sha = hashlib.sha256(zf.read(fm)).hexdigest()
                side_sha = zf.read(fm_side).decode().split()[0]
                structure["frozen_model_file_sha256"] = file_sha
                structure["frozen_model_sidecar_sha256"] = side_sha
                structure["frozen_sidecar_is_file_sha"] = file_sha == side_sha
                structure["confirmed_defect_file_vs_identity_hash"] = file_sha != side_sha

    target = external / "stage-03-unified-source-expansion-v0.1.2.1.1-review.zip"
    target_exists = target.exists()

    struct_ok = (
        structure.get("members") == ACCEPTED_UNIFIED_V0121_MEMBERS
        and structure.get("indexed") == ACCEPTED_UNIFIED_V0121_INDEXED
        and structure.get("members_equals_indexed_plus_one") is True
        and structure.get("review_index_in_indexed_paths") is False
        and baselines.get("unified_v0.1.2.1", {}).get("attestation_status") == "PASS"
        and baselines.get("unified_v0.1.2.1", {}).get("sha_matches") is True
    )
    ok = all_ok and struct_ok and not target_exists
    result.update(
        {
            "baselines": baselines,
            "v0121_structure": structure,
            "immutable_baseline_before_hashes": {
                k: v.get("computed_sha256") for k, v in baselines.items()
            },
            "target_v01211_zip_exists": target_exists,
            "ok": ok,
            "baseline_verification_status": "PASS" if ok else "FAIL",
            "policy": policy_snapshot(),
            "refuse_if_exists_target": "stage-03-unified-source-expansion-v0.1.2.1.1-review.zip",
        }
    )
    return result


def before_after_hash_matrix(repo_root: Path) -> dict[str, Any]:
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
        "phase": "before_v01211_publish",
        "rows": rows,
        "all_match": all(r["matches"] for r in rows),
    }
