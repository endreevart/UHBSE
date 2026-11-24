"""Publish exactly one immutable Stage 05 v0.1 review ZIP."""

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
from human_simulator.intervention_response_readiness_v01.policy import (
    ARTIFACT_DIR,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    VERSION,
)
from human_simulator.intervention_response_readiness_v01.reconciliation import reconcile_final_report

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
UNIT_TESTS = (
    "tests/test_intervention_response_readiness_v01_unit.py",
    "tests/test_intervention_response_readiness_v01_contracts.py",
)
LIVE_TESTS = ("tests/test_intervention_response_readiness_v01_live.py",)
_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")


class PublicationError(RuntimeError):
    pass


def _sha(path: Path | bytes) -> str:
    if isinstance(path, bytes):
        return hashlib.sha256(path).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add_tree(payloads: dict[str, bytes], root: Path, rel: str) -> None:
    folder = root / rel
    if not folder.exists():
        return
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        key = path.relative_to(root).as_posix()
        if _CACHE_RE.search(key) or "/_nc_tmp/" in f"/{key}":
            continue
        payloads[key] = path.read_bytes()


def publish(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    external = root / "artifacts" / "external-review"
    external.mkdir(parents=True, exist_ok=True)
    zip_path = external / ZIP_NAME
    sidecar = external / SHA_NAME
    att_path = external / ATT_NAME
    for path in (zip_path, sidecar, att_path):
        if path.exists():
            raise PublicationError(f"refuse overwrite: {path.name}")

    prior_before = {}
    for label, (name, expected) in PRIOR_ZIPS.items():
        path = external / name
        if not path.is_file() or _sha(path) != expected:
            raise PublicationError(f"baseline fail: {name}")
        prior_before[label] = _sha(path)

    art = root / ARTIFACT_DIR
    ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
    if not ver.get("ok"):
        raise PublicationError("verification.ok false — REFUSE")
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    report = (art / "stage-report.md").read_text(encoding="utf-8")
    if "Report status: FINAL" not in report:
        raise PublicationError("stage-report.md is not FINAL")
    required = {
        "SCIENTIFIC_CROSS_SOURCE_PASS": False,
        "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
        "PRODUCTION_READINESS": "NOT_CLAIMED",
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "TREATMENT_EFFECT_STATUS": "NOT_STARTED",
        "CAUSAL_EFFECT_STATUS": "NOT_STARTED",
        "CLINICAL_VALIDATION_STATUS": "NOT_STARTED",
        "DOMAIN_ACCEPTED_MAPPING_COUNT": 0,
        "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_PERFORMED",
        "HELD_OUT_REOPENED": False,
        "FROZEN_NHR_D0_LEP_MUTATED": False,
        "TECHNICAL_AUDIT_STATUS": "PASS",
    }
    for key, expected in required.items():
        if status.get(key) != expected:
            raise PublicationError(f"{key}={status.get(key)}")
    if status.get("INTERVENTION_RESPONSE_READINESS_STATUS") == "READY":
        raise PublicationError("READY is forbidden for this evidence state")
    priv = json.loads((art / "privacy-scan.json").read_text(encoding="utf-8"))
    if priv.get("PUBLIC_DATA_MINIMIZATION_STATUS") != "PASS_AGGREGATE_ONLY":
        raise PublicationError("privacy scan fail")

    status["ZIP_CONTENT_VERIFICATION_STATUS"] = "PACKED_CONTENTS_VERIFIED"
    status["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "PACKED_CONTENTS_VERIFIED"
    status["PUBLICATION_INTEGRITY_STATUS"] = "DETACHED_SIDECAR_AUTHORITATIVE"
    status["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PASS_AGGREGATE_ONLY"
    from human_simulator.intervention_response_readiness_v01.orchestrator import persist_stage_report

    persist_stage_report(art, status, report_status="FINAL")
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    if status.get("FINAL_REPORT_STATUS_RECONCILIATION_STATUS") != "PASS":
        raise PublicationError("FINAL_REPORT_STATUS_RECONCILIATION_STATUS is not PASS")
    if status.get("PUBLICATION_INTEGRITY_STATUS") != "DETACHED_SIDECAR_AUTHORITATIVE":
        raise PublicationError("inner publication status must remain DETACHED_SIDECAR_AUTHORITATIVE")

    live_proc = subprocess.run(
        ["uv", "run", "--frozen", "pytest", "-q", *UNIT_TESTS, *LIVE_TESTS],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
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
        "tests/test_intervention_response_readiness_v01_live.py",
        *UNIT_TESTS,
        "pyproject.toml",
        "uv.lock",
        ".cursor/rules/09-intervention-readiness.mdc",
    ):
        path = root / rel
        if path.is_file():
            payloads[rel] = path.read_bytes()

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
            "tests/test_intervention_response_readiness_v01_unit.py "
            "tests/test_intervention_response_readiness_v01_contracts.py "
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
        match = re.search(r"(\d+) passed", out)
        if match:
            passed = int(match.group(1))
        match = re.search(r"(\d+) skipped", out)
        if match:
            skipped = int(match.group(1))
        match = re.search(r"(\d+) failed", out)
        if match:
            failed = int(match.group(1))
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
            path.relative_to(staging).as_posix(): path.read_bytes()
            for path in sorted(staging.rglob("*"))
            if path.is_file()
            and not _CACHE_RE.search(path.relative_to(staging).as_posix())
            and path.relative_to(staging).as_posix() not in {"REVIEW_INDEX.md", "REVIEW_INDEX.json"}
        }
        if any(name.endswith(".parquet") for name in staging_files):
            raise PublicationError("parquet in staging")
        index_json = {
            "version": VERSION,
            "self_excluded_markdown": True,
            "PUBLICATION_INTEGRITY_STATUS": "DETACHED_SIDECAR_AUTHORITATIVE",
            "SCIENTIFIC_CROSS_SOURCE_PASS": False,
            "members": [
                {"path": path, "sha256": _sha(data)} for path, data in sorted(staging_files.items())
            ],
        }
        index_json_bytes = (json.dumps(index_json, indent=2, sort_keys=True) + "\n").encode("utf-8")
        (staging / "REVIEW_INDEX.json").write_bytes(index_json_bytes)
        staging_files["REVIEW_INDEX.json"] = index_json_bytes
        rows = [f"| `{path}` | `{_sha(data)}` |" for path, data in sorted(staging_files.items())]
        (staging / "REVIEW_INDEX.md").write_text(
            f"# REVIEW_INDEX — {ZIP_NAME}\n\n"
            "self_excluded=true\n\n"
            "SCIENTIFIC_CROSS_SOURCE_PASS=false\n"
            "INTERVENTION_RESPONSE_READINESS_STATUS=NOT_READY\n"
            "PRODUCTION_READINESS=NOT_CLAIMED\n"
            "PUBLICATION_INTEGRITY_STATUS=DETACHED_SIDECAR_AUTHORITATIVE\n"
            "| path | sha256 |\n|------|--------|\n"
            + "\n".join(rows)
            + "\n",
            encoding="utf-8",
        )
        strip_cache(staging)
        if not scan_cache(staging)["ok"]:
            raise PublicationError("cache residues")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(staging.rglob("*")):
                if path.is_file() and not _CACHE_RE.search(path.relative_to(staging).as_posix()):
                    zf.write(path, path.relative_to(staging).as_posix())

        extract = isolation / "extract"
        extract.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            crc_fail = zf.testzip()
            if crc_fail is not None:
                zip_path.unlink(missing_ok=True)
                raise PublicationError(f"ZIP CRC fail: {crc_fail}")
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if len(names) != len(set(names)):
                zip_path.unlink(missing_ok=True)
                raise PublicationError("duplicate members")
            unsafe = [
                n
                for n in names
                if n.startswith("/")
                or n.startswith("\\")
                or ".." in Path(n).parts
                or Path(n).is_absolute()
            ]
            if unsafe:
                zip_path.unlink(missing_ok=True)
                raise PublicationError(f"unsafe member path: {unsafe[0]}")
            zf.extractall(extract)
        if any(n.endswith(".parquet") for n in names):
            zip_path.unlink(missing_ok=True)
            raise PublicationError("parquet in zip")
        packed_status = json.loads((extract / ARTIFACT_DIR / "status-contract.json").read_text(encoding="utf-8"))
        packed_report = (extract / ARTIFACT_DIR / "stage-report.md").read_text(encoding="utf-8")
        packed_scan = json.loads((extract / ARTIFACT_DIR / "privacy-scan.json").read_text(encoding="utf-8"))
        packed_recon = reconcile_final_report(
            report_text=packed_report, status=packed_status, scan=packed_scan
        )
        if not packed_recon.get("ok"):
            zip_path.unlink(missing_ok=True)
            raise PublicationError(f"packed FINAL report reconciliation FAIL: {packed_recon}")
        if packed_status.get("PUBLICATION_INTEGRITY_STATUS") != "DETACHED_SIDECAR_AUTHORITATIVE":
            zip_path.unlink(missing_ok=True)
            raise PublicationError("ZIP inner publication status must remain DETACHED_SIDECAR_AUTHORITATIVE")
        if packed_status.get("INTERVENTION_RESPONSE_READINESS_STATUS") == "READY":
            zip_path.unlink(missing_ok=True)
            raise PublicationError("packed READY is forbidden")
        if not verify_manifest(extract / ARTIFACT_DIR)["ok"]:
            zip_path.unlink(missing_ok=True)
            raise PublicationError("POST_PACK_MANIFEST FAIL")
        recon = reconcile_review_index(
            names,
            (extract / "REVIEW_INDEX.md").read_text(encoding="utf-8"),
            payloads_on_disk={n: (extract / n).read_bytes() for n in names if n != "REVIEW_INDEX.md"},
        )
        if not recon.get("ok"):
            zip_path.unlink(missing_ok=True)
            raise PublicationError(f"REVIEW_INDEX FAIL: {recon}")

        digest = _sha(zip_path)
        sidecar.write_text(f"{digest}  {ZIP_NAME}\n", encoding="utf-8")
        prior_after = {label: _sha(external / name) for label, (name, _) in PRIOR_ZIPS.items()}
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
            "ZIP_INNER_PUBLICATION_INTEGRITY_STATUS": "DETACHED_SIDECAR_AUTHORITATIVE",
            "note": (
                "Detached sidecar and this attestation are authoritative for publication. "
                "The ZIP status-contract does not claim PUBLICATION_INTEGRITY_STATUS=PASS."
            ),
            "SCIENTIFIC_CROSS_SOURCE_PASS": False,
            "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
            "TECHNICAL_AUDIT_STATUS": packed_status.get("TECHNICAL_AUDIT_STATUS"),
            "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
            "prior_sha_before": prior_before,
            "prior_sha_after": prior_after,
            "clean_extraction": {"passed": passed, "skipped": skipped, "failed": failed},
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        att_path.write_text(json.dumps(att, indent=2) + "\n", encoding="utf-8")
        stage = root / "docs" / "current-stage.md"
        if stage.is_file():
            text = stage.read_text(encoding="utf-8")
            stage.write_text(
                text.replace(
                    "SHA-256: see sidecar after publish-v0.1",
                    f"SHA-256: `{digest}`",
                ).replace(
                    "**Phase:** RUN COMPLETE — security PAUSED",
                    "**Phase:** PUBLISHED — security PAUSED",
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
        "ZIP_INNER_PUBLICATION_INTEGRITY_STATUS": "DETACHED_SIDECAR_AUTHORITATIVE",
    }
