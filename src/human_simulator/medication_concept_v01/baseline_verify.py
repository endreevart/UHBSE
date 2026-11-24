"""Phase 0 — verify prior medication-knowledge v0.1 review ZIP."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.medication_concept_v01.policy import (
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
    }
    try:
        exists = zip_path.is_file()
    except OSError as exc:
        return {
            **out,
            "ok": False,
            "BASELINE_VERIFICATION_STATUS": "FAIL",
            "error": str(exc),
        }
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

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        out["members"] = len(members)
        out["unique_members"] = len(set(members))
        out["members_match_pin"] = len(members) == ACCEPTED_PRIOR_MEMBERS
        out["members_eq_indexed_plus_1"] = len(members) == ACCEPTED_PRIOR_INDEXED + 1

        # Known methodological defects in prior bundle
        art = "artifacts/stage-03-medication-knowledge-representation-v0.1/"
        defects = []
        if art + "medication-source-accounting.json" in set(members):
            acc = json.loads(zf.read(art + "medication-source-accounting.json"))
            by = acc.get("by_mapping_status") or {}
            if by.get("SOURCE_EXACT") == 487 and by.get("SUPPORTED_TRANSFORM", 0) == 0:
                defects.append(
                    {
                        "id": "SOURCE_EXACT_PRESENTED_AS_DRUG_CONCEPT",
                        "detail": (
                            "SOURCE_EXACT=487 reflects source-record join, "
                            "not accepted drug-concept harmonization"
                        ),
                    }
                )
            hyp = acc.get("hypothesis_extractions") or {}
            out["prior_active_ingredient_inferred"] = hyp.get("active_ingredient_inferred")
            out["prior_route_inferred"] = hyp.get("route_inferred")
        if art + "medication-representation-sensitivity.json" in set(members):
            sens = json.loads(zf.read(art + "medication-representation-sensitivity.json"))
            if sens.get("m2sem_gate") == "RUN":
                defects.append(
                    {
                        "id": "M2SEM_RAN_WITHOUT_ACCEPTED_DRUG_CONCEPTS",
                        "detail": "M2SEM ran gated on SOURCE_EXACT identity, not drug concepts",
                    }
                )
            out["prior_signal"] = sens.get("INCREMENTAL_MEDICATION_CONTEXT_SIGNAL_STATUS")
        out["methodological_defects"] = defects

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
        and out.get("all_priors_unchanged")
    )
    out["ok"] = ok
    out["BASELINE_VERIFICATION_STATUS"] = "PASS" if ok else "FAIL"
    return out
