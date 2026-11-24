"""Publish lifecycle — Trajectory Regime + TTE Foundation v0.1."""

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
from human_simulator.trajectory_regime_tte_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    TRANSITIONS_DIR,
    VERSION,
)

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_trajectory_regime_tte_v01_unit.py",
    "tests/test_trajectory_regime_tte_v01_contracts.py",
    "tests/test_trajectory_regime_tte_v01_live.py",
)
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
    if p.suffix.lower() in {".zip", ".parquet"} or _CACHE_RE.search(rel):
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
    for label, (name, exp) in PRIOR_ZIPS.items():
        p = external / name
        if not p.is_file() or _sha(p) != exp:
            raise PublicationError(f"baseline fail: {name}")
        prior_before[label] = _sha(p)

    art = root / ARTIFACT_DIR
    ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
    if not ver.get("ok"):
        raise PublicationError("verification.ok false — REFUSE")
    st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    required = {
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "PRIOR_STATE_ENCODER_FOUNDATION_STATUS": "NOT_ACCEPTED_WEAK_OR_NEGATIVE_EVIDENCE",
        "TRAIN_ONLY_OUTCOME_VOCABULARY_STATUS": "PASS",
        "DENOISING_MASKED_ENCODER_STATUS": "FROZEN",
        "SOURCE_STRATIFIED_APPLICABILITY_STATUS": "TECHNICAL_EVALUATED",
        "TRANSITION_DATASET_STATUS": "BUILT",
        "TRANSITION_DATASET_ACCOUNTING_STATUS": "PASS",
        "TIME_TO_EVENT_DATASET_STATUS": "BUILT",
        "ENGINE_TRAJECTORY_TTE_SHADOW_STATUS": "TECHNICAL_SHADOW_PASS",
        "CURRENT_STATE_CLASSIFIER_STATUS": "NOT_STARTED_NO_ACCEPTED_LABEL_ONTOLOGY",
        "TRAJECTORY_CLASSIFIER_STATUS": "NOT_STARTED",
        "SAFETY_BOUNDARY_CLASSIFIER_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PUBLIC_DATA_MINIMIZATION_STATUS": "PASS_AGGREGATE_ONLY",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
    }
    for k, exp in required.items():
        if st.get(k) != exp:
            raise PublicationError(f"{k}={st.get(k)}")
    if not st.get("TECHNICAL_PASS"):
        raise PublicationError("TECHNICAL_PASS false")
    if not (root / TRANSITIONS_DIR / "transitions.parquet").is_file():
        raise PublicationError("missing private transitions")

    env_live = os.environ.copy()
    live_proc = subprocess.run(
        ["uv", "run", "--frozen", "pytest", "-q", *UNIT_TESTS],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env_live,
        check=False,
    )
    if live_proc.returncode != 0:
        raise PublicationError(
            f"live suite FAIL: {(live_proc.stdout or '') + (live_proc.stderr or '')}"[-2500:]
        )

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
    for rel in payloads:
        if rel.endswith(".parquet") or "private/" in rel:
            raise PublicationError(f"row-level/private in payload: {rel}")

    with tempfile.TemporaryDirectory(prefix="uhbse-traj-tte-v01-") as tmp:
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
            "uv run --frozen pytest "
            "tests/test_trajectory_regime_tte_v01_unit.py "
            "tests/test_trajectory_regime_tte_v01_contracts.py "
            "tests/test_trajectory_regime_tte_v01_live.py "
            "-q --override-ini=cache_dir=/tmp/uhbse-pytest-disabled"
        )
        t0 = datetime.now(UTC)
        proc = subprocess.run(
            cmd, cwd=staging, env=env, shell=True, capture_output=True, text=True, check=False
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        strip_cache(staging)
        if proc.returncode != 0:
            raise PublicationError(f"clean-extraction FAIL: {out[-2500:]}")
        passed = skipped = failed = 0
        m = re.search(r"(\d+) passed", out)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) skipped", out)
        if m:
            skipped = int(m.group(1))
        m = re.search(r"(\d+) failed", out)
        if m:
            failed = int(m.group(1))
        unit = {
            "exit_code": 0,
            "duration_seconds": round((datetime.now(UTC) - t0).total_seconds(), 3),
            "status": "PASS",
            "passed": passed,
            "skipped": skipped,
            "failed": failed,
            "live_repo_suite_exit_code": live_proc.returncode,
            "literal_command": cmd,
            "output_tail": out[-6000:],
        }
        art_s = staging / ARTIFACT_DIR
        (art_s / "tests.json").write_text(json.dumps(unit, indent=2) + "\n", encoding="utf-8")
        write_manifest(art_s)
        if not verify_manifest(art_s)["ok"]:
            raise PublicationError("POST_TEST_MANIFEST FAIL")
        if not mutation_proof(art_s)["ok"]:
            raise PublicationError("MUTATION_PROOF FAIL")

        staging_files = {
            p.relative_to(staging).as_posix(): p.read_bytes()
            for p in sorted(staging.rglob("*"))
            if p.is_file()
            and not _CACHE_RE.search(p.relative_to(staging).as_posix())
            and p.relative_to(staging).as_posix() != "REVIEW_INDEX.md"
        }
        if any(n.endswith(".parquet") for n in staging_files):
            raise PublicationError("parquet in staging")
        rows = [f"| `{path}` | `{_sha(data)}` |" for path, data in sorted(staging_files.items())]
        (staging / "REVIEW_INDEX.md").write_text(
            f"# REVIEW_INDEX — Trajectory Regime + TTE Foundation v{VERSION}\n\n"
            "self_excluded=true\n\n"
            "SCIENTIFIC_CROSS_SOURCE_PASS=false\n"
            "TECHNICAL_PASS=true\n\n"
            "| path | sha256 |\n|------|--------|\n"
            + "\n".join(rows)
            + "\n",
            encoding="utf-8",
        )
        strip_cache(staging)
        if not scan_cache(staging)["ok"]:
            raise PublicationError("cache residues")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(staging.rglob("*")):
                if p.is_file() and not _CACHE_RE.search(p.relative_to(staging).as_posix()):
                    zf.write(p, p.relative_to(staging).as_posix())

        extract = isolation / "extract"
        extract.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract)
            names = [n for n in zf.namelist() if not n.endswith("/")]
        if any(n.endswith(".parquet") for n in names):
            zip_path.unlink(missing_ok=True)
            raise PublicationError("parquet in zip")
        if not verify_manifest(extract / ARTIFACT_DIR)["ok"]:
            zip_path.unlink(missing_ok=True)
            raise PublicationError("POST_PACK_MANIFEST FAIL")
        recon = reconcile_review_index(
            names,
            (extract / "REVIEW_INDEX.md").read_text(encoding="utf-8"),
            payloads_on_disk={
                n: (extract / n).read_bytes() for n in names if n != "REVIEW_INDEX.md"
            },
        )
        if not recon.get("ok"):
            zip_path.unlink(missing_ok=True)
            raise PublicationError(f"REVIEW_INDEX FAIL: {recon}")

        digest = _sha(zip_path)
        sidecar.write_text(f"{digest}  {ZIP_NAME}\n", encoding="utf-8")
        prior_after = {
            label: _sha(external / name) for label, (name, _) in PRIOR_ZIPS.items()
        }
        if prior_before != prior_after:
            zip_path.unlink(missing_ok=True)
            sidecar.unlink(missing_ok=True)
            raise PublicationError("prior ZIP mutated")

        att = {
            "version": VERSION,
            "zip": ZIP_NAME,
            "sha256": digest,
            "members": len(names),
            "indexed_members": recon.get("indexed_members"),
            "status": "PASS",
            "ok": True,
            "PUBLICATION_INTEGRITY_STATUS": "PASS",
            "SCIENTIFIC_CROSS_SOURCE_PASS": False,
            "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
            "prior_sha_before": prior_before,
            "prior_sha_after": prior_after,
            "clean_extraction": {"passed": passed, "skipped": skipped, "failed": failed},
            "generated_at": datetime.now(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        att_path.write_text(json.dumps(att, indent=2) + "\n", encoding="utf-8")

        # stamp publication integrity into live artifacts (re-hash after write)
        st["PUBLICATION_INTEGRITY_STATUS"] = "PASS"
        (art / "status-contract.json").write_text(
            json.dumps(st, indent=2) + "\n", encoding="utf-8"
        )

    return {
        "ok": True,
        "zip": ZIP_NAME,
        "sha256": digest,
        "members": len(names),
        "indexed_members": recon.get("indexed_members"),
        "attestation": ATT_NAME,
        "PUBLICATION_INTEGRITY_STATUS": "PASS",
    }
