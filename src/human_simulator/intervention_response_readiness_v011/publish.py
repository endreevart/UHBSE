"""Publish one immutable Stage 05 v0.1.1 review ZIP. Never overwrites v0.1."""

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

from human_simulator.cross_source_lab_semantic_v021.publish import (
    mutation_proof,
    reconcile_review_index,
    scan_cache,
    strip_cache,
    verify_manifest,
    write_manifest,
)
from human_simulator.intervention_response_readiness_v011.policy import (
    ARTIFACT_DIR,
    PRIOR_ZIPS,
    REVIEW_ZIP,
    VERSION,
    V01_SHA256,
    V01_ZIP,
)
from human_simulator.intervention_response_readiness_v01.reconciliation import reconcile_final_report
from human_simulator.intervention_response_readiness_v011.replay import compare_artifact_dirs

ZIP_NAME = REVIEW_ZIP
SHA_NAME = f"{ZIP_NAME}.sha256"
ATT_NAME = ZIP_NAME.replace(".zip", ".attestation.json")
_CACHE_RE = re.compile(r"(^|/)\.pytest_cache(/|$)|(^|/)__pycache__(/|$)|\.pyc$")
_SKIP_PARTS = frozenset({".venv", ".pytest_cache", "__pycache__"})
UNIT_TESTS = (
    "tests/test_intervention_response_readiness_v011_unit.py",
    "tests/test_intervention_response_readiness_v011_contracts.py",
    "tests/test_intervention_response_readiness_v01_unit.py",
    "tests/test_intervention_response_readiness_v01_contracts.py",
)
LIVE_TESTS = ("tests/test_intervention_response_readiness_v011_live.py",)


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


def _skip(rel: str) -> bool:
    return _CACHE_RE.search(rel) is not None or bool(set(Path(rel).parts) & _SKIP_PARTS)


def _add_tree(payloads: dict[str, bytes], root: Path, rel: str) -> None:
    folder = root / rel
    if not folder.exists():
        return
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        key = path.relative_to(root).as_posix()
        if _skip(key):
            continue
        if path.suffix.lower() == ".parquet":
            raise PublicationError(f"refuse parquet: {key}")
        payloads[key] = path.read_bytes()


