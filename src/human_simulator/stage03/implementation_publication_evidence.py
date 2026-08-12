"""Publication evidence for Stage 03 implementation planning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from human_simulator.stage03.implementation_constants import (
    IMPLEMENTATION_PLAN_MANIFEST_NAME,
    IMPLEMENTATION_PLAN_REPORT_NAME,
    IMPLEMENTATION_PLAN_VERIFICATION_NAME,
    STAGE03_DESIGN_VERSION,
    STAGE03_IMPLEMENTATION_PLAN_VERSION,
)
from human_simulator.stage03.preconditions import sha256_file


@dataclass(frozen=True)
class ReviewBundleEvidence:
    zip_path: Path
    zip_sha256: str
    member_count: int
    indexed_member_count: int
    generated_at: str


@dataclass(frozen=True)
class PytestEvidence:
    command: str
    exit_code: int
    collected: int
    selected: int
    deselected: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float | None
    summary: str


def timestamp_strictly_after(reference: datetime) -> datetime:
    bumped = reference + timedelta(microseconds=1)
    now = datetime.now(tz=UTC)
    return bumped if bumped > now else now


def generate_report_content(
    *,
    timestamp: str,
    manifest_hash: str,
    pytest_evidence: PytestEvidence,
    bundle_evidence: ReviewBundleEvidence | None = None,
) -> str:
    bundle_section = ""
    if bundle_evidence is not None:
        bundle_section = f"""
## Published review bundle

| Field | Value |
|-------|-------|
| Path | `{bundle_evidence.zip_path.name}` |
| SHA-256 | `{bundle_evidence.zip_sha256}` |
| Members | {bundle_evidence.member_count} |
| Indexed members | {bundle_evidence.indexed_member_count} |
| Generated | {bundle_evidence.generated_at} |
"""
    return f"""# Stage 03 Implementation Plan Report

Generated: {timestamp}

**Report status:** DRAFT

## Phase

**Stage 03 — Implementation Planning v{STAGE03_IMPLEMENTATION_PLAN_VERSION}**

## Design baseline

Stage 03 Design **v{STAGE03_DESIGN_VERSION}** (SourceRecord construction patch). Baseline frozen in `design-baseline-manifest.sha256`.

## v0.3.5 corrections

- prior-stage integrity evaluation is strictly read-only; no verifier, gate or test repairs Stage 01/02
- restoring the accepted baseline moved to the explicit `audit restore-prior-stage-baseline --confirm` command
- `artifacts/stage-02/schema-profile-kgz.json` added to byte-controlled Stage 03 dependencies
- false Git provenance replaced by a content-addressed `baseline_source` descriptor with verified member hashes
- live source-relationship test marked `integration`, skips with explicit missing-prerequisite names, and runs in an isolated workspace copy
- release evidence split into `release-verification.json` with per-suite literal commands and counts
- `REPRODUCE.md` carries literal, complete commands and points to the correct evidence file
- published ZIP is validated once, then its SHA-256 is written to a `.sha256` sidecar with no rebuild

## Gate pytest (implementation planning verifier)

| Field | Value |
|-------|-------|
| Command | `{pytest_evidence.command}` |
| Exit code | {pytest_evidence.exit_code} |
| Collected | {pytest_evidence.collected} |
| Selected | {pytest_evidence.selected} |
| Deselected | {pytest_evidence.deselected} |
| Passed | {pytest_evidence.passed} |
| Failed | {pytest_evidence.failed} |
| Skipped | {pytest_evidence.skipped} |
| Duration (s) | {pytest_evidence.duration_seconds if pytest_evidence.duration_seconds is not None else "n/a"} |
| Summary | {pytest_evidence.summary} |

## Verification suites

Per-suite literal commands, counts, exit codes and durations are recorded in
`release-verification.json`. `overall_release_status` is `PASS` only when every mandatory suite
reports exit code 0 with zero failures.

- **Clean review bundle suite:** self-contained tests shipped inside the review bundle (`REPRODUCE.md`).
- **Full repository suite:** publisher-workspace-only; not reproducible from the bundle alone, so its
  evidence lives in `release-verification.json` rather than in this verification JSON.
- **Integration suite:** requires live PostgreSQL sources; skips with explicit missing-prerequisite
  names and never emits DSNs, passwords or environment values.
{bundle_section}
## Explicit non-actions

- No canonical database created
- No SQL DDL
- No ETL executed
- No clinical rows read in planning phase

**implementation-plan-manifest.sha256:** `{manifest_hash}`

**Planning checkpoint v{STAGE03_IMPLEMENTATION_PLAN_VERSION} reached.**
"""


def build_verification_payload(
    *,
    overall_status: str,
    checks: list[Any],
    pytest_evidence: PytestEvidence,
    content_manifest_sha256: str,
    report_sha256: str,
    report_generated_at: str,
    verified_at: str,
    review_bundle_generated_at: str,
    bundle_evidence: ReviewBundleEvidence | None = None,
) -> dict[str, Any]:
    failures = [check for check in checks if getattr(check, "status", None) == "FAIL"]
    passed = sum(1 for check in checks if getattr(check, "status", None) == "PASS")
    payload: dict[str, Any] = {
        "overall_status": overall_status,
        "checks_total": len(checks),
        "checks_passed": passed,
        "checks_failed": len(failures),
        "checks": [asdict(check) if hasattr(check, "__dataclass_fields__") else check for check in checks],
        "failures": [asdict(check) if hasattr(check, "__dataclass_fields__") else check for check in failures],
        "pytest_command": pytest_evidence.command,
        "pytest_exit_code": pytest_evidence.exit_code,
        "pytest_collected": pytest_evidence.collected,
        "pytest_selected": pytest_evidence.selected,
        "pytest_deselected": pytest_evidence.deselected,
        "pytest_passed": pytest_evidence.passed,
        "pytest_failed": pytest_evidence.failed,
        "pytest_skipped": pytest_evidence.skipped,
        "pytest_duration_seconds": pytest_evidence.duration_seconds,
        "pytest_summary": pytest_evidence.summary,
        "content_manifest_sha256": content_manifest_sha256,
        "report_sha256": report_sha256,
        "report_generated_at": report_generated_at,
        "verified_at": verified_at,
        "review_bundle_generated_at": review_bundle_generated_at,
        "design_baseline_version": STAGE03_DESIGN_VERSION,
        "implementation_plan_version": STAGE03_IMPLEMENTATION_PLAN_VERSION,
    }
    if bundle_evidence is not None:
        payload["review_bundle_sha256"] = bundle_evidence.zip_sha256
        payload["review_bundle_member_count"] = bundle_evidence.member_count
        payload["review_bundle_indexed_member_count"] = bundle_evidence.indexed_member_count
        payload["review_bundle_path"] = str(bundle_evidence.zip_path.name)
    return payload


def write_publication_artifacts(
    impl_dir: Path,
    *,
    report_content: str,
    verification_payload: dict[str, Any],
) -> None:
    report_path = impl_dir / IMPLEMENTATION_PLAN_REPORT_NAME
    verification_path = impl_dir / IMPLEMENTATION_PLAN_VERIFICATION_NAME
    report_path.write_text(report_content, encoding="utf-8")
    verification_path.write_text(json.dumps(verification_payload, indent=2) + "\n", encoding="utf-8")


def validate_publication_snapshot(impl_dir: Path) -> tuple[bool, str]:
    from human_simulator.stage03.implementation_publication import validate_publication_snapshot as _validate

    return _validate(impl_dir)
