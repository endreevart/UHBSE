"""Reproduce the published v0.1 provenance defect from the immutable review ZIP."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v021.publish import reconcile_review_index
from human_simulator.intervention_response_readiness_v01.hashes import sha256_file
from human_simulator.intervention_response_readiness_v011.policy import (
    ARTIFACT_DIR,
    EVIDENCE_CATALOG,
    V01_ARTIFACT_DIR,
    V01_INDEXED,
    V01_MEMBERS,
    V01_SHA256,
    V01_ZIP,
)


def _zip_path(root: Path) -> Path:
    return root / "artifacts" / "external-review" / V01_ZIP


def reproduce_v01_defect(root: Path) -> dict[str, Any]:
    """Run the frozen v0.1 tree extracted from the published ZIP.

    The measurement is executed only when that ZIP is in the publisher workspace.
    """
    root = Path(root).resolve()
    zip_path = _zip_path(root)
    if not zip_path.is_file():
        return {
            "executed": False,
            "reason": "V01_ZIP_NOT_IN_TREE",
            "V01_CORE_NEGATIVE_READINESS_STATUS": "NOT_REEXECUTED",
            "V01_UPSTREAM_EVIDENCE_PROVENANCE_STATUS": "NOT_REEXECUTED",
            "V01_CLEAN_REPLAY_STATUS": "NOT_REEXECUTED",
            "V01_SELF_CONTAINMENT_CLAIM_STATUS": "NOT_REEXECUTED",
        }
    digest = sha256_file(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        crc = zf.testzip()
        names = [name for name in zf.namelist() if not name.endswith("/")]
        duplicate = len(names) != len(set(names))
        index = zf.read("REVIEW_INDEX.md").decode("utf-8")
        payloads = {name: zf.read(name) for name in names if name != "REVIEW_INDEX.md"}
        packed_gaps = json.loads(zf.read(f"{V01_ARTIFACT_DIR}/phase0-readiness-gaps.json"))
        packed_status = json.loads(zf.read(f"{V01_ARTIFACT_DIR}/status-contract.json"))
    review = reconcile_review_index(names, index, payloads)
    evidence_in_zip = [
        spec["canonical_source_path"]
        for spec in EVIDENCE_CATALOG
        if spec["canonical_source_path"] not in names
    ]
    with tempfile.TemporaryDirectory(prefix="uhbse-v01-defect-") as tmp:
        work = Path(tmp) / "extract"
        venv = Path(tmp) / "venv"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(work)
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env["UV_PROJECT_ENVIRONMENT"] = str(venv)
        env["UV_LINK_MODE"] = "copy"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        sync = _run(["uv", "sync", "--frozen", "--extra", "dev"], work, env)
        unit = _run(
            [
                "uv", "run", "--frozen", "pytest", "-q",
                "tests/test_intervention_response_readiness_v01_unit.py",
                "tests/test_intervention_response_readiness_v01_contracts.py",
            ],
            work,
            env,
        )
        live = _run(
            ["uv", "run", "--frozen", "pytest", "-q", "tests/test_intervention_response_readiness_v01_live.py"],
            work,
            env,
        )
        audit = _run(
            ["uv", "run", "--frozen", "audit", "--root", ".", "intervention-readiness", "run-v0.1", "--no-publish"],
            work,
            env,
        )
        art = work / V01_ARTIFACT_DIR
        replay_gaps = _read_json(art / "phase0-readiness-gaps.json")
        replay_status = _read_json(art / "status-contract.json")
        replay_nc = _read_json(art / "negative-control-results.json")
        shutil.rmtree(venv, ignore_errors=True)
    unit_passed = _passed_count(unit["tail"])
    missing_replay = replay_gaps.get("evidence_files_missing") or []
    nc_rejected = replay_nc.get("n_rejected")
    nc_cases = replay_nc.get("n_cases")
    packed_ready = packed_status.get("INTERVENTION_RESPONSE_READINESS_STATUS")
    replay_ready = replay_status.get("INTERVENTION_RESPONSE_READINESS_STATUS")
    technical = replay_status.get("TECHNICAL_AUDIT_STATUS")
    core = (
        "PASS"
        if packed_ready == "NOT_READY"
        and replay_ready == "NOT_READY"
        and packed_status.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") == 0
        and packed_status.get("DOMAIN_ACCEPTED_MAPPING_COUNT") == 0
        else "FAIL"
    )
    provenance = "NOT_SELF_CONTAINED" if len(evidence_in_zip) == 10 and len(missing_replay) == 10 else "FAIL"
    clean = (
        "FAIL"
        if audit["exit_code"] == 1
        and technical == "FAIL"
        and nc_cases == 11
        and nc_rejected != 11
        else "UNEXPECTED"
    )
    claim = (
        "CORRECTION_REQUIRED"
        if packed_gaps.get("computed_from_published_artifacts") is True
        and packed_gaps.get("evidence_files_missing") == []
        and packed_status.get("REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS") == "PACKED_CONTENTS_VERIFIED"
        and len(evidence_in_zip) == 10
        else "UNEXPECTED"
    )
    measurement_ok = all(
        (
            digest == V01_SHA256,
            crc is None,
            not duplicate,
            len(names) == V01_MEMBERS,
            review.get("ok") is True,
            review.get("indexed_members") == V01_INDEXED,
            sync["exit_code"] == 0,
            unit["exit_code"] == 0,
            unit_passed == 11,
            live["exit_code"] != 0,
            "test_prior_zips_unmutated" in live["tail"],
            core == "PASS",
            provenance == "NOT_SELF_CONTAINED",
            clean == "FAIL",
            claim == "CORRECTION_REQUIRED",
        )
    )
    return {
        "executed": True,
        "measurement_ok": measurement_ok,
        "zip_sha256": digest,
        "sha_ok": digest == V01_SHA256,
        "crc_ok": crc is None,
        "duplicate_members": duplicate,
        "members": len(names),
        "indexed_members": review.get("indexed_members"),
        "review_index_ok": review.get("ok") is True,
        "unit_contract_passed": unit_passed,
        "unit_exit_code": unit["exit_code"],
        "live_exit_code": live["exit_code"],
        "live_not_fully_reproduced_without_prior_zip_bytes": live["exit_code"] != 0,
        "audit_exit_code": audit["exit_code"],
        "TECHNICAL_AUDIT_STATUS": technical,
        "replay_INTERVENTION_RESPONSE_READINESS_STATUS": replay_ready,
        "evidence_files_missing_count": len(missing_replay),
        "negative_controls": f"{nc_rejected}/{nc_cases}",
        "negative_controls_are_11_of_11": nc_rejected == 11 and nc_cases == 11,
        "packed_INTERVENTION_RESPONSE_READINESS_STATUS": packed_ready,
        "packed_computed_from_published_artifacts": packed_gaps.get("computed_from_published_artifacts"),
        "packed_evidence_files_missing": packed_gaps.get("evidence_files_missing"),
        "packed_REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS": packed_status.get("REVIEW_BUNDLE_SELF_CONTAINMENT_STATUS"),
        "not_ready_conclusion_overturned": False,
        "V01_CORE_NEGATIVE_READINESS_STATUS": core,
        "V01_UPSTREAM_EVIDENCE_PROVENANCE_STATUS": provenance,
        "V01_CLEAN_REPLAY_STATUS": clean,
        "V01_SELF_CONTAINMENT_CLAIM_STATUS": claim,
        "sync_exit_code": sync["exit_code"],
    }


def load_recorded_defect(root: Path) -> dict[str, Any]:
    path = root / ARTIFACT_DIR / "v01-defect-reproduction.json"
    if not path.is_file():
        return {
            "executed": False,
            "reason": "RECORD_MISSING",
            "V01_CORE_NEGATIVE_READINESS_STATUS": "NOT_ESTABLISHED",
            "V01_UPSTREAM_EVIDENCE_PROVENANCE_STATUS": "NOT_ESTABLISHED",
            "V01_CLEAN_REPLAY_STATUS": "NOT_ESTABLISHED",
            "V01_SELF_CONTAINMENT_CLAIM_STATUS": "NOT_ESTABLISHED",
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _run(cmd: list[str], cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, check=False)
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-4000:]
    return {"exit_code": proc.returncode, "tail": tail}


def _passed_count(tail: str) -> int | None:
    import re

    match = re.search(r"(\d+) passed", tail)
    return int(match.group(1)) if match else None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
