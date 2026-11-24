"""Publish lifecycle v0.2.1 — REVIEW_INDEX lists every member with SHA-256."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.policy import (
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
    ARTIFACT_DIR,
    REVIEW_ZIP,
    VERSION,
)

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_cross_source_lab_semantic_v021_unit.py",
    "tests/test_cross_source_lab_semantic_v021_contracts.py",
)
PRIOR_IMMUTABLE_ZIPS = {
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


def write_manifest(art: Path) -> None:
    names = sorted(
        p.relative_to(art).as_posix()
        for p in art.rglob("*")
        if p.is_file() and p.name != "evidence-manifest.sha256"
    )
    (art / "evidence-manifest.sha256").write_text(
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n", encoding="utf-8"
    )


def verify_manifest(art: Path) -> dict[str, Any]:
    man = art / "evidence-manifest.sha256"
    if not man.is_file():
        return {"ok": False, "reason": "missing"}
    mism: list[str] = []
    checked = 0
    tests_in = False
    for line in man.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        name = name.strip()
        if name == "tests.json":
            tests_in = True
        path = art / name
        if not path.is_file():
            mism.append(f"missing:{name}")
            continue
        checked += 1
        if _sha(path) != digest.strip():
            mism.append(name)
    return {
        "ok": not mism and tests_in,
        "checked": checked,
        "mismatches": mism,
        "tests_json_in_manifest": tests_in,
    }


def strip_cache(root: Path) -> None:
    for p in sorted(root.rglob("*"), reverse=True):
        if p.is_dir() and p.name in {"__pycache__", ".pytest_cache"}:
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file() and (p.suffix == ".pyc" or _CACHE_RE.search(p.as_posix())):
            p.unlink(missing_ok=True)


def scan_cache(root: Path) -> dict[str, Any]:
    hits = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and _CACHE_RE.search(p.as_posix())
    ]
    return {"ok": not hits, "n_hits": len(hits), "hits": hits[:20]}


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
            ".html",
            ".csv",
        } or rel.startswith("artifacts/"):
            payloads[r] = path.read_bytes()


def build_review_index(members: dict[str, bytes]) -> str:
    """Index every ZIP member except REVIEW_INDEX.md itself."""
    rows = []
    for path in sorted(members):
        if path == "REVIEW_INDEX.md" or path.endswith("/REVIEW_INDEX.md"):
            continue
        rows.append(f"| `{path}` | `{_sha(members[path])}` |")
    body = "\n".join(rows)
    return f"""# REVIEW_INDEX — Lab Analyte Ontology Metadata Closure v{VERSION}

self_excluded=true

SCIENTIFIC_PASS=false
REVIEW_PACKET_PUBLICATION_STATUS=PASS
SCIENTIFIC_MAPPING_STATUS=DOMAIN_REVIEW_DECISION_REQUIRED

