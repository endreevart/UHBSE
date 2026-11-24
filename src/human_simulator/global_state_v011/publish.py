"""Publish refuse-if-exists review ZIP for global-state v0.1.1.

Publication lifecycle:
- content / pre-pack / clean-staging checks → PASS inside artifacts when green
- post-pack checks inside ZIP → EXTERNAL_ATTESTATION_REQUIRED (never claim PASS post-pack in ZIP)
- final PASS only in external attestation sidecar
"""

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

from human_simulator.global_state_v011.policy import (
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ARTIFACT_DIR,
    REVIEW_ZIP,
    TRAJ_V011_SHA256,
    TRAJ_V011_ZIP,
    VERSION,
    policy_snapshot,
)
from human_simulator.unified_v012.publication_fixes import assert_attestation_index_fields

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_global_state_v011_unit.py",
    "tests/test_global_state_v011_contracts.py",
)

PRIOR_IMMUTABLE_ZIPS = {
    "global_state_v0.1": (ACCEPTED_V01_ZIP, ACCEPTED_V01_SHA256),
    "trajectory_expansion_v0.1.1": (TRAJ_V011_ZIP, TRAJ_V011_SHA256),
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
    identity_keys = ("opaque_subject_key", "pair_id", "component_id", "observation_id")
    for name, data in payloads.items():
        if not name.endswith(".json"):
            continue
        # Allow registry/grain technical hashes; refuse locator/identity keys in public JSON
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for key in identity_keys:
            if re.search(rf'"{re.escape(key)}"\s*:', text):
                hits.append({"member": name, "key": key, "kind": "identity_or_locator_key"})
        if re.search(r'"(t0|t1)"\s*:\s*"\d{4}-\d{2}-\d{2}', text):
            hits.append({"member": name, "key": "t0/t1", "kind": "timestamp_value"})
        if re.search(
            r'"y_t0"\s*:\s*-?\d+(?:\.\d+)?\s*,\s*"y_t1"\s*:\s*-?\d+',
            text,
        ):
            hits.append({"member": name, "key": "y_t0+y_t1", "kind": "pair_value_record"})
    return {
        "ok": len(hits) == 0,
        "n_hits": len(hits),
        "hits": hits[:50],
        "row_level_data_in_zip": len(hits) != 0,
    }


def _assert_publication_lifecycle(st: dict[str, Any]) -> None:
    for k in (
        "PUBLIC_DATA_MINIMIZATION_STATUS",
        "REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS",
        "PUBLICATION_INTEGRITY_STATUS",
    ):
        if st.get(k) == "PASS":
            raise PublicationError(
                f"refuse: {k}=PASS inside ZIP is forbidden; use EXTERNAL_ATTESTATION_REQUIRED"
            )
        if st.get(k) != "EXTERNAL_ATTESTATION_REQUIRED":
            raise PublicationError(f"refuse: {k}={st.get(k)} expected EXTERNAL_ATTESTATION_REQUIRED")


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
        raise PublicationError("run global-state run-v0.1.1 first")

    ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
    if not ver.get("ok"):
        raise PublicationError("refuse publish: verification.ok is false")

    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    required = {
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "FROZEN_PROVIDER_NO_REFIT_STATUS": "PASS",
        "HORIZON_ALIGNMENT_STATUS": "PASS",
        "TARGET_REUSE_AUDIT_STATUS": "PASS",
        "GLOBAL_TEST_POPULATION_EVALUATION_STATUS": "PASS",
        "PER_OUTCOME_EVIDENCE_TIER_STATUS": "PASS",
        "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS": "PASS",
        "GLOBAL_PROVIDER_REGISTRY_STATUS": "PASS",
        "ENGINE_REAL_HELDOUT_TRAJECTORY_STATUS": "TECHNICAL_REAL_HELDOUT_PASS",
        "PRIOR_V01_BACKTEST_HORIZON_STATUS": "INVALID_FOR_HORIZON_ALIGNED_EVALUATION",
    }
    for k, exp in required.items():
        if st.get(k) != exp:
            raise PublicationError(f"refuse publish: {k}={st.get(k)} expected {exp}")

    # Ensure post-pack statuses are attestation-required BEFORE packing
    st["PUBLIC_DATA_MINIMIZATION_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["PUBLICATION_INTEGRITY_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st["CONTENT_PREPACK_STATUS"] = "PASS"
    (art / "status-contract.json").write_text(
        json.dumps({"version": VERSION, **{k: v for k, v in st.items() if k != "version"}}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    _assert_publication_lifecycle(st)

    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce — Global Split Individual Multi-Outcome State v{VERSION}

Self-contained verification (no clinical DB):

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_global_state_v011*.py -q
uv run --frozen audit --root . global-state verify-v0.1.1
```

Private full rebuild requires configured Source A DB + HMAC:

```bash
uv run --frozen audit --root . global-state run-v0.1.1 --no-publish
```

Do not overwrite global-state v0.1 or trajectory-expansion v0.1.1 ZIPs.
Post-pack PASS exists only in the external attestation, not inside this ZIP.
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Global State v{VERSION}

Corrective over accepted v0.1 (`{ACCEPTED_V01_SHA256[:16]}…`).
Horizon-aligned full-test backtest; frozen providers not refit.
Claim level: SECONDARY_EXPLORATORY_RETROSPECTIVE_BACKTEST.
Inside ZIP: PUBLIC_* post-pack statuses = EXTERNAL_ATTESTATION_REQUIRED.
Security remains PAUSED_NOT_ACCEPTED_BY_OWNER.
""",
        encoding="utf-8",
    )

    write_manifest(art)
    if not verify_manifest(art)["ok"]:
        raise PublicationError("manifest FAIL")

    scope = art / "scope-and-claims.json"
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
        "src/human_simulator/logging_config.py",
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
    (art / "public-data-minimization-scan.json").write_text(
        json.dumps(row_scan, indent=2) + "\n"
    )
    payloads[f"{ARTIFACT_DIR}/public-data-minimization-scan.json"] = (
        art / "public-data-minimization-scan.json"
    ).read_bytes()
    write_manifest(art)
    payloads[f"{ARTIFACT_DIR}/evidence-manifest.sha256"] = (
        art / "evidence-manifest.sha256"
    ).read_bytes()
    # Refresh status-contract bytes after scan
    payloads[f"{ARTIFACT_DIR}/status-contract.json"] = (
        art / "status-contract.json"
    ).read_bytes()

    if not row_scan["ok"]:
        raise PublicationError(f"row-level keys: {row_scan['hits'][:10]}")

    # Final lifecycle assert on packed status-contract
    packed_st = json.loads(payloads[f"{ARTIFACT_DIR}/status-contract.json"])
    _assert_publication_lifecycle(packed_st)

    with tempfile.TemporaryDirectory(prefix="uhbse-global-state-v011-") as tmp:
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
            "uv run --frozen pytest tests/test_global_state_v011*.py -q && "
            "uv run --frozen audit --root . global-state verify-v0.1.1"
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
            f"# REVIEW_INDEX — Global Split Individual Multi-Outcome State v{VERSION}",
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
                info.date_time = (2026, 8, 20, 17, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 20, 17, 0, 0)
            zf.writestr(info, index)

    zip_sha = _sha(zip_path)
    sidecar.write_text(f"{zip_sha}  {ZIP_NAME}\n")

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        with tempfile.TemporaryDirectory() as etmp:
            zf.extractall(etmp)
            if not verify_manifest(Path(etmp) / ARTIFACT_DIR)["ok"]:
                raise PublicationError("extract manifest FAIL")
            # Inside ZIP: post-pack must still be EXTERNAL_ATTESTATION_REQUIRED
            extracted_st = json.loads(
                (Path(etmp) / ARTIFACT_DIR / "status-contract.json").read_text()
            )
            _assert_publication_lifecycle(extracted_st)

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

    # External attestation carries final PASS (not written into ZIP)
    attestation = {
        "bundle_kind": "source_a_global_split_individual_multi_outcome_state_v011",
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
        "accepted_v01_sha256": ACCEPTED_V01_SHA256,
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "JOINT_MULTI_OUTCOME_MODEL_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
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
        "PUBLICATION_INTEGRITY_STATUS": "PASS",
        "note": "Final PASS is in external attestation only; ZIP keeps EXTERNAL_ATTESTATION_REQUIRED",
    }
