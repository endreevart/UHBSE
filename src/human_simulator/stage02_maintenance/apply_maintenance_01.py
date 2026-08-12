"""Apply the authorised Stage 02 Maintenance 01 repair.

Only ``artifacts/stage-02/relationship-manifest.sha256`` may change. The eight relationship
artifacts keep the bytes already on disk; the candidate manifest is copied because it was sealed
over those exact bytes during diagnosis. Nothing else is touched — no restore, no reassessment, no
rewrite of the Stage 02 FINAL report.

Without ``--confirm`` the command refuses. Post-apply checks run immediately; on any failure the
original manifest is restored and ``rolled_back: true`` is recorded.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
    verify_relationship_manifest,
)
from human_simulator.stage02_maintenance.constants import (
    CANDIDATE_DIR,
    EXPECTED_MANIFEST_SHA_AFTER,
    EXPECTED_MANIFEST_SHA_BEFORE,
    EXPECTED_REMAINING_GATE_FAILURES,
    FORBIDDEN_STAGE_02_CHANGES,
    HASH_MATRIX_NAME,
    MAINTENANCE_DIR,
    PROMOTION_REPORT_JSON,
    PROMOTION_REPORT_MD,
    PROMOTION_VERIFICATION_JSON,
    STAGE_02_DIR,
)
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_file
from human_simulator.stage03.prior_stage_integrity import ACCEPTED_SHA256

REPORT_STATUS_FINAL = "FINAL"


class MaintenanceApplyBlocked(RuntimeError):
    """Raised when preconditions fail or the repair cannot be applied safely."""


@dataclass
class PreconditionResult:
    passed: bool
    detail: str
    current_manifest_sha256: str
    candidate_manifest_sha256: str
    relationship_artifact_sha256: dict[str, str]
    controlled_stage_01_02_sha256: dict[str, str]

    def document(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "detail": self.detail,
            "current_manifest_sha256": self.current_manifest_sha256,
            "expected_current_manifest_sha256": EXPECTED_MANIFEST_SHA_BEFORE,
            "candidate_manifest_sha256": self.candidate_manifest_sha256,
            "expected_candidate_manifest_sha256": EXPECTED_MANIFEST_SHA_AFTER,
            "relationship_artifact_sha256": dict(sorted(self.relationship_artifact_sha256.items())),
            "controlled_stage_01_02_sha256": dict(
                sorted(self.controlled_stage_01_02_sha256.items())
            ),
        }


def _controlled_hashes(repo_root: Path) -> dict[str, str]:
    root = repo_root.resolve()
    return {
        rel: sha256_file(root / rel)
        for rel in sorted(ACCEPTED_SHA256)
        if (root / rel).is_file()
    }


def _relationship_hashes(repo_root: Path) -> dict[str, str]:
    directory = repo_root / STAGE_02_DIR
    return {
        name: sha256_file(directory / name)
        for name in RELATIONSHIP_MANIFEST_ARTIFACTS
        if (directory / name).is_file()
    }


def evaluate_preconditions(repo_root: Path) -> PreconditionResult:
    """Every hash that must hold before a single byte of Stage 02 is touched."""
    root = repo_root.resolve()
    working_manifest = root / STAGE_02_DIR / MANIFEST_NAME
    candidate_manifest = root / CANDIDATE_DIR / MANIFEST_NAME

    if not working_manifest.is_file():
        return PreconditionResult(False, f"missing working manifest: {working_manifest}", "", "", {}, {})
    if not candidate_manifest.is_file():
        return PreconditionResult(False, f"missing candidate manifest: {candidate_manifest}", "", "", {}, {})

    current_sha = sha256_file(working_manifest)
    candidate_sha = sha256_file(candidate_manifest)
    relationship = _relationship_hashes(root)
    controlled = _controlled_hashes(root)

    failures: list[str] = []
    already_applied = (
        current_sha == EXPECTED_MANIFEST_SHA_AFTER
        and candidate_sha == EXPECTED_MANIFEST_SHA_AFTER
    )
    if already_applied:
        pass  # repair on disk; candidate matches working manifest
    elif current_sha != EXPECTED_MANIFEST_SHA_BEFORE:
        failures.append(
            f"working manifest sha256 {current_sha} != expected {EXPECTED_MANIFEST_SHA_BEFORE}"
        )
    if candidate_sha != EXPECTED_MANIFEST_SHA_AFTER:
        failures.append(
            f"candidate manifest sha256 {candidate_sha} != expected {EXPECTED_MANIFEST_SHA_AFTER}"
        )
    if len(relationship) != len(RELATIONSHIP_MANIFEST_ARTIFACTS):
        missing = sorted(set(RELATIONSHIP_MANIFEST_ARTIFACTS) - set(relationship))
        failures.append(f"missing relationship artifacts: {missing}")
    if len(controlled) != len(ACCEPTED_SHA256):
        missing = sorted(set(ACCEPTED_SHA256) - set(controlled))
        failures.append(f"missing controlled Stage 01/02 files: {missing}")
    for rel, accepted in ACCEPTED_SHA256.items():
        if rel in controlled and controlled[rel] != accepted:
            failures.append(f"{rel}: current {controlled[rel]} != accepted {accepted}")

    verified, manifest_detail = verify_relationship_manifest(root / CANDIDATE_DIR)
    if not verified:
        failures.append(f"candidate manifest does not verify 8/8: {manifest_detail}")

    passed = not failures
    detail = (
        "repair already applied; candidate matches working manifest"
        if passed and already_applied
        else ("all preconditions satisfied" if passed else "; ".join(failures))
    )
    return PreconditionResult(
        passed=passed,
        detail=detail,
        current_manifest_sha256=current_sha,
        candidate_manifest_sha256=candidate_sha,
        relationship_artifact_sha256=relationship,
        controlled_stage_01_02_sha256=controlled,
    )


def _atomic_write(path: Path, content: bytes) -> None:
    """Replace one file without leaving a half-written manifest if the process dies mid-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        os.write(fd, content)
        os.fsync(fd)
        os.close(fd)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def apply_manifest(repo_root: Path) -> bytes:
    """Copy the candidate manifest over the working one. Returns the bytes that were replaced."""
    root = repo_root.resolve()
    target = root / STAGE_02_DIR / MANIFEST_NAME
    source = root / CANDIDATE_DIR / MANIFEST_NAME
    original = target.read_bytes()
    _atomic_write(target, source.read_bytes())
    return original


