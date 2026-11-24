"""Pinned prior ZIP verification including Integrated Runtime v0.1.1."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import reconcile_review_index
from human_simulator.integrated_research_runtime_v016.hashes import sha256_file
from human_simulator.integrated_research_runtime_v016.policy import (
    PRIOR_ZIPS,
    V011_EXPECTED_INDEXED,
    V011_EXPECTED_MEMBERS,
    V011_EXPECTED_SHA256,
    V012_EXPECTED_INDEXED,
    V012_EXPECTED_MEMBERS,
    V012_EXPECTED_SHA256,
    V013_EXPECTED_INDEXED,
    V013_EXPECTED_MEMBERS,
    V013_EXPECTED_SHA256,
    V014_EXPECTED_INDEXED,
    V014_EXPECTED_MEMBERS,
    V014_EXPECTED_SHA256,
    V015_EXPECTED_INDEXED,
    V015_EXPECTED_MEMBERS,
    V015_EXPECTED_SHA256,
    VERSION,
)


def _sidecar_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").split()[0]


def _attestation_sha(external: Path, zip_name: str) -> str | None:
    for p in (external / zip_name.replace(".zip", ".attestation.json"), external / f"{zip_name}.attestation.json"):
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return str(doc.get("sha256") or doc.get("review_zip_sha256") or "")
    return None


def verify_baseline(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    external = root / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []
    before: dict[str, str] = {}
    records: dict[str, Any] = {}
    for label, (name, exp) in PRIOR_ZIPS.items():
        p = external / name
        dig = sha256_file(p) if p.is_file() else ""
        before[label] = dig
        checks.append({"name": f"{label}_sha", "ok": dig == exp})
        sc = _sidecar_digest(external / f"{name}.sha256")
        checks.append({"name": f"{label}_sidecar", "ok": sc == exp})
        att = _attestation_sha(external, name)
        checks.append({"name": f"{label}_attestation", "ok": att == exp})
        rec: dict[str, Any] = {"zip": name, "sha256": dig}
        if p.is_file():
            with zipfile.ZipFile(p) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                rec["members"] = len(names)
                rec["has_parquet"] = any(n.endswith(".parquet") for n in names)
                idx_name = next((n for n in names if n.endswith("REVIEW_INDEX.md")), None)
                if idx_name:
                    idx = zf.read(idx_name).decode("utf-8")
                    payloads = {n: zf.read(n) for n in names if n != idx_name}
                    recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
                    rec["indexed"] = recon.get("indexed_members")
                    member_ok = bool(recon.get("ok")) and rec["members"] == (rec["indexed"] or 0) + 1
                    if label == "irr_v015":
                        member_ok = (
                            member_ok
                            and rec["members"] == V015_EXPECTED_MEMBERS
                            and rec["indexed"] == V015_EXPECTED_INDEXED
                            and dig == V015_EXPECTED_SHA256
                        )
                    if label == "irr_v014":
                        member_ok = (
                            member_ok
                            and rec["members"] == V014_EXPECTED_MEMBERS
                            and rec["indexed"] == V014_EXPECTED_INDEXED
                            and dig == V014_EXPECTED_SHA256
                        )
                    if label == "irr_v013":
                        member_ok = (
                            member_ok
                            and rec["members"] == V013_EXPECTED_MEMBERS
                            and rec["indexed"] == V013_EXPECTED_INDEXED
                            and dig == V013_EXPECTED_SHA256
                        )
                    if label == "irr_v012":
                        member_ok = (
                            member_ok
                            and rec["members"] == V012_EXPECTED_MEMBERS
                            and rec["indexed"] == V012_EXPECTED_INDEXED
                            and dig == V012_EXPECTED_SHA256
                        )
                    if label == "irr_v011":
                        member_ok = (
                            member_ok
                            and rec["members"] == V011_EXPECTED_MEMBERS
                            and rec["indexed"] == V011_EXPECTED_INDEXED
                            and dig == V011_EXPECTED_SHA256
                        )
                    checks.append({"name": f"{label}_members_indexed", "ok": member_ok})
                checks.append({"name": f"{label}_no_parquet", "ok": not rec["has_parquet"]})
        records[label] = rec
    after = {label: sha256_file(external / name) if (external / name).is_file() else "" for label, (name, _) in PRIOR_ZIPS.items()}
    checks.append({"name": "prior_before_after", "ok": before == after})
    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "prior_sha_before": before,
        "checks": checks,
        "records": records,
        "ok": ok,
    }
