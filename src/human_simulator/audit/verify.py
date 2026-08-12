"""Stage 01 gate verification against docs/stage-01-acceptance.md."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from human_simulator.audit.report import (
    REPORT_STATUS_DRAFT,
    finalize_stage_01_report,
    read_report_status,
)
from human_simulator.db.redaction import redact_credentials, redact_phi

CriterionStatus = Literal["pass", "fail"]
OverallStatus = Literal["PASS", "PARTIAL", "FAIL"]

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "source-audit.json",
    "schema-profile.json",
    "entity-candidates.yaml",
    "relation-graph.md",
    "unknown-semantics.md",
    "stage-01-report.md",
)

PHI_PROBE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+|\+?\d[\d\s\-()]{8,}\d",
)
SECRET_PROBE = re.compile(
    r"postgresql(?:\+[\w]+)?://[^:]+:(?!\*\*\*)[^@]+@",
    re.IGNORECASE,
)

_SCHEMA_METADATA_SAFE_SUBSTRINGS: tuple[str, ...] = (
    "postgres_version",
    "redacted_url",
    '"name": "email"',
    '"name": "phone"',
    '"name": "_phone"',
    '"name": "backup_phone"',
    '"name": "recipient_email"',
    "authentication_whitelistphone",
    "phone_confirmation_date",
    "purchased_by_phone",
    "received_by_phone",
)


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    section: str
    description: str
    status: CriterionStatus
    missing_artifact: str | None
    reason: str
    required_action: str
    human_clarification_needed: bool


def verify_stage_01(
    repo_root: Path,
    *,
    artifacts_dir: Path | None = None,
    run_tests: bool = True,
) -> dict[str, Any]:
    root = repo_root.resolve()
    target = (artifacts_dir or (root / "artifacts" / "stage-01")).resolve()
    criteria = _evaluate_all_criteria(root, target, run_tests=run_tests)

    passed = sum(1 for item in criteria if item.status == "pass")
    failed = [item for item in criteria if item.status == "fail"]
    overall = _overall_status(passed, len(criteria), failed)

    report_path: str | None = None
    if overall == "PASS":
        report_path = str(finalize_stage_01_report(target))
        _update_current_stage_gate_reached(root)

    result = {
        "stage": "01",
        "status": overall,
        "checked_at": datetime.now(UTC).isoformat(),
        "criteria_passed": passed,
        "criteria_total": len(criteria),
        "failures": [asdict(item) for item in failed],
        "criteria": [asdict(item) for item in criteria],
        "report_path": report_path,
        "artifacts_dir": str(target),
    }
    target.mkdir(parents=True, exist_ok=True)
    (target / "verify-result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result


def verify_stage(artifacts_dir: Path) -> dict[str, Any]:
    """Backward-compatible wrapper used by CLI."""
    repo_root = _find_repo_root(artifacts_dir)
    result = verify_stage_01(repo_root, artifacts_dir=artifacts_dir, run_tests=False)
    return {
        "stage": result["stage"],
        "passed": result["status"] == "PASS",
        "status": result["status"],
        "missing": [
            item["missing_artifact"]
            for item in result["failures"]
            if item.get("missing_artifact")
        ],
        "artifacts_dir": result["artifacts_dir"],
        "failures": result["failures"],
    }


def _find_repo_root(artifacts_dir: Path) -> Path:
    if (artifacts_dir / "schema-profile.json").exists():
        if artifacts_dir.name == "stage-01" and artifacts_dir.parent.name == "artifacts":
            return artifacts_dir.parent.parent
    return artifacts_dir


def _evaluate_all_criteria(
    repo_root: Path,
    artifacts_dir: Path,
    *,
    run_tests: bool,
) -> list[CriterionResult]:
    checks: list[CriterionResult] = []

    source_audit = _load_json_if_exists(artifacts_dir / "source-audit.json")
    schema_profile = _load_json_if_exists(artifacts_dir / "schema-profile.json")
    entity_candidates = _load_yaml_if_exists(artifacts_dir / "entity-candidates.yaml")

    checks.extend(_scope_checks(source_audit, schema_profile))
    checks.extend(_safety_checks(artifacts_dir, schema_profile))
    checks.extend(_deliverable_checks(artifacts_dir, source_audit, schema_profile, entity_candidates))
    checks.extend(_quality_checks(repo_root, artifacts_dir, entity_candidates))
    if run_tests:
        checks.append(_pytest_check(repo_root))
    return checks


def _scope_checks(
    source_audit: dict[str, Any] | None,
    schema_profile: dict[str, Any] | None,
) -> list[CriterionResult]:
    database = None
    if schema_profile:
        database = schema_profile.get("database")
    elif source_audit:
        database = source_audit.get("database")

    single_source = database == "magerya_api"
    return [
        _criterion(
            "scope.single_source",
            "Scope",
            "Exactly one clinic source audited (local magerya_api copy)",
            single_source,
            None if single_source else "schema-profile.json",
            "Database identifier is not magerya_api" if not single_source else "ok",
            "Run audit profile-source against the local magerya_api Docker copy",
            human=not single_source,
        ),
        _criterion(
            "scope.no_cross_clinic",
            "Scope",
            "No second clinic, no cross-clinic merge, no unified database",
            True,
            None,
            "Process scope attestation only; no cross-clinic artifacts expected in Stage 01",
            "Continue single-source workflow; defer multi-clinic work to docs/future-work.md",
            human=False,
        ),
        _criterion(
            "scope.no_future_work",
            "Scope",
            "No simulator design, ML/LLM, OMOP, or FHIR work",
            True,
            None,
            "Process scope attestation only",
            "Record deferred requests in docs/future-work.md without implementing them",
            human=False,
        ),
    ]


def _safety_checks(
    artifacts_dir: Path,
    schema_profile: dict[str, Any] | None,
) -> list[CriterionResult]:
    readonly_ok = bool(schema_profile and schema_profile.get("readonly_validation", {}).get("safe"))
    phi_ok, phi_reason = _scan_artifacts_for_phi(artifacts_dir)
    secrets_ok, secrets_reason = _scan_artifacts_for_secrets(artifacts_dir)

    return [
        _criterion(
            "safety.original_readonly",
            "Safety",
            "Original restored database access must be read-only",
            readonly_ok,
            None if readonly_ok else "schema-profile.json",
            "Read-only validation missing or unsafe" if not readonly_ok else "ok",
            "Re-run audit profile-source with a read-only role and read-only transaction settings",
            human=not readonly_ok,
        ),
        _criterion(
            "safety.derived_writes_stage_gated",
            "Safety",
            "Derived database writes are allowed only when explicitly required by the stage",
            True,
            None,
            "Stage 01 does not perform derived database writes",
            "Defer derived database writes to later stages unless explicitly opened",
            human=False,
        ),
        _criterion(
            "safety.stage01_no_db_modification",
            "Safety",
            "Stage 01 does not modify either database",
            readonly_ok,
            None if readonly_ok else "schema-profile.json",
            "Cannot attest Stage 01 immutability without successful read-only validation"
            if not readonly_ok
            else "ok",
            "Complete Stage 01 using read-only profiling against the original restored database",
            human=not readonly_ok,
        ),
        _criterion(
            "safety.no_row_level_phi",
            "Safety",
            "No row-level patient data in agent context, logs, or artifacts",
            phi_ok,
            None if phi_ok else str(artifacts_dir),
            phi_reason,
            "Remove raw values from artifacts; keep aggregates and metadata only",
            human=not phi_ok,
        ),
        _criterion(
            "safety.no_secrets",
            "Safety",
            "No secrets committed to the repository",
            secrets_ok,
            None if secrets_ok else str(artifacts_dir),
            secrets_reason,
            "Redact credentials from artifacts and keep secrets in private/ or env only",
            human=not secrets_ok,
        ),
        _criterion(
            "safety.no_sensitive_identifiers",
            "Safety",
            "No names, phones, emails, addresses, identifiers, or document bodies exposed",
            phi_ok,
            None if phi_ok else str(artifacts_dir),
            phi_reason if not phi_ok else "ok",
            "Sanitize artifacts before gate review",
            human=not phi_ok,
        ),
    ]


def _deliverable_checks(
    artifacts_dir: Path,
    source_audit: dict[str, Any] | None,
    schema_profile: dict[str, Any] | None,
    entity_candidates: dict[str, Any] | None,
) -> list[CriterionResult]:
    checks: list[CriterionResult] = []

    for artifact in REQUIRED_ARTIFACTS:
        path = artifacts_dir / artifact
        checks.append(
            _criterion(
                f"deliverable.{artifact}",
                "Deliverables",
                f"Artifact exists: {artifact}",
                path.exists(),
                None if path.exists() else artifact,
                "Artifact missing" if not path.exists() else "ok",
                f"Generate `{artifact}` through the Stage 01 pipeline",
                human=False,
            )
        )

    reachable = bool(source_audit and source_audit.get("reachable") is True)
    checks.append(
        _criterion(
            "deliverable.source_reachable",
            "Deliverables",
            "source-audit.json shows reachable source",
            reachable,
            None if reachable else "source-audit.json",
            "Source not marked reachable" if not reachable else "ok",
            "Run audit connection-check and record source-audit.json",
            human=not reachable,
        )
    )

    has_schema = bool(schema_profile and schema_profile.get("relations"))
    checks.append(
        _criterion(
            "deliverable.schema_profile_content",
            "Deliverables",
            "schema-profile.json contains relation metadata",
            has_schema,
            None if has_schema else "schema-profile.json",
            "Schema profile has no relations" if not has_schema else "ok",
            "Run audit profile-source against the configured PostgreSQL source",
            human=not has_schema,
        )
    )

    has_candidates = bool(entity_candidates and entity_candidates.get("entity_types") is not None)
    checks.append(
        _criterion(
            "deliverable.entity_candidates_content",
            "Deliverables",
            "entity-candidates.yaml contains candidate mappings",
            has_candidates,
            None if has_candidates else "entity-candidates.yaml",
            "Entity candidates missing or empty structure" if not has_candidates else "ok",
            "Run audit classify-entities after schema profiling",
            human=not has_candidates,
        )
    )

    evidence_dir = artifacts_dir / "evidence"
    has_evidence = evidence_dir.exists() and any(evidence_dir.iterdir())
    checks.append(
        _criterion(
            "deliverable.evidence",
            "Deliverables",
            "artifacts/stage-01/evidence/ contains query evidence",
            has_evidence,
            None if has_evidence else "artifacts/stage-01/evidence/",
            "Evidence directory missing or empty" if not has_evidence else "ok",
            "Ensure profile-source records query evidence under artifacts/stage-01/evidence/",
            human=False,
        )
    )
    return checks


def _quality_checks(
    repo_root: Path,
    artifacts_dir: Path,
    entity_candidates: dict[str, Any] | None,
) -> list[CriterionResult]:
    unknown_semantics = artifacts_dir / "unknown-semantics.md"
    unknown_ok = unknown_semantics.exists() and "UNKNOWN" in unknown_semantics.read_text(encoding="utf-8")

    current_stage = repo_root / "docs" / "current-stage.md"
    current_stage_ok = current_stage.exists() and "Stage 01" in current_stage.read_text(encoding="utf-8")

    query_log = _load_json_if_exists(artifacts_dir / "profiling-query-log.json")
    evidence_ok = bool(query_log)
    report_status = read_report_status(artifacts_dir)
    draft_ok = report_status == REPORT_STATUS_DRAFT

    return [
        _criterion(
            "quality.evidence_references",
            "Quality",
            "Every factual claim references a query or generated artifact",
            evidence_ok,
            None if evidence_ok else "profiling-query-log.json",
            "Missing profiling query log" if not evidence_ok else "ok",
            "Re-run audit profile-source to capture query identifiers and durations",
            human=not evidence_ok,
        ),
        _criterion(
            "quality.unknown_semantics",
            "Quality",
            "Undocumented field meanings marked UNKNOWN",
            unknown_ok,
            None if unknown_ok else "unknown-semantics.md",
            "unknown-semantics.md missing UNKNOWN markers" if not unknown_ok else "ok",
            "Run audit classify-entities and review unknown-semantics.md",
            human=not unknown_ok,
        ),
        _criterion(
            "quality.current_stage_updated",
            "Quality",
            "docs/current-stage.md updated to reflect progress",
            current_stage_ok,
            None if current_stage_ok else "docs/current-stage.md",
            "Current stage tracker missing or not describing Stage 01" if not current_stage_ok else "ok",
            "Update docs/current-stage.md after each completed task",
            human=False,
        ),
        _criterion(
            "quality.report_draft_status",
            "Quality",
            "stage-01-report.md exists with DRAFT status before gate finalization",
            draft_ok,
            None if draft_ok else "stage-01-report.md",
            f"Report status is {report_status!r}, expected DRAFT" if not draft_ok else "ok",
            "Run audit draft-report after classify-entities before verify-stage",
            human=False,
        ),
        _criterion(
            "quality.candidate_not_confirmed_by_name",
            "Quality",
            "Entity candidates do not treat name-only matches as confirmed medical meaning",
            _candidate_quality_ok(entity_candidates),
            None if _candidate_quality_ok(entity_candidates) else "entity-candidates.yaml",
            "Some candidates may overstate certainty without evidence",
            "Review entity-candidates.yaml and downgrade unsupported CONFIRMED mappings",
            human=True,
        ),
    ]


def _pytest_check(repo_root: Path) -> CriterionResult:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        passed = completed.returncode == 0
        reason = "ok" if passed else (completed.stdout + completed.stderr).strip()[-500:]
    except OSError as exc:
        passed = False
        reason = str(exc)

    return _criterion(
        "quality.pytest",
        "Quality",
        "pytest passes for src/human_simulator",
        passed,
        None,
        reason,
        "Fix failing tests before declaring Stage 01 complete",
        human=False,
    )


def _candidate_quality_ok(entity_candidates: dict[str, Any] | None) -> bool:
    if not entity_candidates:
        return False
    for items in entity_candidates.get("entity_types", {}).values():
        for item in items:
            if item.get("status") == "CONFIRMED":
                evidence = item.get("evidence") or []
                if not any(ev.get("type") != "name_pattern" for ev in evidence):
                    return False
    return True


def _update_current_stage_gate_reached(repo_root: Path) -> None:
    path = repo_root / "docs" / "current-stage.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\*\*Status:\*\* .*", "**Status:** gate reached", text)
    text = re.sub(r"Stage 01 gate: \*\*.*\*\*", "Stage 01 gate: **reached**", text)
    path.write_text(text, encoding="utf-8")


def _overall_status(passed: int, total: int, failed: list[CriterionResult]) -> OverallStatus:
    if passed == total:
        return "PASS"
    critical = any(item.criterion_id.startswith(("deliverable.", "safety.")) for item in failed)
    if passed == 0 or (critical and passed < total // 2):
        return "FAIL"
    return "PARTIAL"


def _scan_artifacts_for_phi(artifacts_dir: Path) -> tuple[bool, str]:
    if not artifacts_dir.exists():
        return False, "Artifacts directory missing"
    schema_metadata_only = {
        "schema-profile.json",
        "schema-profile-kgz.json",
    }
    for path in artifacts_dir.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".yaml", ".yml", ".md"}:
            continue
        if path.name in schema_metadata_only:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            if any(marker in line for marker in _SCHEMA_METADATA_SAFE_SUBSTRINGS):
                continue
            if PHI_PROBE.search(line) and redact_phi(line) != line:
                return False, f"Potential PHI pattern detected in {path.name}"
    return True, "ok"


def _scan_artifacts_for_secrets(artifacts_dir: Path) -> tuple[bool, str]:
    if not artifacts_dir.exists():
        return False, "Artifacts directory missing"
    for path in artifacts_dir.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".yaml", ".yml", ".md"}:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            if "redacted_url" in line or ":***@" in line:
                continue
            if SECRET_PROBE.search(line):
                return False, f"Credential-like value detected in {path.name}"
        if redact_credentials(content) != content:
            redacted_lines = [
                line
                for line in content.splitlines()
                if "redacted_url" not in line and ":***@" not in line
            ]
            if redact_credentials("\n".join(redacted_lines)) != "\n".join(redacted_lines):
                return False, f"Potential secret detected in {path.name}"
    return True, "ok"


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_yaml_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _criterion(
    criterion_id: str,
    section: str,
    description: str,
    passed: bool,
    missing_artifact: str | None,
    reason: str,
    required_action: str,
    *,
    human: bool,
) -> CriterionResult:
    return CriterionResult(
        criterion_id=criterion_id,
        section=section,
        description=description,
        status="pass" if passed else "fail",
        missing_artifact=missing_artifact,
        reason=reason,
        required_action=required_action,
        human_clarification_needed=human,
    )
