"""Build promotion report and verification evidence for Maintenance 01."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from human_simulator.stage02.relationship_manifest import verify_relationship_manifest
from human_simulator.stage02_maintenance.constants import (
    EXPECTED_MANIFEST_SHA_AFTER,
    EXPECTED_REMAINING_GATE_FAILURES,
    MAINTENANCE_DIR,
    MAINTENANCE_ID,
    PROMOTION_VERSION,
    STAGE_02_DIR,
)
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_file
from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate
from human_simulator.stage03.release_verification import (
    PUBLISHER_ONLY_MARKER_EXPR,
    mandatory_release_suite_command,
    mandatory_release_suite_deselection,
    run_suite,
    shell_quote,
)


def _suite_document(suite: Any) -> dict[str, Any]:
    return {
        "name": suite.name,
        "command": suite.command,
        "exit_code": suite.exit_code,
        "collected": suite.collected,
        "selected": suite.selected,
        "deselected": suite.deselected,
        "passed": suite.passed,
        "failed": suite.failed,
        "skipped": suite.skipped,
        "errors": suite.errors,
        "duration_seconds": suite.duration_seconds,
        "summary": suite.summary,
        "status": "PASS" if suite.ok else "FAIL",
        "executed": True,
    }


def run_mandatory_release_suite(repo_root: Any) -> dict[str, Any]:
    command = mandatory_release_suite_command()
    suite = run_suite(
        repo_root,
        name="mandatory_release_suite",
        command=command,
        mandatory=True,
    )
    deselection = mandatory_release_suite_deselection(repo_root)
    return {
        **_suite_document(suite),
        "selection": {
            "marker_expression": deselection["marker_expression"],
            "keyword_exclusions": deselection["keyword_exclusions"],
            "deselected_by_marker": deselection["deselected_by_marker"],
            "deselected_marker_counts": deselection["deselected_marker_counts"],
            "deselected_total_reported_by_pytest": suite.deselected,
        },
        "literal_command": shell_quote(command),
    }


def run_publisher_only_suite(repo_root: Any) -> dict[str, Any]:
    command = ["uv", "run", "pytest", "-q", "-m", PUBLISHER_ONLY_MARKER_EXPR]
    suite = run_suite(
        repo_root,
        name="publisher_only_suite",
        command=command,
        mandatory=False,
    )
    return {
        **_suite_document(suite),
        "literal_command": shell_quote(command),
        "note": "Publisher-only tests are outside the mandatory release suite and are recorded separately.",
    }


def summarize_verify_stage_02_read_only(result: dict[str, Any]) -> dict[str, Any]:
    checks = {item["name"]: item for item in result.get("checks", [])}
    final_manifest = checks.get("final_manifest_hashes_match", {})
    full_test_suite = checks.get("full_test_suite", {})
    test_result = result.get("test_result", {})
    not_evaluated = []
    if full_test_suite.get("status") != "PASS":
        not_evaluated.append("full_test_suite")
    if test_result.get("status") == "SKIPPED":
        not_evaluated.append("test_result_not_skipped")
    return {
        "status": result.get("status"),
        "overall_fail_reason": "run_tests=False",
        "checks_evaluated": sorted(checks),
        "checks_not_evaluated": not_evaluated,
        "final_manifest_hashes_match": final_manifest.get("status"),
        "full_test_suite": full_test_suite.get("status"),
        "test_result": test_result,
        "verified_at": result.get("verified_at"),
    }


def build_promotion_report(
    *,
    repair_applied: bool,
    rolled_back: bool,
    manifest_sha256_after: str,
    manifest_verified_8_of_8: bool,
    mandatory_release_suite: dict[str, Any],
    publisher_only_suite: dict[str, Any],
    gate_failed_checks: list[str],
    promotion_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "maintenance_id": MAINTENANCE_ID,
        "promotion_version": PROMOTION_VERSION,
        "report_status": "DRAFT",
        "verified_at": datetime.now(UTC).isoformat(),
        "repair_applied": repair_applied,
        "rolled_back": rolled_back,
        "manifest_sha256_after": manifest_sha256_after,
        "expected_manifest_sha256_after": EXPECTED_MANIFEST_SHA_AFTER,
        "manifest_verified_8_of_8": manifest_verified_8_of_8,
        "mandatory_release_suite": {
            "status": mandatory_release_suite.get("status"),
            "passed": mandatory_release_suite.get("passed"),
            "failed": mandatory_release_suite.get("failed"),
            "exit_code": mandatory_release_suite.get("exit_code"),
            "summary": mandatory_release_suite.get("summary"),
        },
        "publisher_only_suite": {
            "status": publisher_only_suite.get("status"),
            "executed": publisher_only_suite.get("executed"),
            "passed": publisher_only_suite.get("passed"),
            "failed": publisher_only_suite.get("failed"),
            "summary": publisher_only_suite.get("summary"),
        },
        "pre_live_load_gate": {
            "status": "FAIL",
            "failed_checks": gate_failed_checks,
            "expected_failed_checks": list(EXPECTED_REMAINING_GATE_FAILURES),
        },
        "promotion_bundle": promotion_bundle or {},
        "evidence_location": f"{MAINTENANCE_DIR.as_posix()}/promotion-verification.json",
    }


def build_promotion_verification(
    *,
    repair_applied: bool,
    rolled_back: bool,
    preconditions: dict[str, Any],
    before_after_matrix: dict[str, Any],
    post_apply_core: dict[str, Any],
    mandatory_release_suite: dict[str, Any],
    publisher_only_suite: dict[str, Any],
    verify_stage_02_summary: dict[str, Any],
    gate_document: dict[str, Any],
    publication_checks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "maintenance_id": MAINTENANCE_ID,
        "promotion_version": PROMOTION_VERSION,
        "verified_at": datetime.now(UTC).isoformat(),
        "report_status": "DRAFT",
        "repair_applied": repair_applied,
        "rolled_back": rolled_back,
        "preconditions": preconditions,
        "before_after_matrix": before_after_matrix,
        "post_apply": post_apply_core,
        "mandatory_release_suite": mandatory_release_suite,
        "publisher_only_suite": publisher_only_suite,
        "verify_stage_02_read_only": verify_stage_02_summary,
        "pre_live_load_gate": gate_document,
        "publication_checks": publication_checks or {},
        "database_connections_during_apply": 0,
        "clinical_rows_read_during_apply": 0,
    }


def collect_post_apply_core(
    repo_root: Any,
    *,
    relationship_before: dict[str, str],
    controlled_before: dict[str, str],
    forbidden_before: dict[str, str],
    mandatory_release_suite: dict[str, Any],
    publisher_only_suite: dict[str, Any],
    verify_stage_02_summary: dict[str, Any],
    gate_document: dict[str, Any],
) -> dict[str, Any]:
    from human_simulator.stage02_maintenance.apply_maintenance_01 import (
        _controlled_hashes,
        _relationship_hashes,
    )

    root = repo_root.resolve()
    directory = root / STAGE_02_DIR
    manifest_sha = sha256_file(directory / "relationship-manifest.sha256")
    manifest_ok, manifest_detail = verify_relationship_manifest(directory)
    relationship_after = _relationship_hashes(root)
    controlled_after = _controlled_hashes(root)
    forbidden_after = {
        name: sha256_file(directory / name)
        for name in forbidden_before
        if (directory / name).is_file()
    }
    gate_failed = tuple(gate_document.get("failed_checks", []))
    return {
        "manifest_verified_8_of_8": manifest_ok,
        "manifest_detail": manifest_detail,
        "manifest_sha256_after": manifest_sha,
        "relationship_artifacts_unchanged": relationship_after == relationship_before,
        "controlled_stage_01_02_unchanged": controlled_after == controlled_before,
        "forbidden_stage_02_files_unchanged": forbidden_after == forbidden_before,
        "relationship_artifact_sha256_after": dict(sorted(relationship_after.items())),
        "controlled_stage_01_02_sha256_after": dict(sorted(controlled_after.items())),
        "mandatory_release_suite": mandatory_release_suite,
        "publisher_only_suite": publisher_only_suite,
        "verify_stage_02_read_only": verify_stage_02_summary,
        "pre_live_load_gate": gate_document,
        "gate_failed_checks_match_expected": set(gate_failed) == set(EXPECTED_REMAINING_GATE_FAILURES),
    }
