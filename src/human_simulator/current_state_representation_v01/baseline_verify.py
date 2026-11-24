"""Baseline verification — immutable individual-state v0.1.1.1."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.cross_source_lab_semantic_v021.publish import (
    mutation_proof,
    reconcile_review_index,
)
from human_simulator.current_state_representation_v01.policy import (
    ACCEPTED_V0111_ARTIFACT_DIR,
    ACCEPTED_V0111_INDEXED,
    ACCEPTED_V0111_MEMBERS,
    ACCEPTED_V0111_SHA256,
    ACCEPTED_V0111_ZIP,
    PRIOR_ZIPS,
    V0111_OVERLAP_DIR,
    V0111_STATES_DIR,
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

    z = external / ACCEPTED_V0111_ZIP
    members = indexed = None
    if z.is_file():
        sc = external / f"{ACCEPTED_V0111_ZIP}.sha256"
        checks.append(
            {
                "name": "sidecar",
                "ok": sc.is_file() and sc.read_text().split()[0] == ACCEPTED_V0111_SHA256,
            }
        )
        att = external / ACCEPTED_V0111_ZIP.replace(".zip", ".attestation.json")
        att_ok = False
        if att.is_file():
            doc = json.loads(att.read_text(encoding="utf-8"))
            att_ok = doc.get("status") == "PASS" or doc.get("ok") is True
        checks.append({"name": "attestation", "ok": att_ok})
        with zipfile.ZipFile(z) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            members = len(names)
            checks.append(
                {
                    "name": "members",
                    "ok": members == ACCEPTED_V0111_MEMBERS,
                    "detail": members,
                }
            )
            checks.append(
                {"name": "no_parquet", "ok": not any(n.endswith(".parquet") for n in names)}
            )
            checks.append(
                {
                    "name": "no_cache",
                    "ok": sum(1 for n in names if _CACHE_RE.search(n)) == 0,
                }
            )
            idx = zf.read("REVIEW_INDEX.md").decode()
            payloads = {n: zf.read(n) for n in names if n != "REVIEW_INDEX.md"}
            recon = reconcile_review_index(names, idx, payloads_on_disk=payloads)
            indexed = recon.get("indexed_members")
            checks.append(
                {
                    "name": "indexed",
                    "ok": indexed == ACCEPTED_V0111_INDEXED and bool(recon.get("ok")),
                    "detail": indexed,
                }
            )
            art = ACCEPTED_V0111_ARTIFACT_DIR
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
            checks.append({"name": "manifest", "ok": not mism})
            with tempfile.TemporaryDirectory() as tmp:
                zf.extractall(tmp)
                checks.append(
                    {"name": "mutation", "ok": bool(mutation_proof(Path(tmp) / art).get("ok"))}
                )

    # Private prerequisites
    st_path = root / V0111_STATES_DIR / "individual_state.parquet"
    tg_path = root / V0111_STATES_DIR / "individual_state_target.parquet"
    sp_path = root / V0111_OVERLAP_DIR / "subject-split.parquet"
    checks.append({"name": "private_states", "ok": st_path.is_file()})
    checks.append({"name": "private_targets", "ok": tg_path.is_file()})
    checks.append({"name": "private_split", "ok": sp_path.is_file()})

    reuse_ok = temporal_ok = namespaces_ok = False
    if tg_path.is_file() and st_path.is_file():
        art_local = root / ACCEPTED_V0111_ARTIFACT_DIR
        sm = json.loads((art_local / "individual-state-dataset.json").read_text())
        reuse_ok = sm.get("TARGET_REUSE_AUDIT_STATUS") == "PASS"
        temporal_ok = sm.get("STATE_TEMPORAL_LEAKAGE_STATUS") == "PASS"
        # namespaces
        outs = set(pq.read_table(tg_path, columns=["outcome_key"])["outcome_key"].to_pylist())
        namespaces_ok = all(o.startswith("A::") or o.startswith("B::") for o in outs) and any(
            o.startswith("A::") for o in outs
        ) and any(o.startswith("B::") for o in outs)
        # no contamination
        namespaces_ok = namespaces_ok and not any(
            o.startswith("A::") and o.startswith("B::") for o in outs
        )
    checks.append({"name": "target_reuse_zero", "ok": reuse_ok})
    checks.append({"name": "temporal_leakage_zero", "ok": temporal_ok})
    checks.append({"name": "a_b_namespaces", "ok": namespaces_ok})
    checks.append(
        {
            "name": "overlap_guarded_split",
            "ok": (
                json.loads(
                    (root / ACCEPTED_V0111_ARTIFACT_DIR / "status-contract.json").read_text()
                ).get("GLOBAL_A_B_SPLIT_STATUS")
                == "PASS_OVERLAP_GUARDED"
            )
            if (root / ACCEPTED_V0111_ARTIFACT_DIR / "status-contract.json").is_file()
            else False,
        }
    )

    after = {
        label: _sha(external / name) if (external / name).is_file() else ""
        for label, (name, _) in PRIOR_ZIPS.items()
    }
    checks.append({"name": "prior_before_after", "ok": before == after})
    ok = all(c["ok"] for c in checks)
    return {
        "version": VERSION,
        "BASELINE_VERIFICATION_STATUS": "PASS" if ok else "FAIL",
        "accepted_v0111_sha256": ACCEPTED_V0111_SHA256,
        "members": members,
        "indexed": indexed,
        "prior_sha_before": before,
        "prior_sha_after": after,
        "checks": checks,
        "ok": ok,
    }
