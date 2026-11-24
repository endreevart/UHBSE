"""Publish refuse-if-exists review ZIP — privacy + cross-source harmonization v0.1."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.privacy_cross_source_v01.policy import (
    ACCEPTED_CONCEPT_PILOT_SHA256,
    ACCEPTED_CONCEPT_PILOT_ZIP,
    ACCEPTED_GS01_SHA256,
    ACCEPTED_GS01_ZIP,
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_TRAJ011_SHA256,
    ACCEPTED_TRAJ011_ZIP,
    ACCEPTED_UNIFIED_V01211_SHA256,
    ACCEPTED_UNIFIED_V01211_ZIP,
    ARTIFACT_DIR,
    REVIEW_ZIP,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_v012.publication_fixes import assert_attestation_index_fields

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_privacy_cross_source_v01_unit.py",
    "tests/test_privacy_cross_source_v01_contracts.py",
)

PRIOR_IMMUTABLE_ZIPS = {
    "global_state_v0.1.1": (ACCEPTED_GS011_ZIP, ACCEPTED_GS011_SHA256),
    "global_state_v0.1": (ACCEPTED_GS01_ZIP, ACCEPTED_GS01_SHA256),
    "trajectory_v0.1.1": (ACCEPTED_TRAJ011_ZIP, ACCEPTED_TRAJ011_SHA256),
    "unified_v0.1.2.1.1": (ACCEPTED_UNIFIED_V01211_ZIP, ACCEPTED_UNIFIED_V01211_SHA256),
    "concept_pilot_v0.1": (ACCEPTED_CONCEPT_PILOT_ZIP, ACCEPTED_CONCEPT_PILOT_SHA256),
}


class PublicationError(RuntimeError):
    pass


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _sha_b(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def verify_manifest(d: Path) -> dict[str, Any]:
    man = d / "evidence-manifest.sha256"
    if not man.is_file():
        return {"ok": False, "reason": "missing"}
    mismatches = []
    checked = 0
    for line in man.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        path = d / name.strip()
        if not path.is_file():
            mismatches.append(name)
            continue
        checked += 1
        if _sha(path) != digest.strip():
            mismatches.append(name)
    return {"ok": not mismatches, "checked": checked, "mismatches": mismatches}


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n"
    )


def _excluded(rel: str) -> bool:
    p = Path(rel)
    if "external-review" in p.parts or "__pycache__" in p.parts or p.name == ".DS_Store":
        return True
    if p.suffix.lower() == ".zip" or "dumps" in p.parts or "private" in p.parts:
        return True
    return False


def _add_tree(payloads: dict[str, bytes], root: Path, rel: str) -> None:
    base = root / rel
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        r = path.relative_to(root).as_posix()
        if _excluded(r):
            continue
        if path.suffix.lower() in {".mp4", ".wav", ".png", ".jpg", ".zip", ".dump"}:
            continue
        if path.suffix in {
            ".py",
            ".md",
            ".toml",
            ".txt",
            ".json",
            ".sha256",
            ".yaml",
            ".yml",
            ".typed",
        } or rel.startswith("artifacts/"):
            payloads[r] = path.read_bytes()


def scan_row_level(payloads: dict[str, bytes]) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    identity_keys = (
        "opaque_subject_key",
        "research_subject_id",
        "source_subject_id",
        "patient_id",
        "pair_id",
        "component_id",
        "observation_id",
    )
    for name, data in payloads.items():
        if not name.endswith(".json"):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for key in identity_keys:
            if re.search(rf'"{re.escape(key)}"\s*:', text):
                hits.append({"member": name, "key": key, "kind": "identity_or_locator_key"})
        if "uhbse-research-hmac" in text or "UHBSE_RESEARCH_HMAC_KEY" in text:
            hits.append({"member": name, "key": "hmac", "kind": "secret_reference"})
    return {
        "ok": len(hits) == 0,
        "n_hits": len(hits),
        "hits": hits[:50],
        "row_level_data_in_zip": len(hits) != 0,
    }


def publish(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    external = root / "artifacts" / "external-review"
    external.mkdir(parents=True, exist_ok=True)
    zip_path = external / ZIP_NAME
    sidecar = external / SHA_NAME
    att_path = external / ATT_NAME
    for p in (zip_path, sidecar, att_path):
        if p.exists():
            raise PublicationError(f"refuse overwrite: {p.name}")

    prior_before = {}
    for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items():
        p = external / name
        if not p.is_file() or _sha(p) != exp:
            raise PublicationError(f"baseline fail: {name}")
        prior_before[label] = _sha(p)

    art = root / ARTIFACT_DIR
    if not (art / "verification.json").is_file():
        raise PublicationError("run privacy-cross-source run-v0.1 first")
    ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
    if not ver.get("ok"):
        raise PublicationError("refuse publish: verification.ok is false")

    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    required = {
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "PRIVACY_BOUNDARY_STATUS": "PASS",
        "SOURCE_B_LONGITUDINAL_INVENTORY_STATUS": "PASS",
        "SOURCE_B_GLOBAL_SPLIT_STATUS": "PASS",
        "PARTIAL_SUPPORT_ACCOUNTING_STATUS": "PASS",
        "SAME_TIMESTAMP_PRESELECTION_AUDIT_STATUS": "PASS",
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
    }
    for k, exp in required.items():
        if st.get(k) != exp:
            raise PublicationError(f"refuse publish: {k}={st.get(k)} expected {exp}")

    st["PUBLIC_DATA_MINIMIZATION_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["PUBLICATION_INTEGRITY_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["CONTENT_PREPACK_STATUS"] = "PASS"
    (art / "status-contract.json").write_text(
        json.dumps({"version": VERSION, **{k: v for k, v in st.items() if k != "version"}}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce — Privacy + Cross-Source Harmonization v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_privacy_cross_source_v01*.py -q
uv run --frozen audit --root . privacy-cross-source verify-v0.1
```

Private rebuild needs Source A/B + canonical DB + HMAC runtime secrets (never in ZIP).
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Privacy + Cross-Source Harmonization v{VERSION}

Honest readiness: ACCEPTED_COMPARABLE_OUTCOME_COUNT may be 0.
Zero-shot not invented from HYPOTHESIS mappings.
Post-pack PASS only in external attestation.
Security remains PAUSED_NOT_ACCEPTED_BY_OWNER.
""",
        encoding="utf-8",
    )

    write_manifest(art)
    if not verify_manifest(art)["ok"]:
        raise PublicationError("manifest FAIL")

    scope = art / "policy.json"
    original = scope.read_bytes()
    scope.write_bytes(original + b"\n")
    failed = not verify_manifest(art)["ok"]
    scope.write_bytes(original)
    restored = verify_manifest(art)["ok"]
    mutation = {"ok": failed and restored}
    (art / "manifest-mutation-proof.json").write_text(json.dumps(mutation, indent=2) + "\n")
    write_manifest(art)

    payloads: dict[str, bytes] = {}
    _add_tree(payloads, root, ARTIFACT_DIR)
    _add_tree(payloads, root, "src/human_simulator")
    for rel in (
        "src/human_simulator/__init__.py",
        "src/human_simulator/cli.py",
        "docs/current-stage.md",
        "AGENTS.md",
        *UNIT_TESTS,
        "pyproject.toml",
        "uv.lock",
    ):
        p = root / rel
        if p.is_file():
            payloads[rel] = p.read_bytes()
    payloads["REPRODUCE.md"] = (art / "REPRODUCE.md").read_bytes()
    payloads["REVIEW_GUIDE.md"] = (art / "REVIEW_GUIDE.md").read_bytes()

    row_scan = scan_row_level(payloads)
    (art / "public-data-minimization-scan.json").write_text(json.dumps(row_scan, indent=2) + "\n")
    payloads[f"{ARTIFACT_DIR}/public-data-minimization-scan.json"] = (
        art / "public-data-minimization-scan.json"
    ).read_bytes()
    write_manifest(art)
    payloads[f"{ARTIFACT_DIR}/evidence-manifest.sha256"] = (
        art / "evidence-manifest.sha256"
    ).read_bytes()
    payloads[f"{ARTIFACT_DIR}/status-contract.json"] = (
        art / "status-contract.json"
    ).read_bytes()
    if not row_scan["ok"]:
        raise PublicationError(f"row-level keys: {row_scan['hits'][:10]}")

    with tempfile.TemporaryDirectory(prefix="uhbse-privacy-xs-v01-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        pkg = staging / "src" / "human_simulator"
        pkg.mkdir(parents=True, exist_ok=True)
        init = pkg / "__init__.py"
        if not init.is_file():
            init.write_text("", encoding="utf-8")

        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest tests/test_privacy_cross_source_v01*.py -q && "
            "uv run --frozen audit --root . privacy-cross-source verify-v0.1"
        )
        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
        )
        unit_out = (proc.stdout or "") + (proc.stderr or "")
        unit = {
            "exit_code": proc.returncode,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "output_tail": unit_out[-6000:],
            "literal_command": cmd,
        }
        m = re.search(r"(\d+)\s+passed", unit_out)
        unit["passed"] = int(m.group(1)) if m else None
        if unit["status"] != "PASS":
            raise PublicationError(f"clean-room FAIL: {unit}")

        index_lines = [
            f"# REVIEW_INDEX — Privacy Boundary + Cross-Source Harmonization v{VERSION}",
            "",
            "| Path | SHA-256 |",
            "|------|---------|",
        ]
        for name in sorted(payloads):
            index_lines.append(f"| `{name}` | `{_sha_b(payloads[name])}` |")
        index = ("\n".join(index_lines) + "\n").encode()

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(payloads):
                info = zipfile.ZipInfo(name)
                info.date_time = (2026, 8, 25, 14, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 25, 14, 0, 0)
            zf.writestr(info, index)

    zip_sha = _sha(zip_path)
    sidecar.write_text(f"{zip_sha}  {ZIP_NAME}\n")

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        with tempfile.TemporaryDirectory() as etmp:
            zf.extractall(etmp)
            if not verify_manifest(Path(etmp) / ARTIFACT_DIR)["ok"]:
                raise PublicationError("extract manifest FAIL")

    indexed = len(payloads)
    chk = assert_attestation_index_fields(members=len(members), indexed_members=indexed)
    if not chk["accepted"]:
        raise PublicationError(f"index invariant FAIL: {chk}")

    prior_ok = True
    prior_after = {}
    for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items():
        got = _sha(external / name)
        prior_after[label] = got
        if got != exp or got != prior_before[label]:
            prior_ok = False

    attestation = {
        "bundle_kind": "privacy_boundary_cross_source_longitudinal_harmonization_v01",
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "PUBLICATION_INTEGRITY_STATUS": "PASS" if prior_ok else "FAIL",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS" if row_scan["ok"] else "FAIL",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": "PASS" if unit["status"] == "PASS" else "FAIL",
        "CONTENT_PREPACK_STATUS": "PASS",
        "CLEAN_STAGING_STATUS": "PASS" if unit["status"] == "PASS" else "FAIL",
        "POST_PACK_INSIDE_ZIP_STATUS": "EXTERNAL_ATTESTATION_REQUIRED",
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(members),
        "indexed_members": indexed,
        "members_equals_indexed_plus_one": len(members) == indexed + 1,
        "unit_reproduce": unit,
        "manifest_mutation_proof": mutation,
        "row_level_data_in_zip": False,
        "prior_immutable_zips_untouched": prior_ok,
        "prior_sha256": prior_after,
        "accepted_gs011_sha256": ACCEPTED_GS011_SHA256,
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "ACCEPTED_COMPARABLE_OUTCOME_COUNT": st.get("ACCEPTED_COMPARABLE_OUTCOME_COUNT"),
        "A_TO_B_ZERO_SHOT_SHADOW_STATUS": st.get("A_TO_B_ZERO_SHOT_SHADOW_STATUS"),
        "policy": policy_snapshot(),
    }
    ok = (
        prior_ok
        and unit["status"] == "PASS"
        and mutation["ok"]
        and attestation["members_equals_indexed_plus_one"]
        and row_scan["ok"]
    )
    attestation["attestation_status"] = "PASS" if ok else "FAIL"
    att_path.write_text(json.dumps(attestation, indent=2) + "\n")
    if not ok:
        raise PublicationError("attestation FAIL")
    return {
        "zip": str(zip_path),
        "sidecar": str(sidecar),
        "attestation": str(att_path),
        "sha256": zip_sha,
        "members": len(members),
        "indexed_members": indexed,
        "attestation_status": "PASS",
    }
