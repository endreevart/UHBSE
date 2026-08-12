"""Stage 03 design preconditions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from human_simulator.audit.report import REPORT_STATUS_FINAL, read_report_status
from human_simulator.stage02.verify_stage_02 import (
    FINAL_MANIFEST_NAME as STAGE02_FINAL_MANIFEST,
    _verify_final_manifest,
    extract_unresolved_mappings,
)

CheckStatus = Literal["PASS", "FAIL"]


@dataclass(frozen=True)
class PreconditionResult:
    name: str
    status: CheckStatus
    detail: str


def check_stage_03_preconditions(repo_root: Path) -> tuple[bool, list[PreconditionResult]]:
    root = repo_root.resolve()
    stage01_dir = root / "artifacts" / "stage-01"
    stage02_dir = root / "artifacts" / "stage-02"
    results: list[PreconditionResult] = []

    stage01_status = read_report_status(stage01_dir)
    results.append(
        PreconditionResult(
            "stage_01_final",
            "PASS" if stage01_status == REPORT_STATUS_FINAL else "FAIL",
            f"stage-01-report status={stage01_status!r}",
        )
    )

    stage02_report = stage02_dir / "stage-02-report.md"
    stage02_final = (
        stage02_report.exists()
        and f"**Report status:** {REPORT_STATUS_FINAL}" in stage02_report.read_text(encoding="utf-8")
    )
    results.append(
        PreconditionResult(
            "stage_02_final",
            "PASS" if stage02_final else "FAIL",
            "stage-02-report.md FINAL" if stage02_final else "stage-02-report not FINAL",
        )
    )

    verify_path = stage02_dir / "verify-stage-02.json"
    verify_data: dict[str, Any] | None = None
    if verify_path.exists():
        verify_data = json.loads(verify_path.read_text(encoding="utf-8"))
    verify_pass = bool(verify_data and verify_data.get("status") == "PASS")
    results.append(
        PreconditionResult(
            "verify_stage_02_pass",
            "PASS" if verify_pass else "FAIL",
            f"verify-stage-02 status={verify_data.get('status') if verify_data else 'missing'}",
        )
    )

    manifest_path = stage02_dir / STAGE02_FINAL_MANIFEST
    manifest_ok, manifest_detail = _verify_final_manifest(manifest_path, stage02_dir)
    results.append(
        PreconditionResult(
            "stage_02_final_manifest_valid",
            "PASS" if manifest_ok else "FAIL",
            manifest_detail,
        )
    )

    crosswalk_path = stage02_dir / "entity-crosswalk.yaml"
    crosswalk = yaml.safe_load(crosswalk_path.read_text(encoding="utf-8")) if crosswalk_path.exists() else None
    unresolved = extract_unresolved_mappings(crosswalk)
    results.append(
        PreconditionResult(
            "unresolved_mappings_available",
            "PASS" if len(unresolved) == 17 else "FAIL",
            f"unresolved_mappings={len(unresolved)}",
        )
    )

    identity_path = stage02_dir / "identity-linkage-assessment.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8")) if identity_path.exists() else None
    pop_status = (
        identity.get("overlap_aggregates", {}).get("population_overlap_estimate", {}).get("status")
        if identity
        else None
    )
    results.append(
        PreconditionResult(
            "population_overlap_not_estimable",
            "PASS" if pop_status == "NOT_ESTIMABLE" else "FAIL",
            f"population_overlap_estimate.status={pop_status!r}",
        )
    )

    subject_root_path = stage02_dir / "subject-root-analysis.json"
    subject_root = json.loads(subject_root_path.read_text(encoding="utf-8")) if subject_root_path.exists() else None
    subject_b = subject_root.get("source_b", {}).get("overall_verdict") if subject_root else None
    results.append(
        PreconditionResult(
            "subject_b_candidate",
            "PASS" if subject_b == "SUBJECT_ROOT_CANDIDATE" else "FAIL",
            f"subject_root_b={subject_b!r}",
        )
    )

    ok = all(item.status == "PASS" for item in results)
    return ok, results


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
