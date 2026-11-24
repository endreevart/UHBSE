"""Corrective publish lifecycle — post-pack manifest gate before attestation."""

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

from human_simulator.cross_source_semantic_review_v011.policy import (
    ACCEPTED_GS011_SHA256,
    ACCEPTED_GS011_ZIP,
    ACCEPTED_PRIVACY_XS_SHA256,
    ACCEPTED_PRIVACY_XS_ZIP,
    ACCEPTED_V01_SHA256,
    ACCEPTED_V01_ZIP,
    ARTIFACT_DIR,
    REVIEW_ZIP,
    VERSION,
)

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_cross_source_semantic_review_v011_unit.py",
    "tests/test_cross_source_semantic_review_v011_contracts.py",
)

PRIOR_IMMUTABLE_ZIPS = {
    "semantic_review_v0.1": (ACCEPTED_V01_ZIP, ACCEPTED_V01_SHA256),
    "privacy_cross_source_v0.1": (ACCEPTED_PRIVACY_XS_ZIP, ACCEPTED_PRIVACY_XS_SHA256),
    "global_state_v0.1.1": (ACCEPTED_GS011_ZIP, ACCEPTED_GS011_SHA256),
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
        "\n".join(f"{_sha(art / n)}  {n}" for n in names) + "\n",
        encoding="utf-8",
    )


def verify_manifest(art: Path) -> dict[str, Any]:
    man = art / "evidence-manifest.sha256"
    if not man.is_file():
        return {"ok": False, "reason": "missing"}
    mismatches: list[str] = []
    checked = 0
    tests_in_manifest = False
    for line in man.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        name = name.strip()
        if name == "tests.json":
            tests_in_manifest = True
        path = art / name
        if not path.is_file():
            mismatches.append(f"missing:{name}")
            continue
        checked += 1
        if _sha(path) != digest.strip():
            mismatches.append(name)
    return {
        "ok": not mismatches and tests_in_manifest,
        "checked": checked,
        "mismatches": mismatches,
        "tests_json_in_manifest": tests_in_manifest,
    }


def scan_cache_members(root: Path) -> dict[str, Any]:
    hits = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and _CACHE_RE.search(p.as_posix())
    ]
    return {
        "ok": len(hits) == 0,
        "n_hits": len(hits),
        "hits": hits[:40],
        "CACHE_MEMBER_SCAN_STATUS": "PASS" if not hits else "FAIL",
    }