def restore_manifest(repo_root: Path, original: bytes) -> None:
    _atomic_write(repo_root.resolve() / STAGE_02_DIR / MANIFEST_NAME, original)


@dataclass
class PostApplyResult:
    passed: bool
    rolled_back: bool
    detail: str
    manifest_verified: bool
    relationship_artifacts_unchanged: bool
    controlled_files_unchanged: bool
    forbidden_files_unchanged: bool
    mandatory_release_suite: dict[str, Any]
    publisher_only_suite: dict[str, Any]
    verify_stage_02: dict[str, Any]
    gate: dict[str, Any]
    relationship_artifact_sha256_after: dict[str, str]
    controlled_stage_01_02_sha256_after: dict[str, str]
    manifest_sha256_after: str

    def document(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "rolled_back": self.rolled_back,
            "detail": self.detail,
            "manifest_verified_8_of_8": self.manifest_verified,
            "relationship_artifacts_unchanged": self.relationship_artifacts_unchanged,
            "controlled_stage_01_02_unchanged": self.controlled_files_unchanged,
            "forbidden_stage_02_files_unchanged": self.forbidden_files_unchanged,
            "mandatory_release_suite": self.mandatory_release_suite,
            "publisher_only_suite": self.publisher_only_suite,
            "verify_stage_02_read_only": self.verify_stage_02,
            "pre_live_load_gate": self.gate,
            "manifest_sha256_after": self.manifest_sha256_after,
            "expected_manifest_sha256_after": EXPECTED_MANIFEST_SHA_AFTER,
            "relationship_artifact_sha256_after": dict(
                sorted(self.relationship_artifact_sha256_after.items())
            ),
            "controlled_stage_01_02_sha256_after": dict(
                sorted(self.controlled_stage_01_02_sha256_after.items())
            ),
        }


