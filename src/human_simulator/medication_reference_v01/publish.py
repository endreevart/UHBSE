"""Publish refuse-if-exists medication-reference acquisition v0.1 review ZIP."""

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

from human_simulator.medication_reference_v01.lifecycle import (
    assert_lifecycle_consistency,
)
from human_simulator.medication_reference_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_IMMUTABLE_ZIPS,
    REVIEW_ZIP,
    VERSION,
    policy_snapshot,
)

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = ("tests/test_medication_reference_acquisition_v01_unit.py",)
PUBLIC_REPRODUCE_COMMANDS = (
    "uv sync --frozen --extra dev",
    "uv run --frozen pytest tests/test_medication_reference_acquisition_v01_unit.py -q",
    "uv run --frozen audit --root . medication-reference verify-v0.1",
)


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
    if "episodes_" in p.name and p.suffix == ".jsonl":
        return True
    if ".private." in p.name or p.name.endswith(".private.jsonl"):
        return True
    if "provider-cache" in p.parts or "decision-log" in p.name:
        return True
    return False


def _add_tree(payloads: dict[str, bytes], root: Path, rel: str) -> None:
    base = root / rel
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        if path.is_file():
            r = path.relative_to(root).as_posix()
            if not _excluded(r):
                payloads[r] = path.read_bytes()