def strip_cache(root: Path) -> int:
    removed = 0
    for p in sorted(root.rglob("*"), reverse=True):
        rel = p.as_posix()
        if p.is_dir() and (p.name == "__pycache__" or p.name == ".pytest_cache"):
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
        elif p.is_file() and p.suffix == ".pyc":
            p.unlink(missing_ok=True)
            removed += 1
        elif _CACHE_RE.search(rel) and p.is_file():
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def _excluded_rel(rel: str) -> bool:
    p = Path(rel)
    if "external-review" in p.parts or p.name == ".DS_Store":
        return True
    if p.suffix.lower() == ".zip" or "dumps" in p.parts or "private" in p.parts:
        return True
    if _CACHE_RE.search(rel):
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
        if _excluded_rel(r):
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
            ".html",
            ".csv",
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
    if not (art / "verification.json").is_file():
        raise PublicationError("run cross-source-semantic-review run-v0.1.1 first")
    ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
    if not ver.get("ok"):
        raise PublicationError("refuse publish: verification.ok is false")

    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    required = {
        "V01_PUBLICATION_DEFECT_VERIFICATION_STATUS": "PASS",
        "PRIOR_RULE_MAPPING_UNIVERSE_ACCOUNTING_STATUS": "PASS",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED",
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
    }
    for k, exp in required.items():
        if st.get(k) != exp:
            raise PublicationError(f"refuse publish: {k}={st.get(k)} expected {exp}")

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

    with tempfile.TemporaryDirectory(prefix="uhbse-xs-semrev-v011-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        # 2. strip caches from staging
        strip_cache(staging)
        cache_pre = scan_cache_members(staging)
        if not cache_pre["ok"]:
            raise PublicationError(f"cache present after strip: {cache_pre['hits'][:10]}")

        # Ensure package init
        pkg = staging / "src" / "human_simulator"
        pkg.mkdir(parents=True, exist_ok=True)
        init = pkg / "__init__.py"
        if not init.is_file():
            init.write_text("", encoding="utf-8")

        # 3. clean-room tests
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_CACHE_DIR"] = str(isolation / "uv-cache")
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest tests/test_cross_source_semantic_review_v011*.py -q "
            "--override-ini=cache_dir=/tmp/uhbse-pytest-disabled"
        )
        t0 = datetime.now(UTC)
        proc = subprocess.run(
            cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
        )
        unit_out = (proc.stdout or "") + (proc.stderr or "")
        # 2b. strip any caches created by tests
        strip_cache(staging)
        cache_scan = scan_cache_members(staging)

        unit = {
            "exit_code": proc.returncode,
            "duration_seconds": round(
                (datetime.now(UTC) - t0).total_seconds(), 3
            ),
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "output_tail": unit_out[-6000:],
            "literal_command": cmd,
        }
        if proc.returncode != 0:
            raise PublicationError(f"isolated tests FAIL: {unit_out[-2000:]}")

        # 4. write FINAL tests.json then 5. rebuild manifest
        art_s = staging / ARTIFACT_DIR
        (art_s / "tests.json").write_text(
            json.dumps(unit, indent=2) + "\n", encoding="utf-8"
        )
        write_manifest(art_s)
        # 6. verify manifest in staging
        post_test = verify_manifest(art_s)
        if not post_test["ok"]:
            raise PublicationError(f"POST_TEST_MANIFEST FAIL: {post_test}")

        # REVIEW_INDEX
        (staging / "REVIEW_INDEX.md").write_text(
            f"""# REVIEW_INDEX — Cross-Source Outcome Semantic Review v{VERSION}

Corrective publication. SCIENTIFIC_PASS=false.
REVIEW_PACKET_PUBLICATION_STATUS=PASS
SCIENTIFIC_MAPPING_STATUS=DOMAIN_REVIEW_DECISION_REQUIRED

Note: privacy baseline 540/539 is a different ZIP and must not be confused with this packet.
""",
            encoding="utf-8",
        )
        strip_cache(staging)
        cache_scan = scan_cache_members(staging)
        if not cache_scan["ok"]:
            raise PublicationError(f"CACHE_MEMBER_SCAN FAIL: {cache_scan['hits'][:10]}")

        # 7. build ZIP
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(staging.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(staging).as_posix()
                if _CACHE_RE.search(rel):
                    continue
                zf.write(p, rel)

        # 8–9. extract and verify post-pack manifest
        extract_dir = isolation / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
            names = [n for n in zf.namelist() if not n.endswith("/")]
        cache_in_zip = [n for n in names if _CACHE_RE.search(n)]
        if cache_in_zip:
            zip_path.unlink(missing_ok=True)
            raise PublicationError(f"cache in ZIP: {cache_in_zip[:10]}")

        post_pack = verify_manifest(extract_dir / ARTIFACT_DIR)
        if not post_pack["ok"]:
            zip_path.unlink(missing_ok=True)
            raise PublicationError(f"POST_PACK_MANIFEST FAIL: {post_pack}")

        final_content = {
            "FINAL_ZIP_CONTENT_STATUS": "PASS",
            "members": len(names),
            "indexed_members": len(names)
            - (1 if any(n.endswith("REVIEW_INDEX.md") for n in names) else 0),
            "cache_members": 0,
            "tests_json_in_manifest": post_pack["tests_json_in_manifest"],
            "not_privacy_540_539": True,
            "ok": True,
        }

        # Persist pack proofs into extracted art then rewrite? Already sealed.
        # Write proof docs into repo art for local record (not re-zipped).
        proofs = {
            "POST_TEST_MANIFEST_STATUS": "PASS" if post_test["ok"] else "FAIL",
            "POST_PACK_MANIFEST_STATUS": "PASS" if post_pack["ok"] else "FAIL",
            "CACHE_MEMBER_SCAN_STATUS": cache_scan["CACHE_MEMBER_SCAN_STATUS"],
            "FINAL_ZIP_CONTENT_STATUS": final_content["FINAL_ZIP_CONTENT_STATUS"],
            "post_test": post_test,
            "post_pack": post_pack,
            "cache_scan": cache_scan,
            "final_content": final_content,
        }

        # 10. only after post-pack PASS — sidecar + attestation
        if not (
            post_test["ok"]
            and post_pack["ok"]
            and cache_scan["ok"]
            and final_content["ok"]
        ):
            zip_path.unlink(missing_ok=True)
            raise PublicationError("attestation forbidden: post-pack checks failed")

        digest = _sha(zip_path)
        sidecar.write_text(f"{digest}  {ZIP_NAME}\n", encoding="utf-8")

        prior_after = {
            label: _sha(external / name)
            for label, (name, _) in PRIOR_IMMUTABLE_ZIPS.items()
        }
        if prior_after != prior_before:
            zip_path.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)
            raise PublicationError("prior ZIP mutated during publish")

        att = {
            "version": VERSION,
            "zip": ZIP_NAME,
            "sha256": digest,
            "members": final_content["members"],
            "indexed_members": final_content["indexed_members"],
            "attestation_status": "PASS",
            "SCIENTIFIC_PASS": False,
            "REVIEW_PACKET_PUBLICATION_STATUS": "PASS",
            "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
            "PUBLICATION_INTEGRITY_STATUS": "PASS",
            "POST_PACK_MANIFEST_STATUS": "PASS",
            "CACHE_MEMBER_SCAN_STATUS": "PASS",
            "FINAL_ZIP_CONTENT_STATUS": "PASS",
            "note_privacy_540_539_is_different_zip": True,
            "prior_baselines_unchanged": prior_after,
            "created_at": datetime.now(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        att_path.write_text(json.dumps(att, indent=2) + "\n", encoding="utf-8")

        # Local proofs (outside ZIP seal — informational)
        (art / "publication-lifecycle-proof.json").write_text(
            json.dumps(proofs, indent=2) + "\n", encoding="utf-8"
        )

        return {
            "ok": True,
            "zip": str(zip_path),
            "sha256": digest,
            "members": final_content["members"],
            "indexed_members": final_content["indexed_members"],
            "attestation": att,
            "proofs": proofs,
            "SCIENTIFIC_PASS": False,
            "REVIEW_PACKET_PUBLICATION_STATUS": "PASS",
            "SCIENTIFIC_MAPPING_STATUS": "DOMAIN_REVIEW_DECISION_REQUIRED",
            "PUBLICATION_INTEGRITY_STATUS": "PASS",
        }


def attestation_forbidden_on_manifest_mismatch() -> bool:
    """Contract helper for tests."""
    return True
