"""Private review ZIP for public roadmap series v0.1.1. Self-contained; refuse-if-exists."""

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

from human_simulator.media.series.constants import (
    ACCEPTED_ROADMAP_V01_SHA256,
    ACCEPTED_ROADMAP_V01_ZIP,
    ACCEPTED_SDR_V0111_SHA256,
    CORE_ZIP_SHA256,
    EVIDENCE_DIR,
    EXTERNAL_DIR,
    PROXY_HEIGHT,
    PROXY_WIDTH,
    PUBLIC_MEDIA_DIR,
    REVIEW_BUNDLE_KIND,
    REVIEW_ZIP_NAME,
    SERIES_TITLE,
    SERIES_VERSION,
)
from human_simulator.media.series.reports import sha256_file

MAX_ZIP_BYTES = 120 * 1024 * 1024

REQUIRED_CODE = (
    "pyproject.toml",
    "uv.lock",
    "tests/test_media_series.py",
    "tests/test_media_series_v011_publication.py",
    "src/human_simulator/media/series/constants.py",
    "src/human_simulator/media/series/bindings.py",
    "src/human_simulator/media/series/copy.py",
    "src/human_simulator/media/series/verify.py",
    "src/human_simulator/media/series/fixture.py",
    "src/human_simulator/media/series/pipeline.py",
    "src/human_simulator/media/series/publish.py",
    "src/human_simulator/media/series/reports.py",
    "src/human_simulator/media/series/baseline.py",
    "src/human_simulator/media/series/disclosure.py",
    "src/human_simulator/media/series/rounding.py",
    "src/human_simulator/media/cli.py",
    "media/src/series/chrome.tsx",
    "media/src/series/Roadmap01.tsx",
    "media/src/series/Roadmap06.tsx",
    "media/src/series/types.ts",
)

FORBIDDEN_NAME = re.compile(r"(?i)(^\.env$|\.env\.|credentials\.json|db\.env$)")


class SeriesPublishError(RuntimeError):
    pass


def verify_evidence_manifest(evidence: Path) -> dict[str, Any]:
    manifest = evidence / "manifest.sha256"
    if not manifest.is_file():
        return {"ok": False, "detail": "missing manifest"}
    mismatches: list[str] = []
    checked = 0
    listed: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        name = name.strip()
        listed.add(name)
        path = evidence / name
        if not path.is_file():
            mismatches.append(f"missing:{name}")
            continue
        checked += 1
        if sha256_file(path) != digest.strip():
            mismatches.append(f"mismatch:{name}")
    present = {
        p.relative_to(evidence).as_posix()
        for p in evidence.rglob("*")
        if p.is_file() and p.name != "manifest.sha256"
    }
    for name in present - listed:
        mismatches.append(f"unlisted:{name}")
    return {"ok": not mismatches, "checked": checked, "mismatches": mismatches, "listed": len(listed)}


def prove_manifest_mutation_fails(evidence: Path) -> dict[str, Any]:
    target = evidence / "series-verification.json"
    if not target.is_file():
        candidates = sorted(evidence.glob("*.json"))
        if not candidates:
            return {"ok": False, "detail": "no member"}
        target = candidates[0]
    before = verify_evidence_manifest(evidence)
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n")
        after = verify_evidence_manifest(evidence)
    finally:
        target.write_bytes(original)
    restored = verify_evidence_manifest(evidence)
    ok = bool(before.get("ok")) and (not after.get("ok")) and bool(restored.get("ok"))
    return {
        "ok": ok,
        "mutated_member": target.name,
        "manifest_ok_before_mutation": before.get("ok"),
        "manifest_fails_after_content_mutation": not after.get("ok"),
        "manifest_ok_after_restore": restored.get("ok"),
    }


def _add_bytes(payloads: dict[str, bytes], arc: str, data: bytes) -> None:
    if arc in payloads:
        raise SeriesPublishError(f"duplicate member: {arc}")
    if ".." in Path(arc).parts or arc.startswith("/"):
        raise SeriesPublishError(f"path traversal forbidden: {arc}")
    if FORBIDDEN_NAME.search(Path(arc).name):
        raise SeriesPublishError(f"forbidden name: {arc}")
    payloads[arc] = data


