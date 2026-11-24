"""Baseline verification for privacy + cross-source harmonization v0.1."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.privacy_cross_source_v01.policy import (
    ACCEPTED_CONCEPT_PILOT_SHA256,
    ACCEPTED_CONCEPT_PILOT_ZIP,
    ACCEPTED_GS01_SHA256,
    ACCEPTED_GS01_ZIP,
    ACCEPTED_GS011_ARTIFACT_DIR,
    ACCEPTED_GS011_INDEXED,
    ACCEPTED_GS011_MEMBERS,
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_TRAJ011_SHA256,
    ACCEPTED_TRAJ011_ZIP,
    ACCEPTED_UNIFIED_V012_SHA256,
    ACCEPTED_UNIFIED_V012_ZIP,
    ACCEPTED_UNIFIED_V01211_SHA256,
    ACCEPTED_UNIFIED_V01211_ZIP,
    CARRIED_SOURCE_A_GLOBAL_TEST,
    CARRIED_SOURCE_A_SUBJECTS,
    CARRIED_SOURCE_B_SUBJECTS,
    CARRIED_V011_DIAGNOSTIC_ONLY,
    CARRIED_V011_EVALUABLE,
    CARRIED_V011_HORIZON_ALIGNED_SUBJECTS,
    CARRIED_V011_IN_SUPPORT_SUM,
    CARRIED_V011_PRIMARY_TARGETS,
    CARRIED_V011_PROVIDERS,
    VERSION,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path, *, live_subject_counts: dict[str, int] | None = None) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # Primary GS v0.1.1
    z = external / ACCEPTED_GS011_ZIP
    digest = _sha(z) if z.is_file() else None
    add("gs011_zip_present", z.is_file())
    add("gs011_sha256", digest == ACCEPTED_GS011_SHA256, digest)
    side = external / f"{ACCEPTED_GS011_ZIP}.sha256"
    add("gs011_sidecar", side.is_file() and side.read_text().split()[0] == ACCEPTED_GS011_SHA256)
    att_path = external / ACCEPTED_GS011_ZIP.replace(".zip", ".attestation.json")
    members = indexed = None
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        members = att.get("members")
        indexed = att.get("indexed_members")
        add("gs011_attestation_pass", att.get("attestation_status") == "PASS")
        add(
            "gs011_members_indexed",
            members == ACCEPTED_GS011_MEMBERS and indexed == ACCEPTED_GS011_INDEXED,
            {"members": members, "indexed": indexed},
        )
    if z.is_file():
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            add("gs011_zip_member_count", len(names) == ACCEPTED_GS011_MEMBERS, len(names))
            add("REVIEW_INDEX_present", any(n.endswith("REVIEW_INDEX.md") for n in names))
            add(
                "evidence_manifest_present",
                any(n.endswith("evidence-manifest.sha256") for n in names),
            )

    # Immutable priors
    for label, name, exp in [
        ("gs01", ACCEPTED_GS01_ZIP, ACCEPTED_GS01_SHA256),
        ("traj011", ACCEPTED_TRAJ011_ZIP, ACCEPTED_TRAJ011_SHA256),
        ("unified012", ACCEPTED_UNIFIED_V012_ZIP, ACCEPTED_UNIFIED_V012_SHA256),
        ("unified01211", ACCEPTED_UNIFIED_V01211_ZIP, ACCEPTED_UNIFIED_V01211_SHA256),
        ("concept_pilot", ACCEPTED_CONCEPT_PILOT_ZIP, ACCEPTED_CONCEPT_PILOT_SHA256),
    ]:
        p = external / name
        got = _sha(p) if p.is_file() else None
        add(f"{label}_unchanged", got == exp, got)

    # Carried facts from GS v0.1.1 artifacts
    art = Path(root) / ACCEPTED_GS011_ARTIFACT_DIR
    agg = json.loads((art / "aggregate-report.json").read_text(encoding="utf-8"))
    inv = json.loads((art / "real-heldout-state-inventory.json").read_text(encoding="utf-8"))
    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    bt = json.loads((art / "real-heldout-multi-outcome-backtest.json").read_text(encoding="utf-8"))
    funnel = inv.get("funnel") or {}
    add("carried_providers_95", int(agg.get("n_providers_frozen") or 0) == CARRIED_V011_PROVIDERS)
    add("carried_evaluable_85", int(agg.get("n_evaluable") or 0) == CARRIED_V011_EVALUABLE)
    add(
        "carried_diagnostic_10",
        int(agg.get("n_diagnostic_only") or 0) == CARRIED_V011_DIAGNOSTIC_ONLY,
    )
    add(
        "carried_primary_targets",
        int(agg.get("n_primary_targets") or 0) == CARRIED_V011_PRIMARY_TARGETS,
    )
    add(
        "carried_horizon_subjects",
        int(inv.get("n_subjects_with_horizon_aligned_targets") or 0)
        == CARRIED_V011_HORIZON_ALIGNED_SUBJECTS,
    )
    add(
        "carried_global_test",
        int(funnel.get("n_global_test_subjects") or 0) == CARRIED_SOURCE_A_GLOBAL_TEST,
    )
    add(
        "classifier_not_started",
        st.get("CURRENT_STATE_CLASSIFIER_STATUS") == "NOT_STARTED",
    )

    in_sup = sum(int(o.get("n_in_support") or 0) for o in (bt.get("evaluable_per_outcome") or []))
    in_sup += sum(
        int(o.get("n_in_support") or 0) for o in (bt.get("diagnostic_only_per_outcome") or [])
    )
    add("carried_in_support_sum_18311", in_sup == CARRIED_V011_IN_SUPPORT_SUM, in_sup)
    gap = CARRIED_V011_PRIMARY_TARGETS - in_sup
    add("carried_applicability_gap_884", gap == 884, gap)

    drift = False
    if live_subject_counts is not None:
        a = int(live_subject_counts.get("magerya_api") or -1)
        b = int(live_subject_counts.get("kgz_raw") or -1)
        add("live_a_subjects", a == CARRIED_SOURCE_A_SUBJECTS, a)
        add("live_b_subjects", b == CARRIED_SOURCE_B_SUBJECTS, b)
        if a != CARRIED_SOURCE_A_SUBJECTS or b != CARRIED_SOURCE_B_SUBJECTS:
            drift = True

    ok = all(c["ok"] for c in checks) and not drift
    status = "PASS" if ok else ("BASELINE_DRIFT_DETECTED" if drift else "FAIL")
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": status,
        "accepted_gs011_sha256_observed": digest,
        "members": members,
        "indexed_members": indexed,
        "carried_facts": {
            "source_a_subjects": CARRIED_SOURCE_A_SUBJECTS,
            "source_b_subjects": CARRIED_SOURCE_B_SUBJECTS,
            "do_not_sum_as_unique_patients": True,
            "source_a_global_test": CARRIED_SOURCE_A_GLOBAL_TEST,
            "v011_horizon_aligned_subjects": CARRIED_V011_HORIZON_ALIGNED_SUBJECTS,
            "v011_primary_targets": CARRIED_V011_PRIMARY_TARGETS,
            "v011_providers": CARRIED_V011_PROVIDERS,
            "v011_evaluable": CARRIED_V011_EVALUABLE,
            "v011_diagnostic_only": CARRIED_V011_DIAGNOSTIC_ONLY,
            "v011_in_support_sum": CARRIED_V011_IN_SUPPORT_SUM,
            "v011_applicability_unclassified_gap": gap,
            "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
            "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        },
        "checks": checks,
        "ok": ok,
        "drift": drift,
    }