def _run_mandatory_release_suite(repo_root: Path) -> dict[str, Any]:
    """Mandatory release suite including maintenance tests."""
    from human_simulator.stage02_maintenance.promotion_evidence import run_mandatory_release_suite

    return run_mandatory_release_suite(repo_root)


def evaluate_post_apply(
    repo_root: Path,
    *,
    relationship_before: dict[str, str],
    controlled_before: dict[str, str],
    forbidden_before: dict[str, str],
) -> PostApplyResult:
    """Everything that must still hold after the manifest alone has changed."""
    from human_simulator.stage02.verify_stage_02 import verify_stage_02
    from human_simulator.stage02_maintenance.promotion_evidence import (
        run_publisher_only_suite,
        summarize_verify_stage_02_read_only,
    )
    from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate

    root = repo_root.resolve()
    directory = root / STAGE_02_DIR
    manifest_path = directory / MANIFEST_NAME

    manifest_sha = sha256_file(manifest_path) if manifest_path.is_file() else ""
    manifest_ok, manifest_detail = verify_relationship_manifest(directory)

    relationship_after = _relationship_hashes(root)
    controlled_after = _controlled_hashes(root)
    forbidden_after = {
        name: sha256_file(directory / name)
        for name in FORBIDDEN_STAGE_02_CHANGES
        if (directory / name).is_file()
    }

    relationship_unchanged = relationship_after == relationship_before
    controlled_unchanged = controlled_after == controlled_before
    forbidden_unchanged = forbidden_after == forbidden_before

    mandatory_result = _run_mandatory_release_suite(root)
    publisher_only_result = run_publisher_only_suite(root)
    verify_result = verify_stage_02(root, run_tests=False, publish_artifacts=False)
    verify_summary = summarize_verify_stage_02_read_only(verify_result)
    gate_result = evaluate_pre_live_load_gate(root).document()

    gate_failed = tuple(gate_result.get("failed_checks", []))
    gate_expectation_ok = set(gate_failed) == set(EXPECTED_REMAINING_GATE_FAILURES)
    manifest_hash_ok = gate_result.get("checks", [])
    manifest_check_pass = any(
        item.get("name") == "relationship_manifest_hashes_match" and item.get("status") == "PASS"
        for item in manifest_hash_ok
    )
    drift_blocker_pass = "stage02_relationship_manifest_drift" not in gate_failed

    checks_ok = (
        manifest_ok
        and manifest_sha == EXPECTED_MANIFEST_SHA_AFTER
        and relationship_unchanged
        and controlled_unchanged
        and forbidden_unchanged
        and mandatory_result["status"] == "PASS"
        and manifest_check_pass
        and drift_blocker_pass
        and gate_expectation_ok
    )

    failures: list[str] = []
    if not manifest_ok:
        failures.append(f"manifest verify: {manifest_detail}")
    if manifest_sha != EXPECTED_MANIFEST_SHA_AFTER:
        failures.append(f"manifest sha {manifest_sha} != expected {EXPECTED_MANIFEST_SHA_AFTER}")
    if not relationship_unchanged:
        failures.append("relationship artifact bytes changed")
    if not controlled_unchanged:
        failures.append("controlled Stage 01/02 bytes changed")
    if not forbidden_unchanged:
        failures.append("forbidden Stage 02 FINAL files changed")
    if mandatory_result["status"] != "PASS":
        failures.append(
            f"mandatory release suite {mandatory_result['status']} "
            f"exit={mandatory_result['exit_code']}"
        )
    if not manifest_check_pass:
        failures.append("gate relationship_manifest_hashes_match not PASS")
    if not drift_blocker_pass:
        failures.append("gate stage02_relationship_manifest_drift still FAIL")
    if not gate_expectation_ok:
        failures.append(
            f"gate failed_checks {sorted(gate_failed)} != expected {sorted(EXPECTED_REMAINING_GATE_FAILURES)}"
        )

    return PostApplyResult(
        passed=checks_ok,
        rolled_back=False,
        detail="all post-apply checks passed" if checks_ok else "; ".join(failures),
        manifest_verified=manifest_ok,
        relationship_artifacts_unchanged=relationship_unchanged,
        controlled_files_unchanged=controlled_unchanged,
        forbidden_files_unchanged=forbidden_unchanged,
        mandatory_release_suite=mandatory_result,
        publisher_only_suite=publisher_only_result,
        verify_stage_02=verify_summary,
        gate=gate_result,
        relationship_artifact_sha256_after=relationship_after,
        controlled_stage_01_02_sha256_after=controlled_after,
        manifest_sha256_after=manifest_sha,
    )


