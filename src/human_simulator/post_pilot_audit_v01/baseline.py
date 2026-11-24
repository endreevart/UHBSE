"""Phase 0 — verify immutable pilot review ZIP and prior baselines."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.post_pilot_audit_v01.policy import (
    PILOT_ARTIFACT_DIR,
    PILOT_ZIP,
    PILOT_ZIP_SHA256,
    PRIOR_CONCEPT_COHORTS_SHA256,
    PRIOR_CONCEPT_COHORTS_ZIP,
    PRIOR_MEDICATION_ASSOC_SHA256,
    PRIOR_MEDICATION_ASSOC_ZIP,
    V011_DECISION_LOG,
    V011_DECISION_LOG_SHA256,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_pilot_baseline(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    external = root / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []

    zip_path = external / PILOT_ZIP
    sidecar = external / f"{PILOT_ZIP}.sha256"
    att_path = external / PILOT_ZIP.replace(".zip", ".attestation.json")

    zip_ok = zip_path.is_file()
    zip_sha = _sha(zip_path) if zip_ok else None
    checks.append(
        {
            "name": "pilot_zip_sha256",
            "ok": zip_ok and zip_sha == PILOT_ZIP_SHA256,
            "expected": PILOT_ZIP_SHA256,
            "got": zip_sha,
        }
    )

    side_ok = False
    if sidecar.is_file():
        side_text = sidecar.read_text(encoding="utf-8").strip()
        side_ok = side_text.startswith(PILOT_ZIP_SHA256)
    checks.append({"name": "sidecar_matches", "ok": side_ok})

    att_ok = False
    att: dict[str, Any] = {}
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        att_ok = (
            att.get("attestation_status") == "PASS"
            and att.get("review_zip_sha256") == PILOT_ZIP_SHA256
        )
    checks.append(
        {
            "name": "attestation",
            "ok": att_ok,
            "members": att.get("members"),
            "indexed_members": att.get("indexed_members"),
        }
    )

    review_index_ok = False
    manifest_ok = False
    if zip_ok:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            review_index_ok = "REVIEW_INDEX.md" in names
            man_name = f"{PILOT_ARTIFACT_DIR}/evidence-manifest.sha256"
            if man_name in names:
                # verify a sample of manifest entries inside ZIP
                man_text = zf.read(man_name).decode("utf-8")
                mismatches = []
                checked = 0
                for line in man_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    digest, _, rel = line.partition("  ")
                    if not rel:
                        digest, _, rel = line.partition(" ")
                    member = f"{PILOT_ARTIFACT_DIR}/{rel.strip()}"
                    if member not in names:
                        mismatches.append(rel)
                        continue
                    got = hashlib.sha256(zf.read(member)).hexdigest()
                    checked += 1
                    if got != digest.strip():
                        mismatches.append(rel)
                manifest_ok = checked > 0 and not mismatches
    checks.append({"name": "review_index_present", "ok": review_index_ok})
    checks.append({"name": "internal_manifest", "ok": manifest_ok})

    art = root / PILOT_ARTIFACT_DIR
    for name in (
        "predeclared-cohorts.json",
        "status-contract.json",
        "verification.json",
        "cohorts/udca_oral_tablet_500mg.json",
        "cohorts/levothyroxine_oral_tablet_50mcg.json",
        "cohorts/udca_oral_tablet_250mg.json",
    ):
        p = art / name
        checks.append({"name": f"artifact_present:{name}", "ok": p.is_file()})

    prior_ok = True
    prior_hashes = {}
    for name, exp in (
        (PRIOR_MEDICATION_ASSOC_ZIP, PRIOR_MEDICATION_ASSOC_SHA256),
        (PRIOR_CONCEPT_COHORTS_ZIP, PRIOR_CONCEPT_COHORTS_SHA256),
        (PILOT_ZIP, PILOT_ZIP_SHA256),
    ):
        p = external / name
        if not p.is_file():
            prior_ok = False
            prior_hashes[name] = None
            continue
        got = _sha(p)
        prior_hashes[name] = got
        if got != exp:
            prior_ok = False
    checks.append({"name": "prior_zips_unchanged", "ok": prior_ok, "hashes": prior_hashes})

    log_path = root / V011_DECISION_LOG
    log_ok = log_path.is_file() and _sha(log_path) == V011_DECISION_LOG_SHA256
    checks.append({"name": "decision_log_unchanged", "ok": log_ok})

    return {
        "PILOT_BASELINE_VERIFICATION_STATUS": (
            "PASS" if all(c["ok"] for c in checks) else "FAIL"
        ),
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "no_retrain": True,
        "no_zip_rewrite": True,
    }
