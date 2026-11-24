"""Phase 0 — audit carried v0.1.1 analytical payload vs review-bundle packaging."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.medication_knowledge_v01.policy import (
    ACCEPTED_V011_INDEXED,
    ACCEPTED_V011_MEMBERS,
    ACCEPTED_V011_SHA256,
    ACCEPTED_V011_ZIP,
    PRIOR_IMMUTABLE_ZIPS,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def audit_v011_baseline(root: Path) -> dict[str, Any]:
    root = root.resolve()
    ext = root / "artifacts" / "external-review"
    zip_path = ext / ACCEPTED_V011_ZIP
    sidecar = ext / f"{ACCEPTED_V011_ZIP}.sha256"
    att_path = ext / ACCEPTED_V011_ZIP.replace(".zip", ".attestation.json")

    out: dict[str, Any] = {
        "accepted_zip": ACCEPTED_V011_ZIP,
        "accepted_sha256_pin": ACCEPTED_V011_SHA256,
    }
    try:
        out["zip_exists"] = zip_path.is_file()
    except OSError as exc:
        out["zip_exists"] = False
        out["zip_access_error"] = str(exc)
        out["V011_ANALYTICAL_PAYLOAD_STATUS"] = "FAIL"
        out["V011_REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "FAIL"
        out["ok"] = False
        return out
    got = _sha(zip_path) if out["zip_exists"] else None
    out["zip_sha256"] = got
    out["zip_sha_matches_pin"] = got == ACCEPTED_V011_SHA256
    out["sidecar_matches"] = (
        sidecar.is_file() and sidecar.read_text().strip().split()[0] == got
    )
    att = json.loads(att_path.read_text()) if att_path.is_file() else {}
    out["attestation_sha_matches"] = att.get("review_zip_sha256") == got
    out["attestation_status"] = att.get("attestation_status")
    out["attestation_unit_passed"] = (att.get("unit_reproduce") or {}).get("passed")

    defects: list[dict[str, str]] = []
    analytical_ok = False
    if out["zip_exists"]:
        with zipfile.ZipFile(zip_path) as zf:
            members = [n for n in zf.namelist() if not n.endswith("/")]
            names = set(members)
            out["members"] = len(members)
            out["unique_members"] = len(set(members))
            out["members_match_pin"] = len(members) == ACCEPTED_V011_MEMBERS
            out["members_eq_indexed_plus_1"] = len(members) == ACCEPTED_V011_INDEXED + 1

            # Analytical payload present?
            art = "artifacts/stage-03-first-medication-association-baseline-v0.1.1/"
            needed = [
                art + "medication-association-baselines-v011.json",
                art + "status-contract.json",
                art + "model-freeze.json",
                art + "engine-shadow-integration.json",
            ]
            analytical_ok = all(n in names for n in needed)
            out["analytical_payload_files_present"] = analytical_ok

            # Defect 1: stale PENDING in verification.json
            verj_path = art + "verification.json"
            if verj_path in names:
                verj = json.loads(zf.read(verj_path))
                st = verj.get("statuses") or {}
                if st.get("pre_pack_manifest_status") == "PENDING_WRITE":
                    defects.append(
                        {
                            "id": "STALE_PENDING_WRITE_IN_VERIFICATION_JSON",
                            "detail": "verification.json statuses.pre_pack_manifest_status=PENDING_WRITE",
                        }
                    )
                if st.get("clean_staging_test_status") == "PENDING_PUBLISH":
                    defects.append(
                        {
                            "id": "STALE_PENDING_PUBLISH_IN_VERIFICATION_JSON",
                            "detail": "verification.json statuses.clean_staging_test_status=PENDING_PUBLISH",
                        }
                    )

            # Defect 2: REPRODUCE invokes audit without cli.py
            repro = zf.read("REPRODUCE.md").decode("utf-8") if "REPRODUCE.md" in names else ""
            if "audit" in repro and "src/human_simulator/cli.py" not in names:
                defects.append(
                    {
                        "id": "REPRODUCE_AUDIT_WITHOUT_CLI",
                        "detail": "REPRODUCE.md invokes audit but ZIP lacks src/human_simulator/cli.py",
                    }
                )

            # Defect 3: v01 unit test without full v01 package
            if "tests/test_intervention_association_v01_unit.py" in names:
                v01_files = [
                    n
                    for n in names
                    if n.startswith("src/human_simulator/intervention_association_v01/")
                    and n.endswith(".py")
                ]
                out["v01_py_modules_in_zip"] = sorted(v01_files)
                required_v01 = {
                    "policy.py",
                    "models.py",
                    "evaluate.py",
                    "accounting.py",
                    "episodes.py",
                }
                present_basenames = {Path(n).name for n in v01_files}
                missing = sorted(required_v01 - present_basenames)
                if missing:
                    defects.append(
                        {
                            "id": "V01_TEST_WITHOUT_FULL_PACKAGE",
                            "detail": f"v01 unit test present; missing modules: {missing}",
                        }
                    )

            # Defect 4: clean extraction only ran 12 v011 tests
            unit_n = (att.get("unit_reproduce") or {}).get("passed")
            if unit_n is not None and int(unit_n) < 20:
                defects.append(
                    {
                        "id": "CLEAN_EXTRACTION_NARROW_SUITE",
                        "detail": (
                            f"attestation unit_reproduce.passed={unit_n}; "
                            "does not prove v01 regression or audit CLI"
                        ),
                    }
                )

            # hash collision facts from analytical payload
            if art + "medication-association-baselines-v011.json" in names:
                mod = json.loads(
                    zf.read(art + "medication-association-baselines-v011.json")
                )
                collisions = []
                for c in mod.get("cohorts") or []:
                    hr = c.get("m2c_hash_report") or {}
                    collisions.append(
                        {
                            "outcome": c.get("outcome"),
                            "n_train_medicine_ids": hr.get("n_train_medicine_ids"),
                            "occupied_buckets": hr.get("occupied_buckets"),
                            "n_collision_buckets": hr.get("n_collision_buckets"),
                            "hash_dim": hr.get("hash_dim"),
                        }
                    )
                out["v011_hash_collision_summary"] = collisions

    out["packaging_defects"] = defects
    out["V011_ANALYTICAL_PAYLOAD_STATUS"] = (
        "VERIFIED" if analytical_ok and out.get("zip_sha_matches_pin") else "FAIL"
    )
    out["V011_REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = (
        "FAIL" if defects else "PASS"
    )

    prior = {}
    for label, (name, pin) in PRIOR_IMMUTABLE_ZIPS.items():
        p = ext / name
        if not p.is_file():
            prior[label] = {"exists": False, "unchanged": False}
            continue
        h = _sha(p)
        prior[label] = {"exists": True, "sha256": h, "unchanged": h == pin}
    out["prior_immutable_zips"] = prior
    out["all_priors_unchanged"] = all(v.get("unchanged") for v in prior.values())
    out["ok"] = bool(
        out.get("zip_sha_matches_pin")
        and out.get("sidecar_matches")
        and out.get("attestation_sha_matches")
        and out.get("V011_ANALYTICAL_PAYLOAD_STATUS") == "VERIFIED"
        and out.get("all_priors_unchanged")
    )
    return out
