"""Verify immutable v0.1 medication-reference baseline."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v011.policy import (
    ACCEPTED_PRIOR_INDEXED,
    ACCEPTED_PRIOR_MEMBERS,
    ACCEPTED_PRIOR_SHA256,
    ACCEPTED_PRIOR_ZIP,
    CARRIED_FROM_V01,
    PRIOR_IMMUTABLE_ZIPS,
    V01_ARTIFACT_DIR,
)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_prior_baseline(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    ext = root / "artifacts" / "external-review"
    zip_path = ext / ACCEPTED_PRIOR_ZIP
    sidecar = Path(str(zip_path) + ".sha256")
    att_path = ext / ACCEPTED_PRIOR_ZIP.replace(".zip", ".attestation.json")

    out: dict[str, Any] = {
        "accepted_zip": ACCEPTED_PRIOR_ZIP,
        "accepted_sha256_pin": ACCEPTED_PRIOR_SHA256,
        "accepted_members_pin": ACCEPTED_PRIOR_MEMBERS,
        "accepted_indexed_pin": ACCEPTED_PRIOR_INDEXED,
        "carried_status": dict(CARRIED_FROM_V01),
        "zip_exists": zip_path.is_file(),
    }
    if not zip_path.is_file():
        out["ok"] = False
        out["BASELINE_VERIFICATION_STATUS"] = "FAIL"
        out["reason"] = "prior_zip_missing"
        return out

    sha = _sha_file(zip_path)
    out["zip_sha256"] = sha
    out["zip_sha_matches_pin"] = sha == ACCEPTED_PRIOR_SHA256
    out["sidecar_exists"] = sidecar.is_file()
    out["sidecar_matches"] = False
    if sidecar.is_file():
        out["sidecar_matches"] = sidecar.read_text(encoding="utf-8").split()[0] == sha

    out["attestation_exists"] = att_path.is_file()
    out["attestation_sha_matches"] = False
    out["attestation_members"] = None
    out["attestation_indexed"] = None
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        out["attestation_sha_matches"] = att.get("review_zip_sha256") == sha
        out["attestation_members"] = att.get("members")
        out["attestation_indexed"] = att.get("indexed_members")
        out["attestation_status"] = att.get("attestation_status")

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        out["members"] = len(names)
        out["unique_members"] = len(set(names))
        out["has_review_index"] = any(n.endswith("REVIEW_INDEX.md") for n in names)
        # evidence manifest presence
        out["has_evidence_manifest"] = any(
            "evidence-manifest" in n or n.endswith("manifest.sha256") for n in names
        )

    out["members_match_pin"] = out["members"] == ACCEPTED_PRIOR_MEMBERS
    out["members_eq_indexed_plus_1"] = (
        out.get("attestation_indexed") is not None
        and out["members"] == int(out["attestation_indexed"]) + 1
    )

    # Frozen M2ID_ONEHOT hashes from v0.1 artifacts
    freeze_path = root / V01_ARTIFACT_DIR / "m2id-onehot-model-freeze.json"
    shadow_path = root / V01_ARTIFACT_DIR / "m2id-onehot-engine-shadow.json"
    out["v01_freeze_artifact_exists"] = freeze_path.is_file()
    out["v01_shadow_artifact_exists"] = shadow_path.is_file()
    freeze_hashes: list[dict[str, str]] = []
    if freeze_path.is_file():
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        out["v01_freeze_status"] = freeze.get("M2ID_ONEHOT_MODEL_FREEZE_STATUS")
        for c in freeze.get("cohorts") or []:
            freeze_hashes.append(
                {
                    "outcome": c.get("outcome"),
                    "unit": c.get("unit"),
                    "file_sha256": c.get("file_sha256"),
                    "model_identity_sha256": c.get("model_identity_sha256"),
                    "vocab_hash": c.get("vocab_hash"),
                }
            )
    out["frozen_m2id_onehot_hashes"] = freeze_hashes
    if shadow_path.is_file():
        shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
        out["v01_shadow_status"] = shadow.get("M2ID_ONEHOT_ENGINE_SHADOW_STATUS")

    priors: dict[str, Any] = {}
    all_ok = True
    for key, (name, pin) in PRIOR_IMMUTABLE_ZIPS.items():
        p = ext / name
        exists = p.is_file()
        got = _sha_file(p) if exists else None
        unchanged = exists and got == pin
        priors[key] = {"exists": exists, "sha256": got, "unchanged": unchanged, "pin": pin}
        if not unchanged:
            all_ok = False
    out["prior_immutable_zips"] = priors
    out["all_priors_unchanged"] = all_ok

    ok = (
        out["zip_sha_matches_pin"]
        and out["sidecar_matches"]
        and out["attestation_sha_matches"]
        and out["members_match_pin"]
        and out["members_eq_indexed_plus_1"]
        and out["has_review_index"]
        and out.get("v01_freeze_status") == "FROZEN"
        and out.get("v01_shadow_status") == "PASS"
        and all_ok
    )
    out["ok"] = ok
    out["BASELINE_VERIFICATION_STATUS"] = "PASS" if ok else "FAIL"
    return out