def _write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_promotion_report(
    *,
    preconditions: PreconditionResult,
    post_apply: PostApplyResult,
    before_matrix: dict[str, Any],
    rolled_back: bool,
    report_status: str,
) -> str:
    lines = [
        "# Stage 02 Maintenance 01 — Authorised Repair Application",
        "",
        f"Report status: **{report_status}**",
        f"Repair applied: **{not rolled_back}**",
        f"Rolled back: **{rolled_back}**",
        "",
        "## What changed",
        "",
        "Only `artifacts/stage-02/relationship-manifest.sha256`.",
        "",
        f"* before: `{EXPECTED_MANIFEST_SHA_BEFORE}`",
        f"* after: `{EXPECTED_MANIFEST_SHA_AFTER}`",
        "",
        "The eight relationship artifacts were not copied from the candidate. Their working bytes "
        "were already authoritative; the candidate manifest was sealed over them during diagnosis.",
        "",
        "## Preconditions",
        "",
        f"Status: {'PASS' if preconditions.passed else 'FAIL'} — {preconditions.detail}",
        "",
        "## Post-apply verification",
        "",
        f"Status: {'PASS' if post_apply.passed else 'FAIL'} — {post_apply.detail}",
        "",
        f"* manifest 8/8: {'PASS' if post_apply.manifest_verified else 'FAIL'}",
        f"* relationship artifacts unchanged: {post_apply.relationship_artifacts_unchanged}",
        f"* nine controlled Stage 01/02 files unchanged: {post_apply.controlled_files_unchanged}",
        f"* Stage 02 FINAL report/verify/manifest untouched: {post_apply.forbidden_files_unchanged}",
        f"* mandatory release suite: {post_apply.mandatory_release_suite.get('status')} "
        f"({post_apply.mandatory_release_suite.get('passed')} passed, "
        f"exit {post_apply.mandatory_release_suite.get('exit_code')})",
        f"* read-only verify-stage-02: {post_apply.verify_stage_02.get('status')} "
        f"(final_manifest_hashes_match expected PASS; full_test_suite not evaluated)",
        f"* pre-live-load gate: {post_apply.gate.get('status')} — "
        f"failed: {post_apply.gate.get('failed_checks')}",
        "",
        "## Data handling during apply",
        "",
        "No database connections were opened and no clinical rows were read during the apply step. "
        "Read-only gate and verification commands also open no database connections.",
        "",
    ]
    return "\n".join(lines)


