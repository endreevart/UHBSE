"""Publish the Stage 03 implementation planning release in a strict, single-pass order.

Order of operations:

1. snapshot prior-stage hashes (read-only);
2. run every mandatory suite plus the optional integration suite;
3. snapshot prior-stage hashes again and compare without repairing anything;
4. run both gates without publishing;
5. write ``release-verification.json``;
6. refuse to continue unless ``overall_release_status`` is ``PASS``;
7. publish report, verification and the review bundle ZIP once;
8. validate the ZIP, compute its SHA-256 and write the sidecar.

Nothing is rebuilt after step 8.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage03.implementation_constants import (
    STAGE03_DESIGN_VERSION,
    STAGE03_IMPLEMENTATION_PLAN_VERSION,
)
from human_simulator.stage03.prior_stage_integrity import snapshot_prior_stage_hashes
from human_simulator.stage03.release_verification import (
    RELEASE_VERIFICATION_NAME,
    ReleaseEvidence,
    build_release_document,
    clean_bundle_suite_command,
    full_repository_suite_command,
    gate_evidence,
    integration_suite_command,
    run_suite,
    write_release_verification,
)


class ReleaseBlocked(RuntimeError):
    """Raised when a mandatory check fails; the ZIP must not be published."""


def publish_release(repo_root: Path, *, run_integration_suite: bool = True) -> dict[str, Any]:
    from human_simulator.stage03.verify_implementation_plan import verify_implementation_plan
    from human_simulator.stage03.verify_stage_03_design import verify_stage_03_design

    root = repo_root.resolve()
    impl_dir = root / "artifacts" / "stage-03-implementation"

    # Release evidence must describe only this run. A leftover document from an earlier attempt
    # would otherwise be observed by the gates running inside the evidence suites below.
    (impl_dir / RELEASE_VERIFICATION_NAME).unlink(missing_ok=True)

    # Bring manifest, report and verification into a consistent state first. The evidence suites
    # below assert publication consistency, so they cannot be the step that establishes it.
    sync_result = verify_implementation_plan(root, run_pytest=True, publish_artifacts=True)
    if sync_result["status"] != "PASS":
        raise ReleaseBlocked(f"Pre-evidence publication sync failed: {sync_result.get('failures')}")

    hashes_before = snapshot_prior_stage_hashes(root)

    evidence = ReleaseEvidence()
    evidence.suites.append(
        run_suite(
            root,
            name="clean_review_bundle_suite",
            command=clean_bundle_suite_command(),
            mandatory=True,
        )
    )
    evidence.suites.append(
        run_suite(
            root,
            name="full_repository_suite",
            command=full_repository_suite_command(),
            mandatory=True,
        )
    )
    if run_integration_suite:
        evidence.suites.append(
            run_suite(
                root,
                name="integration_suite",
                command=integration_suite_command(),
                mandatory=False,
            )
        )

    hashes_after = snapshot_prior_stage_hashes(root)
    prior_stage_unchanged = hashes_before == hashes_after

    design_result = verify_stage_03_design(root, run_pytest=False, publish_artifacts=False)
    plan_result = verify_implementation_plan(root, run_pytest=False, publish_artifacts=False)
    evidence.gates.append(gate_evidence("stage_03_design_gate", design_result))
    evidence.gates.append(gate_evidence("stage_03_implementation_plan_gate", plan_result))

    gate_pytest = _gate_pytest_from_clean_suite(evidence)

    document = build_release_document(
        evidence=evidence,
        gate_pytest=gate_pytest,
        prior_stage_hashes_before=hashes_before,
        prior_stage_hashes_after=hashes_after,
        prior_stage_unchanged=prior_stage_unchanged,
        generated_at=datetime.now(tz=UTC).isoformat(),
        design_version=STAGE03_DESIGN_VERSION,
        plan_version=STAGE03_IMPLEMENTATION_PLAN_VERSION,
    )
    release_path = write_release_verification(impl_dir, document)

    if document["overall_release_status"] != "PASS":
        raise ReleaseBlocked(
            "Refusing to publish review bundle; mandatory failures: "
            f"{document['mandatory_failures']}, prior_stage_unchanged={prior_stage_unchanged}"
        )

    publish_result = verify_implementation_plan(root, run_pytest=True, publish_artifacts=True)
    if publish_result["status"] != "PASS":
        raise ReleaseBlocked(f"Publication gate failed: {publish_result.get('failures')}")

    verification = json.loads(
        (impl_dir / "implementation-plan-verification.json").read_text(encoding="utf-8")
    )
    return {
        "release_verification": str(release_path),
        "overall_release_status": document["overall_release_status"],
        "design_gate": design_result["status"],
        "implementation_plan_gate": publish_result["status"],
        "review_bundle_sha256": verification.get("review_bundle_sha256"),
        "review_bundle_member_count": verification.get("review_bundle_member_count"),
        "review_bundle_indexed_member_count": verification.get("review_bundle_indexed_member_count"),
        "prior_stage_unchanged": prior_stage_unchanged,
    }


def _gate_pytest_from_clean_suite(evidence: ReleaseEvidence) -> dict[str, Any]:
    suite = next(
        (item for item in evidence.suites if item.name == "clean_review_bundle_suite"),
        None,
    )
    if suite is None:
        return {"pytest_command": "", "pytest_exit_code": 1, "pytest_summary": "not run"}
    return {
        "pytest_command": suite.command,
        "pytest_exit_code": suite.exit_code,
        "pytest_collected": suite.collected,
        "pytest_selected": suite.selected,
        "pytest_deselected": suite.deselected,
        "pytest_passed": suite.passed,
        "pytest_failed": suite.failed,
        "pytest_skipped": suite.skipped,
        "pytest_duration_seconds": suite.duration_seconds,
        "pytest_summary": suite.summary,
    }
