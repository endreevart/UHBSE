"""Read-only baseline verification for Scientific Data Readiness v0.1.1."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.scientific.policy import (
    ACCEPTED_CORE_V0121_SHA256,
    ACCEPTED_CORE_V0121_ZIP,
    ACCEPTED_SDR_V01_SHA256,
    ACCEPTED_SDR_V01_ZIP,
    ACCEPTED_SDR_V011_SHA256,
    ACCEPTED_SDR_V011_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
    policy_snapshot,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_core_baseline(repo_root: Path) -> dict[str, Any]:
    """Verify accepted core v0.1.2.1 and SDR v0.1 ZIPs; never restore or republish."""
    external = repo_root / "artifacts" / "external-review"
    zip_path = external / ACCEPTED_CORE_V0121_ZIP
    sidecar = external / f"{ACCEPTED_CORE_V0121_ZIP}.sha256"
    att_path = external / "stage-03-core-vertical-slice-v0.1.2.1-review.attestation.json"
    result: dict[str, Any] = {
        "check_name": "accepted_baselines_v011",
        "expected_core_sha256": ACCEPTED_CORE_V0121_SHA256,
        "expected_sdr_v01_sha256": ACCEPTED_SDR_V01_SHA256,
        "zip_present": zip_path.is_file(),
        "sidecar_present": sidecar.is_file(),
        "attestation_present": att_path.is_file(),
    }
    if not zip_path.is_file():
        result.update({"ok": False, "detail": "core baseline ZIP missing"})
        return result
    computed = _sha256_file(zip_path)
    result["computed_core_sha256"] = computed
    result["computed_sha256"] = computed  # back-compat
    result["core_sha_matches"] = computed == ACCEPTED_CORE_V0121_SHA256
    if sidecar.is_file():
        side = sidecar.read_text(encoding="utf-8").strip().split()[0]
        result["sidecar_sha256"] = side
        result["sidecar_matches"] = side == ACCEPTED_CORE_V0121_SHA256
    else:
        result["sidecar_matches"] = False
    att_ok = False
    members = indexed = None
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        result["attestation_status"] = att.get("attestation_status")
        members = att.get("members")
        indexed = att.get("indexed_members")
        att_ok = att.get("attestation_status") == "PASS"
    result["members"] = members
    result["indexed_members"] = indexed
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        result["zip_member_count"] = len(names)
        result["review_index_present"] = "REVIEW_INDEX.md" in names

    sdr = external / ACCEPTED_SDR_V01_ZIP
    result["sdr_v01_present"] = sdr.is_file()
    if sdr.is_file():
        sdr_sha = _sha256_file(sdr)
        result["computed_sdr_v01_sha256"] = sdr_sha
        result["sdr_v01_untouched"] = sdr_sha == ACCEPTED_SDR_V01_SHA256
    else:
        result["sdr_v01_untouched"] = False

    sdr011 = external / ACCEPTED_SDR_V011_ZIP
    result["sdr_v011_present"] = sdr011.is_file()
    if sdr011.is_file():
        sdr011_sha = _sha256_file(sdr011)
        result["computed_sdr_v011_sha256"] = sdr011_sha
        result["sdr_v011_untouched"] = sdr011_sha == ACCEPTED_SDR_V011_SHA256
    else:
        result["sdr_v011_untouched"] = False

    priors = {}
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
        result.get("core_sha_matches")
        and result.get("sidecar_matches")
        and att_ok
        and result.get("zip_member_count") == 205
        and indexed == 204
        and result.get("review_index_present")
        and result.get("sdr_v01_untouched")
        and result.get("sdr_v011_untouched")
        and all_priors_ok
    )
    result["policy"] = policy_snapshot()
    result["security_stage_paused"] = True
    result["clinical_validation"] = "NOT_STARTED"
    return result