def finalize_applied_repair(repo_root: Path) -> dict[str, Any]:
    """Record post-apply verification when the manifest repair is already on disk.

    Used when apply succeeded but promotion artifacts were not written, or when re-running
    verification after an interrupted apply.
    """
    root = repo_root.resolve()
    manifest_sha = sha256_file(root / STAGE_02_DIR / MANIFEST_NAME)
    if manifest_sha != EXPECTED_MANIFEST_SHA_AFTER:
        raise MaintenanceApplyBlocked(
            f"manifest is {manifest_sha}, expected {EXPECTED_MANIFEST_SHA_AFTER}; apply first"
        )

    relationship = _relationship_hashes(root)
    controlled = _controlled_hashes(root)
    directory = root / STAGE_02_DIR
    forbidden_before = {
        name: sha256_file(directory / name)
        for name in FORBIDDEN_STAGE_02_CHANGES
        if (directory / name).is_file()
    }

    before_matrix = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "manifest_sha256_before": EXPECTED_MANIFEST_SHA_BEFORE,
        "manifest_sha256_expected_after": EXPECTED_MANIFEST_SHA_AFTER,
        "relationship_artifacts": dict(sorted(relationship.items())),
        "controlled_stage_01_02": dict(sorted(controlled.items())),
        "forbidden_stage_02_files": dict(sorted(forbidden_before.items())),
        "note": "before manifest captured from authorised expected value; repair already on disk",
    }

    pre = PreconditionResult(
        passed=True,
        detail="repair already applied; preconditions inferred from on-disk state",
        current_manifest_sha256=EXPECTED_MANIFEST_SHA_AFTER,
        candidate_manifest_sha256=EXPECTED_MANIFEST_SHA_AFTER,
        relationship_artifact_sha256=relationship,
        controlled_stage_01_02_sha256=controlled,
    )

    post = evaluate_post_apply(
        root,
        relationship_before=relationship,
        controlled_before=controlled,
        forbidden_before=forbidden_before,
    )

    after_matrix = {
        **before_matrix,
        "manifest_sha256_after": manifest_sha,
        "rolled_back": False,
        "relationship_artifacts_after": dict(sorted(post.relationship_artifact_sha256_after.items())),
        "controlled_stage_01_02_after": dict(
            sorted(post.controlled_stage_01_02_sha256_after.items())
        ),
    }

    report_status = REPORT_STATUS_FINAL if post.passed else "DRAFT"
    verification = {
        "maintenance_id": "stage-02-maintenance-01",
        "verified_at": datetime.now(UTC).isoformat(),
        "report_status": report_status,
        "repair_applied": True,
        "rolled_back": False,
        "preconditions": pre.document(),
        "post_apply": post.document(),
        "before_after_matrix": after_matrix,
        "database_connections_during_apply": 0,
        "clinical_rows_read_during_apply": 0,
    }

    output = root / MAINTENANCE_DIR
    _write_json(output / PROMOTION_REPORT_JSON, verification)
    _write_json(output / PROMOTION_VERIFICATION_JSON, verification)
    (output / PROMOTION_REPORT_MD).write_text(
        _render_promotion_report(
            preconditions=pre,
            post_apply=post,
            before_matrix=after_matrix,
            rolled_back=False,
            report_status=report_status,
        ),
        encoding="utf-8",
    )

    if (output / HASH_MATRIX_NAME).is_file():
        matrix = json.loads((output / HASH_MATRIX_NAME).read_text(encoding="utf-8"))
        matrix["promotion"] = after_matrix
        _write_json(output / HASH_MATRIX_NAME, matrix)

    return {
        "status": "PASS" if post.passed else "FAIL",
        "report_status": report_status,
        "repair_applied": True,
        "rolled_back": False,
        "detail": post.detail,
        "preconditions": pre.document(),
        "post_apply": post.document(),
        "artifacts_written": [
            str(MAINTENANCE_DIR / PROMOTION_REPORT_JSON),
            str(MAINTENANCE_DIR / PROMOTION_REPORT_MD),
            str(MAINTENANCE_DIR / PROMOTION_VERIFICATION_JSON),
        ],
    }


