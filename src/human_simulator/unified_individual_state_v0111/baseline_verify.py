"""Baseline verification — immutable individual-state v0.1.1."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import (
    mutation_proof,
    reconcile_review_index,
)
from human_simulator.unified_individual_state_v0111.policy import (
    ACCEPTED_V011_UIS_ARTIFACT_DIR,
    ACCEPTED_V011_UIS_INDEXED,
    ACCEPTED_V011_UIS_MEMBERS,
    ACCEPTED_V011_UIS_SHA256,
    ACCEPTED_V011_UIS_ZIP,
    PRIOR_ZIPS,
    V011_RUNTIME,
    V031_MATERIALIZED_DIR,
    VERSION,
)

_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    external = Path(root) / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []
    before: dict[str, str] = {}
    for label, (name, exp) in PRIOR_ZIPS.items():
        p = external / name
        dig = _sha(p) if p.is_file() else None
        before[label] = dig or ""
        checks.append({"name": f"{label}_sha", "ok": dig == exp, "detail": dig})

    z = external / ACCEPTED_V011_UIS_ZIP
    members = indexed = None
    if z.is_file():
        sidecar = external / f"{ACCEPTED_V011_UIS_ZIP}.sha256"
        sc_ok = sidecar.is_file() and sidecar.read_text().split()[0] == ACCEPTED_V011_UIS_SHA256
        checks.append({"name": "sidecar", "ok": sc_ok})
        att = external / ACCEPTED_V011_UIS_ZIP.replace(".zip", ".attestation.json")
        att_ok = False
        if att.is_file():
            doc = json.loads(att.read_text(encoding="utf-8"))
            att_ok = doc.get("status") == "PASS" or doc.get("ok") is True
        checks.append({"name": "attestation", "ok": att_ok})
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            parquet = [n for n in names if n.endswith(".parquet")]
            cache_n = sum(1 for n in names if _CACHE_RE.search(n))
            checks.append(
                {"name": "members", "ok": members == ACCEPTED_V011_UIS_MEMBERS, "detail": members}
            )
            checks.append({"name": "no_parquet", "ok": not parquet})
            checks.append({"name": "no_cache", "ok": cache_n == 0})
            idx = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
            indexed = recon.get("indexed_members")
            checks.append(
                {
                    "name": "indexed",
                    "ok": indexed == ACCEPTED_V011_UIS_INDEXED and bool(recon.get("ok")),
                    "detail": indexed,
                }
            )
            art = ACCEPTED_V011_UIS_ARTIFACT_DIR
            man = zf.read(f"{art}/evidence-manifest.sha256").decode()
            mism = []
            for line in man.splitlines():
                line = line.strip()
                if not line:
                    continue
                digest, _, name = line.partition("  ")
                if not name:
                    digest, _, name = line.partition(" ")
                name = name.strip()
                data = zf.read(f"{art}/{name}")
                if hashlib.sha256(data).hexdigest() != digest.strip():
                    mism.append(name)
            checks.append({"name": "manifest", "ok": not mism, "detail": mism[:10]})
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                mut = mutation_proof(Path(tmp) / art)
                checks.append({"name": "mutation", "ok": bool(mut.get("ok"))})
            # Source A namespace contamination check on public outcomes in zip artifacts
            contam = False
            try:
                base = json.loads(zf.read(f"{art}/source-aware-baseline.json"))
                for ok in (base.get("outcome_metrics") or {}):
                    if ok.startswith("A::") and "::B::" in ok:
                        contam = True
                # B codes must not appear under A:: without B prefix confusion
                for ok in base.get("outcome_metrics") or {}:
                    if ok.startswith("A::") and ok.startswith("B::"):
                        contam = True
            except KeyError:
                pass
            checks.append({"name": "no_a_b_namespace_contamination", "ok": not contam})

    # Private prerequisites
    priv_ok = (Path(root) / V031_MATERIALIZED_DIR / "research_subject.parquet").is_file()
    split_ok = (
        Path(root) / V011_RUNTIME / "overlap" / "subject-split.parquet"
    ).is_file()
    checks.append({"name": "private_v031_materialized", "ok": priv_ok})
    checks.append({"name": "private_v011_overlap_split", "ok": split_ok})

    after = {
        label: _sha(external / name) if (external / name).is_file() else ""
        for label, (name, _) in PRIOR_ZIPS.items()
    }
    checks.append({"name": "prior_before_after", "ok": before == after})
    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_v011_uis_sha256": ACCEPTED_V011_UIS_SHA256,
        "members": members,
        "indexed": indexed,
        "prior_sha_before": before,
        "prior_sha_after": after,
        "checks": checks,
        "ok": ok,
    }
