"""Read-only baseline verification for Stage 03 alignment candidate."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
    sha256_file,
    verify_relationship_manifest,
)
from human_simulator.stage03.changeset_01_baseline import verify_sha256_manifest
from human_simulator.stage03.changeset_01_constants import (
    DESIGN_CONTENT_MANIFEST_NAME,
    DESIGN_DIR,
    IMPLEMENTATION_DIR,
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
)
from human_simulator.stage03.frozen_evidence import FROZEN_MIGRATION_SHA256
from human_simulator.stage03.prior_stage_integrity import evaluate_prior_stage_integrity
from human_simulator.stage03_alignment.constants import (
    DESIGN_VERSION,
    EXTERNAL_REVIEW_DIR,
    FROZEN_DESIGN_VERSION,
    FROZEN_DESIGN_ZIP_RECOVERED,
    FROZEN_PLAN_VERSION,
    FROZEN_PLAN_ZIP_RECOVERED,
    MIGRATION_FILES,
    PLAN_VERSION,
    RELATIONSHIP_MANIFEST_SHA_ACCEPTED,
)
from human_simulator.stage03_alignment.recovery import (
    FROZEN_DESIGN_ZIP_INVALID,
    FROZEN_PLAN_ZIP_INVALID,
    INVALID_BASELINE_STATUS,
    audit_baseline_recovery,
)

from human_simulator.stage03_alignment.canonical_db_baseline import evaluate_canonical_db_baseline

MAINTENANCE_PROMOTION_REPORT = Path("artifacts/stage-02-maintenance-01/promotion-report.json")

DESIGN_VERSION_PATTERN = re.compile(rb'document_version:\s*"?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"?')
PLAN_VERSION_PATTERN = re.compile(rb'document_version:\s*"?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"?')


@dataclass(frozen=True)
class BaselineCheck:
    name: str
    passed: bool
    detail: str
    status: str = "EVALUATED"


def _zip_member_sha256(zip_path: Path, member_suffix: str) -> str | None:
    if not zip_path.is_file():
        return None
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if name.endswith(member_suffix):
                return hashlib.sha256(archive.read(name)).hexdigest()
    return None


def _zip_member_version(zip_path: Path, member_suffix: str, pattern: re.Pattern[bytes]) -> str | None:
    if not zip_path.is_file():
        return None
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if name.endswith(member_suffix):
                match = pattern.search(archive.read(name))
                return match.group(1).decode("utf-8") if match else None
    return None


def _verify_frozen_zip_manifest(zip_path: Path, manifest_suffix: str) -> tuple[bool, str]:
    if not zip_path.is_file():
        return False, f"missing {zip_path.name}"
    digest = _zip_member_sha256(zip_path, manifest_suffix)
    if digest is None:
        return False, f"{manifest_suffix} not found inside {zip_path.name}"
    with zipfile.ZipFile(zip_path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(manifest_suffix))
        lines = archive.read(member).decode("utf-8").splitlines()
    verified = 0
    for line in lines:
        if not line.strip():
            continue
        expected, name = line.split(maxsplit=1)
        file_digest = _zip_member_sha256(zip_path, name.strip())
        if file_digest != expected:
            return False, f"{name.strip()} hash mismatch inside {zip_path.name}"
        verified += 1
    return True, f"{zip_path.name} manifest verifies ({verified} entries)"


def _migration_immutability(repo_root: Path) -> BaselineCheck:
    current: dict[str, str] = {}
    for rel in MIGRATION_FILES:
        file_path = repo_root / rel
        current[rel] = sha256_file(file_path) if file_path.is_file() else "MISSING"
    ok = True
    details: list[str] = []
    for rel in MIGRATION_FILES:
        filename = Path(rel).name
        expected = FROZEN_MIGRATION_SHA256.get(filename)
        actual = current.get(rel, "MISSING")
        if expected is None or actual != expected:
            ok = False
            details.append(f"{filename}: drift")
    return BaselineCheck(
        "migrations_0001_0004_immutable",
        ok,
        "all four migration digests match accepted SHA" if ok else "; ".join(details),
    )


def _workspace_document_version(path: Path, pattern: re.Pattern[bytes]) -> str | None:
    if not path.is_file():
        return None
    match = pattern.search(path.read_bytes())
    return match.group(1).decode("utf-8") if match else None


def evaluate_baseline(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    checks: list[BaselineCheck] = []

    recovery_audit = audit_baseline_recovery(root)
    checks.append(
        BaselineCheck(
            "recovery_source_members_verified",
            recovery_audit["recovery_source_complete"],
            f"source={recovery_audit['recovery_source_archive']}",
        )
    )
    checks.append(
        BaselineCheck(
            "recovered_design_bundle_present",
            (root / FROZEN_DESIGN_ZIP_RECOVERED).is_file(),
            FROZEN_DESIGN_ZIP_RECOVERED.as_posix(),
        )
    )
    checks.append(
        BaselineCheck(
            "recovered_plan_bundle_present",
            (root / FROZEN_PLAN_ZIP_RECOVERED).is_file(),
            FROZEN_PLAN_ZIP_RECOVERED.as_posix(),
        )
    )

    for label, invalid in (
        ("invalid_design_archive_marked", recovery_audit["invalid_archives"]["design"]),
        ("invalid_plan_archive_marked", recovery_audit["invalid_archives"]["plan"]),
    ):
        checks.append(
            BaselineCheck(
                label,
                invalid.get("status") == INVALID_BASELINE_STATUS,
                f"{invalid.get('path')}: version={invalid.get('declared_version_inside')}",
            )
        )

    prior_ok, records = evaluate_prior_stage_integrity(root)
    checks.append(
        BaselineCheck(
            "stage_01_02_accepted_hashes",
            prior_ok,
            f"{sum(1 for item in records if item.unchanged)}/{len(records)} controlled files unchanged",
        )
    )

    maintenance_ok = False
    maintenance_detail = "promotion-report.json missing"
    if (root / MAINTENANCE_PROMOTION_REPORT).is_file():
        payload = json.loads((root / MAINTENANCE_PROMOTION_REPORT).read_text(encoding="utf-8"))
        maintenance_ok = payload.get("report_status") == "FINAL"
        maintenance_detail = f"report_status={payload.get('report_status')!r}"
    checks.append(BaselineCheck("stage_02_maintenance_01_final", maintenance_ok, maintenance_detail))

    rel_ok, rel_detail = verify_relationship_manifest(root / "artifacts/stage-02")
    manifest_path = root / "artifacts/stage-02" / MANIFEST_NAME
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.is_file() else None
    rel_manifest_ok = rel_ok and manifest_sha == RELATIONSHIP_MANIFEST_SHA_ACCEPTED
    checks.append(
        BaselineCheck(
            "relationship_manifest_8_of_8",
            rel_manifest_ok,
            f"{rel_detail}; manifest_sha={manifest_sha}",
        )
    )

    recovered_design = root / FROZEN_DESIGN_ZIP_RECOVERED
    frozen_design_ok, frozen_design_detail = _verify_frozen_zip_manifest(
        recovered_design, "stage-03/design-content-manifest.sha256"
    )
    design_version = _zip_member_version(
        recovered_design, "canonical-id-contract.yaml", DESIGN_VERSION_PATTERN
    )
    design_version_ok = design_version == FROZEN_DESIGN_VERSION
    checks.append(
        BaselineCheck(
            "design_v074_frozen_manifest",
            frozen_design_ok and design_version_ok,
            f"{frozen_design_detail}; document_version={design_version}",
        )
    )

    recovered_plan = root / FROZEN_PLAN_ZIP_RECOVERED
    frozen_plan_ok, frozen_plan_detail = _verify_frozen_zip_manifest(
        recovered_plan, "stage-03-implementation/implementation-plan-manifest.sha256"
    )
    plan_version = _zip_member_version(
        recovered_plan, "implementation-plan.yaml", PLAN_VERSION_PATTERN
    )
    plan_version_ok = plan_version == FROZEN_PLAN_VERSION
    checks.append(
        BaselineCheck(
            "plan_v035_frozen_manifest",
            frozen_plan_ok and plan_version_ok,
            f"{frozen_plan_detail}; document_version={plan_version}",
        )
    )

    candidate_design_version = _workspace_document_version(
        root / DESIGN_DIR / "canonical-id-contract.yaml", DESIGN_VERSION_PATTERN
    )
    checks.append(
        BaselineCheck(
            "candidate_design_version",
            candidate_design_version == DESIGN_VERSION,
            f"document_version={candidate_design_version}",
        )
    )
    candidate_plan_version = _workspace_document_version(
        root / IMPLEMENTATION_DIR / "implementation-plan.yaml", PLAN_VERSION_PATTERN
    )
    checks.append(
        BaselineCheck(
            "candidate_plan_version",
            candidate_plan_version == PLAN_VERSION,
            f"document_version={candidate_plan_version}",
        )
    )

    baseline_manifest = root / IMPLEMENTATION_DIR / "design-baseline-manifest.sha256"
    frozen_baseline_digest = _zip_member_sha256(
        recovered_plan, "design-baseline-manifest.sha256"
    )
    baseline_ok = (
        baseline_manifest.is_file()
        and frozen_baseline_digest is not None
        and hashlib.sha256(baseline_manifest.read_bytes()).hexdigest() == frozen_baseline_digest
    )
    checks.append(
        BaselineCheck(
            "design_baseline_manifest_matches_frozen_v074",
            baseline_ok,
            "design-baseline-manifest.sha256 matches recovered v0.7.4 baseline"
            if baseline_ok
            else "design-baseline-manifest drift from recovered v0.7.4",
        )
    )

    candidate_manifest = root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME
    candidate_differs = (
        candidate_manifest.is_file()
        and baseline_manifest.is_file()
        and candidate_manifest.read_text(encoding="utf-8") != baseline_manifest.read_text(encoding="utf-8")
    )
    checks.append(
        BaselineCheck(
            "candidate_design_differs_from_frozen_baseline",
            candidate_differs,
            "candidate design manifest differs from frozen v0.7.4 baseline"
            if candidate_differs
            else "candidate design manifest must differ from frozen baseline",
        )
    )

    checks.append(_migration_immutability(root))
    canonical_db = evaluate_canonical_db_baseline()
    checks.append(
        BaselineCheck(
            "canonical_db_row_counts_zero",
            canonical_db.check_passed,
            canonical_db.check_detail,
            status=canonical_db.check_status,
        )
    )

    design_manifest = verify_sha256_manifest(root / DESIGN_DIR / DESIGN_CONTENT_MANIFEST_NAME)
    plan_manifest = verify_sha256_manifest(root / IMPLEMENTATION_DIR / IMPLEMENTATION_PLAN_MANIFEST_NAME)

    evaluated_checks = [check for check in checks if check.status == "EVALUATED"]
    not_evaluated = [check.name for check in checks if check.status == "NOT_EVALUATED"]
    status = "PASS" if all(check.passed for check in evaluated_checks) and not not_evaluated else "FAIL"

    return {
        "evaluated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "status": status,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "detail": c.detail,
                "status": c.status,
            }
            for c in checks
        ],
        "not_evaluated_checks": not_evaluated,
        "relationship_artifact_count": len(RELATIONSHIP_MANIFEST_ARTIFACTS),
        "frozen_design_zip_recovered": FROZEN_DESIGN_ZIP_RECOVERED.as_posix(),
        "frozen_plan_zip_recovered": FROZEN_PLAN_ZIP_RECOVERED.as_posix(),
        "invalid_design_zip": FROZEN_DESIGN_ZIP_INVALID.as_posix(),
        "invalid_plan_zip": FROZEN_PLAN_ZIP_INVALID.as_posix(),
        "candidate_design_manifest_verified": design_manifest.verified,
        "candidate_plan_manifest_verified": plan_manifest.verified,
        "canonical_db": canonical_db.document,
        "raw_db_connections": 0,
        "clinical_source_rows_read": 0,
        "database_connections_for_clinical_rows": 0,
        "clinical_rows_read": 0,
        "etl_executed": False,
        "live_load_executed": False,
        "changeset_02_started": False,
    }
