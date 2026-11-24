"""Publish Unified Source Expansion v0.1 review ZIP (refuse-if-exists)."""

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

from human_simulator.unified.policy import (
    ACCEPTED_CORE_V0121_SHA256,
    ACCEPTED_ROADMAP_V011_SHA256,
    ACCEPTED_SDR_V0111_SHA256,
    ARTIFACT_DIR,
    PRIOR_IMMUTABLE_ZIPS,
    VERSION,
    policy_snapshot,
)

ZIP_NAME = f"stage-03-unified-source-expansion-v{VERSION}-review.zip"
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = f"stage-03-unified-source-expansion-v{VERSION}-review.attestation.json"

UNIT_TEST_FILES = ("tests/test_unified_source_expansion_unit.py",)

REPRODUCE_COMMANDS = (
    "uv sync --frozen --extra dev",
    "uv run --frozen pytest " + " ".join(UNIT_TEST_FILES) + " -q",
    "uv run --frozen audit --root . unified-source-expansion verify",
)

FORBIDDEN_NAME_PATTERNS = (
    re.compile(r"(?i)^\.env(?:\..*)?$"),
    re.compile(r"(?i)secret"),
    re.compile(r"(?i)\.dump$"),
)
VAULT_TOKEN_PATTERN = re.compile(r"(?i)\bhvs\.[A-Za-z0-9_-]{12,}\b")
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PATIENT_ID_PATTERN = re.compile(r'(?i)"patient_id"\s*:')


class PublicationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_manifest(dir_path: Path) -> dict[str, Any]:
    manifest = dir_path / "evidence-manifest.sha256"
    if not manifest.is_file():
        manifest = dir_path / "manifest.sha256"
    if not manifest.is_file():
        return {"ok": False, "detail": "missing manifest"}
    mismatches = []
    checked = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        name = name.strip()
        if name in ("evidence-manifest.sha256", "manifest.sha256"):
            return {"ok": False, "detail": "self-hash"}
        path = dir_path / name
        if not path.is_file():
            mismatches.append(f"missing:{name}")
            continue
        checked += 1
        if _sha256_file(path) != digest.strip():
            mismatches.append(f"mismatch:{name}")
    return {"ok": not mismatches, "checked": checked, "mismatches": mismatches}


def prove_manifest_mutation_fails(dir_path: Path) -> dict[str, Any]:
    """Copy one hashed member, mutate it, prove verify_manifest FAILS, then restore."""
    target = dir_path / "scope-and-claims.json"
    if not target.is_file():
        candidates = sorted(
            p
            for p in dir_path.glob("*.json")
            if p.name not in ("evidence-manifest.sha256", "manifest.sha256")
        )
        if not candidates:
            return {"ok": False, "detail": "no member to mutate"}
        target = candidates[0]
    before = verify_manifest(dir_path)
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n")
        after = verify_manifest(dir_path)
    finally:
        target.write_bytes(original)
    restored = verify_manifest(dir_path)
    ok = bool(before.get("ok")) and (not after.get("ok")) and bool(restored.get("ok"))
    return {
        "ok": ok,
        "mutated_member": target.name,
        "manifest_ok_before_mutation": before.get("ok"),
        "manifest_fails_after_content_mutation": not after.get("ok"),
        "manifest_ok_after_restore": restored.get("ok"),
        "after_mismatches": after.get("mismatches", []),
    }


def _excluded(rel: str) -> bool:
    path = Path(rel)
    if "external-review" in path.parts or "unified-runtime" in path.parts:
        return True
    if path.suffix.lower() == ".zip" or "dumps" in path.parts:
        return True
    if "__pycache__" in path.parts or path.name == ".DS_Store":
        return True
    return any(p.search(path.name) for p in FORBIDDEN_NAME_PATTERNS)


def _add_tree(payloads: dict[str, bytes], root: Path, rel_dir: str) -> None:
    base = root / rel_dir
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if not _excluded(rel):
                payloads[rel] = path.read_bytes()


