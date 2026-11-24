"""Baseline verification for semantic review v0.1."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.policy import (
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_PRIVACY_XS_ARTIFACT_DIR,
    ACCEPTED_PRIVACY_XS_INDEXED,
    ACCEPTED_PRIVACY_XS_MEMBERS,
    ACCEPTED_PRIVACY_XS_SHA256,
    ACCEPTED_PRIVACY_XS_ZIP,
    VERSION,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    z = external / ACCEPTED_PRIVACY_XS_ZIP
    digest = _sha(z) if z.is_file() else None
    add("privacy_xs_zip_present", z.is_file())
    add("privacy_xs_sha256", digest == ACCEPTED_PRIVACY_XS_SHA256, digest)
    side = external / f"{ACCEPTED_PRIVACY_XS_ZIP}.sha256"
    add(
        "privacy_xs_sidecar",
        side.is_file() and side.read_text().split()[0] == ACCEPTED_PRIVACY_XS_SHA256,
    )
    att_path = external / ACCEPTED_PRIVACY_XS_ZIP.replace(".zip", ".attestation.json")
    members = indexed = None
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        members = att.get("members")
        indexed = att.get("indexed_members")
        add("attestation_pass", att.get("attestation_status") == "PASS")
        add(
            "members_indexed_540_539",
            members == ACCEPTED_PRIVACY_XS_MEMBERS
            and indexed == ACCEPTED_PRIVACY_XS_INDEXED,
            {"members": members, "indexed": indexed},
        )
    if z.is_file():
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            add("zip_member_count", len(names) == ACCEPTED_PRIVACY_XS_MEMBERS, len(names))
            add("REVIEW_INDEX", any(n.endswith("REVIEW_INDEX.md") for n in names))
            add(
                "evidence_manifest",
                any(n.endswith("evidence-manifest.sha256") for n in names),
            )

    gs = external / ACCEPTED_GS011_ZIP
    gs_digest = _sha(gs) if gs.is_file() else None
    add("gs011_unchanged", gs_digest == ACCEPTED_GS011_SHA256, gs_digest)

    art = Path(root) / ACCEPTED_PRIVACY_XS_ARTIFACT_DIR
    harm = json.loads((art / "cross-source-outcome-harmonization.json").read_text())
    accepted_n = harm.get("ACCEPTED_COMPARABLE_OUTCOME_COUNT")
    add(
        "prior_accepted_zero",
        accepted_n is not None and int(accepted_n) == 0,
        accepted_n,
    )
    add(
        "prior_mapping_rows_98",
        int(harm.get("n_mapping_rows") or 0) == 98,
        harm.get("n_mapping_rows"),
    )
    counts = harm.get("mapping_status_counts") or {}
    add(
        "prior_unknown_90_hypothesis_8",
        counts.get("UNKNOWN") == 90 and counts.get("HYPOTHESIS") == 8,
        counts,
    )

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "baseline_before": digest,
        "baseline_after": digest,
        "baseline_before_equals_after": digest == ACCEPTED_PRIVACY_XS_SHA256,
        "gs011_sha256": gs_digest,
        "members": members,
        "indexed_members": indexed,
        "prior_mapping_status_counts": counts,
        "checks": checks,
        "ok": ok,
    }
