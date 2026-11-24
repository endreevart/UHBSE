"""Publish lifecycle — Unified Research Layer v0.3."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import (
    mutation_proof,
    reconcile_review_index,
    scan_cache,
    strip_cache,
    verify_manifest,
    write_manifest,
)
from human_simulator.unified_research_layer_v03.policy import (
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_PRIVACY_XS_SHA256,
    ACCEPTED_PRIVACY_XS_ZIP,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ACCEPTED_V011_SHA256,
    ACCEPTED_V011_ZIP,
    ACCEPTED_V02_SHA256,
    ACCEPTED_V02_ZIP,
    ACCEPTED_V021_SHA256,
    ACCEPTED_V021_ZIP,
    ACCEPTED_V0211_SHA256,
    ACCEPTED_V0211_ZIP,
    ARTIFACT_DIR,
    REVIEW_ZIP,
    VERSION,
)

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_unified_research_layer_v03_unit.py",
    "tests/test_unified_research_layer_v03_contracts.py",
)
PRIOR_IMMUTABLE_ZIPS = {
    "lab_v0.2.1.1": (ACCEPTED_V0211_ZIP, ACCEPTED_V0211_SHA256),
    "lab_v0.2.1": (ACCEPTED_V021_ZIP, ACCEPTED_V021_SHA256),
    "lab_v0.2": (ACCEPTED_V02_ZIP, ACCEPTED_V02_SHA256),
    "semantic_v0.1.1": (ACCEPTED_V011_ZIP, ACCEPTED_V011_SHA256),
    "semantic_v0.1": (ACCEPTED_V01_ZIP, ACCEPTED_V01_SHA256),
    "privacy_v0.1": (ACCEPTED_PRIVACY_XS_ZIP, ACCEPTED_PRIVACY_XS_SHA256),
    "gs_v0.1.1": (ACCEPTED_GS011_ZIP, ACCEPTED_GS011_SHA256),
}
_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")


class PublicationError(RuntimeError):
    pass


def _sha(p: Path | bytes) -> str:
    if isinstance(p, bytes):
        return hashlib.sha256(p).hexdigest()
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _excluded(rel: str) -> bool:
    p = Path(rel)
    if "external-review" in p.parts or "private" in p.parts or "dumps" in p.parts:
        return True
    if p.suffix.lower() == ".zip" or _CACHE_RE.search(rel):
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
    ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
    if not ver.get("ok"):
        raise PublicationError("verification.ok false")
    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    for k, exp in {
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "UNACCOUNTED_COUNT": 0,
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "SCIENTIFIC_PASS": False,
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY",
    }.items():
        if st.get(k) != exp:
            raise PublicationError(f"{k}={st.get(k)}")
    if not st.get("TECHNICAL_PASS"):
        raise PublicationError("TECHNICAL_PASS false")

    payloads: dict[str, bytes] = {}
    _add_tree(payloads, root, ARTIFACT_DIR)
    _add_tree(payloads, root, "src/human_simulator")
    for rel in (
        "docs/current-stage.md",
        "AGENTS.md",
        *UNIT_TESTS,
        "pyproject.toml",
        "uv.lock",
    ):
        p = root / rel
        if p.is_file():
            payloads[rel] = p.read_bytes()

    with tempfile.TemporaryDirectory(prefix="uhbse-url-v03-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        strip_cache(staging)
        init = staging / "src" / "human_simulator" / "__init__.py"
        init.parent.mkdir(parents=True, exist_ok=True)
        if not init.is_file():
            init.write_text("", encoding="utf-8")

        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest tests/test_unified_research_layer_v03*.py -q "
            "--override-ini=cache_dir=/tmp/uhbse-pytest-disabled"
        )
        t0 = datetime.now(UTC)
        proc = subprocess.run(
            cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        strip_cache(staging)
        if proc.returncode != 0:
            raise PublicationError(f"tests FAIL: {out[-2500:]}")
        unit = {
            "exit_code": 0,
            "duration_seconds": round((datetime.now(UTC) - t0).total_seconds(), 3),
            "status": "PASS",
            "output_tail": out[-6000:],
            "literal_command": cmd,
        }
        art_s = staging / ARTIFACT_DIR
        (art_s / "tests.json").write_text(json.dumps(unit, indent=2) + "\n", encoding="utf-8")
        write_manifest(art_s)
        post_test = verify_manifest(art_s)
        if not post_test["ok"]:
            raise PublicationError(f"POST_TEST_MANIFEST FAIL: {post_test}")
        mut = mutation_proof(art_s)
        if not mut["ok"]:
            raise PublicationError(f"MUTATION_PROOF FAIL: {mut}")

        staging_files = {
            p.relative_to(staging).as_posix(): p.read_bytes()
            for p in sorted(staging.rglob("*"))
            if p.is_file() and not _CACHE_RE.search(p.relative_to(staging).as_posix())
            and p.relative_to(staging).as_posix() != "REVIEW_INDEX.md"
        }
        rows = [f"| `{path}` | `{_sha(data)}` |" for path, data in sorted(staging_files.items())]
        index_text = (
            f"# REVIEW_INDEX — Unified A+B Clinical Research Layer v{VERSION}\n\n"
            "self_excluded=true\n\n"
            "SCIENTIFIC_PASS=false\n"
            "TECHNICAL_PASS=true\n"
            "REVIEW_PACKET_PUBLICATION_STATUS=PASS\n\n"
            "| path | sha256 |\n|------|--------|\n"
            + "\n".join(rows)
            + "\n"
        )
        (staging / "REVIEW_INDEX.md").write_text(index_text, encoding="utf-8")
        strip_cache(staging)
        cache = scan_cache(staging)
        if not cache["ok"]:
            raise PublicationError(f"cache: {cache['hits']}")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(staging.rglob("*")):
                if p.is_file() and not _CACHE_RE.search(p.relative_to(staging).as_posix()):
                    zf.write(p, p.relative_to(staging).as_posix())

        extract = isolation / "extract"
        extract.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract)
            names = [n for n in zf.namelist() if not n.endswith("/")]
        if any(_CACHE_RE.search(n) for n in names):
            zip_path.unlink(missing_ok=True)
            raise PublicationError("cache in zip")
        post_pack = verify_manifest(extract / ARTIFACT_DIR)
        if not post_pack["ok"]:
            zip_path.unlink(missing_ok=True)
            raise PublicationError(f"POST_PACK_MANIFEST FAIL: {post_pack}")

        recon = reconcile_review_index(
            names,
            (extract / "REVIEW_INDEX.md").read_text(encoding="utf-8"),
            payloads_on_disk={
                n: (extract / n).read_bytes()
                for n in names
                if n != "REVIEW_INDEX.md" and (extract / n).is_file()
            },
        )
        if not recon["ok"]:
            zip_path.unlink(missing_ok=True)
            raise PublicationError(f"REVIEW_INDEX FAIL: {recon}")

        digest = _sha(zip_path)
        sidecar.write_text(f"{digest}  {ZIP_NAME}\n", encoding="utf-8")
        prior_after = {
            label: _sha(external / name)
            for label, (name, _) in PRIOR_IMMUTABLE_ZIPS.items()
        }
        if prior_after != prior_before:
            raise PublicationError("prior ZIP mutated")

        att = {
            "version": VERSION,
            "zip": ZIP_NAME,
            "sha256": digest,
            "members": recon["members"],
            "indexed_members": recon["indexed_members"],
            "self_excluded": True,
            "cache_members": 0,
            "attestation_status": "PASS",
            "SCIENTIFIC_PASS": False,
            "TECHNICAL_PASS": True,
            "REVIEW_PACKET_PUBLICATION_STATUS": "PASS",
            "PUBLICATION_INTEGRITY_STATUS": "PASS",
            "REVIEW_INDEX_ACCOUNTING_STATUS": "PASS",
            "POST_TEST_MANIFEST_STATUS": "PASS",
            "POST_PACK_MANIFEST_STATUS": "PASS",
            "MUTATION_PROOF_STATUS": "PASS",
            "prior_baselines_unchanged": prior_after,
            "created_at": datetime.now(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        att_path.write_text(json.dumps(att, indent=2) + "\n", encoding="utf-8")
        st.update(
            {
                "REVIEW_PACKET_PUBLICATION_STATUS": "PASS",
                "PUBLICATION_INTEGRITY_STATUS": "PASS",
            }
        )
        (art / "status-contract.json").write_text(
            json.dumps(st, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return {
            "ok": True,
            "zip": str(zip_path),
            "sha256": digest,
            "members": recon["members"],
            "indexed_members": recon["indexed_members"],
            "attestation": att,
            "SCIENTIFIC_PASS": False,
            "TECHNICAL_PASS": True,
        }
