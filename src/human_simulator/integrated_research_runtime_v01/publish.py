"""Publish lifecycle — UHBSE Integrated Research Runtime Foundation v0.1."""

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
from human_simulator.integrated_research_runtime_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    SEQ_DIR,
    TRAIN_VAL_PARQUET,
    VERSION,
)

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_integrated_research_runtime_v01_unit.py",
    "tests/test_integrated_research_runtime_v01_contracts.py",
)
LIVE_TESTS = ("tests/test_integrated_research_runtime_v01_live.py",)
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
            ".html",
            ".css",
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
    report = (art / "stage-report.md").read_text(encoding="utf-8")
    if "Report status: FINAL" not in report:
        raise PublicationError("stage-report.md is not FINAL")
    if st.get("TEST_ACCESS_LIFECYCLE_STATUS") != "OPENED":
        raise PublicationError("test not opened")
    if st.get("PRE_TEST_PHYSICAL_FREEZE_STATUS") not in {"FROZEN", "VERIFIED"}:
        raise PublicationError("freeze missing")
    if not (root / SEQ_DIR / TRAIN_VAL_PARQUET).is_file():
        raise PublicationError("missing private train/val sequences")
    required = {
        "BASELINE_VERIFICATION_STATUS": "PASS",
        "PRIOR_JOINT_FOUNDATION_STATUS": "NOT_ACCEPTED_EVIDENCE_AND_RUNTIME_CORRECTION_REQUIRED",
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
        "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
        "SAFETY_BOUNDARY_CLASSIFIER_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_PERFORMED",
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": "NOT_CONSUMED_NOT_ACCEPTED",
        "EXTERNAL_VALIDATION_STATUS": "NOT_RUN",
        "EXTERNAL_VALIDATION_PROTOCOL_STATUS": "READY_FOR_PROVIDER_SCOPING",
        "TEST_SET_NOVELTY_STATUS": "REUSED_HISTORICAL_HELDOUT_NOT_EXTERNAL_VALIDATION",
        "PATIENT_SPECIFIC_QSP_STATUS": "NOT_RUN_NO_ACCEPTED_INTERVENTION_MAPPING",
        "REAL_DRUG_PKPD_STATUS": "NOT_STARTED_PROVIDER_AND_DOMAIN_INPUT_REQUIRED",
    }
    for k, exp in required.items():
        if st.get(k) != exp:
            raise PublicationError(f"{k}={st.get(k)}")
    if st.get("ENGINE_JOINT_ROLLOUT_STATUS") in {None, "TECHNICAL_SHADOW_PASS"}:
        raise PublicationError("false joint runtime PASS")
    if st.get("ENGINE_CROSS_PROCESS_REPLAY_STATUS") == "PASS_SAME_PROCESS_DETERMINISTIC":
        raise PublicationError("same-process replay cannot be claimed as cross-process")
    if "raw-unit" in json.dumps(st).lower() and st.get("JOINT_DEPENDENCE_FOUNDATION_STATUS") == "PARTIAL_ACCEPTED_WITH_EXPLICIT_CELL_REGISTRY":
        raise PublicationError("raw-unit joint acceptance")
    priv = json.loads((art / "public-privacy-scan.json").read_text(encoding="utf-8"))
    if priv.get("PUBLIC_DATA_MINIMIZATION_STATUS") != "PASS_AGGREGATE_ONLY":
        raise PublicationError("privacy scan fail")

    env_live = os.environ.copy()
    live_proc = subprocess.run(
        ["uv", "run", "--frozen", "pytest", "-q", *UNIT_TESTS, *LIVE_TESTS],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env_live,
        check=False,
    )
    live_out = (live_proc.stdout or "") + (live_proc.stderr or "")
    if live_proc.returncode != 0:
        raise PublicationError(f"live tests FAIL: {live_out[-2500:]}")

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

    with tempfile.TemporaryDirectory(prefix="uhbse-irr-v01-") as tmp:
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
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cmd = (
            "uv sync --frozen --extra dev && "
            "uv run --frozen pytest "
            "tests/test_integrated_research_runtime_v01_unit.py "
            "tests/test_integrated_research_runtime_v01_contracts.py "
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
        if "skipped" in out and re.search(r"[1-9]\d* skipped", out):
            raise PublicationError(f"clean-extraction skipped tests: {out[-1500:]}")
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
            "live_repo_output_tail": live_out[-4000:],
            "literal_command": cmd,
            "output_tail": out[-6000:],
            "clean_extraction_excludes_live_parquet_tests": True,
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
            f"# REVIEW_INDEX — UHBSE Integrated Research Runtime Foundation v{VERSION}\n\n"
            "self_excluded=true\n\n"
            "SCIENTIFIC_CROSS_SOURCE_PASS=false\n"
            "NATURAL_HISTORY_ONLY=true\n"
            "PRODUCTION_READINESS=NOT_CLAIMED\n"
            "PRIOR_JOINT_FOUNDATION_STATUS=NOT_ACCEPTED_EVIDENCE_AND_RUNTIME_CORRECTION_REQUIRED\n"
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
        st["PUBLICATION_INTEGRITY_STATUS"] = "PASS"
        st["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "PASS"
        st["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PASS_AGGREGATE_ONLY"
        (art / "status-contract.json").write_text(
            json.dumps(st, indent=2) + "\n", encoding="utf-8"
        )
        stage = root / "docs" / "current-stage.md"
        if stage.is_file():
            text = stage.read_text(encoding="utf-8")
            stage.write_text(
                text.replace(
                    "SHA-256: see sidecar after publish-v0.1",
                    f"SHA-256: `{digest}`",
                ),
                encoding="utf-8",
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
