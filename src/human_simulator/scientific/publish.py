"""Publish Scientific Data Readiness v0.1.1 review bundle."""

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

from human_simulator.scientific.policy import (
    ACCEPTED_CORE_V0121_SHA256,
    ACCEPTED_SDR_V01_SHA256,
    ACCEPTED_SDR_V011_SHA256,
    ARTIFACT_DIR,
    PRIOR_IMMUTABLE_ZIPS,
    SCIENTIFIC_VERSION,
    policy_snapshot,
)

VERSION = SCIENTIFIC_VERSION
ZIP_NAME = f"stage-03-scientific-data-readiness-v{VERSION}-review.zip"
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = f"stage-03-scientific-data-readiness-v{VERSION}-review.attestation.json"

UNIT_TEST_FILES = (
    "tests/test_scientific_data_readiness_unit.py",
    "tests/test_scientific_dataset_builder.py",
    "tests/test_scientific_temporal_leakage.py",
    "tests/test_scientific_splits.py",
    "tests/test_scientific_baselines.py",
    "tests/test_scientific_backtest.py",
    "tests/test_scientific_engine_integration.py",
    "tests/test_scientific_v011_methodology.py",
    "tests/test_scientific_v0111_evidence.py",
)
PUBLICATION_TEST = "tests/test_scientific_data_readiness_publication.py"
CLEAN_TEST = "tests/test_scientific_data_readiness_clean_extraction.py"

REPRODUCE_COMMANDS = (
    "uv sync --frozen --extra dev",
    "uv run --frozen pytest " + " ".join(UNIT_TEST_FILES) + " -q",
    "uv run --frozen audit --root . scientific-data-readiness verify",
)

FORBIDDEN_NAME_PATTERNS = (
    re.compile(r"(?i)^\.env(?:\..*)?$"),
    re.compile(r"(?i)secret"),
    re.compile(r"(?i)\.dump$"),
    re.compile(r"(?i)longitudinal_pairs\.jsonl$"),
)
VAULT_TOKEN_PATTERN = re.compile(r"(?i)\bhvs\.[A-Za-z0-9_-]{12,}\b")
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
PATIENT_ID_PATTERN = re.compile(r'(?i)"patient_id"\s*:')
SUBJECT_HASH_LIST_PATTERN = re.compile(
    r'(?i)"opaque_subject_keys"\s*:\s*\[|"assignment"\s*:\s*\{|"subject_assignment_hashes"\s*:\s*\{'
)


class PublicationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_manifest(dir_path: Path) -> dict[str, Any]:
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
        if name == "manifest.sha256":
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
        # fall back to any non-manifest json
        candidates = sorted(p for p in dir_path.glob("*.json") if p.name != "manifest.sha256")
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
    if "external-review" in path.parts or "scientific-runtime" in path.parts:
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
        "artifacts/stage-03/canonical-model.yaml",
        "artifacts/stage-03/provenance-contract.yaml",
        "artifacts/stage-03/temporal-contract.yaml",
        "artifacts/stage-03/design-content-manifest.sha256",
    ):
        path = repo_root / rel
        if path.is_dir():
            _add_tree(payloads, repo_root, rel)
        elif path.is_file() and not _excluded(rel):
            payloads[rel] = path.read_bytes()

    required = ("pyproject.toml", "uv.lock", *UNIT_TEST_FILES, PUBLICATION_TEST, CLEAN_TEST)
    for rel in required:
        p = repo_root / rel
        if not p.is_file():
            raise PublicationError(f"missing required payload: {rel}")
        payloads[rel] = p.read_bytes()

    # live test optional in zip
    live = repo_root / "tests/test_scientific_data_readiness_live.py"
    if live.is_file():
        payloads["tests/test_scientific_data_readiness_live.py"] = live.read_bytes()

    reproduce = f"""# REPRODUCE — Scientific Data Readiness v{VERSION}

```bash
export UV_CACHE_DIR=<tmp>/uv-cache
export UV_PROJECT_ENVIRONMENT=<tmp>/venv
{REPRODUCE_COMMANDS[0]}
{REPRODUCE_COMMANDS[1]}
{REPRODUCE_COMMANDS[2]}
```

Live suite (credentials required, not assumed in clean room):

```bash
uv run --frozen pytest tests/test_scientific_data_readiness_live.py -q
```

Baseline core ZIP SHA-256 (immutable): `{ACCEPTED_CORE_V0121_SHA256}`
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
        if rel.startswith(ARTIFACT_DIR) and SUBJECT_HASH_LIST_PATTERN.search(text):
            findings.append(f"subject_hash_list:{rel}")
        if "longitudinal_pairs" in rel or "scientific-runtime" in rel:
            findings.append(f"runtime_dataset:{rel}")
    return {"ok": not findings, "findings": findings, "scanned": len(payloads)}


def _build_index(payloads: dict[str, bytes]) -> str:
    lines = [
        f"# REVIEW_INDEX — Scientific Data Readiness v{VERSION}",
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


def _run_reproduce(staging: Path, isolation: Path) -> dict[str, Any]:
    env = {
        **os.environ,
        "UV_CACHE_DIR": str(isolation / "uv-cache"),
        "UV_PROJECT_ENVIRONMENT": str(isolation / "venv"),
    }
    executions = []
    for cmd in REPRODUCE_COMMANDS:
        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        item = {
            "literal_command": cmd,
            "exit_code": proc.returncode,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "execution_environment": {
                "working_directory": "isolated_staging_root",
                "UV_CACHE_DIR": "<tmp>/uv-cache",
                "UV_PROJECT_ENVIRONMENT": "<tmp>/venv",
            },
            **_parse_pytest(out),
        }
        executions.append(item)
    ok = all(e["exit_code"] == 0 for e in executions)
    return {
        "status": "PASS" if ok else "FAIL",
        "exact_reproduce_commands_executed": True,
        "commands": executions,
    }


def publish_scientific_v01(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    external = root / "artifacts" / "external-review"
    external.mkdir(parents=True, exist_ok=True)
    zip_path = external / ZIP_NAME
    sidecar = external / SHA_NAME
    att_path = external / ATT_NAME
    for p in (zip_path, sidecar, att_path):
        if p.exists():
            raise PublicationError(f"target exists; refuse overwrite: {p.name}")

    # prior hashes before pack
    prior_before = {
        label: _sha256_file(external / name) if (external / name).is_file() else None
        for label, (name, _) in PRIOR_IMMUTABLE_ZIPS.items()
    }

    art = root / ARTIFACT_DIR
    if not art.is_dir():
        raise PublicationError("missing artifacts; run scientific-data-readiness run-v0.1 first")
    ver = json.loads((art / "scientific-data-readiness-verification.json").read_text())
    if ver.get("technical_pipeline_status") == "BACKTEST_PIPELINE_FAIL":
        raise PublicationError("mandatory technical checks FAIL; refuse publish")

    # refresh manifest
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "manifest.sha256"
    )
    (art / "manifest.sha256").write_text(
        "\n".join(f"{_sha256_file(art / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )
    man = verify_manifest(art)
    if not man["ok"]:
        raise PublicationError(f"manifest FAIL: {man}")
    mutation = prove_manifest_mutation_fails(art)
    if not mutation.get("ok"):
        raise PublicationError(f"manifest mutation proof FAIL: {mutation}")
    (art / "manifest-mutation-proof.json").write_text(
        json.dumps(mutation, indent=2) + "\n", encoding="utf-8"
    )
    # refresh manifest to include mutation proof artifact
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "manifest.sha256"
    )
    (art / "manifest.sha256").write_text(
        "\n".join(f"{_sha256_file(art / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )
    man = verify_manifest(art)
    if not man["ok"]:
        raise PublicationError(f"manifest FAIL after mutation proof: {man}")

    payloads = _collect_payloads(root)
    with tempfile.TemporaryDirectory(prefix="uhbse-sdr-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        repro = _run_reproduce(staging, isolation)
        repro_bytes = (json.dumps(repro, indent=2) + "\n").encode()
        rel_repro = f"{ARTIFACT_DIR}/reproducibility-verification.json"
        (staging / rel_repro).parent.mkdir(parents=True, exist_ok=True)
        (staging / rel_repro).write_bytes(repro_bytes)
        (art / "reproducibility-verification.json").write_bytes(repro_bytes)
        payloads[rel_repro] = repro_bytes

        # refresh staging artifact manifest
        st_art = staging / ARTIFACT_DIR
        st_names = sorted(
            p.relative_to(st_art).as_posix()
            for p in st_art.rglob("*")
            if p.is_file() and p.name != "manifest.sha256"
        )
        man_bytes = (
            "\n".join(f"{_sha256_file(st_art / n)}  {n}" for n in st_names) + "\n"
        ).encode()
        (st_art / "manifest.sha256").write_bytes(man_bytes)
        (art / "manifest.sha256").write_bytes(man_bytes)
        payloads[f"{ARTIFACT_DIR}/manifest.sha256"] = man_bytes

        payloads = {k: (staging / k).read_bytes() for k in payloads}
        index = _build_index(payloads).encode()
        scan = _scan({**payloads, "REVIEW_INDEX.md": index})
        if not scan["ok"]:
            raise PublicationError(f"PII scan FAIL: {scan['findings']}")
        if repro["status"] != "PASS":
            raise PublicationError("clean-room reproduce FAIL")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(payloads):
                info = zipfile.ZipInfo(name)
                info.date_time = (2026, 8, 14, 0, 0, 0)
                zf.writestr(info, payloads[name])
            info = zipfile.ZipInfo("REVIEW_INDEX.md")
            info.date_time = (2026, 8, 14, 0, 0, 0)
            zf.writestr(info, index)

    zip_sha = _sha256_file(zip_path)
    sidecar.write_text(f"{zip_sha}  {ZIP_NAME}\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
    expected = set(payloads) | {"REVIEW_INDEX.md"}
    if set(members) != expected:
        raise PublicationError("members/index mismatch")

    # clean extraction suite
    with tempfile.TemporaryDirectory(prefix="uhbse-sdr-extract-") as tmp:
        extract = Path(tmp) / "extract"
        extract.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract)
        env = {
            **os.environ,
            "UV_CACHE_DIR": str(Path(tmp) / "uv-cache"),
            "UV_PROJECT_ENVIRONMENT": str(Path(tmp) / "venv"),
        }
        # copy clean extraction test into extract if needed — already in zip
        t0 = time.perf_counter()
        proc = subprocess.run(
            f"uv sync --frozen --extra dev && uv run --frozen pytest {CLEAN_TEST} -q",
            cwd=extract,
            env=env,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        clean = {
            "literal_command": f"uv sync --frozen --extra dev && uv run --frozen pytest {CLEAN_TEST} -q",
            "exit_code": proc.returncode,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            **_parse_pytest((proc.stdout or "") + (proc.stderr or "")),
        }
    if clean["exit_code"] != 0:
        raise PublicationError(f"clean-extraction FAIL: {clean}")

    # priors untouched
    prior_ok = True
    prior_after = {}
    for label, (name, expected_sha) in PRIOR_IMMUTABLE_ZIPS.items():
        p = external / name
        got = _sha256_file(p) if p.is_file() else None
        prior_after[label] = got
        if got != expected_sha or got != prior_before.get(label):
            prior_ok = False

    qlog = json.loads((art / "query-log.json").read_text()) if (art / "query-log.json").is_file() else {}
    attestation = {
        "bundle_kind": "scientific_data_readiness",
        "version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "publication_integrity_status": "PASS" if prior_ok else "FAIL",
        "technical_pipeline_status": ver.get("technical_pipeline_status"),
        "scientific_data_readiness_status": ver.get("scientific_data_readiness_status"),
        "retrospective_backtest_status": ver.get("retrospective_backtest_status"),
        "incremental_signal_status": ver.get("incremental_signal_status"),
        "uncertainty_calibration_status": ver.get("uncertainty_calibration_status"),
        "clinical_validation_status": "NOT_STARTED",
        "intervention_response_model_status": "NOT_STARTED",
        "production_readiness": "NOT_CLAIMED",
        "security_stage_status": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "security_work_executed": False,
        "review_zip": ZIP_NAME,
        "review_zip_sha256": zip_sha,
        "members": len(members),
        "indexed_members": len(payloads),
        "reproducibility": repro,
        "clean_extraction": clean,
        "payload_scan": scan,
        "manifest_mutation_proof": mutation,
        "prior_immutable_zips_untouched": prior_ok,
        "prior_core_zips_untouched": prior_ok,
        "prior_sha256": prior_after,
        "accepted_core_v0121_sha256": ACCEPTED_CORE_V0121_SHA256,
        "accepted_sdr_v01_sha256": ACCEPTED_SDR_V01_SHA256,
        "accepted_sdr_v011_sha256": ACCEPTED_SDR_V011_SHA256,
        "clinical_rows_read": qlog.get("clinical_rows_read"),
        "raw_db_writes": qlog.get("raw_db_writes", 0),
        "selected_outcome": ver.get("selected_outcome"),
        "n_pairs": ver.get("n_pairs"),
        "split_counts": ver.get("split_counts"),
        "split_subjects": ver.get("split_subjects"),
        "pair_definition": ver.get("pair_definition"),
        "policy": policy_snapshot(),
    }
    bool_ok = (
        attestation["publication_integrity_status"] == "PASS"
        and prior_ok
        and scan["ok"]
        and repro["status"] == "PASS"
        and clean["exit_code"] == 0
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
