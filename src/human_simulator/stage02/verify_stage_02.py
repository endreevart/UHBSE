"""Stage 02 gate verification."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from human_simulator.audit.report import REPORT_STATUS_DRAFT, REPORT_STATUS_FINAL, read_report_status
from human_simulator.audit.verify import SECRET_PROBE
from human_simulator.classify.data_levels import data_levels_compatible
from human_simulator.stage01.manifest import verify_manifest as verify_stage01_manifest
from human_simulator.stage02.artifact_safety import validate_relationship_artifacts
from human_simulator.stage02.classify_second_source import verify_manifest as verify_stage02_manifest
from human_simulator.stage02.compare_source_audits import STRUCTURAL_EVIDENCE_CROSSWALK
from human_simulator.stage02.relationship_manifest import verify_relationship_manifest

CheckStatus = Literal["PASS", "FAIL"]
OverallStatus = Literal["PASS", "FAIL"]

PRELIMINARY_STATUS = "PRELIMINARY_SCHEMA_ONLY"
LIVE_EXTRACTION_METHOD = "live_readonly_profile"

STAGE02_INPUT_ARTIFACTS: tuple[str, ...] = (
    "restore-report.json",
    "source-b-audit.json",
    "schema-profile-kgz.json",
    "entity-candidates-kgz.yaml",
    "relation-graph-kgz.md",
    "unknown-semantics-kgz.md",
    "schema-diff.yaml",
    "entity-crosswalk.yaml",
    "compare-verification-report.json",
    "subject-root-analysis.json",
    "subject-root-analysis.md",
    "source-relationship-assessment.json",
    "source-relationship-assessment.md",
    "identity-linkage-assessment.json",
    "identity-linkage-assessment.md",
    "relationship-verification-report.json",
    "relationship-query-log.json",
    "manifest.sha256",
    "relationship-manifest.sha256",
)

STAGE02_FINAL_MANIFEST_ARTIFACTS: tuple[str, ...] = (
    "verify-stage-02.json",
    "stage-02-report.md",
)

FINAL_MANIFEST_NAME = "stage-02-final-manifest.sha256"

SECRET_PATH_PROBE = re.compile(
    r"postgresql(?:\+[\w]+)?://[^:]+:(?!\*\*\*)[^@]+@",
    re.IGNORECASE,
)

FORBIDDEN_POPULATION_FIELDS = (
    "estimated_overlap_percentage",
    "population_overlap_percentage",
    "overall_overlap_percentage",
)

PYTEST_COMMAND = [
    sys.executable,
    "-m",
    "pytest",
    "-q",
    "--tb=no",
    "-m",
    "not verify_stage02_gate",
]


@dataclass(frozen=True)
class CheckResult:
    name: str
    section: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True)
class PytestRunResult:
    check: CheckResult
    payload: dict[str, Any]


def extract_unresolved_mappings(crosswalk: dict[str, Any] | None) -> list[str]:
    if not crosswalk:
        return []
    explicit = crosswalk.get("unresolved_mappings")
    if isinstance(explicit, list) and explicit:
        return list(explicit)

    unresolved: list[str] = []
    for entity_type, block in crosswalk.get("entity_types", {}).items():
        for mapping in block.get("mappings", []):
            if mapping.get("confidence") in {"UNKNOWN", "HYPOTHESIS"}:
                unresolved.append(
                    f"{entity_type}:{mapping.get('source_a')}->{mapping.get('source_b')}"
                )
    return unresolved


def verify_stage_02(repo_root: Path, *, run_tests: bool = True, publish_artifacts: bool = True) -> dict[str, Any]:
    root = repo_root.resolve()
    stage01_dir = root / "artifacts" / "stage-01"
    stage02_dir = root / "artifacts" / "stage-02"
    stage02_dir.mkdir(parents=True, exist_ok=True)

    checks: list[CheckResult] = []

    def add(check: CheckResult) -> None:
        checks.append(check)

    stage01_audit = _load_json(stage01_dir / "source-audit.json")
    stage01_profile = _load_json(stage01_dir / "schema-profile.json")
    stage01_fingerprint = _load_json(stage01_dir / "schema-fingerprint.json")
    stage02_audit = _load_json(stage02_dir / "source-b-audit.json")
    restore_report = _load_json(stage02_dir / "restore-report.json")
    compare_report = _load_json(stage02_dir / "compare-verification-report.json")
    relationship_report = _load_json(stage02_dir / "relationship-verification-report.json")
    crosswalk = _load_yaml(stage02_dir / "entity-crosswalk.yaml")
    subject_root = _load_json(stage02_dir / "subject-root-analysis.json")
    identity = _load_json(stage02_dir / "identity-linkage-assessment.json")
    structural = _load_json(stage02_dir / "source-relationship-assessment.json")

    crosswalk_unresolved = extract_unresolved_mappings(crosswalk)
    unresolved_questions = _collect_unresolved_questions(structural, relationship_report)

    _check_source_a(add, stage01_dir, stage01_audit, stage01_profile)
    _check_source_b(add, stage02_dir, stage02_audit, restore_report, relationship_report)
    _check_compare(add, stage02_dir, compare_report, crosswalk, crosswalk_unresolved)
    _check_relationship(add, stage02_dir, relationship_report, subject_root, identity, structural)
    _check_integrity(add, root, stage02_dir, run_tests=run_tests)

    if not run_tests:
        if not any(check.name == "full_test_suite" for check in checks):
            add(
                CheckResult(
                    "full_test_suite",
                    "integrity",
                    "FAIL",
                    "pytest suite was not executed",
                )
            )

    test_result = _build_test_result(checks, run_tests=run_tests)

    passed = sum(1 for check in checks if check.status == "PASS")
    failed_checks = [check for check in checks if check.status == "FAIL"]
    checks_total = len(checks)
    checks_failed = len(failed_checks)
    preliminary_overall: OverallStatus = "PASS" if checks_failed == 0 else "FAIL"

    artifact_hashes = {
        name: _sha256_file(stage02_dir / name)
        for name in STAGE02_INPUT_ARTIFACTS
        if (stage02_dir / name).exists()
    }

    preliminary_result: dict[str, Any] = {
        "stage": "02",
        "status": preliminary_overall,
        "verified_at": datetime.now(tz=UTC).isoformat(),
        "checks_passed": passed,
        "checks_failed": checks_failed,
        "checks_total": checks_total,
        "checks": [asdict(check) for check in checks],
        "failures": [asdict(check) for check in failed_checks],
        "artifact_hashes": artifact_hashes,
        "unresolved_mappings": crosswalk_unresolved,
        "reported_unresolved_count": len(crosswalk_unresolved),
        "compare_unresolved_count": (
            compare_report.get("summary", {}).get("unresolved_mappings") if compare_report else None
        ),
        "unresolved_questions": unresolved_questions,
        "test_result": test_result,
    }

    consistency_checks = _consistency_checks(
        checks=checks,
        preliminary_result=preliminary_result,
        crosswalk_unresolved=crosswalk_unresolved,
        identity=identity,
        structural=structural,
        subject_root=subject_root,
    )
    for check in consistency_checks:
        add(check)

    result = _finalize_and_publish(
        checks=checks,
        stage02_dir=stage02_dir,
        artifact_hashes=artifact_hashes,
        crosswalk_unresolved=crosswalk_unresolved,
        unresolved_questions=unresolved_questions,
        run_tests=run_tests,
        publish_artifacts=publish_artifacts,
        stage01_audit=stage01_audit,
        stage01_fingerprint=stage01_fingerprint,
        stage02_audit=stage02_audit,
        restore_report=restore_report,
        subject_root=subject_root,
        identity=identity,
        structural=structural,
    )
    return result


def _consistency_checks(
    *,
    checks: list[CheckResult],
    preliminary_result: dict[str, Any],
    crosswalk_unresolved: list[str],
    identity: dict[str, Any] | None,
    structural: dict[str, Any] | None,
    subject_root: dict[str, Any] | None,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    test_status = preliminary_result.get("test_result", {}).get("status")
    results.append(
        CheckResult(
            "test_result_not_skipped",
            "consistency",
            "PASS" if test_status != "SKIPPED" else "FAIL",
            f"test_result.status={test_status!r}",
        )
    )

    forbidden_self_hash = "final_artifact_hashes" in preliminary_result or any(
        key == "verify-stage-02.json"
        for key in preliminary_result.get("final_artifact_hashes", {}).keys()
    )
    results.append(
        CheckResult(
            "verify_json_no_self_hash",
            "consistency",
            "PASS" if not forbidden_self_hash else "FAIL",
            "verify JSON must not embed its own SHA-256",
        )
    )

    crosswalk_count = len(crosswalk_unresolved)
    compare_count = preliminary_result.get("compare_unresolved_count")
    complete_ok = (
        crosswalk_count > 0
        and preliminary_result.get("reported_unresolved_count") == crosswalk_count
        and preliminary_result.get("unresolved_mappings") == crosswalk_unresolved
        and (compare_count is None or compare_count == crosswalk_count)
    )
    results.append(
        CheckResult(
            "unresolved_mappings_complete",
            "consistency",
            "PASS" if complete_ok else "FAIL",
            f"crosswalk_unresolved={crosswalk_count}, compare_unresolved={compare_count}",
        )
    )

    expected_verdicts = {
        "subject_root_a": "SUBJECT_ROOT_CONFIRMED",
        "subject_root_b": "SUBJECT_ROOT_CANDIDATE",
        "identity": "POTENTIAL_OVERLAP",
        "source_relationship": "SAME_DOMAIN_DIFFERENT_SYSTEMS",
    }
    actual_verdicts = {
        "subject_root_a": subject_root.get("source_a", {}).get("verdict") if subject_root else None,
        "subject_root_b": subject_root.get("source_b", {}).get("overall_verdict") if subject_root else None,
        "identity": identity.get("identity_verdict", {}).get("verdict") if identity else None,
        "source_relationship": structural.get("source_relationship_verdict", {}).get("verdict")
        if structural
        else None,
    }
    verdicts_ok = actual_verdicts == expected_verdicts
    results.append(
        CheckResult(
            "verdicts_match_relationship_assessment",
            "consistency",
            "PASS" if verdicts_ok else "FAIL",
            f"actual={actual_verdicts}",
        )
    )

    results.append(
        CheckResult(
            "unresolved_mappings_exact_match",
            "consistency",
            "PASS"
            if preliminary_result.get("unresolved_mappings") == crosswalk_unresolved
            else "FAIL",
            "verify unresolved_mappings equals entity-crosswalk.yaml unresolved_mappings",
        )
    )

    return results


def _finalize_and_publish(
    *,
    checks: list[CheckResult],
    stage02_dir: Path,
    artifact_hashes: dict[str, str],
    crosswalk_unresolved: list[str],
    unresolved_questions: list[str],
    run_tests: bool,
    publish_artifacts: bool,
    stage01_audit: dict[str, Any] | None,
    stage01_fingerprint: dict[str, Any] | None,
    stage02_audit: dict[str, Any] | None,
    restore_report: dict[str, Any] | None,
    subject_root: dict[str, Any] | None,
    identity: dict[str, Any] | None,
    structural: dict[str, Any] | None,
) -> dict[str, Any]:
    verify_content = ""
    report_content = ""

    for _ in range(3):
        passed, _, checks_total, _, overall = _summarize_checks(checks)
        report_status = REPORT_STATUS_FINAL if overall == "PASS" else REPORT_STATUS_DRAFT

        _replace_or_append(
            checks,
            CheckResult(
                "report_final_only_on_overall_pass",
                "consistency",
                "PASS"
                if (overall == "PASS") == (report_status == REPORT_STATUS_FINAL)
                else "FAIL",
                f"overall={overall}, report_status={report_status!r}",
            ),
        )

        passed, _, checks_total, checks_failed, overall = _summarize_checks(checks)
        all_pass = all(check.status == "PASS" for check in checks)
        _replace_or_append(
            checks,
            CheckResult(
                "overall_pass_requires_all_checks",
                "consistency",
                "PASS" if (overall == "PASS") == all_pass else "FAIL",
                f"overall={overall}, all_pass={all_pass}",
            ),
        )
        _replace_or_append(
            checks,
            CheckResult(
                "checks_arithmetic",
                "consistency",
                "PASS" if passed + checks_failed == checks_total == len(checks) else "FAIL",
                f"passed={passed}, failed={checks_failed}, total={checks_total}, len(checks)={len(checks)}",
            ),
        )

        passed, _, checks_total, _, overall = _summarize_checks(checks)
        report_status = REPORT_STATUS_FINAL if overall == "PASS" else REPORT_STATUS_DRAFT
        result = _build_verify_result(
            checks=checks,
            overall=overall,
            artifact_hashes=artifact_hashes,
            crosswalk_unresolved=crosswalk_unresolved,
            unresolved_questions=unresolved_questions,
            run_tests=run_tests,
        )
        next_verify_content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        next_report_content = _render_stage_02_report(
            stage01_audit,
            stage01_fingerprint,
            stage02_audit,
            restore_report,
            subject_root,
            identity,
            structural,
            crosswalk_unresolved,
            unresolved_questions,
            overall,
            report_status,
            passed,
            checks_total,
        )

        manifest_ok, manifest_detail = _dry_run_final_manifest(next_verify_content, next_report_content)
        _replace_or_append(
            checks,
            CheckResult(
                "final_manifest_hashes_match",
                "consistency",
                "PASS" if manifest_ok else "FAIL",
                manifest_detail,
            ),
        )

        if next_verify_content == verify_content and next_report_content == report_content:
            verify_content = next_verify_content
            report_content = next_report_content
            break

        verify_content = next_verify_content
        report_content = next_report_content

    if publish_artifacts:
        _publish_final_artifacts(stage02_dir, verify_content, report_content)
    return json.loads(verify_content)


def _summarize_checks(
    checks: list[CheckResult],
) -> tuple[int, list[CheckResult], int, int, OverallStatus]:
    passed = sum(1 for check in checks if check.status == "PASS")
    failed_checks = [check for check in checks if check.status == "FAIL"]
    checks_total = len(checks)
    checks_failed = len(failed_checks)
    overall: OverallStatus = "PASS" if checks_failed == 0 else "FAIL"
    return passed, failed_checks, checks_total, checks_failed, overall


def _build_verify_result(
    *,
    checks: list[CheckResult],
    overall: OverallStatus,
    artifact_hashes: dict[str, str],
    crosswalk_unresolved: list[str],
    unresolved_questions: list[str],
    run_tests: bool,
) -> dict[str, Any]:
    passed, failed_checks, checks_total, checks_failed, _ = _summarize_checks(checks)
    return {
        "stage": "02",
        "status": overall,
        "verified_at": datetime.now(tz=UTC).isoformat(),
        "checks_passed": passed,
        "checks_failed": checks_failed,
        "checks_total": checks_total,
        "checks": [asdict(check) for check in checks],
        "failures": [asdict(check) for check in failed_checks],
        "artifact_hashes": artifact_hashes,
        "unresolved_mappings": crosswalk_unresolved,
        "reported_unresolved_count": len(crosswalk_unresolved),
        "unresolved_questions": unresolved_questions,
        "test_result": _build_test_result(checks, run_tests=run_tests),
        "final_manifest": FINAL_MANIFEST_NAME,
    }


def _replace_or_append(checks: list[CheckResult], check: CheckResult) -> None:
    for index, existing in enumerate(checks):
        if existing.name == check.name:
            checks[index] = check
            return
    checks.append(check)


def _dry_run_final_manifest(verify_content: str, report_content: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="stage02-manifest-dry-", dir=tempfile.gettempdir()) as tmp:
        tmpdir = Path(tmp)
        verify_tmp = tmpdir / "verify-stage-02.json"
        report_tmp = tmpdir / "stage-02-report.md"
        manifest_tmp = tmpdir / FINAL_MANIFEST_NAME
        verify_tmp.write_text(verify_content, encoding="utf-8")
        report_tmp.write_text(report_content, encoding="utf-8")
        manifest_lines = [
            f"{_sha256_file(verify_tmp)}  verify-stage-02.json",
            f"{_sha256_file(report_tmp)}  stage-02-report.md",
        ]
        manifest_tmp.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        return _verify_final_manifest(manifest_tmp, tmpdir)


def _publish_final_artifacts(stage02_dir: Path, verify_content: str, report_content: str) -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="stage02-verify-", dir=stage02_dir))
    try:
        verify_tmp = tmpdir / "verify-stage-02.json"
        report_tmp = tmpdir / "stage-02-report.md"
        manifest_tmp = tmpdir / FINAL_MANIFEST_NAME

        verify_tmp.write_text(verify_content, encoding="utf-8")
        report_tmp.write_text(report_content, encoding="utf-8")

        manifest_lines = [
            f"{_sha256_file(verify_tmp)}  verify-stage-02.json",
            f"{_sha256_file(report_tmp)}  stage-02-report.md",
        ]
        manifest_tmp.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

        manifest_ok, manifest_detail = _verify_final_manifest(manifest_tmp, tmpdir)
        if not manifest_ok:
            raise RuntimeError(f"final manifest verification failed: {manifest_detail}")

        for source in (verify_tmp, report_tmp, manifest_tmp):
            destination = stage02_dir / source.name
            shutil.move(str(source), str(destination))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _verify_final_manifest(manifest_path: Path, artifacts_dir: Path) -> tuple[bool, str]:
    if not manifest_path.exists():
        return False, f"missing {manifest_path.name}"
    verified = 0
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        if name.strip() == FINAL_MANIFEST_NAME:
            return False, "manifest must not include itself"
        path = artifacts_dir / name.strip()
        if not path.exists():
            return False, f"manifest entry missing file: {name.strip()}"
        if _sha256_file(path) != digest:
            return False, f"hash mismatch: {name.strip()}"
        verified += 1
    return True, f"verified {verified} entries in {manifest_path.name}"


def _check_source_a(
    add: Any,
    stage01_dir: Path,
    audit: dict[str, Any] | None,
    profile: dict[str, Any] | None,
) -> None:
    report_status = read_report_status(stage01_dir)
    add(
        CheckResult(
            "source_a_report_final",
            "source_a",
            "PASS" if report_status == REPORT_STATUS_FINAL else "FAIL",
            f"stage-01-report status={report_status!r}",
        )
    )
    add(
        CheckResult(
            "source_a_live_extraction",
            "source_a",
            "PASS" if audit and audit.get("extraction_method") == LIVE_EXTRACTION_METHOD else "FAIL",
            f"extraction_method={audit.get('extraction_method') if audit else 'missing'}",
        )
    )
    add(
        CheckResult(
            "source_a_audit_user",
            "source_a",
            "PASS" if audit and audit.get("connection_user") == "mg_audit_ro" else "FAIL",
            f"connection_user={audit.get('connection_user') if audit else 'missing'}",
        )
    )
    readonly_ok = bool(profile and profile.get("readonly_validation", {}).get("safe"))
    add(
        CheckResult(
            "source_a_readonly_validation",
            "source_a",
            "PASS" if readonly_ok else "FAIL",
            "readonly_validation.safe=true" if readonly_ok else "readonly validation missing or unsafe",
        )
    )
    fingerprint_match = bool(
        audit and audit.get("schema_fingerprint_check", {}).get("fingerprints_match") is True
    )
    add(
        CheckResult(
            "source_a_fingerprint_match",
            "source_a",
            "PASS" if fingerprint_match else "FAIL",
            f"fingerprints_match={audit.get('schema_fingerprint_check', {}).get('fingerprints_match') if audit else 'missing'}",
        )
    )
    manifest_ok, manifest_detail = verify_stage01_manifest(stage01_dir)
    add(
        CheckResult(
            "source_a_manifest",
            "source_a",
            "PASS" if manifest_ok else "FAIL",
            manifest_detail,
        )
    )
    prelim_path = stage01_dir.parent / "stage-01-preliminary" / "source-audit.json"
    prelim_used = prelim_path.exists() and audit and audit.get("status") == PRELIMINARY_STATUS
    add(
        CheckResult(
            "source_a_not_preliminary",
            "source_a",
            "PASS" if not prelim_used else "FAIL",
            "preliminary artifacts must not gate Stage 02",
        )
    )


def _check_source_b(
    add: Any,
    stage02_dir: Path,
    audit: dict[str, Any] | None,
    restore_report: dict[str, Any] | None,
    relationship_report: dict[str, Any] | None,
) -> None:
    add(
        CheckResult(
            "source_b_audit_pass",
            "source_b",
            "PASS" if audit and audit.get("status") == "PASS" else "FAIL",
            f"source-b-audit status={audit.get('status') if audit else 'missing'}",
        )
    )
    add(
        CheckResult(
            "source_b_audit_user",
            "source_b",
            "PASS" if audit and audit.get("connection_user") == "kgz_audit_ro" else "FAIL",
            f"connection_user={audit.get('connection_user') if audit else 'missing'}",
        )
    )
    manifest_ok, manifest_detail = verify_stage02_manifest(stage02_dir)
    add(
        CheckResult(
            "source_b_manifest",
            "source_b",
            "PASS" if manifest_ok else "FAIL",
            manifest_detail,
        )
    )
    restore_ok = bool(
        restore_report
        and restore_report.get("restore_performed") is True
        and restore_report.get("pg_restore_exit_code") == 0
    )
    add(
        CheckResult(
            "source_b_restore_completed",
            "source_b",
            "PASS" if restore_ok else "FAIL",
            f"restore_performed={restore_report.get('restore_performed') if restore_report else 'missing'}",
        )
    )
    profile_ok = (stage02_dir / "schema-profile-kgz.json").exists() and audit and audit.get("status") == "PASS"
    add(
        CheckResult(
            "source_b_profile_completed",
            "source_b",
            "PASS" if profile_ok else "FAIL",
            "schema profile and source-b-audit present",
        )
    )
    db_unchanged = bool(
        relationship_report
        and any(
            check.get("name") == "raw_databases_unchanged" and check.get("status") == "PASS"
            for check in relationship_report.get("checks", [])
        )
    )
    add(
        CheckResult(
            "source_b_raw_db_unchanged",
            "source_b",
            "PASS" if db_unchanged else "FAIL",
            "relationship assessment row-count fingerprints unchanged",
        )
    )


def _check_compare(
    add: Any,
    stage02_dir: Path,
    compare_report: dict[str, Any] | None,
    crosswalk: dict[str, Any] | None,
    crosswalk_unresolved: list[str],
) -> None:
    add(
        CheckResult(
            "compare_verification_report",
            "compare",
            "PASS" if compare_report and compare_report.get("status") == "PASS" else "FAIL",
            f"status={compare_report.get('status') if compare_report else 'missing'}",
        )
    )
    for name in ("schema-diff.yaml", "entity-crosswalk.yaml"):
        add(
            CheckResult(
                f"compare_artifact_{name}",
                "compare",
                "PASS" if (stage02_dir / name).exists() else "FAIL",
                "present" if (stage02_dir / name).exists() else "missing",
            )
        )

    if not crosswalk:
        add(CheckResult("crosswalk_loaded", "compare", "FAIL", "entity-crosswalk.yaml missing or invalid"))
        return

    candidate_only = True
    evidence_without_proof = False
    incompatible_mapped = False
    missing_data_level = False
    for entity_type, block in crosswalk.get("entity_types", {}).items():
        for mapping in block.get("mappings", []):
            if mapping.get("candidate_status") != "CANDIDATE":
                candidate_only = False
            confidence = mapping.get("confidence", "UNKNOWN")
            if confidence == "EVIDENCE_BACKED":
                key = (
                    entity_type,
                    mapping.get("source_a") or "",
                    mapping.get("source_b") or "",
                )
                if key not in STRUCTURAL_EVIDENCE_CROSSWALK:
                    evidence_without_proof = True
            a_level = mapping.get("source_a_data_level")
            b_level = mapping.get("source_b_data_level")
            if mapping.get("source_a") and mapping.get("source_b"):
                if not a_level or not b_level:
                    missing_data_level = True
                elif not data_levels_compatible(a_level, b_level) and confidence not in {"UNKNOWN", "HYPOTHESIS"}:
                    incompatible_mapped = True

    add(
        CheckResult(
            "crosswalk_candidate_only",
            "compare",
            "PASS" if candidate_only else "FAIL",
            "all mappings remain CANDIDATE",
        )
    )
    add(
        CheckResult(
            "crosswalk_no_unproven_evidence_backed",
            "compare",
            "PASS" if not evidence_without_proof else "FAIL",
            "EVIDENCE_BACKED requires recorded structural proofs",
        )
    )
    compare_unresolved = (
        compare_report.get("summary", {}).get("unresolved_mappings") if compare_report else None
    )
    unresolved_count_ok = len(crosswalk_unresolved) > 0 and (
        compare_unresolved is None or compare_unresolved == len(crosswalk_unresolved)
    )
    add(
        CheckResult(
            "crosswalk_unresolved_mappings_count",
            "compare",
            "PASS" if unresolved_count_ok else "FAIL",
            f"unresolved_mappings={len(crosswalk_unresolved)}, compare_report={compare_unresolved}",
        )
    )
    add(
        CheckResult(
            "crosswalk_data_level_present",
            "compare",
            "PASS" if not missing_data_level else "FAIL",
            "data_level on mapped pairs",
        )
    )
    add(
        CheckResult(
            "crosswalk_incompatible_levels_not_mapped",
            "compare",
            "PASS" if not incompatible_mapped else "FAIL",
            "incompatible data_level pairs not promoted",
        )
    )
    rules_text = yaml.safe_dump(crosswalk.get("rules", {}))
    no_permanent = "No cross-source patient identity linkage" in rules_text
    add(
        CheckResult(
            "no_permanent_patient_crosswalk",
            "compare",
            "PASS" if no_permanent else "FAIL",
            "crosswalk rules prohibit permanent patient linkage",
        )
    )


def _check_relationship(
    add: Any,
    stage02_dir: Path,
    relationship_report: dict[str, Any] | None,
    subject_root: dict[str, Any] | None,
    identity: dict[str, Any] | None,
    structural: dict[str, Any] | None,
) -> None:
    add(
        CheckResult(
            "relationship_verification_report",
            "relationship",
            "PASS" if relationship_report and relationship_report.get("status") == "PASS" else "FAIL",
            f"status={relationship_report.get('status') if relationship_report else 'missing'}",
        )
    )
    manifest_ok, manifest_detail = verify_relationship_manifest(stage02_dir)
    add(
        CheckResult(
            "relationship_manifest",
            "relationship",
            "PASS" if manifest_ok else "FAIL",
            manifest_detail,
        )
    )

    summary = relationship_report.get("summary", {}) if relationship_report else {}
    expected = {
        "subject_root_a_verdict": "SUBJECT_ROOT_CONFIRMED",
        "subject_root_b_verdict": "SUBJECT_ROOT_CANDIDATE",
        "identity_verdict": "POTENTIAL_OVERLAP",
        "source_relationship_verdict": "SAME_DOMAIN_DIFFERENT_SYSTEMS",
        "population_overlap_estimate_status": "NOT_ESTIMABLE",
    }
    for key, expected_value in expected.items():
        actual = summary.get(key)
        add(
            CheckResult(
                f"relationship_summary_{key}",
                "relationship",
                "PASS" if actual == expected_value else "FAIL",
                f"{key}={actual!r}, expected {expected_value!r}",
            )
        )

    identity_verdict = identity.get("identity_verdict", {}).get("verdict") if identity else None
    add(
        CheckResult(
            "no_linkage_proven",
            "relationship",
            "PASS" if identity_verdict != "LINKAGE_PROVEN" else "FAIL",
            f"identity_verdict={identity_verdict}",
        )
    )

    overlap = identity.get("overlap_aggregates", {}) if identity else {}
    has_population_pct = any(field in overlap for field in FORBIDDEN_POPULATION_FIELDS)
    add(
        CheckResult(
            "no_population_overlap_percentage",
            "relationship",
            "PASS" if not has_population_pct else "FAIL",
            "estimated population overlap percentage absent",
        )
    )
    pop_status = overlap.get("population_overlap_estimate", {}).get("status")
    add(
        CheckResult(
            "population_overlap_not_estimable",
            "relationship",
            "PASS" if pop_status == "NOT_ESTIMABLE" else "FAIL",
            f"population_overlap_estimate.status={pop_status!r}",
        )
    )

    identifier_split = (
        "matched_unique_phone_identifiers" in overlap
        and "uniquely_resolved_subject_pairs_by_phone" in overlap
        and "matches_by_phone" not in overlap
    )
    add(
        CheckResult(
            "identifier_matches_separate_from_subject_pairs",
            "relationship",
            "PASS" if identifier_split else "FAIL",
            "identifier-level and subject-pair metrics separated",
        )
    )

    add(
        CheckResult(
            "conflict_definition_present",
            "relationship",
            "PASS" if identity and identity.get("conflict_definition") else "FAIL",
            "conflict_definition block present",
        )
    )

    per_source_missing = all(
        key in overlap
        for key in (
            "source_a_subjects_without_any_strong_identifier",
            "source_b_subjects_without_any_strong_identifier",
        )
    ) and "unevaluable_due_to_missing_identifiers" not in overlap
    add(
        CheckResult(
            "missingness_per_source",
            "relationship",
            "PASS" if per_source_missing else "FAIL",
            "missingness reported separately per source",
        )
    )

    app_shared = (
        structural.get("structural_similarity", {}).get("application_shared_relation_name_count")
        if structural
        else None
    )
    add(
        CheckResult(
            "application_shared_relation_name_count",
            "relationship",
            "PASS" if app_shared == 0 else "FAIL",
            f"application_shared_relation_name_count={app_shared}",
        )
    )

    supporting = structural.get("source_relationship_verdict", {}).get("supporting_evidence", []) if structural else []
    supporting_text = " ".join(supporting).lower()
    infra_misused = "infrastructure_shared_relation_name_count" in supporting_text or "39 shared" in supporting_text
    add(
        CheckResult(
            "infrastructure_overlap_not_evidence",
            "relationship",
            "PASS" if not infra_misused else "FAIL",
            "infrastructure overlap excluded from supporting evidence",
        )
    )

    safety = validate_relationship_artifacts(stage02_dir)
    add(
        CheckResult(
            "relationship_artifacts_no_pii",
            "relationship",
            "PASS" if not safety else "FAIL",
            "no PII/raw IDs/HMAC leaks" if not safety else str(safety[:2]),
        )
    )


def _check_integrity(
    add: Any,
    repo_root: Path,
    stage02_dir: Path,
    *,
    run_tests: bool,
) -> None:
    hash_failures: list[str] = []
    for name in STAGE02_INPUT_ARTIFACTS:
        path = stage02_dir / name
        if not path.exists():
            hash_failures.append(f"missing {name}")

    add(
        CheckResult(
            "input_artifact_hashes_computed",
            "integrity",
            "PASS" if not hash_failures else "FAIL",
            "all input artifacts present" if not hash_failures else "; ".join(hash_failures[:5]),
        )
    )

    for manifest_name in ("manifest.sha256", "relationship-manifest.sha256"):
        manifest_path = stage02_dir / manifest_name
        if not manifest_path.exists():
            add(CheckResult(f"{manifest_name}_present", "integrity", "FAIL", "missing"))
            continue
        self_hash = any(
            line.strip().endswith(manifest_name) for line in manifest_path.read_text(encoding="utf-8").splitlines()
        )
        add(
            CheckResult(
                f"{manifest_name}_no_self_hash",
                "integrity",
                "PASS" if not self_hash else "FAIL",
                "manifest does not include itself",
            )
        )

    query_logs_ok = all((stage02_dir / name).exists() for name in ("profiling-query-log.json", "relationship-query-log.json"))
    add(
        CheckResult(
            "sanitized_query_logs_present",
            "integrity",
            "PASS" if query_logs_ok else "FAIL",
            "profiling and relationship query logs present",
        )
    )

    secrets_ok, secrets_detail = _scan_stage02_for_secrets(stage02_dir)
    add(
        CheckResult(
            "no_secrets_in_artifacts",
            "integrity",
            "PASS" if secrets_ok else "FAIL",
            secrets_detail,
        )
    )

    if run_tests:
        pytest_run = _run_pytest(repo_root)
        add(pytest_run.check)


def _scan_stage02_for_secrets(stage02_dir: Path) -> tuple[bool, str]:
    skip_names = {FINAL_MANIFEST_NAME, "restore-pg_restore.log"}
    for path in stage02_dir.rglob("*"):
        if path.is_dir() or path.suffix not in {".json", ".md", ".yaml", ".yml", ".log", ".sha256"}:
            continue
        if path.name in skip_names:
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if SECRET_PROBE.search(line) or SECRET_PATH_PROBE.search(line):
                return False, f"credential or absolute path pattern in {path.name}"
    return True, "no secrets or absolute credential paths detected"


def _run_pytest(repo_root: Path) -> PytestRunResult:
    started = time.perf_counter()
    proc = subprocess.run(
        PYTEST_COMMAND,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    duration = round(time.perf_counter() - started, 3)
    output = (proc.stdout or "") + (proc.stderr or "")
    parsed = _parse_pytest_output(output)
    parsed.update(
        {
            "command": " ".join(PYTEST_COMMAND),
            "exit_code": proc.returncode,
            "duration_seconds": duration,
            "executed": True,
        }
    )

    passed_gate = (
        parsed["executed"]
        and parsed["exit_code"] == 0
        and parsed["collected"] > 0
        and parsed["failed"] == 0
        and parsed["error"] == 0
        and parsed["passed"] + parsed["skipped"] == parsed["collected"]
    )
    parsed["status"] = "PASS" if passed_gate else "FAIL"

    return PytestRunResult(
        check=CheckResult(
            "full_test_suite",
            "integrity",
            "PASS" if passed_gate else "FAIL",
            json.dumps(parsed, ensure_ascii=False),
        ),
        payload=parsed,
    )


def _parse_pytest_output(output: str) -> dict[str, int]:
    passed = _first_int(output, r"(\d+) passed")
    failed = _first_int(output, r"(\d+) failed")
    skipped = _first_int(output, r"(\d+) skipped")
    error = _first_int(output, r"(\d+) error")
    collected = passed + failed + skipped + error
    return {
        "collected": collected,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "error": error,
    }


def _first_int(text: str, pattern: str) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


def _build_test_result(checks: list[CheckResult], *, run_tests: bool) -> dict[str, Any]:
    if not run_tests:
        return {"status": "SKIPPED", "executed": False, "detail": "tests not run"}
    for check in checks:
        if check.name == "full_test_suite":
            try:
                return json.loads(check.detail)
            except json.JSONDecodeError:
                return {"status": check.status, "detail": check.detail, "executed": True}
    return {"status": "SKIPPED", "executed": False, "detail": "full_test_suite check missing"}


def _collect_unresolved_questions(
    structural: dict[str, Any] | None,
    relationship_report: dict[str, Any] | None,
) -> list[str]:
    questions: list[str] = []
    if structural:
        questions.extend(structural.get("source_relationship_verdict", {}).get("unresolved_questions", []))
    if relationship_report:
        for item in relationship_report.get("unresolved_questions", []):
            if item not in questions:
                questions.append(item)
    return questions


def _render_stage_02_report(
    stage01_audit: dict[str, Any] | None,
    stage01_fingerprint: dict[str, Any] | None,
    stage02_audit: dict[str, Any] | None,
    restore_report: dict[str, Any] | None,
    subject_root: dict[str, Any] | None,
    identity: dict[str, Any] | None,
    structural: dict[str, Any] | None,
    unresolved_mappings: list[str],
    unresolved_questions: list[str],
    overall: OverallStatus,
    report_status: str,
    passed: int,
    total: int,
) -> str:
    fp_a = stage01_audit.get("schema_fingerprint_check", {}) if stage01_audit else {}
    fp_a_sha = fp_a.get("current_fingerprint_sha256") or (stage01_fingerprint or {}).get("sha256", "unknown")
    pop_reason = (
        identity.get("overlap_aggregates", {}).get("population_overlap_estimate", {}).get("reason", "unknown")
        if identity
        else "unknown"
    )

    lines = [
        "# Stage 02 Report",
        "",
        f"Generated: {datetime.now(tz=UTC).isoformat()}",
        "",
        f"**Report status:** {report_status}",
        "",
        "## Sources",
        "",
        "### Source A (magerya_api)",
        f"- Extraction: `{stage01_audit.get('extraction_method') if stage01_audit else 'unknown'}`",
        f"- Audit user: `{stage01_audit.get('connection_user') if stage01_audit else 'unknown'}`",
        f"- Schema fingerprint SHA-256: `{fp_a_sha}`",
        "",
        "### Source B (kgz_raw)",
        f"- Audit user: `{stage02_audit.get('connection_user') if stage02_audit else 'unknown'}`",
        f"- Restore: `{restore_report.get('message') if restore_report else 'unknown'}`",
        f"- Database: `{stage02_audit.get('database') if stage02_audit else 'unknown'}`",
        "",
        "## Completed substeps",
        "",
        "1. restore-second-source (confirmed)",
        "2. profile-second-source via kgz_audit_ro",
        "3. compare-source-audits",
        "4. assess-source-relationship",
        "5. verify-stage-02",
        "",
        "## Confirmed results",
        "",
        f"- Gate status: **{overall}** ({passed}/{total} checks)",
        f"- Subject root A: **{subject_root.get('source_a', {}).get('verdict') if subject_root else 'unknown'}**",
        f"- Subject root B: **{subject_root.get('source_b', {}).get('overall_verdict') if subject_root else 'unknown'}**",
        f"- Identity verdict: **{identity.get('identity_verdict', {}).get('verdict') if identity else 'unknown'}**",
        f"- Source relationship: **{structural.get('source_relationship_verdict', {}).get('verdict') if structural else 'unknown'}**",
        f"- Unresolved crosswalk mappings: **{len(unresolved_mappings)}**",
        "",
        "## Identity assessment limitations",
        "",
        f"- Population overlap: **NOT_ESTIMABLE** — {pop_reason}",
        "- Identifier intersections are not treated as confirmed patient matches.",
        "- Duplicate identifiers, cross-field conflicts, and asymmetric missingness prevent population extrapolation.",
        "- No per-patient HMAC digests or raw identifiers are stored in artifacts.",
        "",
        "## Explicit non-actions",
        "",
        "- No merge of Source A and Source B databases",
        "- No canonical database created",
        "- No permanent patient crosswalk created",
        "- No Stage 03 work started",
        "",
        "## Unresolved crosswalk mappings",
        "",
    ]
    for item in unresolved_mappings:
        lines.append(f"- `{item}`")

    lines.extend(["", "## Unresolved questions (carried to Stage 03)", ""])
    if unresolved_questions:
        for item in unresolved_questions:
            lines.append(f"- {item}")
    else:
        lines.append("- _None recorded_")

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `verify-stage-02.json`",
            "- `stage-02-final-manifest.sha256`",
            "- `compare-verification-report.json`",
            "- `relationship-verification-report.json`",
            "- `entity-crosswalk.yaml`",
            "- `subject-root-analysis.json`",
            "- `identity-linkage-assessment.json`",
            "- `source-relationship-assessment.json`",
            "",
        ]
    )
    if overall == "PASS":
        lines.append("**PASS** — Stage 02 gate reached.")
    else:
        lines.append("**FAIL** — Stage 02 gate not reached. See `verify-stage-02.json` for failed checks.")
    lines.append("")
    return "\n".join(lines)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))