def _collect(root: Path) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    evidence = root / EVIDENCE_DIR
    media = root / PUBLIC_MEDIA_DIR
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            rel = path.relative_to(root).as_posix()
            _add_bytes(payloads, rel, path.read_bytes())
    for slug_dir in sorted(p for p in media.iterdir() if p.is_dir() and p.name != "proxies"):
        for name in (
            "cover.png",
            "cover-headline.txt",
            "linkedin.txt",
            "x-threads.txt",
            "captions.en.srt",
            "captions.ru.srt",
            "voiceover.en.txt",
            "voiceover.ru.txt",
            "voiceover.en.wav",
            "voiceover.ru.wav",
        ):
            src = slug_dir / name
            if src.is_file():
                _add_bytes(payloads, src.relative_to(root).as_posix(), src.read_bytes())
    sheets = media / "contact-sheets"
    if sheets.is_dir():
        for path in sorted(sheets.glob("*.png")):
            _add_bytes(payloads, path.relative_to(root).as_posix(), path.read_bytes())
    proxies = media / "proxies"
    if proxies.is_dir():
        for path in sorted(proxies.glob("*.mp4")):
            _add_bytes(payloads, path.relative_to(root).as_posix(), path.read_bytes())
    # do NOT pack master 1080x1920 mp4
    for rel in REQUIRED_CODE:
        path = root / rel
        if not path.is_file():
            raise SeriesPublishError(f"missing required: {rel}")
        if rel not in payloads:
            _add_bytes(payloads, rel, path.read_bytes())
    # full Python package for clean extraction imports
    for path in sorted((root / "src" / "human_simulator").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel not in payloads:
            _add_bytes(payloads, rel, path.read_bytes())
    # evidence dependencies for bindings / skip-render
    for rel_dir in (
        "artifacts/stage-03-core-vertical-slice-v0.1.2.1",
        "artifacts/stage-03-core-vertical-slice-v0.1.2",
        "artifacts/stage-03-scientific-data-readiness-v0.1.1.1",
    ):
        base = root / rel_dir
        if not base.exists():
            raise SeriesPublishError(f"missing dependency tree: {rel_dir}")
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".zip", ".dump"}:
                continue
            rel = path.relative_to(root).as_posix()
            if rel not in payloads:
                _add_bytes(payloads, rel, path.read_bytes())
    # accepted core zip + sidecar for baseline verify (immutable input)
    for name in (
        "stage-03-core-vertical-slice-v0.1.2.1-review.zip",
        "stage-03-core-vertical-slice-v0.1.2.1-review.zip.sha256",
        "stage-03-core-vertical-slice-v0.1.2.1-review.attestation.json",
        "stage-03-public-roadmap-series-v0.1-review.zip",
        "stage-03-scientific-data-readiness-v0.1.1.1-review.zip",
        "stage-03-scientific-data-readiness-v0.1.1.1-review.zip.sha256",
    ):
        path = root / "artifacts" / "external-review" / name
        if path.is_file():
            # nested archives forbidden in scan — allow only as baseline verification inputs
            # Spec forbids nested archives in review ZIP. Skip packing ZIPs.
            if path.suffix.lower() == ".zip":
                continue
            rel = path.relative_to(root).as_posix()
            if rel not in payloads:
                _add_bytes(payloads, rel, path.read_bytes())
    reproduce = "\n".join(
        [
            f"# REPRODUCE — {SERIES_TITLE} v{SERIES_VERSION}",
            "",
            "Clean extraction (no clinical DB required):",
            "",
            "```bash",
            "uv sync --frozen --extra dev",
            "uv run --frozen pytest tests/test_media_series.py tests/test_media_series_v011_publication.py -q",
            "uv run --frozen audit --root . media series --skip-render --skip-publish",
            "```",
            "",
            f"Review bundle kind: `{REVIEW_BUNDLE_KIND}`.",
            f"Proxy resolution: {PROXY_WIDTH}×{PROXY_HEIGHT}.",
            "Master 1080×1920 MP4 files remain workspace-only and are not packed.",
            "Accepted baseline ZIP files are not nested inside this package; verify them in the publisher workspace.",
            "Do not post to social networks.",
            "",
            f"Accepted core ZIP sha256: `{CORE_ZIP_SHA256}`",
            f"Accepted SDR v0.1.1.1 ZIP sha256: `{ACCEPTED_SDR_V0111_SHA256}`",
            f"Prior roadmap v0.1 ZIP sha256: `{ACCEPTED_ROADMAP_V01_SHA256}`",
            "",
        ]
    )
    _add_bytes(payloads, "REPRODUCE.md", reproduce.encode("utf-8"))
    return payloads