def apply_maintenance_01(repo_root: Path, *, confirm: bool) -> dict[str, Any]:
    """Apply the authorised manifest repair when ``confirm`` is true."""
    if not confirm:
        raise MaintenanceApplyBlocked(
            "refusing to apply without explicit confirmation: "
            "audit --root . stage-02-maintenance-01-apply --confirm"
        )

    root = repo_root.resolve()
    output = root / MAINTENANCE_DIR
    pre = evaluate_preconditions(root)
    if not pre.passed:
        raise MaintenanceApplyBlocked(f"preconditions failed: {pre.detail}")

    directory = root / STAGE_02_DIR
    forbidden_before = {
        name: sha256_file(directory / name)
        for name in FORBIDDEN_STAGE_02_CHANGES
        if (directory / name).is_file()
    }

    before_matrix = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "manifest_sha256_before": pre.current_manifest_sha256,
        "manifest_sha256_expected_after": EXPECTED_MANIFEST_SHA_AFTER,
        "relationship_artifacts": dict(sorted(pre.relationship_artifact_sha256.items())),
        "controlled_stage_01_02": dict(sorted(pre.controlled_stage_01_02_sha256.items())),
        "forbidden_stage_02_files": dict(sorted(forbidden_before.items())),
    }

    original_manifest = apply_manifest(root)
    post = evaluate_post_apply(
        root,
        relationship_before=pre.relationship_artifact_sha256,
        controlled_before=pre.controlled_stage_01_02_sha256,
        forbidden_before=forbidden_before,
    )

    rolled_back = False
    if not post.passed:
        restore_manifest(root, original_manifest)
        rolled_back = True
        post.rolled_back = True
        post.detail = f"post-apply checks failed; manifest restored. {post.detail}"

    after_matrix = {
        **before_matrix,
        "manifest_sha256_after": sha256_file(directory / MANIFEST_NAME)
        if not rolled_back
        else pre.current_manifest_sha256,
        "rolled_back": rolled_back,
        "relationship_artifacts_after": dict(sorted(post.relationship_artifact_sha256_after.items())),
        "controlled_stage_01_02_after": dict(
            sorted(post.controlled_stage_01_02_sha256_after.items())
        ),
    }

    report_status = REPORT_STATUS_FINAL if post.passed and not rolled_back else "DRAFT"
    verification = {
        "maintenance_id": "stage-02-maintenance-01",
        "verified_at": datetime.now(UTC).isoformat(),
        "report_status": report_status,
        "repair_applied": not rolled_back,
        "rolled_back": rolled_back,
        "preconditions": pre.document(),
        "post_apply": post.document(),
        "before_after_matrix": after_matrix,
        "database_connections_during_apply": 0,
        "clinical_rows_read_during_apply": 0,
    }

    _write_json(output / PROMOTION_REPORT_JSON, verification)
    _write_json(output / PROMOTION_VERIFICATION_JSON, verification)
    (output / PROMOTION_REPORT_MD).write_text(
        _render_promotion_report(
            preconditions=pre,
            post_apply=post,
            before_matrix=after_matrix,
            rolled_back=rolled_back,
            report_status=report_status,
        ),
        encoding="utf-8",
    )

    # Refresh the hash matrix with the after state for the promotion bundle.
    if (output / HASH_MATRIX_NAME).is_file():
        matrix = json.loads((output / HASH_MATRIX_NAME).read_text(encoding="utf-8"))
        matrix["promotion"] = after_matrix
        _write_json(output / HASH_MATRIX_NAME, matrix)

    return {
        "status": "PASS" if post.passed and not rolled_back else "FAIL",
        "report_status": report_status,
        "repair_applied": not rolled_back,
        "rolled_back": rolled_back,
        "detail": post.detail,
        "preconditions": pre.document(),
        "post_apply": post.document(),
        "artifacts_written": [
            str(MAINTENANCE_DIR / PROMOTION_REPORT_JSON),
            str(MAINTENANCE_DIR / PROMOTION_REPORT_MD),
            str(MAINTENANCE_DIR / PROMOTION_VERIFICATION_JSON),
        ],
    }
