"""Atomic publication helpers for Stage 03 implementation planning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from human_simulator.stage03.implementation_constants import (
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
    IMPLEMENTATION_PLAN_REPORT_NAME,
    IMPLEMENTATION_PLAN_VERIFICATION_NAME,
)
from human_simulator.stage03.preconditions import sha256_file

REPORT_GENERATED_PREFIX = "Generated:"


@dataclass(frozen=True)
class PublicationSnapshot:
    report_sha256: str
    report_generated_at: str
    verified_at: str
    review_bundle_generated_at: str
    content_manifest_sha256: str
    overall_status: str
    checks_total: int
    checks_passed: int
    checks_failed: int


def parse_iso_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def timestamp_strictly_after(reference: datetime) -> datetime:
    bumped = reference + timedelta(microseconds=1)
    now = datetime.now(tz=UTC)
    return bumped if bumped > now else now


def read_report_generated_timestamp(report_path: Path) -> str | None:
    if not report_path.exists():
        return None
    for line in report_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(REPORT_GENERATED_PREFIX):
            return line.removeprefix(REPORT_GENERATED_PREFIX).strip()
    return None


def validate_publication_snapshot(impl_dir: Path) -> tuple[bool, str]:
    report_path = impl_dir / IMPLEMENTATION_PLAN_REPORT_NAME
    verification_path = impl_dir / IMPLEMENTATION_PLAN_VERIFICATION_NAME
    manifest_path = impl_dir / IMPLEMENTATION_PLAN_MANIFEST_NAME
    if not report_path.exists():
        return False, "missing report"
    if not verification_path.exists():
        return False, "missing verification"
    if not manifest_path.exists():
        return False, "missing manifest"

    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    report_sha = sha256_file(report_path)
    manifest_sha = sha256_file(manifest_path)
    report_generated_at = read_report_generated_timestamp(report_path)
    verified_at = verification.get("verified_at")
    bundle_generated_at = verification.get("review_bundle_generated_at")

    if verification.get("report_sha256") != report_sha:
        return False, f"report_sha mismatch verification={verification.get('report_sha256')!r} disk={report_sha!r}"
    if verification.get("content_manifest_sha256") != manifest_sha:
        return (
            False,
            f"manifest_sha mismatch verification={verification.get('content_manifest_sha256')!r} disk={manifest_sha!r}",
        )
    if manifest_sha not in report_path.read_text(encoding="utf-8"):
        return False, "report missing manifest sha256 reference"

    report_dt = parse_iso_timestamp(report_generated_at) if report_generated_at else None
    verified_dt = parse_iso_timestamp(verified_at) if verified_at else None
    bundle_dt = parse_iso_timestamp(bundle_generated_at) if bundle_generated_at else None
    if not (report_dt and verified_dt and bundle_dt and report_dt <= verified_dt <= bundle_dt):
        return False, f"chronology invalid report={report_generated_at}, verified={verified_at}, bundle={bundle_generated_at}"

    checks = verification.get("checks", [])
    if verification.get("checks_total") != len(checks):
        return False, "checks_total mismatch"
    passed = sum(1 for item in checks if item.get("status") == "PASS")
    failed = sum(1 for item in checks if item.get("status") == "FAIL")
    if verification.get("checks_passed") != passed or verification.get("checks_failed") != failed:
        return False, "check count arithmetic mismatch"
    if passed + failed != len(checks):
        return False, "checks do not sum"

    return True, "publication snapshot consistent"


def publication_snapshot_from_disk(impl_dir: Path) -> PublicationSnapshot:
    verification = json.loads((impl_dir / IMPLEMENTATION_PLAN_VERIFICATION_NAME).read_text(encoding="utf-8"))
    return PublicationSnapshot(
        report_sha256=sha256_file(impl_dir / IMPLEMENTATION_PLAN_REPORT_NAME),
        report_generated_at=read_report_generated_timestamp(impl_dir / IMPLEMENTATION_PLAN_REPORT_NAME) or "",
        verified_at=str(verification.get("verified_at", "")),
        review_bundle_generated_at=str(verification.get("review_bundle_generated_at", "")),
        content_manifest_sha256=sha256_file(impl_dir / IMPLEMENTATION_PLAN_MANIFEST_NAME),
        overall_status=str(verification.get("overall_status", "")),
        checks_total=int(verification.get("checks_total", 0)),
        checks_passed=int(verification.get("checks_passed", 0)),
        checks_failed=int(verification.get("checks_failed", 0)),
    )
