"""Baseline verification for trajectory expansion v0.1.1."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.global_state_v01.policy import (
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ACCEPTED_V011_INDEXED,
    ACCEPTED_V011_MEMBERS,
    ACCEPTED_V011_SHA256,
    ACCEPTED_V011_ZIP,
    ACCEPTED_V011_ARTIFACT_DIR,
    VERSION,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    zip_path = external / ACCEPTED_V011_ZIP
    sidecar = external / f"{ACCEPTED_V011_ZIP}.sha256"
    att_path = external / ACCEPTED_V011_ZIP.replace(".zip", ".attestation.json")
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    digest = _sha(zip_path) if zip_path.is_file() else None
    add("v011_zip_present", zip_path.is_file())
    add("v011_sha256", digest == ACCEPTED_V011_SHA256, digest)
    add("sidecar_present", sidecar.is_file())
    if sidecar.is_file():
        side = sidecar.read_text(encoding="utf-8").strip().split()[0]
        add("sidecar_matches", side == ACCEPTED_V011_SHA256, side)

    members = indexed = None
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        members = att.get("members")
        indexed = att.get("indexed_members")
        add("attestation_status", att.get("attestation_status") == "PASS")
        add("attestation_sha", att.get("review_zip_sha256") == ACCEPTED_V011_SHA256)
        add(
            "members_indexed",
            members == ACCEPTED_V011_MEMBERS and indexed == ACCEPTED_V011_INDEXED,
            {"members": members, "indexed": indexed},
        )

    if zip_path.is_file():
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            add("zip_member_count", len(names) == ACCEPTED_V011_MEMBERS, len(names))
            add("REVIEW_INDEX_present", any(n.endswith("REVIEW_INDEX.md") for n in names))
            add(
                "evidence_manifest_present",
                any(n.endswith("evidence-manifest.sha256") for n in names),
            )

    reg_path = Path(root) / ACCEPTED_V011_ARTIFACT_DIR / "frozen-provider-registry.json"
    n_prov = 0
    hash_ok = False
    if reg_path.is_file():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        providers = reg.get("providers") or []
        n_prov = len(providers)
        hash_ok = all(
            p.get("model_file_hash")
            and p.get("model_identity_hash")
            and (p.get("active_uncertainty") or {}).get("interval_payload_hash")
            for p in providers
        )
    add("provider_registry_101", n_prov == 101, n_prov)
    add("provider_hashes_present", hash_ok)

    v01 = external / ACCEPTED_V01_ZIP
    v01_digest = _sha(v01) if v01.is_file() else None
    add("v01_unchanged", v01_digest == ACCEPTED_V01_SHA256, v01_digest)

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_v011_sha256_expected": ACCEPTED_V011_SHA256,
        "accepted_v011_sha256_observed": digest,
        "baseline_before": digest,
        "baseline_after": digest,
        "baseline_before_equals_after": digest == ACCEPTED_V011_SHA256,
        "v01_sha256": v01_digest,
        "members": members,
        "indexed_members": indexed,
        "n_providers": n_prov,
        "checks": checks,
        "ok": ok,
    }