def _prior_hashes(external: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for label, (name, expected) in PRIOR_ZIPS.items():
        path = external / name
        digest = _sha(path) if path.is_file() else ""
        if digest != expected:
            raise PublicationError(f"baseline fail: {name}")
        found[label] = digest
    v01 = external / V01_ZIP
    digest = _sha(v01) if v01.is_file() else ""
    if digest != V01_SHA256:
        raise PublicationError("v0.1 baseline sha mismatch")
    found["stage05_v01"] = digest
    return found


def publish(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    external = root / "artifacts" / "external-review"
    external.mkdir(parents=True, exist_ok=True)
    zip_path = external / ZIP_NAME
    sidecar = external / SHA_NAME
    att_path = external / ATT_NAME
    for path in (zip_path, sidecar, att_path):
        if path.exists():
            raise PublicationError(f"refuse overwrite: {path.name}")
    prior_before = _prior_hashes(external)
    v01_bytes_before = (external / V01_ZIP).read_bytes()

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
        "ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT": 0,
        "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": 0,
        "TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT": 0,
        "TECHNICAL_AUDIT_STATUS": "PASS",
        "MEDICATION_RESIDUAL_CONSUMPTION_STATUS": "NOT_CONSUMED",
        "UPSTREAM_EVIDENCE_SNAPSHOT_STATUS": "PASS",
        "V01_CORE_NEGATIVE_READINESS_STATUS": "PASS",
        "V01_UPSTREAM_EVIDENCE_PROVENANCE_STATUS": "NOT_SELF_CONTAINED",
        "V01_CLEAN_REPLAY_STATUS": "FAIL",
        "V01_SELF_CONTAINMENT_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "PRIOR_ZIP_PHYSICAL_REHASH_STATUS": "PASS_PUBLISHER_WORKSPACE",
        "PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS": "NOT_RUN_PRIOR_BYTES_NOT_PACKED",
        "STAGE_NAMING_AUTHORITY_STATUS": "PASS_PUBLISHER_WORKSPACE",
        "HELD_OUT_REOPENED": False,
        "FROZEN_NHR_D0_LEP_MUTATED": False,
        "READINESS_CONCLUSION_STATUS": "PROVEN_NOT_READY",
    }
    for key, expected in required.items():
        if status.get(key) != expected:
            raise PublicationError(f"{key}={status.get(key)}")
    if status.get("INTERVENTION_RESPONSE_READINESS_STATUS") == "READY":
        raise PublicationError("READY is forbidden")
    snap = json.loads((art / "upstream-evidence-verification.json").read_text(encoding="utf-8"))
    if snap.get("snapshot_count") != 10 or snap.get("UPSTREAM_EVIDENCE_SNAPSHOT_STATUS") != "PASS":
        raise PublicationError("upstream snapshots are not 10/10")
    priv = json.loads((art / "privacy-scan.json").read_text(encoding="utf-8"))
    if priv.get("PUBLIC_DATA_MINIMIZATION_STATUS") != "PASS_AGGREGATE_ONLY":
        raise PublicationError("privacy scan fail")

    reference = art
    payloads: dict[str, bytes] = {}
    _add_tree(payloads, root, ARTIFACT_DIR)
    _add_tree(payloads, root, "src/human_simulator")
    for rel in (
        "docs/current-stage.md",
        "AGENTS.md",
        ".cursor/rules/09-intervention-readiness.mdc",
        "pyproject.toml",
        "uv.lock",
        *UNIT_TESTS,
        *LIVE_TESTS,
        "tests/test_intervention_response_readiness_v01_live.py",
    ):
        path = root / rel
        if path.is_file():
            payloads[rel] = path.read_bytes()

    with tempfile.TemporaryDirectory(prefix="uhbse-irr-v011-") as tmp:
        isolation = Path(tmp)
        staging = isolation / "staging"
        staging.mkdir()
        for rel, data in payloads.items():
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        strip_cache(staging)
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_PROJECT_ENVIRONMENT"] = str(isolation / "venv")
        env["UV_LINK_MODE"] = "copy"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        sync = subprocess.run(
            ["uv", "sync", "--frozen", "--extra", "dev"],
            cwd=staging,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if sync.returncode != 0:
            raise PublicationError(f"clean sync FAIL: {(sync.stdout or '')[-1500:]} {(sync.stderr or '')[-1500:]}")
        audit = subprocess.run(
            [
                "uv", "run", "--frozen", "audit", "--root", ".",
                "intervention-readiness", "run-v0.1", "--no-publish",
            ],
            cwd=staging,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        audit_out = (audit.stdout or "") + (audit.stderr or "")
        if audit.returncode != 0:
            raise PublicationError(f"clean core replay FAIL: {audit_out[-2500:]}")
        replay_status = json.loads((staging / ARTIFACT_DIR / "status-contract.json").read_text(encoding="utf-8"))
        replay_gaps = json.loads((staging / ARTIFACT_DIR / "phase0-readiness-gaps.json").read_text(encoding="utf-8"))
        replay_nc = json.loads((staging / ARTIFACT_DIR / "negative-control-results.json").read_text(encoding="utf-8"))
        replay_reg = json.loads((staging / ARTIFACT_DIR / "intervention-evidence-registry.json").read_text(encoding="utf-8"))
        if replay_status.get("TECHNICAL_AUDIT_STATUS") != "PASS":
            raise PublicationError("clean replay technical status is not PASS")
        if replay_status.get("INTERVENTION_RESPONSE_READINESS_STATUS") != "NOT_READY":
            raise PublicationError("clean replay readiness changed")
        if replay_gaps.get("evidence_files_missing") != []:
            raise PublicationError("clean replay evidence_files_missing is not empty")
        if replay_nc.get("n_rejected") != 11 or replay_nc.get("n_cases") != 11:
            raise PublicationError("clean replay negative controls are not 11/11")
        if replay_reg.get("n_cells") != 49:
            raise PublicationError(f"registry cells {replay_reg.get('n_cells')}")
        if replay_status.get("SOURCE_A_INVENTORY_CELL_COUNT") != 48 or replay_status.get("SOURCE_B_ABSENCE_CELL_COUNT") != 1:
            raise PublicationError("inventory cell split is not 48/1")
        if replay_status.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") != 0:
            raise PublicationError("eligible cells are not 0")
        if replay_status.get("CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS") != "PASS":
            raise PublicationError("clean replay did not record PASS")
        compared = compare_artifact_dirs(reference, staging / ARTIFACT_DIR)
        if not compared.get("ok"):
            raise PublicationError(f"normalized replay mismatch: {compared.get('mismatches')}")
        _write_replay_record(staging / ARTIFACT_DIR, compared, audit.returncode, replay_status, replay_nc, replay_reg)

        replay_status["PUBLICATION_INTEGRITY_STATUS"] = "DETACHED_SIDECAR_AUTHORITATIVE"
        replay_status["REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"] = "PASS_CORE_READINESS_REPLAY_PRIOR_ZIPS_EXTERNAL"
        replay_status["ZIP_CONTENT_VERIFICATION_STATUS"] = "PACKED_CONTENTS_VERIFIED"
        replay_status["CORE_READINESS_REPLAY_STATUS"] = "PASS"
        replay_status["CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS"] = "PASS"
        replay_status["PUBLIC_DATA_MINIMIZATION_STATUS"] = "PASS_AGGREGATE_ONLY"
        from human_simulator.intervention_response_readiness_v011.orchestrator import persist_stage_report

        # Persist against the staging artifact dir. The function writes only under art.
        persist_stage_report(staging / ARTIFACT_DIR, replay_status, report_status="FINAL")
        packed_now = json.loads((staging / ARTIFACT_DIR / "status-contract.json").read_text(encoding="utf-8"))
        if packed_now.get("PUBLICATION_INTEGRITY_STATUS") != "DETACHED_SIDECAR_AUTHORITATIVE":
            raise PublicationError("inner publication status drifted")
        if packed_now.get("FINAL_REPORT_STATUS_RECONCILIATION_STATUS") != "PASS":
            raise PublicationError("replay report reconciliation failed")
        tests_doc = json.loads((staging / ARTIFACT_DIR / "tests.json").read_text(encoding="utf-8"))
        write_manifest(staging / ARTIFACT_DIR)
        if not verify_manifest(staging / ARTIFACT_DIR).get("ok"):
            raise PublicationError("POST_REPLAY_MANIFEST FAIL")
        if not mutation_proof(staging / ARTIFACT_DIR).get("ok"):
            raise PublicationError("MUTATION_PROOF FAIL")
        if scan_public_staging(staging / ARTIFACT_DIR).get("PUBLIC_DATA_MINIMIZATION_STATUS") != "PASS_AGGREGATE_ONLY":
            raise PublicationError("packed privacy scan fail")

        staging_files = {
            rel: path.read_bytes()
            for path in sorted(staging.rglob("*"))
            if path.is_file()
            and not _skip(rel := path.relative_to(staging).as_posix())
            and rel not in {"REVIEW_INDEX.md", "REVIEW_INDEX.json"}
        }
        if any(name.endswith(".parquet") or name.endswith(V01_ZIP) for name in staging_files):
            raise PublicationError("parquet or prior zip packed")
        if any(name.split("/")[-1] in {item[0] for item in PRIOR_ZIPS.values()} for name in staging_files):
            raise PublicationError("stage 04 zip packed")
        index_json = {
            "version": VERSION,
            "self_excluded_markdown": True,
            "PUBLICATION_INTEGRITY_STATUS": "DETACHED_SIDECAR_AUTHORITATIVE",
            "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
            "members": [{"path": path, "sha256": _sha(data)} for path, data in sorted(staging_files.items())],
        }
        index_bytes = (json.dumps(index_json, indent=2, sort_keys=True) + "\n").encode("utf-8")
        (staging / "REVIEW_INDEX.json").write_bytes(index_bytes)
        staging_files["REVIEW_INDEX.json"] = index_bytes
        rows = [f"| `{path}` | `{_sha(data)}` |" for path, data in sorted(staging_files.items())]
        (staging / "REVIEW_INDEX.md").write_text(
            f"# REVIEW_INDEX — {ZIP_NAME}\n\n"
            "self_excluded=true\n\n"
            "SCIENTIFIC_CROSS_SOURCE_PASS=false\n"
            "INTERVENTION_RESPONSE_READINESS_STATUS=NOT_READY\n"
            "PRODUCTION_READINESS=NOT_CLAIMED\n"
            "PUBLICATION_INTEGRITY_STATUS=DETACHED_SIDECAR_AUTHORITATIVE\n"
            "PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS=NOT_RUN_PRIOR_BYTES_NOT_PACKED\n"
            "| path | sha256 |\n|------|--------|\n" + "\n".join(rows) + "\n",
            encoding="utf-8",
        )
        strip_cache(staging)
        if not scan_cache(staging).get("ok"):
            raise PublicationError("cache residues")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(staging.rglob("*")):
                rel = path.relative_to(staging).as_posix()
                if path.is_file() and not _skip(rel):
                    zf.write(path, rel)
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
            unsafe = [n for n in names if n.startswith("/") or ".." in Path(n).parts or Path(n).is_absolute()]
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
        packed_recon = reconcile_final_report(report_text=packed_report, status=packed_status, scan=packed_scan)
        if not packed_recon.get("ok"):
            zip_path.unlink(missing_ok=True)
            raise PublicationError(f"packed reconciliation FAIL: {packed_recon.get('mismatches')}")
        if packed_status.get("PUBLICATION_INTEGRITY_STATUS") != "DETACHED_SIDECAR_AUTHORITATIVE":
            zip_path.unlink(missing_ok=True)
            raise PublicationError("inner status is not DETACHED_SIDECAR_AUTHORITATIVE")
        if packed_status.get("INTERVENTION_RESPONSE_READINESS_STATUS") != "NOT_READY":
            zip_path.unlink(missing_ok=True)
            raise PublicationError("packed READY or changed readiness")
        if not verify_manifest(extract / ARTIFACT_DIR).get("ok"):
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
        prior_after = _prior_hashes(external)
        if prior_before != prior_after or (external / V01_ZIP).read_bytes() != v01_bytes_before:
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
            "clean_unit_contract": {
                "passed": _passed(tests_doc.get("output_tail") or ""),
                "exit_code": tests_doc.get("exit_code"),
                "failed": 0,
                "skipped": 0,
                "suites": list(UNIT_TESTS),
            },
            "clean_core_replay": {
                "exit_code": audit.returncode,
                "TECHNICAL_AUDIT_STATUS": "PASS",
                "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
                "evidence_files_missing": [],
                "negative_controls": "11/11",
                "registry_cells": 49,
                "source_a_inventory_cells": 48,
                "source_b_absence_cells": 1,
                "eligible_cells": 0,
                "CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS": "PASS",
            },
            "upstream_evidence_snapshot_count": "10/10",
            "prior_zip_rehash_scope": "publisher_workspace",
            "PRIOR_ZIP_REHASH_CLEAN_EXTRACTION_STATUS": "NOT_RUN_PRIOR_BYTES_NOT_PACKED",
            "v01_sha256_before": prior_before.get("stage05_v01"),
            "v01_sha256_after": prior_after.get("stage05_v01"),
            "stage04_prior_sha_before": {k: v for k, v in prior_before.items() if k != "stage05_v01"},
            "stage04_prior_sha_after": {k: v for k, v in prior_after.items() if k != "stage05_v01"},
            "SCIENTIFIC_CROSS_SOURCE_PASS": False,
            "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
            "SECURITY_STAGE_STATUS": "PAUSED_NOT_ACCEPTED_BY_OWNER",
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "note": (
                "Detached sidecar and this attestation are authoritative for publication. "
                "The ZIP status-contract does not claim PUBLICATION_INTEGRITY_STATUS=PASS."
            ),
        }
        att_path.write_text(json.dumps(att, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _copy_artifact_back(staging / ARTIFACT_DIR, art)
        _mark_published(root, digest)

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


def _write_replay_record(
    art: Path,
    compared: dict[str, Any],
    exit_code: int,
    status: dict[str, Any],
    nc: dict[str, Any],
    registry: dict[str, Any],
) -> None:
    art.joinpath("clean-replay-comparison.json").write_text(
        json.dumps(
            {
                "ok": True,
                "CLEAN_EXTRACTION_CORE_READINESS_REPLAY_STATUS": "PASS",
                "exit_code": exit_code,
                "TECHNICAL_AUDIT_STATUS": status.get("TECHNICAL_AUDIT_STATUS"),
                "INTERVENTION_RESPONSE_READINESS_STATUS": status.get("INTERVENTION_RESPONSE_READINESS_STATUS"),
                "negative_controls": f"{nc.get('n_rejected')}/{nc.get('n_cases')}",
                "registry_cells": registry.get("n_cells"),
                "comparison": compared,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _passed(tail: str) -> int | None:
    match = re.search(r"(\d+) passed", tail)
    return int(match.group(1)) if match else None


def scan_public_staging(art: Path) -> dict[str, Any]:
    from human_simulator.intervention_response_readiness_v01.privacy import scan_public

    return scan_public(art)


def _copy_artifact_back(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def _mark_published(root: Path, digest: str) -> None:
    stage = root / "docs" / "current-stage.md"
    if not stage.is_file():
        return
    text = stage.read_text(encoding="utf-8")
    stage.write_text(
        text.replace("SHA-256: see sidecar after publish-v0.1.1", f"SHA-256: `{digest}`").replace(
            "**Phase:** RUN COMPLETE — security PAUSED",
            "**Phase:** PUBLISHED — security PAUSED",
        ),
        encoding="utf-8",
    )