def _scan(payloads: dict[str, bytes]) -> dict[str, Any]:
    patterns = [
        (re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"), "PRIVATE_KEY"),
        (re.compile(rb"\bVAULT_TOKEN\s*=\s*\S+"), "VAULT_TOKEN"),
        (
            re.compile(rb"(?:postgres|postgresql)://[^/\s\"'{]+?:[^/\s\"'{]+?@"),
            "POSTGRES_URI",
        ),
    ]
    hits = []
    for name, data in payloads.items():
        if name.endswith("_unit.py") or name.endswith("publish.py"):
            continue
        sample = data if len(data) < 400_000 else data[:400_000]
        for rx, label in patterns:
            if rx.search(sample):
                hits.append({"member": name, "pattern": label})
        if name.endswith(".jsonl") and b"opaque_subject_key" in sample:
            hits.append({"member": name, "pattern": "EPISODE_JSONL"})
        if b'"original_name"' in sample and name.endswith(".json"):
            # sanitized artifacts should not include full catalog names
            if "sanitized" in name or "accounting" in name or "coverage" in name:
                hits.append({"member": name, "pattern": "ORIGINAL_NAME_IN_PUBLIC"})
    return {"ok": not hits, "hits": hits}


def _write_guides(art: Path) -> None:
    (art / "REPRODUCE.md").write_text(
        f"""# Reproduce — Medication Reference Acquisition v{VERSION}

```bash
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_medication_reference_acquisition_v01_unit.py -q
uv run --frozen audit --root . medication-reference verify-v0.1
```

Private provider caches, decision logs and full medication strings are not in this ZIP.
Clinical use and causal interpretation are prohibited.
""",
        encoding="utf-8",
    )
    (art / "REPRODUCE_PRIVATE.md").write_text(
        f"""# Private reproduce — Medication Reference Acquisition v{VERSION}

Requires episodes JSONL, db-audit.env, optional RxNorm network or cache under
`private/medication-reference-v01/provider-cache/`.

```bash
uv run --frozen audit --root . medication-reference run-v0.1 --no-publish
uv run --frozen audit --root . medication-reference publish-v0.1
```
""",
        encoding="utf-8",
    )
    (art / "REVIEW_GUIDE.md").write_text(
        f"""# Review guide — Medication Reference Acquisition v{VERSION}

Scope correction: prior ENGINE_SHADOW_PASS was M1/M2C only; this release freezes and
shadows M2ID_ONEHOT. HUMAN_ACCEPTED requires append-only review log entries.

Non-claims: intervention-response, treatment-effect, causal, clinical, QSP, PK/PD.
Security PAUSED_NOT_ACCEPTED_BY_OWNER.
""",
        encoding="utf-8",
    )


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
        raise PublicationError("run medication-reference run-v0.1 first")

    _write_guides(art)
    write_manifest(art)
    if not verify_manifest(art)["ok"]:
        raise PublicationError("manifest FAIL")

    st_path = art / "status-contract.json"
    statuses = json.loads(st_path.read_text(encoding="utf-8"))
    statuses["pre_pack_manifest_status"] = "PASS"
    statuses["content_verification_status"] = "PASS"
    statuses["PUBLICATION_INTEGRITY_STATUS"] = "EXTERNAL_ATTESTATION_REQUIRED"
    statuses["post_pack_publication_verification_status"] = "EXTERNAL_ATTESTATION_REQUIRED"
    st_path.write_text(json.dumps(statuses, indent=2) + "\n")

    scope = art / "scope-and-claims.json"
    write_manifest(art)
    original = scope.read_bytes()
    scope.write_bytes(original + b"\n")
    failed = not verify_manifest(art)["ok"]
    scope.write_bytes(original)
    restored = verify_manifest(art)["ok"]
    mutation = {"ok": failed and restored}
    (art / "manifest-mutation-proof.json").write_text(json.dumps(mutation, indent=2) + "\n")
    write_manifest(art)

    payloads: dict[str, bytes] = {}
    _add_tree(payloads, root, "src/human_simulator")
    _add_tree(payloads, root, ARTIFACT_DIR)
    for rel in (
        "docs/current-stage.md",
        "docs/owner-priority-override-core-first.md",
        "AGENTS.md",
        *UNIT_TESTS,
        "pyproject.toml",
        "uv.lock",
        "README.md",
    ):
        p = root / rel
        if p.is_file():
            payloads[rel] = p.read_bytes()

    payloads["REPRODUCE.md"] = (art / "REPRODUCE.md").read_bytes()
    payloads["REPRODUCE_PRIVATE.md"] = (art / "REPRODUCE_PRIVATE.md").read_bytes()
    payloads["REVIEW_GUIDE.md"] = (art / "REVIEW_GUIDE.md").read_bytes()

    scan = _scan(payloads)
    if not scan["ok"]:
        raise PublicationError(f"banned content: {scan['hits']}")

    with tempfile.TemporaryDirectory(prefix="uhbse-med-ref-v01-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        cmd = " && ".join(PUBLIC_REPRODUCE_COMMANDS)
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
            "literal_commands": list(PUBLIC_REPRODUCE_COMMANDS),
        }
        m = re.search(r"(\d+)\s+passed", unit_out)
        unit["passed"] = int(m.group(1)) if m else None
        if unit["status"] != "PASS":
            raise PublicationError(f"clean-room FAIL: {unit}")

        statuses["clean_staging_test_status"] = "PASS"
        st_path.write_text(json.dumps(statuses, indent=2) + "\n")
        ver = json.loads((art / "verification.json").read_text())
        ver.setdefault("statuses", {})
        ver["statuses"]["pre_pack_manifest_status"] = "PASS"
        ver["statuses"]["clean_staging_test_status"] = "PASS"
        (art / "verification.json").write_text(json.dumps(ver, indent=2) + "\n")
        write_manifest(art)

        for path in art.rglob("*"):
            if path.is_file():
                payloads[path.relative_to(root).as_posix()] = path.read_bytes()

        art_files = {
            k[len(ARTIFACT_DIR) + 1 :]: v
            for k, v in payloads.items()
            if k.startswith(ARTIFACT_DIR + "/") and not k.endswith("evidence-manifest.sha256")
        }
        payloads[f"{ARTIFACT_DIR}/evidence-manifest.sha256"] = (
            "\n".join(f"{_sha_b(art_files[n])}  {n}" for n in sorted(art_files)) + "\n"
        ).encode()

        index_lines = [
            f"# REVIEW_INDEX — Medication Reference Acquisition v{VERSION}",
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
                info.date_time = (2026, 8, 19, 17, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 19, 17, 0, 0)
            zf.writestr(info, index)

    zip_sha = _sha(zip_path)
    sidecar.write_text(f"{zip_sha}  {ZIP_NAME}\n")

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        if len(members) != len(set(members)):
            raise PublicationError("duplicate members")
        with tempfile.TemporaryDirectory() as etmp:
            zf.extractall(etmp)
            if not verify_manifest(Path(etmp) / ARTIFACT_DIR)["ok"]:
                raise PublicationError("extract manifest FAIL")
            env2 = os.environ.copy()
            env2["UV_CACHE_DIR"] = str(Path(etmp) / "uv-cache")
            env2["UV_PROJECT_ENVIRONMENT"] = str(Path(etmp) / "venv")
            proc2 = subprocess.run(
                " && ".join(PUBLIC_REPRODUCE_COMMANDS),
                cwd=etmp,
                env=env2,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc2.returncode != 0:
                raise PublicationError(
                    "clean-extraction FAIL: "
                    + ((proc2.stdout or "") + (proc2.stderr or ""))[-3000:]
                )
            packed_st = json.loads(
                (Path(etmp) / ARTIFACT_DIR / "status-contract.json").read_text()
            )
            for k, v in packed_st.items():
                if isinstance(v, str) and v in ("PENDING_WRITE", "PENDING_PUBLISH"):
                    raise PublicationError(f"stale pending: {k}={v}")

    indexed = len(payloads)
    if len(members) != indexed + 1:
        raise PublicationError(f"index invariant FAIL: {len(members)} vs {indexed}+1")

    prior_ok = True
    prior_after = {}
    for label, (name, exp) in PRIOR_IMMUTABLE_ZIPS.items():
        got = _sha(external / name)
        prior_after[label] = got
        if got != exp or got != prior_before[label]:
            prior_ok = False

    attestation = {
        "bundle_kind": "medication_reference_acquisition_first_concept_cohorts_v01",
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "PUBLICATION_INTEGRITY_STATUS": "PASS" if prior_ok else "FAIL",
        "publication_integrity_status": "PASS" if prior_ok else "FAIL",
        "post_pack_zip_verification_status": "PASS",
        "sidecar_matches_final_zip": True,
        "clean_extraction_verification_status": "PASS",
        "archive_rebuilt_after_hashing": False,
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(members),
        "indexed_members": indexed,
        "members_equals_indexed_plus_one": len(members) == indexed + 1,
        "unit_reproduce": unit,
        "manifest_mutation_proof": mutation,
        "prior_immutable_zips_untouched": prior_ok,
        "prior_sha256": prior_after,
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "row_level_episodes_in_zip": False,
        "private_provider_responses_in_zip": False,
        "policy": policy_snapshot(),
    }
    life = assert_lifecycle_consistency(status_contract=statuses, attestation=attestation)
    if not life["ok"]:
        raise PublicationError(f"lifecycle FAIL: {life}")

    ok = prior_ok and unit["status"] == "PASS" and mutation["ok"] and life["ok"]
    attestation["attestation_status"] = "PASS" if ok else "FAIL"
    attestation["lifecycle_consistency"] = life
    att_path.write_text(json.dumps(attestation, indent=2) + "\n")
    if not ok:
        raise PublicationError("attestation FAIL")
    st_path.write_text(json.dumps(statuses, indent=2) + "\n")

    return {
        "zip": str(zip_path),
        "sidecar": str(sidecar),
        "attestation": str(att_path),
        "sha256": zip_sha,
        "members": len(members),
        "indexed_members": indexed,
        "attestation_status": "PASS",
        "PUBLICATION_INTEGRITY_STATUS": "PASS",
    }