def _collect_payloads(repo_root: Path) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for rel in (
        ARTIFACT_DIR,
        "src/human_simulator",
        "artifacts/stage-03/source-b-mapping-draft.yaml",
    ):
        path = repo_root / rel
        if path.is_dir():
            _add_tree(payloads, repo_root, rel)
        elif path.is_file() and not _excluded(rel):
            payloads[rel] = path.read_bytes()

    required = ("pyproject.toml", "uv.lock", *UNIT_TEST_FILES)
    for rel in required:
        p = repo_root / rel
        if not p.is_file():
            raise PublicationError(f"missing required payload: {rel}")
        payloads[rel] = p.read_bytes()

    reproduce = f"""# REPRODUCE — Unified Source Expansion v{VERSION}

```bash
export UV_CACHE_DIR=<tmp>/uv-cache
export UV_PROJECT_ENVIRONMENT=<tmp>/venv
{REPRODUCE_COMMANDS[0]}
{REPRODUCE_COMMANDS[1]}
{REPRODUCE_COMMANDS[2]}
```

Live full expansion (credentials required):

```bash
uv run --frozen audit --root . unified-source-expansion run --full --no-publish
```

Accepted baselines (immutable):
- Core v0.1.2.1: `{ACCEPTED_CORE_V0121_SHA256}`
- SDR v0.1.1.1: `{ACCEPTED_SDR_V0111_SHA256}`
- Roadmap v0.1.1: `{ACCEPTED_ROADMAP_V011_SHA256}`
"""
    payloads["REPRODUCE.md"] = reproduce.encode()
    return payloads


def _scan(payloads: dict[str, bytes]) -> dict[str, Any]:
    findings = []
    for rel, data in payloads.items():
        text = data.decode("utf-8", errors="replace")
        if VAULT_TOKEN_PATTERN.search(text):
            findings.append(f"vault:{rel}")
        if EMAIL_PATTERN.search(text):
            findings.append(f"email:{rel}")
        if rel.startswith(ARTIFACT_DIR) and PATIENT_ID_PATTERN.search(text):
            findings.append(f"patient_id:{rel}")
    return {"ok": not findings, "findings": findings, "scanned": len(payloads)}


def _build_index(payloads: dict[str, bytes]) -> str:
    lines = [
        f"# REVIEW_INDEX — Unified Source Expansion v{VERSION}",
        "",
        "| Path | SHA-256 |",
        "|------|---------|",
    ]
    for name in sorted(payloads):
        lines.append(f"| `{name}` | `{_sha256_bytes(payloads[name])}` |")
    lines.extend(["", "## Policy", "", "```text"])
    for k, v in policy_snapshot().items():
        lines.append(f"{k}: {v}")
    lines.extend(["```", ""])
    return "\n".join(lines)


def _parse_pytest(output: str) -> dict[str, int | None]:
    counts: dict[str, int | None] = {
        "collected": None,
        "passed": None,
        "failed": None,
        "skipped": None,
    }
    m = re.search(r"collected\s+(\d+)", output, re.I)
    if m:
        counts["collected"] = int(m.group(1))
    for key in ("passed", "failed", "skipped"):
        ms = re.findall(rf"(\d+)\s+{key}\b", output, re.I)
        if ms:
            counts[key] = int(ms[-1])
    return counts


