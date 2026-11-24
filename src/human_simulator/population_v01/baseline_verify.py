"""Verify accepted baselines before population stage work."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.population_v01.policy import (
    ACCEPTED_V02_SHA256,
    ACCEPTED_V02_ZIP,
    FROZEN_V02_FILE_SHA,
    FROZEN_V02_IDENTITY_SHA,
    PRIOR_IMMUTABLE_ZIPS,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_accepted_baselines(root: Path) -> dict[str, Any]:
    root = root.resolve()
    ext = root / "artifacts" / "external-review"
    zip_path = ext / ACCEPTED_V02_ZIP
    sidecar = ext / f"{ACCEPTED_V02_ZIP}.sha256"
    att = ext / ACCEPTED_V02_ZIP.replace(".zip", ".attestation.json")

    checks: dict[str, Any] = {}
    checks["zip_exists"] = zip_path.is_file()
    got = _sha(zip_path) if zip_path.is_file() else None
    checks["zip_sha256"] = got
    checks["zip_sha_matches_expected"] = got == ACCEPTED_V02_SHA256
    if sidecar.is_file():
        side_sha = sidecar.read_text().split()[0]
        checks["sidecar_matches_zip"] = side_sha == got
    else:
        checks["sidecar_matches_zip"] = False

    if att.is_file():
        att_doc = json.loads(att.read_text())
        checks["attestation_status"] = att_doc.get("attestation_status")
        checks["attestation_sha_matches"] = att_doc.get("review_zip_sha256") == got
    else:
        checks["attestation_status"] = None
        checks["attestation_sha_matches"] = False

    review_index_ok = False
    frozen_file_ok = False
    frozen_identity_ok = False
    internal_manifest_ok = False
    if zip_path.is_file():
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            review_index_ok = "REVIEW_INDEX.md" in names
            # find evidence manifest
            man_names = [n for n in names if n.endswith("evidence-manifest.sha256")]
            if man_names:
                man_text = zf.read(man_names[0]).decode()
                mismatches = []
                for line in man_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    digest, _, name = line.partition("  ")
                    if not name:
                        digest, _, name = line.partition(" ")
                    # path relative to artifact dir inside zip
                    base = Path(man_names[0]).parent.as_posix()
                    member = f"{base}/{name.strip()}" if base != "." else name.strip()
                    # try both
                    candidates = [member, name.strip()]
                    found = None
                    for c in candidates:
                        if c in names:
                            found = c
                            break
                    if not found:
                        # search by basename
                        bn = Path(name.strip()).name
                        hits = [n for n in names if n.endswith("/" + bn) or n == bn]
                        found = hits[0] if hits else None
                    if not found:
                        mismatches.append(name)
                        continue
                    if hashlib.sha256(zf.read(found)).hexdigest() != digest.strip():
                        mismatches.append(name)
                internal_manifest_ok = not mismatches
                checks["internal_manifest_mismatches"] = mismatches[:20]
            frozen = [
                n
                for n in names
                if n.endswith("frozen-source-a-model-v0.2.json")
            ]
            if frozen:
                fbytes = zf.read(frozen[0])
                frozen_file_ok = hashlib.sha256(fbytes).hexdigest() == FROZEN_V02_FILE_SHA
                try:
                    fdoc = json.loads(fbytes)
                    ident = (
                        fdoc.get("canonical_model_identity_sha256")
                        or fdoc.get("model_identity_sha256")
                        or fdoc.get("identity_sha256")
                    )
                    if ident is None:
                        # Prefer companion identity member inside the same ZIP.
                        id_members = [
                            n
                            for n in names
                            if n.endswith("frozen-source-a-model-v0.2.identity.json")
                        ]
                        if id_members:
                            idoc = json.loads(zf.read(id_members[0]))
                            ident = idoc.get("canonical_model_identity_sha256")
                    frozen_identity_ok = ident == FROZEN_V02_IDENTITY_SHA
                    checks["frozen_identity_sha256"] = ident
                except json.JSONDecodeError:
                    frozen_identity_ok = False

    checks["review_index_present"] = review_index_ok
    checks["internal_manifest_ok"] = internal_manifest_ok
    checks["frozen_file_sha_ok"] = frozen_file_ok
    checks["frozen_identity_sha_ok"] = frozen_identity_ok

    prior_rows = []
    for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items():
        p = ext / name
        g = _sha(p) if p.is_file() else None
        prior_rows.append(
            {
                "label": label,
                "filename": name,
                "expected": exp,
                "got": g,
                "matches": g == exp,
            }
        )
    checks["prior_immutable"] = prior_rows
    checks["prior_all_match"] = all(r["matches"] for r in prior_rows)

    ok = all(
        [
            checks["zip_sha_matches_expected"],
            checks["sidecar_matches_zip"],
            checks.get("attestation_status") == "PASS",
            checks["attestation_sha_matches"],
            checks["review_index_present"],
            checks["internal_manifest_ok"],
            checks["frozen_file_sha_ok"],
            checks["frozen_identity_sha_ok"],
            checks["prior_all_match"],
        ]
    )
    return {
        "baseline_verification_status": "PASS" if ok else "FAIL",
        "ok": ok,
        "checks": checks,
        "accepted_zip": ACCEPTED_V02_ZIP,
        "accepted_sha256": ACCEPTED_V02_SHA256,
        "expected_frozen_file_sha": FROZEN_V02_FILE_SHA,
        "expected_frozen_identity_sha": FROZEN_V02_IDENTITY_SHA,
    }
