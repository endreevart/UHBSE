"""Phase 0 — verify prior concept-harmonization ZIP + scope correction."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.medication_reference_v01.policy import (
    ACCEPTED_PRIOR_INDEXED,
    ACCEPTED_PRIOR_MEMBERS,
    ACCEPTED_PRIOR_SHA256,
    ACCEPTED_PRIOR_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_prior_baseline(root: Path) -> dict[str, Any]:
    root = root.resolve()
    ext = root / "artifacts" / "external-review"
    zip_path = ext / ACCEPTED_PRIOR_ZIP
    out: dict[str, Any] = {
        "accepted_zip": ACCEPTED_PRIOR_ZIP,
        "accepted_sha256_pin": ACCEPTED_PRIOR_SHA256,
        "scope_correction": {
            "M2ID_ONEHOT_REPRESENTATION_STATUS": "EVALUATED",
            "M2ID_ONEHOT_MODEL_FREEZE_STATUS": "NOT_DONE_IN_PRIOR_RELEASE",
            "M2ID_ONEHOT_ENGINE_SHADOW_STATUS": "NOT_RUN_IN_PRIOR_RELEASE",
            "prior_ENGINE_SHADOW_PASS_applies_only_to_frozen_M1_M2C": True,
            "onehot_demo_is_not_model_inference": True,
        },
    }
    try:
        exists = zip_path.is_file()
    except OSError as exc:
        return {**out, "ok": False, "BASELINE_VERIFICATION_STATUS": "FAIL", "error": str(exc)}

    out["zip_exists"] = exists
    if not exists:
        out["ok"] = False
        out["BASELINE_VERIFICATION_STATUS"] = "FAIL"
        return out

    got = _sha(zip_path)
    out["zip_sha256"] = got
    out["zip_sha_matches_pin"] = got == ACCEPTED_PRIOR_SHA256
    sidecar = ext / f"{ACCEPTED_PRIOR_ZIP}.sha256"
    out["sidecar_matches"] = (
        sidecar.is_file() and sidecar.read_text().strip().split()[0] == got
    )
    att_path = ext / ACCEPTED_PRIOR_ZIP.replace(".zip", ".attestation.json")
    att = json.loads(att_path.read_text()) if att_path.is_file() else {}
    out["attestation_sha_matches"] = att.get("review_zip_sha256") == got
    out["attestation_members"] = att.get("members")
    out["attestation_indexed"] = att.get("indexed_members")

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        out["members"] = len(members)
        out["unique_members"] = len(set(members))
        out["members_match_pin"] = len(members) == ACCEPTED_PRIOR_MEMBERS
        out["members_eq_indexed_plus_1"] = len(members) == ACCEPTED_PRIOR_INDEXED + 1
        out["has_review_index"] = "REVIEW_INDEX.md" in members
        # Confirm prior shadow was M1/M2C, not frozen onehot
        art = (
            "artifacts/stage-03-medication-concept-harmonization-categorical-baseline-v0.1/"
        )
        shadow_name = art + "medication-model-shadow-inference.json"
        if shadow_name in members:
            shadow = json.loads(zf.read(shadow_name))
            out["prior_shadow_has_onehot_demo"] = bool(shadow.get("onehot_demo"))
            out["prior_shadow_has_m2id_onehot_predictions"] = any(
                "m2id_onehot" in str(k).lower()
                for k in (shadow.get("evidence_object_keys") or [])
            )
            out["prior_inferences_are_m1_m2c"] = all(
                "m2c_y_pred" in inf for inf in (shadow.get("inferences") or [])
            )

    priors = {}
    for label, (name, pin) in PRIOR_IMMUTABLE_ZIPS.items():
        p = ext / name
        if not p.is_file():
            priors[label] = {"exists": False, "unchanged": False}
            continue
        h = _sha(p)
        priors[label] = {"exists": True, "sha256": h, "unchanged": h == pin}
    out["prior_immutable_zips"] = priors
    out["all_priors_unchanged"] = all(v.get("unchanged") for v in priors.values())
    ok = bool(
        out.get("zip_sha_matches_pin")
        and out.get("sidecar_matches")
        and out.get("attestation_sha_matches")
        and out.get("members_match_pin")
        and out.get("members_eq_indexed_plus_1")
        and out.get("has_review_index")
        and out.get("all_priors_unchanged")
    )
    out["ok"] = ok
    out["BASELINE_VERIFICATION_STATUS"] = "PASS" if ok else "FAIL"
    return out
