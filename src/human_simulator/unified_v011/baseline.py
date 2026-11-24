"""Verify accepted Unified v0.1 + Core + SDR + roadmap hashes are unchanged."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.unified_v011.policy import (
    ACCEPTED_CORE_V0121_SHA256,
    ACCEPTED_CORE_V0121_ZIP,
    ACCEPTED_ROADMAP_V011_SHA256,
    ACCEPTED_ROADMAP_V011_ZIP,
    ACCEPTED_SDR_V0111_SHA256,
    ACCEPTED_SDR_V0111_ZIP,
    ACCEPTED_UNIFIED_V01_SHA256,
    ACCEPTED_UNIFIED_V01_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
    policy_snapshot,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_baselines(repo_root: Path) -> dict[str, Any]:
    """Read-only check: refuse if Unified v0.1 missing/mismatched or priors drift."""
    external = repo_root / "artifacts" / "external-review"
    result: dict[str, Any] = {
        "check_name": "unified_source_expansion_baselines_v0.1.1",
        "expected_unified_v01_sha256": ACCEPTED_UNIFIED_V01_SHA256,
        "expected_core_sha256": ACCEPTED_CORE_V0121_SHA256,
        "expected_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "expected_roadmap_v011_sha256": ACCEPTED_ROADMAP_V011_SHA256,
    }

    unified_zip = external / ACCEPTED_UNIFIED_V01_ZIP
    core_zip = external / ACCEPTED_CORE_V0121_ZIP
    sdr_zip = external / ACCEPTED_SDR_V0111_ZIP
    roadmap_zip = external / ACCEPTED_ROADMAP_V011_ZIP

    result["unified_v01_present"] = unified_zip.is_file()
    result["core_present"] = core_zip.is_file()
    result["sdr_v0111_present"] = sdr_zip.is_file()
    result["roadmap_v011_present"] = roadmap_zip.is_file()

    if not unified_zip.is_file():
        result["unified_v01_sha_matches"] = False
        result["ok"] = False
        result["refuse_reason"] = "Unified Source Expansion v0.1 ZIP missing; refuse DB mutation"
        result["policy"] = policy_snapshot()
        return result

    got_u = _sha256_file(unified_zip)
    result["computed_unified_v01_sha256"] = got_u
    result["unified_v01_sha_matches"] = got_u == ACCEPTED_UNIFIED_V01_SHA256
    if not result["unified_v01_sha_matches"]:
        result["ok"] = False
        result["refuse_reason"] = (
            "Unified Source Expansion v0.1 SHA mismatch; refuse DB mutation"
        )
        result["policy"] = policy_snapshot()
        return result

    with zipfile.ZipFile(unified_zip) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        result["unified_v01_zip_member_count"] = len(names)
        result["unified_v01_review_index_present"] = "REVIEW_INDEX.md" in names

    if core_zip.is_file():
        got = _sha256_file(core_zip)
        result["computed_core_sha256"] = got
        result["core_sha_matches"] = got == ACCEPTED_CORE_V0121_SHA256
        with zipfile.ZipFile(core_zip) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            result["core_zip_member_count"] = len(names)
            result["core_review_index_present"] = "REVIEW_INDEX.md" in names
    else:
        result["core_sha_matches"] = False

    if sdr_zip.is_file():
        got = _sha256_file(sdr_zip)
        result["computed_sdr_v0111_sha256"] = got
        result["sdr_v0111_untouched"] = got == ACCEPTED_SDR_V0111_SHA256
    else:
        result["sdr_v0111_untouched"] = False

    if roadmap_zip.is_file():
        got = _sha256_file(roadmap_zip)
        result["computed_roadmap_v011_sha256"] = got
        result["roadmap_v011_untouched"] = got == ACCEPTED_ROADMAP_V011_SHA256
    else:
        result["roadmap_v011_untouched"] = False

    att_path = external / "stage-03-core-vertical-slice-v0.1.2.1-review.attestation.json"
    result["core_attestation_present"] = att_path.is_file()
    att_ok = False
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        result["core_attestation_status"] = att.get("attestation_status")
        att_ok = att.get("attestation_status") == "PASS"

    u_att = external / "stage-03-unified-source-expansion-v0.1-review.attestation.json"
    result["unified_v01_attestation_present"] = u_att.is_file()

    priors: dict[str, Any] = {}
    all_priors_ok = True
    for label, (name, expected) in PRIOR_IMMUTABLE_ZIPS.items():
        p = external / name
        if not p.is_file():
            priors[label] = {"present": False, "untouched": False}
            all_priors_ok = False
            continue
        got = _sha256_file(p)
        ok = got == expected
        priors[label] = {"present": True, "sha256": got, "untouched": ok}
        if not ok:
            all_priors_ok = False
    result["prior_zips"] = priors

    result["ok"] = bool(
        result.get("unified_v01_sha_matches")
        and result.get("core_sha_matches")
        and result.get("sdr_v0111_untouched")
        and result.get("roadmap_v011_untouched")
        and att_ok
        and all_priors_ok
    )
    result["policy"] = policy_snapshot()
    result["security_stage_paused"] = True
    result["clinical_validation"] = "NOT_STARTED"
    return result
