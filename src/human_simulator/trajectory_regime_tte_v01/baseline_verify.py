"""Baseline verification — CSR v0.1 + v0.1.1.1 immutable."""

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
from human_simulator.trajectory_regime_tte_v01.policy import (
    ACCEPTED_CSR_ARTIFACT_DIR,
    ACCEPTED_CSR_INDEXED,
    ACCEPTED_CSR_MEMBERS,
    ACCEPTED_CSR_SHA256,
    ACCEPTED_CSR_ZIP,
    ACCEPTED_V0111_SHA256,
    ACCEPTED_V0111_ZIP,
    CSR_TENSOR_DIR,
    PRIOR_ZIPS,
    VERSION,
)

_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_baseline(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    external = root / "artifacts" / "external-review"
    checks: list[dict[str, Any]] = []
    before: dict[str, str] = {}
    for label, (name, exp) in PRIOR_ZIPS.items():
        p = external / name
        dig = _sha(p) if p.is_file() else None
        before[label] = dig or ""
        checks.append({"name": f"{label}_sha", "ok": dig == exp, "detail": dig})

    z = external / ACCEPTED_CSR_ZIP
    members = indexed = None
    if z.is_file():
        sc = external / f"{ACCEPTED_CSR_ZIP}.sha256"
        checks.append(
            {
                "name": "csr_sidecar",
                "ok": sc.is_file() and sc.read_text().split()[0] == ACCEPTED_CSR_SHA256,
            }
        )
        att = external / ACCEPTED_CSR_ZIP.replace(".zip", ".attestation.json")
        att_ok = False
        if att.is_file():
            doc = json.loads(att.read_text(encoding="utf-8"))
            att_ok = doc.get("status") == "PASS" or doc.get("ok") is True
        checks.append({"name": "csr_attestation", "ok": att_ok})
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            checks.append(
                {"name": "csr_members", "ok": members == ACCEPTED_CSR_MEMBERS, "detail": members}
            )
            checks.append(
                {"name": "csr_no_parquet", "ok": not any(n.endswith(".parquet") for n in names)}
            )
            idx = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
            indexed = recon.get("indexed_members")
            checks.append(
                {
                    "name": "csr_indexed",
                    "ok": indexed == ACCEPTED_CSR_INDEXED and bool(recon.get("ok")),
                    "detail": indexed,
                }
            )
            art = ACCEPTED_CSR_ARTIFACT_DIR
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
            checks.append({"name": "csr_manifest", "ok": not mism})
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                checks.append(
                    {
                        "name": "csr_mutation",
                        "ok": bool(mutation_proof(Path(tmp) / art).get("ok")),
                    }
                )

    v0111 = external / ACCEPTED_V0111_ZIP
    checks.append(
        {
            "name": "v0111_sha",
            "ok": v0111.is_file() and _sha(v0111) == ACCEPTED_V0111_SHA256,
        }
    )

    tensor_path = root / CSR_TENSOR_DIR / "current_state_tensor.parquet"
    checks.append({"name": "private_csr_tensor", "ok": tensor_path.is_file()})

    after = {
        label: _sha(external / name) if (external / name).is_file() else ""
        for label, (name, _) in PRIOR_ZIPS.items()
    }
    checks.append({"name": "prior_before_after", "ok": before == after})
    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_csr_sha256": ACCEPTED_CSR_SHA256,
        "accepted_v0111_sha256": ACCEPTED_V0111_SHA256,
        "members": members,
        "indexed": indexed,
        "prior_sha_before": before,
        "prior_sha_after": after,
        "checks": checks,
        "ok": ok,
    }
