"""Phase 0 — evidence verification + owner threshold decision."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.trajectory_expansion_v01.policy import (
    EXPECTED_GRAIN_COUNT,
    INVENTORY_PATH,
    PILOT_ZIP,
    PILOT_ZIP_SHA256,
    PRIMARY_THRESHOLD_PROFILE,
    THRESHOLD_OPTIONS_PATH,
    VERSION,
    threshold_options_sha256,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_threshold_profile(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / THRESHOLD_OPTIONS_PATH
    if not path.is_file():
        return {
            "THRESHOLD_PROFILE_VERIFICATION_STATUS": "FAIL",
            "THRESHOLD_PROFILE_MISMATCH": True,
            "reason": "threshold_options_missing",
        }
    doc = json.loads(path.read_text(encoding="utf-8"))
    options = doc.get("options") or {}
    if PRIMARY_THRESHOLD_PROFILE not in options:
        return {
            "THRESHOLD_PROFILE_VERIFICATION_STATUS": "FAIL",
            "THRESHOLD_PROFILE_MISMATCH": True,
            "reason": "conservative_profile_missing",
        }
    cons = options[PRIMARY_THRESHOLD_PROFILE]
    criteria = {
        "min_subjects_with_ge2": cons.get("min_subjects_with_ge2"),
        "min_strict_consecutive_pairs": cons.get("min_strict_consecutive_pairs"),
        "min_test_subjects_if_split": cons.get("min_test_subjects_if_split"),
    }
    expected = (cons.get("pass") or {}).get("n_outcomes_passing")
    inv_path = root / INVENTORY_PATH
    if not inv_path.is_file():
        return {
            "THRESHOLD_PROFILE_VERIFICATION_STATUS": "FAIL",
            "THRESHOLD_PROFILE_MISMATCH": True,
            "reason": "inventory_missing",
        }
    grains = json.loads(inv_path.read_text(encoding="utf-8")).get("grains") or []
    passing = [
        g
        for g in grains
        if int(g.get("n_subjects_with_ge2") or 0) >= int(criteria["min_subjects_with_ge2"])
        and int(g.get("n_strict_consecutive_pairs") or 0)
        >= int(criteria["min_strict_consecutive_pairs"])
    ]
    ok = (
        expected == EXPECTED_GRAIN_COUNT
        and len(passing) == EXPECTED_GRAIN_COUNT
        and criteria["min_subjects_with_ge2"] == 100
        and criteria["min_strict_consecutive_pairs"] == 300
        and criteria["min_test_subjects_if_split"] == 30
    )
    return {
        "THRESHOLD_PROFILE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "THRESHOLD_PROFILE_MISMATCH": not ok,
        "criteria": criteria,
        "expected_count_from_artifact": expected,
        "actual_passing_count": len(passing),
        "EXPECTED_GRAIN_COUNT": EXPECTED_GRAIN_COUNT,
        "threshold_options_sha256": threshold_options_sha256(root),
        "passing_grains_preview": [
            {
                "outcome": g["outcome"],
                "unit": g["unit"],
                "n_pairs": g["n_strict_consecutive_pairs"],
                "n_subjects_ge2": g["n_subjects_with_ge2"],
            }
            for g in passing[:5]
        ],
    }


def build_owner_decision(root: Path, verify: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "OWNER_THRESHOLD_DECISION_STATUS": (
            "RECORDED" if not verify.get("THRESHOLD_PROFILE_MISMATCH") else "REJECTED"
        ),
        "profile": PRIMARY_THRESHOLD_PROFILE,
        "source_artifact": THRESHOLD_OPTIONS_PATH,
        "source_artifact_sha256": verify.get("threshold_options_sha256"),
        "exact_criteria_copied_from_threshold_options": verify.get("criteria"),
        "expected_count": EXPECTED_GRAIN_COUNT,
        "scope": "single-outcome-trajectory-expansion-v0.1_only",
        "global_policy_changed": False,
        "medication_gates_changed": False,
        "written_into_global_scientific_policy": False,
    }


def verify_baseline_evidence(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    external = root / "artifacts" / "external-review"
    checks = []
    z = external / PILOT_ZIP
    zip_ok = z.is_file() and _sha(z) == PILOT_ZIP_SHA256
    checks.append({"name": "concept_pilot_zip", "ok": zip_ok})
    side = external / f"{PILOT_ZIP}.sha256"
    checks.append(
        {
            "name": "pilot_sidecar",
            "ok": side.is_file()
            and side.read_text(encoding="utf-8").strip().startswith(PILOT_ZIP_SHA256),
        }
    )
    att = external / PILOT_ZIP.replace(".zip", ".attestation.json")
    att_ok = False
    if att.is_file():
        a = json.loads(att.read_text(encoding="utf-8"))
        att_ok = a.get("review_zip_sha256") == PILOT_ZIP_SHA256
    checks.append({"name": "pilot_attestation", "ok": att_ok})
    for rel in (
        "private/post-pilot-audit-v01/verification.json",
        "private/post-pilot-audit-v01/source-a-longitudinal-inventory.json",
        THRESHOLD_OPTIONS_PATH,
    ):
        checks.append({"name": f"present:{rel}", "ok": (root / rel).is_file()})
    inv = json.loads((root / INVENTORY_PATH).read_text(encoding="utf-8"))
    checks.append(
        {
            "name": "source_b_contamination_zero",
            "ok": inv.get("SOURCE_B_CONTAMINATION") == 0,
        }
    )
    checks.append(
        {
            "name": "source_a_provenance",
            "ok": inv.get("provenance_filter") == "OBSERVED_source_a_clinic_rows_only",
        }
    )
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "no_training_after_audit": True,
    }