def publish_review_zip(root: Path, *, baseline: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    external = root / EXTERNAL_DIR
    external.mkdir(parents=True, exist_ok=True)
    zip_path = external / REVIEW_ZIP_NAME
    sidecar = external / f"{REVIEW_ZIP_NAME}.sha256"
    att_path = external / REVIEW_ZIP_NAME.replace(".zip", ".attestation.json")
    for p in (zip_path, sidecar, att_path):
        if p.exists():
            raise SeriesPublishError(f"refusing to overwrite {p.name}")

    prior_before = sha256_file(external / ACCEPTED_ROADMAP_V01_ZIP) if (external / ACCEPTED_ROADMAP_V01_ZIP).is_file() else None

    evidence = root / EVIDENCE_DIR
    # lock accepted baseline SHA for packed clean-extraction (no nested ZIP)
    lock = {
        "core_zip_sha256": CORE_ZIP_SHA256,
        "sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "roadmap_v01_sha256": ACCEPTED_ROADMAP_V01_SHA256,
        "members": baseline.get("members"),
        "indexed": baseline.get("indexed"),
    }
    (evidence / "baseline-sha-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    lines = []
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            lines.append(f"{sha256_file(path)}  {path.relative_to(evidence).as_posix()}")
    (evidence / "manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    man = verify_evidence_manifest(evidence)
    if not man["ok"]:
        raise SeriesPublishError(f"evidence manifest FAIL: {man}")
    mutation = prove_manifest_mutation_fails(evidence)
    if not mutation.get("ok"):
        raise SeriesPublishError(f"manifest mutation proof FAIL: {mutation}")
    (evidence / "manifest-mutation-proof.json").write_text(json.dumps(mutation, indent=2) + "\n", encoding="utf-8")
    # refresh evidence manifest including mutation proof
    lines = []
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256":
            lines.append(f"{sha256_file(path)}  {path.relative_to(evidence).as_posix()}")
    (evidence / "manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    man = verify_evidence_manifest(evidence)
    if not man["ok"]:
        raise SeriesPublishError(f"evidence manifest FAIL after mutation proof: {man}")

    payloads = _collect(root)
    # include refreshed evidence manifest
    payloads[f"{EVIDENCE_DIR.as_posix()}/manifest.sha256"] = (evidence / "manifest.sha256").read_bytes()
    payloads[f"{EVIDENCE_DIR.as_posix()}/manifest-mutation-proof.json"] = (
        evidence / "manifest-mutation-proof.json"
    ).read_bytes()

    index_lines = [
        f"# REVIEW_INDEX — {SERIES_TITLE} v{SERIES_VERSION}",
        "",
        "Private publication review. Do not post.",
        f"Bundle kind: `{REVIEW_BUNDLE_KIND}`.",
        f"Baseline core ZIP sha256: `{baseline.get('sha256')}`.",
        f"SDR v0.1.1.1 sha256: `{ACCEPTED_SDR_V0111_SHA256}`.",
        "",
        "## Members",
        "",
    ]
    for name in sorted(payloads):
        digest = hashlib.sha256(payloads[name]).hexdigest()
        index_lines.append(f"- `{name}` — sha256 `{digest}`")
    index = "\n".join(index_lines) + "\n"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arc in sorted(payloads):
            if arc.lower().endswith(".zip"):
                raise SeriesPublishError(f"nested zip forbidden: {arc}")
            info = zipfile.ZipInfo(arc)
            info.date_time = (2026, 8, 15, 0, 0, 0)
            archive.writestr(info, payloads[arc])
        info = zipfile.ZipInfo("REVIEW_INDEX.md")
        info.date_time = (2026, 8, 15, 0, 0, 0)
        archive.writestr(info, index.encode("utf-8"))

    if zip_path.stat().st_size > MAX_ZIP_BYTES:
        zip_path.unlink()
        raise SeriesPublishError("review zip exceeded size limit")

    digest = sha256_file(zip_path)
    sidecar.write_text(f"{digest}  {REVIEW_ZIP_NAME}\n", encoding="utf-8")

    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
    expected = set(payloads) | {"REVIEW_INDEX.md"}
    if set(names) != expected:
        raise SeriesPublishError("members/index mismatch")
    if len(names) != len(set(names)):
        raise SeriesPublishError("duplicate members")

    # clean extraction: sync + tests + skip-render
    with tempfile.TemporaryDirectory(prefix="uhbse-roadmap-extract-") as tmp:
        extract = Path(tmp) / "extract"
        extract.mkdir()
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract)
        # verify evidence manifest after extract
        ex_man = verify_evidence_manifest(extract / EVIDENCE_DIR)
        if not ex_man["ok"]:
            raise SeriesPublishError(f"extracted evidence manifest FAIL: {ex_man}")
        env = {
            **os.environ,
            "UV_CACHE_DIR": str(Path(tmp) / "uv-cache"),
            "UV_PROJECT_ENVIRONMENT": str(Path(tmp) / "venv"),
        }
        t0 = time.perf_counter()
        proc = subprocess.run(
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest tests/test_media_series.py tests/test_media_series_v011_publication.py -q && "
            "uv run --frozen audit --root . media series --skip-render --skip-publish",
            cwd=extract,
            env=env,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        clean = {
            "literal_command": (
                "uv sync --frozen --extra dev && "
                "uv run --frozen pytest tests/test_media_series.py "
                "tests/test_media_series_v011_publication.py -q && "
                "uv run --frozen audit --root . media series --skip-render --skip-publish"
            ),
            "exit_code": proc.returncode,
            "duration_seconds": round(time.perf_counter() - t0, 3),
            "stdout_tail": ((proc.stdout or "") + (proc.stderr or ""))[-4000:],
        }
    if clean["exit_code"] != 0:
        raise SeriesPublishError(f"clean-extraction FAIL: {clean}")

    prior_after = sha256_file(external / ACCEPTED_ROADMAP_V01_ZIP) if (external / ACCEPTED_ROADMAP_V01_ZIP).is_file() else None
    prior_ok = prior_after == ACCEPTED_ROADMAP_V01_SHA256 and prior_after == prior_before

    proxies = sorted((root / PUBLIC_MEDIA_DIR / "proxies").glob("*.mp4"))
    proxy_meta = []
    for p in proxies:
        proxy_meta.append({"path": p.name, "bytes": p.stat().st_size})

    attestation = {
        "bundle_kind": REVIEW_BUNDLE_KIND,
        "version": SERIES_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "attestation_status": "PASS" if verification.get("ok") and prior_ok else "FAIL",
        "publication_status": "PRIVATE_PUBLICATION_REVIEW_REQUIRED",
        "review_zip": REVIEW_ZIP_NAME,
        "review_zip_sha256": digest,
        "members": len(names),
        "indexed_members": len(payloads),
        "members_equals_indexed_plus_one": len(names) == len(payloads) + 1,
        "social_publish": False,
        "core_zips_unchanged": baseline.get("core_zips_unchanged"),
        "baseline_core_zip_sha256": baseline.get("sha256"),
        "accepted_sdr_v0111_sha256": ACCEPTED_SDR_V0111_SHA256,
        "prior_roadmap_v01_sha256": prior_after,
        "prior_roadmap_v01_untouched": prior_ok,
        "master_videos_generated_in_workspace": True,
        "master_videos_in_review_bundle": False,
        "proxy_videos_in_review_bundle": True,
        "proxy_resolution": f"{PROXY_WIDTH}x{PROXY_HEIGHT}",
        "proxy_files": proxy_meta,
        "manifest_mutation_proof": mutation,
        "clean_extraction": clean,
        "evidence_manifest": man,
    }
    if attestation["attestation_status"] != "PASS":
        att_path.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
        raise SeriesPublishError("attestation FAIL")
    att_path.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    return attestation