def _run_unit(staging: Path, isolation: Path) -> dict[str, Any]:
    env = {
        **os.environ,
        "UV_CACHE_DIR": str(isolation / "uv-cache"),
        "UV_PROJECT_ENVIRONMENT": str(isolation / "venv"),
    }
    cmd = REPRODUCE_COMMANDS[0] + " && " + REPRODUCE_COMMANDS[1]
    t0 = time.perf_counter()
    proc = subprocess.run(
        cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return {
        "literal_command": cmd,
        "exit_code": proc.returncode,
        "duration_seconds": round(time.perf_counter() - t0, 3),
        **_parse_pytest(out),
        "status": "PASS" if proc.returncode == 0 else "FAIL",
    }


def write_evidence_manifest(art: Path) -> Path:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name not in ("evidence-manifest.sha256", "manifest.sha256")
    )
    path = art / "evidence-manifest.sha256"
    path.write_text(
        "\n".join(f"{_sha256_file(art / n)}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )
    return path


def publish_unified_v01(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    external = root / "artifacts" / "external-review"
    external.mkdir(parents=True, exist_ok=True)
    zip_path = external / ZIP_NAME
    sidecar = external / SHA_NAME
    att_path = external / ATT_NAME
    for p in (zip_path, sidecar, att_path):
        if p.exists():
            raise PublicationError(f"target exists; refuse overwrite: {p.name}")

    prior_before = {
        label: _sha256_file(external / name) if (external / name).is_file() else None
        for label, (name, _) in PRIOR_IMMUTABLE_ZIPS.items()
    }

    art = root / ARTIFACT_DIR
    if not art.is_dir():
        raise PublicationError("missing artifacts; run unified-source-expansion run first")
    ver_path = art / "verification.json"
    if not ver_path.is_file():
        raise PublicationError("missing verification.json")

    write_evidence_manifest(art)
    man = verify_manifest(art)
    if not man["ok"]:
        raise PublicationError(f"manifest FAIL: {man}")
    mutation = prove_manifest_mutation_fails(art)
    if not mutation.get("ok"):
        raise PublicationError(f"manifest mutation proof FAIL: {mutation}")
    (art / "manifest-mutation-proof.json").write_text(
        json.dumps(mutation, indent=2) + "\n", encoding="utf-8"
    )
    write_evidence_manifest(art)
    man = verify_manifest(art)
    if not man["ok"]:
        raise PublicationError(f"manifest FAIL after mutation proof: {man}")

    payloads = _collect_payloads(root)
    with tempfile.TemporaryDirectory(prefix="uhbse-unified-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        # Ensure artifact REPRODUCE in staging matches
        if (art / "REPRODUCE.md").is_file():
            (staging / ARTIFACT_DIR / "REPRODUCE.md").write_bytes((art / "REPRODUCE.md").read_bytes())
            payloads[f"{ARTIFACT_DIR}/REPRODUCE.md"] = (art / "REPRODUCE.md").read_bytes()

        unit = _run_unit(staging, isolation)
        if unit["status"] != "PASS":
            raise PublicationError(f"clean-room unit FAIL: {unit}")

        index = _build_index(payloads).encode()
        scan = _scan({**payloads, "REVIEW_INDEX.md": index})
        if not scan["ok"]:
            raise PublicationError(f"PII scan FAIL: {scan['findings']}")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(payloads):
                info = zipfile.ZipInfo(name)
                info.date_time = (2026, 8, 15, 0, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 15, 0, 0, 0)
            zf.writestr(info, index)

    zip_sha = _sha256_file(zip_path)
    sidecar.write_text(f"{zip_sha}  {ZIP_NAME}\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        if any(n.endswith(".zip") for n in members):
            raise PublicationError("nested zip forbidden")

    prior_ok = True
    prior_after = {}
    for label, (name, expected_sha) in PRIOR_IMMUTABLE_ZIPS.items():
        p = external / name
        got = _sha256_file(p) if p.is_file() else None
        prior_after[label] = got
        if got != expected_sha or got != prior_before.get(label):
            prior_ok = False

    ver = json.loads(ver_path.read_text(encoding="utf-8"))
    attestation = {
        "bundle_kind": "unified_source_expansion",
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_integrity_status": "PASS" if prior_ok else "FAIL",
        "archive_rebuilt_after_hashing": False,
        "statuses": ver,
        "clinical_validation_status": "NOT_STARTED",
        "intervention_response_model_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "security_work_executed": False,
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(members),
        "indexed_members": len(payloads),
        "unit_reproduce": unit,
        "payload_scan": scan,
        "manifest_mutation_proof": mutation,
        "prior_immutable_zips_untouched": prior_ok,
        "prior_sha256": prior_after,
        "accepted_core_v0121_sha256": ACCEPTED_CORE_V0121_SHA256,
        "accepted_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "accepted_roadmap_v011_sha256": ACCEPTED_ROADMAP_V011_SHA256,
        "policy": policy_snapshot(),
    }
    bool_ok = (
        attestation["publication_integrity_status"] == "PASS"
        and prior_ok
        and scan["ok"]
        and unit["status"] == "PASS"
        and mutation.get("ok") is True
    )
    attestation["attestation_status"] = "PASS" if bool_ok else "FAIL"
    att_path.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    if not bool_ok:
        raise PublicationError("attestation FAIL")
    return {
        "zip": str(zip_path),
        "sidecar": str(sidecar),
        "attestation": str(att_path),
        "sha256": zip_sha,
        "members": len(members),
        "indexed_members": len(payloads),
        "attestation_status": "PASS",
    }
