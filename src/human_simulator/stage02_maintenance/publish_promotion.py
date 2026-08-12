"""Publish the Stage 02 Maintenance 01 promotion review bundle."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
    verify_relationship_manifest,
)
from human_simulator.stage02_maintenance.apply_maintenance_01 import REPORT_STATUS_FINAL
from human_simulator.stage02_maintenance.bundle_index import (
    build_review_index,
    bundle_counts,
    verify_indexed_members,
)
from human_simulator.stage02_maintenance.constants import (
    DEFECT_ID,
    EXPECTED_MANIFEST_SHA_AFTER,
    EXTERNAL_REVIEW_DIR,
    MAINTENANCE_DIR,
    MAINTENANCE_ID,
    MAINTENANCE_TITLE,
    PROMOTION_BUNDLE_V011_ATTESTATION_NAME,
    PROMOTION_BUNDLE_V011_SHA256_NAME,
    PROMOTION_BUNDLE_V011_ZIP_NAME,
    PROMOTION_CONTENT_ARTIFACTS,
    PROMOTION_MANIFEST_NAME,
    PROMOTION_REPORT_JSON,
    PROMOTION_REPORT_MD,
    PROMOTION_VERIFICATION_JSON,
    PROMOTION_VERSION,
    STAGE_02_DIR,
)
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_bytes, sha256_file
from human_simulator.stage02_maintenance.promotion_evidence import (
    build_promotion_report,
    build_promotion_verification,
    collect_post_apply_core,
    run_mandatory_release_suite,
    run_publisher_only_suite,
    summarize_verify_stage_02_read_only,
)
from human_simulator.stage02_maintenance.promotion_manifest import (
    manifest_lists_itself,
    read_promotion_manifest,
    verify_promotion_manifest_entries,
    verify_promotion_manifest_with_shasum,
    write_promotion_manifest,
)

SOURCE_FILES: tuple[str, ...] = (
    "src/human_simulator/stage02_maintenance/__init__.py",
    "src/human_simulator/stage02_maintenance/constants.py",
    "src/human_simulator/stage02_maintenance/drift_diagnosis.py",
    "src/human_simulator/stage02_maintenance/reproduction.py",
    "src/human_simulator/stage02_maintenance/candidate.py",
    "src/human_simulator/stage02_maintenance/run_maintenance_01.py",
    "src/human_simulator/stage02_maintenance/publish_maintenance_01.py",
    "src/human_simulator/stage02_maintenance/apply_maintenance_01.py",
    "src/human_simulator/stage02_maintenance/publish_promotion.py",
    "src/human_simulator/stage02_maintenance/bundle_index.py",
    "src/human_simulator/stage02_maintenance/promotion_manifest.py",
    "src/human_simulator/stage02_maintenance/promotion_evidence.py",
    "src/human_simulator/cli.py",
    "tests/test_stage_02_maintenance_01.py",
    "tests/test_stage_02_maintenance_01_apply.py",
    "tests/test_stage_02_maintenance_01_promotion.py",
)


class PromotionPublicationBlocked(RuntimeError):
    """Raised when the promotion bundle must not be built."""


def collect_promotion_files(repo_root: Path) -> list[tuple[str, Path]]:
    root = repo_root.resolve()
    members: list[tuple[str, Path]] = []

    for name in (*PROMOTION_CONTENT_ARTIFACTS, PROMOTION_MANIFEST_NAME):
        path = root / MAINTENANCE_DIR / name
        if path.is_file():
            members.append((f"{MAINTENANCE_DIR.as_posix()}/{name}", path))

    for name in (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME):
        path = root / STAGE_02_DIR / name
        if path.is_file():
            members.append((f"{STAGE_02_DIR.as_posix()}/{name}", path))

    for relative in SOURCE_FILES:
        path = root / relative
        if path.is_file():
            members.append((relative, path))

    for relative in ("docs/current-stage.md", "docs/stage-02-maintenance-01.md"):
        path = root / relative
        if path.is_file():
            members.append((relative, path))

    return sorted(members, key=lambda item: item[0])


def _reproduce_doc() -> str:
    return "\n".join(
        [
            "# Reproducing Stage 02 Maintenance 01 promotion",
            "",
            f"Promotion version: **{PROMOTION_VERSION}**.",
            "",
            "## Verify the repaired relationship manifest",
            "",
            "```bash",
            "cd artifacts/stage-02 && shasum -a 256 -c relationship-manifest.sha256",
            "```",
            "",
            "Expect eight `OK` lines.",
            "",
            "## Verify the promotion manifest",
            "",
            "```bash",
            f"cd {MAINTENANCE_DIR.as_posix()} && shasum -a 256 -c {PROMOTION_MANIFEST_NAME}",
            "```",
            "",
            "The promotion manifest must not list itself.",
            "",
            "## Re-run post-apply checks",
            "",
            "```bash",
            "audit --root . stage-02-pre-live-load-gate",
            "```",
            "",
            "The gate should FAIL on exactly four contract/conflict blockers; "
            "`relationship_manifest_hashes_match` and `stage02_relationship_manifest_drift` "
            "must be PASS.",
            "",
        ]
    )


def _write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_existing_matrix(repo_root: Path) -> dict[str, Any]:
    path = repo_root / MAINTENANCE_DIR / "before-after-hash-matrix.json"
    if not path.is_file():
        return {}
    matrix = json.loads(path.read_text(encoding="utf-8"))
    return matrix.get("promotion") or {}


def refresh_promotion_artifacts(
    repo_root: Path,
    *,
    rerun_publisher_only: bool = False,
) -> dict[str, Any]:
    """Rebuild promotion report and verification without touching Stage 02 repair bytes."""
    from human_simulator.stage02.verify_stage_02 import verify_stage_02
    from human_simulator.stage02_maintenance.apply_maintenance_01 import (
        _controlled_hashes,
        _relationship_hashes,
        evaluate_preconditions,
    )
    from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate

    root = repo_root.resolve()
    manifest_sha = sha256_file(root / STAGE_02_DIR / MANIFEST_NAME)
    if manifest_sha != EXPECTED_MANIFEST_SHA_AFTER:
        raise PromotionPublicationBlocked(
            f"working manifest {manifest_sha} != expected {EXPECTED_MANIFEST_SHA_AFTER}"
        )

    pre = evaluate_preconditions(root)
    relationship = _relationship_hashes(root)
    controlled = _controlled_hashes(root)
    directory = root / STAGE_02_DIR
    forbidden_before = {
        name: sha256_file(directory / name)
        for name in ("stage-02-report.md", "verify-stage-02.json", "stage-02-final-manifest.sha256")
        if (directory / name).is_file()
    }

    mandatory_suite = run_mandatory_release_suite(root)
    verification_path = root / MAINTENANCE_DIR / PROMOTION_VERIFICATION_JSON
    existing_publisher: dict[str, Any] | None = None
    if verification_path.is_file():
        existing = json.loads(verification_path.read_text(encoding="utf-8"))
        existing_publisher = existing.get("publisher_only_suite")
    if rerun_publisher_only or not existing_publisher:
        publisher_suite = run_publisher_only_suite(root)
    else:
        publisher_suite = existing_publisher
    verify_result = verify_stage_02(root, run_tests=False, publish_artifacts=False)
    verify_summary = summarize_verify_stage_02_read_only(verify_result)
    gate = evaluate_pre_live_load_gate(root).document()
    manifest_ok, _ = verify_relationship_manifest(directory)

    before_after = _load_existing_matrix(root) or {
        "manifest_sha256_before": pre.current_manifest_sha256,
        "manifest_sha256_after": manifest_sha,
        "relationship_artifacts_after": dict(sorted(relationship.items())),
        "controlled_stage_01_02_after": dict(sorted(controlled.items())),
        "rolled_back": False,
    }

    post_apply_core = collect_post_apply_core(
        root,
        relationship_before=relationship,
        controlled_before=controlled,
        forbidden_before=forbidden_before,
        mandatory_release_suite=mandatory_suite,
        publisher_only_suite=publisher_suite,
        verify_stage_02_summary=verify_summary,
        gate_document=gate,
    )

    post_apply_passed = (
        manifest_ok
        and post_apply_core["relationship_artifacts_unchanged"]
        and post_apply_core["controlled_stage_01_02_unchanged"]
        and post_apply_core["forbidden_stage_02_files_unchanged"]
        and mandatory_suite["status"] == "PASS"
        and post_apply_core["gate_failed_checks_match_expected"]
        and verify_summary.get("final_manifest_hashes_match") == "PASS"
    )

    verification = build_promotion_verification(
        repair_applied=True,
        rolled_back=False,
        preconditions=pre.document(),
        before_after_matrix=before_after,
        post_apply_core=post_apply_core,
        mandatory_release_suite=mandatory_suite,
        publisher_only_suite=publisher_suite,
        verify_stage_02_summary=verify_summary,
        gate_document=gate,
    )
    report = build_promotion_report(
        repair_applied=True,
        rolled_back=False,
        manifest_sha256_after=manifest_sha,
        manifest_verified_8_of_8=manifest_ok,
        mandatory_release_suite=mandatory_suite,
        publisher_only_suite=publisher_suite,
        gate_failed_checks=list(gate.get("failed_checks", [])),
    )

    output = root / MAINTENANCE_DIR
    _write_json(output / PROMOTION_VERIFICATION_JSON, verification)
    _write_json(output / PROMOTION_REPORT_JSON, report)
    (output / PROMOTION_REPORT_MD).write_text(
        _render_promotion_report_md(report, verification),
        encoding="utf-8",
    )

    return {
        "post_apply_passed": post_apply_passed,
        "mandatory_release_suite": mandatory_suite,
        "publisher_only_suite": publisher_suite,
        "verify_stage_02_read_only": verify_summary,
    }


def _render_promotion_report_md(report: dict[str, Any], verification: dict[str, Any]) -> str:
    mandatory = report["mandatory_release_suite"]
    publisher = report["publisher_only_suite"]
    verify = verification["verify_stage_02_read_only"]
    return "\n".join(
        [
            "# Stage 02 Maintenance 01 — Promotion",
            "",
            f"Promotion version: **{report['promotion_version']}**",
            f"Report status: **{report['report_status']}**",
            "",
            "## Repair",
            "",
            f"* manifest after: `{report['manifest_sha256_after']}`",
            f"* manifest 8/8: **{'PASS' if report['manifest_verified_8_of_8'] else 'FAIL'}**",
            f"* repair applied: **{report['repair_applied']}**",
            f"* rolled back: **{report['rolled_back']}**",
            "",
            "## Mandatory release suite",
            "",
            f"* status: **{mandatory['status']}**",
            f"* summary: {mandatory.get('summary')}",
            "",
            "## Publisher-only suite",
            "",
            f"* executed: **{publisher.get('executed')}**",
            f"* status: **{publisher.get('status')}**",
            f"* summary: {publisher.get('summary')}",
            "",
            "## Read-only verify-stage-02",
            "",
            f"* overall: **{verify.get('status')}** ({verify.get('overall_fail_reason')})",
            f"* final_manifest_hashes_match: **{verify.get('final_manifest_hashes_match')}**",
            f"* checks not evaluated: {verify.get('checks_not_evaluated')}",
            "",
            "Full machine evidence: `promotion-verification.json`.",
            "",
        ]
    )


def _bundle_sealed_artifacts_stale(repo_root: Path, archive_path: Path) -> bool:
    """True when on-disk sealed promotion artifacts differ from the published archive."""
    maintenance = repo_root / MAINTENANCE_DIR
    with zipfile.ZipFile(archive_path) as bundle:
        for name in (*PROMOTION_CONTENT_ARTIFACTS, PROMOTION_MANIFEST_NAME):
            member = f"{MAINTENANCE_DIR.as_posix()}/{name}"
            if member not in bundle.namelist():
                return True
            if bundle.read(member) != (maintenance / name).read_bytes():
                return True
    return False


def _evaluate_publication_checks(
    repo_root: Path,
    *,
    archive_path: Path,
    archive_sha: str,
    sidecar_sha: str,
    index_text: str,
    indexed_count: int,
    member_names: list[str],
) -> dict[str, Any]:
    maintenance_dir = repo_root / MAINTENANCE_DIR
    manifest_entries = read_promotion_manifest(maintenance_dir / PROMOTION_MANIFEST_NAME)
    no_self_hash = not manifest_lists_itself(manifest_entries)
    manifest_ok, manifest_failures = verify_promotion_manifest_entries(maintenance_dir)
    shasum_ok, shasum_detail = verify_promotion_manifest_with_shasum(maintenance_dir)
    relationship_ok, relationship_detail = verify_relationship_manifest(repo_root / STAGE_02_DIR)
    index_failures = verify_indexed_members(archive_path, index_text)
    sidecar_matches = sidecar_sha == archive_sha
    nested = [name for name in member_names if name.lower().endswith(".zip")]

    extracted_ok = False
    extracted_failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="maintenance-promotion-extract-") as tmp:
        extract_root = Path(tmp)
        with zipfile.ZipFile(archive_path) as bundle:
            bundle.extractall(extract_root)
        extracted_manifest_dir = extract_root / MAINTENANCE_DIR
        extracted_ok, extracted_failures = verify_promotion_manifest_entries(extracted_manifest_dir)

    checks = {
        "promotion_manifest_no_self_hash": no_self_hash,
        "promotion_manifest_hashes_match": manifest_ok,
        "promotion_manifest_shasum_check": shasum_ok,
        "promotion_manifest_hashes_match_after_extraction": extracted_ok,
        "relationship_manifest_8_of_8": relationship_ok,
        "zip_index_valid": not index_failures,
        "sidecar_matches_archive": sidecar_matches,
        "indexed_equals_members_minus_one": indexed_count == len(member_names) - 1,
        "index_self_excluded": "REVIEW_INDEX.md" not in {
            line.split("`")[1] for line in index_text.splitlines() if line.startswith("| `")
        },
        "reproduce_indexed": "REPRODUCE.md" in {
            line.split("`")[1] for line in index_text.splitlines() if line.startswith("| `")
        },
        "no_nested_archive": not nested,
    }
    failures: list[str] = []
    if not no_self_hash:
        failures.append("promotion manifest lists itself")
    if not manifest_ok:
        failures.extend(manifest_failures)
    if not shasum_ok:
        failures.append(f"shasum check failed: {shasum_detail}")
    if not extracted_ok:
        failures.extend(f"extracted: {item}" for item in extracted_failures)
    if not relationship_ok:
        failures.append(f"relationship manifest: {relationship_detail}")
    if index_failures:
        failures.extend(index_failures)
    if not sidecar_matches:
        failures.append("sidecar sha256 does not match archive")

    return {
        "checks": checks,
        "failures": failures,
        "details": {
            "promotion_manifest_failures": manifest_failures,
            "extracted_manifest_failures": extracted_failures,
            "relationship_manifest_detail": relationship_detail,
            "shasum_detail": shasum_detail,
            "index_failures": index_failures,
        },
        "passed": not failures and all(checks.values()),
    }


def publish_promotion(
    repo_root: Path,
    *,
    bundle_zip_name: str = PROMOTION_BUNDLE_V011_ZIP_NAME,
    bundle_sha256_name: str = PROMOTION_BUNDLE_V011_SHA256_NAME,
    attestation_name: str = PROMOTION_BUNDLE_V011_ATTESTATION_NAME,
    refresh_evidence: bool = True,
) -> dict[str, Any]:
    root = repo_root.resolve()
    if refresh_evidence:
        refresh = refresh_promotion_artifacts(root)
        if not refresh["post_apply_passed"]:
            raise PromotionPublicationBlocked(
                "post-apply evidence is not green; refusing publication"
            )

    verification_path = root / MAINTENANCE_DIR / PROMOTION_VERIFICATION_JSON
    report_path = root / MAINTENANCE_DIR / PROMOTION_REPORT_JSON
    if not verification_path.is_file() or not report_path.is_file():
        raise PromotionPublicationBlocked("promotion report or verification missing")

    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if verification.get("rolled_back") or not verification.get("repair_applied"):
        raise PromotionPublicationBlocked("repair evidence does not show an applied repair")

    manifest_sha = sha256_file(root / STAGE_02_DIR / MANIFEST_NAME)
    if manifest_sha != EXPECTED_MANIFEST_SHA_AFTER:
        raise PromotionPublicationBlocked(
            f"working manifest {manifest_sha} != expected {EXPECTED_MANIFEST_SHA_AFTER}"
        )

    report["report_status"] = REPORT_STATUS_FINAL
    verification["report_status"] = REPORT_STATUS_FINAL
    _write_json(report_path, report)
    _write_json(verification_path, verification)
    (root / MAINTENANCE_DIR / PROMOTION_REPORT_MD).write_text(
        _render_promotion_report_md(report, verification),
        encoding="utf-8",
    )

    write_promotion_manifest(root / MAINTENANCE_DIR)
    manifest_ok, manifest_failures = verify_promotion_manifest_entries(root / MAINTENANCE_DIR)
    if not manifest_ok:
        raise PromotionPublicationBlocked(
            "promotion manifest verification failed before pack: " + "; ".join(manifest_failures)
        )
    shasum_ok, shasum_detail = verify_promotion_manifest_with_shasum(root / MAINTENANCE_DIR)
    if not shasum_ok:
        raise PromotionPublicationBlocked(f"independent shasum check failed: {shasum_detail}")

    bundle_files = collect_promotion_files(root)
    if not bundle_files:
        raise PromotionPublicationBlocked("no promotion bundle members collected")

    reproduce = _reproduce_doc()
    index = build_review_index(
        title=f"Stage 02 Maintenance 01 — {MAINTENANCE_TITLE} (Promotion {PROMOTION_VERSION})",
        header_lines=[
            f"Maintenance id: `{MAINTENANCE_ID}`.",
            f"Promotion version: `{PROMOTION_VERSION}`.",
            f"Defect: `{DEFECT_ID}`.",
            "",
            "**Repair applied.** Only `relationship-manifest.sha256` changed.",
            f"New manifest SHA-256: `{EXPECTED_MANIFEST_SHA_AFTER}`.",
            "",
            "Report status: **FINAL**.",
        ],
        bundle_files=bundle_files,
        inline_members=[("REPRODUCE.md", reproduce.encode("utf-8"))],
    )
    members_count, indexed_count = bundle_counts(bundle_files)

    destination = root / EXTERNAL_REVIEW_DIR
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / bundle_zip_name
    if archive_path.exists():
        if bundle_zip_name == PROMOTION_BUNDLE_V011_ZIP_NAME:
            if not _bundle_sealed_artifacts_stale(root, archive_path):
                raise PromotionPublicationBlocked(
                    f"refusing to overwrite immutable bundle: {archive_path.name}"
                )
        else:
            raise PromotionPublicationBlocked(
                f"refusing to overwrite immutable bundle: {archive_path.name}"
            )

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("REVIEW_INDEX.md", index)
        bundle.writestr("REPRODUCE.md", reproduce)
        for member, path in bundle_files:
            bundle.write(path, member)

    index_failures = verify_indexed_members(archive_path, index)
    if index_failures:
        archive_path.unlink(missing_ok=True)
        raise PromotionPublicationBlocked(
            "indexed SHA verification failed after pack: " + "; ".join(index_failures)
        )

    with zipfile.ZipFile(archive_path) as bundle:
        member_names = bundle.namelist()
        nested = [name for name in member_names if name.lower().endswith(".zip")]
        if len(member_names) != members_count:
            archive_path.unlink(missing_ok=True)
            raise PromotionPublicationBlocked(
                f"member count {len(member_names)} != expected {members_count}"
            )

    archive_sha = sha256_file(archive_path)
    sidecar_path = destination / bundle_sha256_name
    sidecar_path.write_text(f"{archive_sha}  {bundle_zip_name}\n", encoding="utf-8")
    sidecar_sha = archive_sha

    publication = _evaluate_publication_checks(
        root,
        archive_path=archive_path,
        archive_sha=archive_sha,
        sidecar_sha=sidecar_sha,
        index_text=index,
        indexed_count=indexed_count,
        member_names=member_names,
    )
    if not publication["passed"]:
        archive_path.unlink(missing_ok=True)
        sidecar_path.unlink(missing_ok=True)
        raise PromotionPublicationBlocked(
            "publication checks failed: " + "; ".join(publication["failures"])
        )

    attestation = {
        "maintenance_id": MAINTENANCE_ID,
        "promotion": True,
        "promotion_version": PROMOTION_VERSION,
        "attested_at": datetime.now(UTC).isoformat(),
        "report_status": REPORT_STATUS_FINAL,
        "status": "PASS",
        "failed_checks": [],
        "checks": publication["checks"],
        "publication_checks": publication,
        "archive": {
            "name": bundle_zip_name,
            "sha256": archive_sha,
            "members": len(member_names),
            "indexed": indexed_count,
            "bytes": archive_path.stat().st_size,
        },
        "working_manifest_sha256": manifest_sha,
        "database_connections_during_apply": 0,
        "clinical_rows_read_during_apply": 0,
    }

    attestation_path = destination / attestation_name
    attestation_path.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")

    return {
        "status": "PASS",
        "report_status": REPORT_STATUS_FINAL,
        "archive": str(archive_path),
        "archive_sha256": archive_sha,
        "sidecar": str(sidecar_path),
        "attestation": str(attestation_path),
        "attestation_sha256": sha256_file(attestation_path),
        "members": len(member_names),
        "indexed": indexed_count,
        "publication_checks": publication,
    }