| path | sha256 |
|------|--------|
{body}
"""


def reconcile_review_index(
    names: list[str], index_text: str, payloads_on_disk: dict[str, bytes] | None = None
) -> dict[str, Any]:
    indexed_paths: list[str] = []
    indexed_hashes: dict[str, str] = {}
    for line in index_text.splitlines():
        line = line.strip()
        if not line.startswith("| `"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 2:
            continue
        path = parts[0].strip("`")
        digest = parts[1].strip("`")
        if path == "path" or digest == "sha256":
            continue
        indexed_paths.append(path)
        indexed_hashes[path] = digest

    member_files = [n for n in names if not n.endswith("/")]
    index_name = next((n for n in member_files if n.endswith("REVIEW_INDEX.md")), None)
    non_index = [n for n in member_files if n != index_name]
    duplicate_paths = sorted({p for p in indexed_paths if indexed_paths.count(p) > 1})
    unindexed = sorted(set(non_index) - set(indexed_paths))
    extra_indexed = sorted(set(indexed_paths) - set(non_index))
    members = len(member_files)
    indexed = len(indexed_paths)
    ok = (
        index_name is not None
        and members == indexed + 1
        and not duplicate_paths
        and not unindexed
        and not extra_indexed
    )
    hash_mismatches: list[str] = []
    if payloads_on_disk:
        for p, dig in indexed_hashes.items():
            if p in payloads_on_disk and _sha(payloads_on_disk[p]) != dig:
                hash_mismatches.append(p)
        ok = ok and not hash_mismatches
    return {
        "ok": ok,
        "members": members,
        "indexed_members": indexed,
        "self_excluded": True,
        "duplicate_paths": duplicate_paths,
        "unindexed_members": unindexed,
        "extra_indexed": extra_indexed,
        "hash_mismatches": hash_mismatches[:20],
        "REVIEW_INDEX_ACCOUNTING_STATUS": "PASS" if ok else "FAIL",
    }


def mutation_proof(art: Path) -> dict[str, Any]:
    man = art / "evidence-manifest.sha256"
    original = man.read_bytes()
    # mutate
    man.write_bytes(original + b"\n#mutated\n")
    fail = verify_manifest(art)
    # restore
    man.write_bytes(original)
    ok = verify_manifest(art)
    return {
        "after_mutation_ok": fail.get("ok"),
        "after_restore_ok": ok.get("ok"),
        "ok": (fail.get("ok") is False) and bool(ok.get("ok")),
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
    ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
    if not ver.get("ok"):
        raise PublicationError("verification.ok false")
    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    for k, exp in {
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "V02_ANALYTE_IDENTITY_DEFECT_REPRODUCTION_STATUS": "PASS",
        "EXHAUSTIVE_CROSS_SOURCE_CANDIDATE_DISCOVERY_STATUS": "PASS",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
        "SCIENTIFIC_PASS": False,
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
    }.items():
        if st.get(k) != exp:
            raise PublicationError(f"{k}={st.get(k)}")

    payloads: dict[str, bytes] = {}
    _add_tree(payloads, root, ARTIFACT_DIR)
    _add_tree(payloads, root, "src/human_simulator")
    for rel in (
        "docs/current-stage.md",
        "AGENTS.md",
        *UNIT_TESTS,
        "tests/test_cross_source_lab_semantic_v02_unit.py",
        "tests/test_cross_source_lab_semantic_v02_contracts.py",
        "pyproject.toml",
        "uv.lock",
    ):
        p = root / rel
        if p.is_file():
            payloads[rel] = p.read_bytes()

    with tempfile.TemporaryDirectory(prefix="uhbse-lab-sem-v021-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        strip_cache(staging)
        (staging / "src" / "human_simulator").mkdir(parents=True, exist_ok=True)
        init = staging / "src" / "human_simulator" / "__init__.py"
        if not init.is_file():
            init.write_text("", encoding="utf-8")

        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest "
            "tests/test_cross_source_lab_semantic_v021*.py "
            "tests/test_cross_source_lab_semantic_v02*.py -q "
            "--override-ini=cache_dir=/tmp/uhbse-pytest-disabled"
        )
        t0 = datetime.now(UTC)
        proc = subprocess.run(
            cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        strip_cache(staging)
        cache = scan_cache(staging)
        unit = {
            "exit_code": proc.returncode,
            "duration_seconds": round((datetime.now(UTC) - t0).total_seconds(), 3),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "output_tail": out[-6000:],
            "literal_command": cmd,
        }
        if proc.returncode != 0:
            raise PublicationError(f"tests FAIL: {out[-2000:]}")
        art_s = staging / ARTIFACT_DIR
        (art_s / "tests.json").write_text(json.dumps(unit, indent=2) + "\n", encoding="utf-8")
        write_manifest(art_s)
        post_test = verify_manifest(art_s)
        if not post_test["ok"]:
            raise PublicationError(f"POST_TEST_MANIFEST FAIL: {post_test}")

        mut = mutation_proof(art_s)
        if not mut["ok"]:
            raise PublicationError(f"MUTATION_PROOF FAIL: {mut}")

        # Build file map for REVIEW_INDEX (all staging files that will be zipped)
        staging_files: dict[str, bytes] = {}
        for p in sorted(staging.rglob("*")):
            if p.is_file() and not _CACHE_RE.search(p.relative_to(staging).as_posix()):
                rel = p.relative_to(staging).as_posix()
                if rel == "REVIEW_INDEX.md":
                    continue
                staging_files[rel] = p.read_bytes()
        index_text = build_review_index(staging_files)
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

        index_bytes = (extract / "REVIEW_INDEX.md").read_bytes()
        disk_payloads = {
            n: (extract / n).read_bytes()
            for n in names
            if n != "REVIEW_INDEX.md" and (extract / n).is_file()
        }
        recon = reconcile_review_index(
            names, index_bytes.decode("utf-8"), payloads_on_disk=disk_payloads
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
            "duplicate_paths": [],
            "unindexed_members": [],
            "cache_members": 0,
            "attestation_status": "PASS",
            "SCIENTIFIC_PASS": False,
            "REVIEW_PACKET_PUBLICATION_STATUS": "PASS",
            "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
            "PUBLICATION_INTEGRITY_STATUS": "PASS",
            "REVIEW_INDEX_ACCOUNTING_STATUS": "PASS",
            "POST_TEST_MANIFEST_STATUS": "PASS",
            "POST_PACK_MANIFEST_STATUS": "PASS",
            "MUTATION_PROOF_STATUS": "PASS",
            "CACHE_MEMBER_SCAN_STATUS": "PASS",
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
                "REVIEW_INDEX_ACCOUNTING_STATUS": "PASS",
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
            "post_test": post_test,
            "post_pack": post_pack,
            "mutation_proof": mut,
            "review_index": recon,
            "prior_before": prior_before,
            "prior_after": prior_after,
            "SCIENTIFIC_PASS": False,
        }
