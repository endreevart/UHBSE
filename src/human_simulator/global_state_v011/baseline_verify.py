"""Baseline verification — accepted Global State v0.1 (immutable)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from human_simulator.global_state_v011.policy import (
    ACCEPTED_V01_ARTIFACT_DIR,
    ACCEPTED_V01_INDEXED,
    ACCEPTED_V01_MEMBERS,
    ACCEPTED_V01_RUNTIME_DIR,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    TRAJ_V011_SHA256,
    TRAJ_V011_ZIP,
    VERSION,
)
from human_simulator.global_state_v01.provider_registry import reload_all_providers_equality


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    zip_path = external / ACCEPTED_V01_ZIP
    sidecar = external / f"{ACCEPTED_V01_ZIP}.sha256"
    att_path = external / ACCEPTED_V01_ZIP.replace(".zip", ".attestation.json")
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    digest = _sha(zip_path) if zip_path.is_file() else None
    add("v01_zip_present", zip_path.is_file())
    add("v01_sha256", digest == ACCEPTED_V01_SHA256, digest)
    add("sidecar_present", sidecar.is_file())
    if sidecar.is_file():
        side = sidecar.read_text(encoding="utf-8").strip().split()[0]
        add("sidecar_matches", side == ACCEPTED_V01_SHA256, side)

    members = indexed = None
    if att_path.is_file():
        att = json.loads(att_path.read_text(encoding="utf-8"))
        members = att.get("members")
        indexed = att.get("indexed_members")
        add("attestation_status", att.get("attestation_status") == "PASS")
        add("attestation_sha", att.get("review_zip_sha256") == ACCEPTED_V01_SHA256)
        add(
            "members_indexed",
            members == ACCEPTED_V01_MEMBERS and indexed == ACCEPTED_V01_INDEXED,
            {"members": members, "indexed": indexed},
        )

    if zip_path.is_file():
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            add("zip_member_count", len(names) == ACCEPTED_V01_MEMBERS, len(names))
            add("REVIEW_INDEX_present", any(n.endswith("REVIEW_INDEX.md") for n in names))
            add(
                "evidence_manifest_present",
                any(n.endswith("evidence-manifest.sha256") for n in names),
            )

    # Trajectory expansion v0.1.1 unchanged
    traj = external / TRAJ_V011_ZIP
    traj_digest = _sha(traj) if traj.is_file() else None
    add("traj_v011_unchanged", traj_digest == TRAJ_V011_SHA256, traj_digest)

    art = Path(root) / ACCEPTED_V01_ARTIFACT_DIR
    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    split = json.loads((art / "global-subject-split-contract.json").read_text(encoding="utf-8"))
    cont = json.loads((art / "global-split-contamination.json").read_text(encoding="utf-8"))
    reg = json.loads((art / "global-provider-registry.json").read_text(encoding="utf-8"))
    reload = reload_all_providers_equality(reg)

    n_subj = (split.get("n_subjects") or {})
    add("subjects_43856", int(n_subj.get("total") or 0) == 43856, n_subj)
    add(
        "split_30652_6569_6635",
        int(n_subj.get("train") or 0) == 30652
        and int(n_subj.get("validation") or 0) == 6569
        and int(n_subj.get("test") or 0) == 6635,
        n_subj,
    )
    add(
        "source_b_contamination_zero",
        int(cont.get("source_b_rows_in_universe", -1)) == 0
        and cont.get("GLOBAL_SPLIT_CONTAMINATION_STATUS") == "PASS",
    )
    providers = reg.get("providers") or []
    counts = Counter(p.get("active_provider") for p in providers)
    add("n_providers_95", len(providers) == 95, len(providers))
    add(
        "active_ridge_69_persistence_26",
        counts.get("ridge") == 69 and counts.get("persistence") == 26,
        dict(counts),
    )
    hash_ok = all(
        p.get("model_file_hash") and p.get("model_identity_hash") for p in providers
    )
    add("all_model_hashes_present", hash_ok)
    add("registry_reload_equality", bool(reload.get("ok")), reload)
    add("eligible_grain_count_95", int(st.get("GLOBAL_SPLIT_ELIGIBLE_GRAIN_COUNT") or 0) == 95)

    # Private split presence (runtime, not in ZIP)
    priv_split = Path(root) / ACCEPTED_V01_RUNTIME_DIR / "global-subject-split-manifest.json"
    add("private_split_present", priv_split.is_file())

    provider_hashes_before = [
        {
            "grain_id": p.get("grain_id"),
            "model_file_hash": p.get("model_file_hash"),
            "model_identity_hash": p.get("model_identity_hash"),
        }
        for p in providers
    ]
    provider_hashes_before.sort(key=lambda x: str(x["grain_id"]))
    hashes_digest = hashlib.sha256(
        json.dumps(provider_hashes_before, sort_keys=True).encode()
    ).hexdigest()

    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_v01_sha256_expected": ACCEPTED_V01_SHA256,
        "accepted_v01_sha256_observed": digest,
        "baseline_before": digest,
        "baseline_after": digest,
        "baseline_before_equals_after": digest == ACCEPTED_V01_SHA256,
        "members": members,
        "indexed_members": indexed,
        "n_providers": len(providers),
        "active_provider_counts": dict(counts),
        "registry_hash": reg.get("registry_hash"),
        "provider_hashes_digest_before": hashes_digest,
        "provider_hashes_before": provider_hashes_before,
        "reload_equality": {
            "ok": reload.get("ok"),
            "predictions_hash_before": reload.get("predictions_hash_before"),
            "predictions_hash_after": reload.get("predictions_hash_after"),
            "equality": reload.get("equality"),
        },
        "checks": checks,
        "ok": ok,
    }


def assert_no_refit(
    *,
    hashes_before: list[dict[str, Any]],
    registry_after: dict[str, Any],
) -> dict[str, Any]:
    after = [
        {
            "grain_id": p.get("grain_id"),
            "model_file_hash": p.get("model_file_hash"),
            "model_identity_hash": p.get("model_identity_hash"),
        }
        for p in (registry_after.get("providers") or [])
    ]
    after.sort(key=lambda x: str(x["grain_id"]))
    before_d = hashlib.sha256(json.dumps(hashes_before, sort_keys=True).encode()).hexdigest()
    after_d = hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest()
    equal = before_d == after_d and hashes_before == after
    return {
        "FROZEN_PROVIDER_NO_REFIT_STATUS": "PASS" if equal else "FAIL",
        "provider_hashes_digest_before": before_d,
        "provider_hashes_digest_after": after_d,
        "before_equals_after": equal,
        "n_before": len(hashes_before),
        "n_after": len(after),
        "ok": equal,
    }
