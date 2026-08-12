"""Publish Stage 03 Implementation Changeset 01 in a strict, single-pass order.

1. re-verify the frozen baseline (read-only, no repair);
2. bring report, verification and manifest into a consistent state;
3. snapshot the nine controlled Stage 01/02 hashes;
4. run the gate suite, the clean review-bundle suite, the full repository suite and the
   integration/migration suite, recording each literal command and its counts;
5. snapshot the controlled hashes again and compare without repairing anything;
6. re-run every gate without publishing;
7. write ``release-verification.json``;
8. refuse to continue unless every mandatory entry passed and prior stages are unchanged;
9. publish the review bundle once, then write the SHA-256 sidecar.

Nothing is rebuilt after step 9. The changeset report stays DRAFT.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage03.changeset_01_attestation import (
    attest_published_bundle,
    write_attestation,
)
from human_simulator.stage03.changeset_01_baseline import evaluate_baseline
from human_simulator.stage03.changeset_01_constants import (
    CHANGESET_DIR,
    CHANGESET_ID,
    CHANGESET_VERIFICATION_NAME,
    CHANGESET_VERSION,
    RELEASE_VERIFICATION_NAME,
)
from human_simulator.stage03.changeset_01_review_bundle import build_changeset_01_review_bundle
from human_simulator.stage03.frozen_evidence import (
    evaluate_frozen_evidence,
    frozen_evidence_fingerprint,
)
from human_simulator.stage03.implementation_constants import (
    STAGE03_DESIGN_VERSION,
    STAGE03_IMPLEMENTATION_PLAN_VERSION,
)
from human_simulator.stage03.pre_live_load_gate import evaluate_pre_live_load_gate
from human_simulator.stage03.prior_stage_integrity import snapshot_prior_stage_hashes
from human_simulator.stage03.publication_lock import (
    LockInfo,
    lock_path,
    lock_verification,
    publication_lock,
)
from human_simulator.stage03.release_verification import (
    ReleaseEvidence,
    build_release_document,
    changeset_01_clean_bundle_suite_command,
    changeset_01_gate_suite_command,
    changeset_01_migration_suite_command,
    full_repository_suite_command,
    gate_evidence,
    run_suite,
)


class ChangesetPublicationBlocked(RuntimeError):
    """Raised when a mandatory check fails; the review bundle must not be published."""


def publish_changeset_01(repo_root: Path, *, run_migration_suite: bool = True) -> dict[str, Any]:
    """Publish once, in order. ``run_migration_suite=False`` can only produce a FAIL.

    Skipping the integration suite is deliberately not an escape hatch: the suite is in
    ``MANDATORY_SUITE_NAMES``, so its absence is recorded as a mandatory failure and the
    bundle is not written.

    The whole pipeline runs under an exclusive inter-process lock. A second publisher fails
    immediately rather than interleaving writes into the same snapshot and archive.
    """
    root = repo_root.resolve()
    with publication_lock(root, operation="changeset_01_publish") as lock:
        result = _publish_locked(root, lock=lock, run_migration_suite=run_migration_suite)
    result["publication_lock_released"] = not lock_path(root).exists()
    return result


def _publish_locked(root: Path, *, lock: LockInfo, run_migration_suite: bool) -> dict[str, Any]:
    from human_simulator.stage03.verify_changeset_01 import verify_changeset_01
    from human_simulator.stage03.verify_implementation_plan import verify_implementation_plan
    from human_simulator.stage03.verify_stage_03_design import verify_stage_03_design

    changeset_dir = root / CHANGESET_DIR

    baseline = evaluate_baseline(root)
    if baseline["status"] != "PASS":
        raise ChangesetPublicationBlocked(
            f"Frozen baseline mismatch; refusing to change anything: {baseline['failures']}"
        )

    # Release evidence must describe only this run; a leftover document would otherwise be
    # observed by the gates that run inside the suites below.
    (changeset_dir / RELEASE_VERIFICATION_NAME).unlink(missing_ok=True)

    sync = verify_changeset_01(root, publish_artifacts=True)
    if sync["overall_status"] != "PASS":
        raise ChangesetPublicationBlocked(f"Pre-evidence publication sync failed: {sync['failures']}")

    hashes_before = snapshot_prior_stage_hashes(root)
    frozen_before = frozen_evidence_fingerprint(root)

    # Every suite is bracketed by a frozen-evidence comparison, so a suite that writes into a
    # frozen path is attributed to the suite that did it rather than discovered afterwards.
    suite_plan: list[tuple[str, list[str]]] = [
        ("changeset_01_gate_suite", changeset_01_gate_suite_command()),
        ("clean_review_bundle_suite", changeset_01_clean_bundle_suite_command()),
        ("full_repository_suite", full_repository_suite_command()),
    ]
    if run_migration_suite:
        suite_plan.append(
            ("integration_migration_suite", changeset_01_migration_suite_command())
        )

    evidence = ReleaseEvidence()
    frozen_drift: list[dict[str, Any]] = []
    for name, command in suite_plan:
        before = frozen_evidence_fingerprint(root)
        evidence.suites.append(run_suite(root, name=name, command=command, mandatory=True))
        after = frozen_evidence_fingerprint(root)
        if before != after:
            frozen_drift.append(
                {
                    "suite": name,
                    "changed": sorted(
                        path for path in set(before) | set(after)
                        if before.get(path) != after.get(path)
                    ),
                }
            )

    hashes_after = snapshot_prior_stage_hashes(root)
    frozen_after = frozen_evidence_fingerprint(root)
    prior_stage_unchanged = hashes_before == hashes_after
    frozen_evidence = evaluate_frozen_evidence(root)

    design = verify_stage_03_design(root, run_pytest=False, publish_artifacts=False)
    plan = verify_implementation_plan(root, run_pytest=False, publish_artifacts=False)
    changeset = verify_changeset_01(root, publish_artifacts=False)
    evidence.gates.append(gate_evidence("stage_03_design_gate", design))
    evidence.gates.append(gate_evidence("stage_03_implementation_plan_gate", plan))
    evidence.gates.append(gate_evidence("changeset_01_gate", _as_gate_result(changeset)))

    document = build_release_document(
        evidence=evidence,
        gate_pytest=_gate_pytest(evidence),
        prior_stage_hashes_before=hashes_before,
        prior_stage_hashes_after=hashes_after,
        prior_stage_unchanged=prior_stage_unchanged,
        generated_at=datetime.now(tz=UTC).isoformat(),
        design_version=STAGE03_DESIGN_VERSION,
        plan_version=STAGE03_IMPLEMENTATION_PLAN_VERSION,
    )
    document["gate_pytest"]["name"] = "gate_pytest_changeset_01_verifier"

    all_frozen_unchanged = (
        frozen_before == frozen_after
        and not frozen_drift
        and frozen_evidence["all_unchanged"]
    )
    document["frozen_evidence"] = {
        "frozen_design_report_match": frozen_evidence["frozen_design_report_match"],
        "frozen_design_verification_match": frozen_evidence["frozen_design_verification_match"],
        "all_frozen_evidence_unchanged": all_frozen_unchanged,
        "publication_lock_verified": lock_verification(lock)["held_during_publication"],
        "automatic_restore_performed": False,
        "repairs_performed": 0,
        "file_count": frozen_evidence["file_count"],
        "hashes_before": frozen_before,
        "hashes_after": frozen_after,
        "suites_that_changed_frozen_evidence": frozen_drift,
        "lock": lock_verification(lock),
    }
    document["frozen_design_report_match"] = frozen_evidence["frozen_design_report_match"]
    document["frozen_design_verification_match"] = frozen_evidence[
        "frozen_design_verification_match"
    ]
    document["all_frozen_evidence_unchanged"] = all_frozen_unchanged
    document["publication_lock_verified"] = True
    document["automatic_restore_performed"] = False

    if not all_frozen_unchanged:
        raise ChangesetPublicationBlocked(
            "A suite modified frozen evidence; refusing to publish and refusing to restore it: "
            f"{frozen_drift or frozen_evidence['changed']}"
        )

    # The Stage 02 pre-live-load gate is recorded outside ``gates`` because its FAIL is the
    # expected, required state until a separate maintenance changeset repairs the manifest.
    # It must not turn the release status to FAIL, and it must stay visible.
    gate_document = evaluate_pre_live_load_gate(root).document()
    document["changeset_id"] = CHANGESET_ID
    document["changeset_version"] = CHANGESET_VERSION
    document["stage02_pre_live_load_gate"] = {
        "gate_id": gate_document["gate_id"],
        "status": gate_document["status"],
        "expected_status": "FAIL",
        "expected_status_matches": gate_document["status"] == "FAIL",
        "blocked_live_operations": gate_document["blocks_live_operations"],
        "does_not_block": gate_document["does_not_block"],
        "known_open_defect": gate_document["known_open_defect"],
        "repairs_performed": gate_document["repairs_performed"],
        "stage_02_modified": gate_document["stage_02_modified"],
        "failed_checks": gate_document["failed_checks"],
    }
    if gate_document["status"] != "FAIL":
        raise ChangesetPublicationBlocked(
            "Stage 02 pre-live-load gate no longer reports the open drift defect; "
            "publication requires the defect to stay explicit"
        )

    document["report_status"] = "DRAFT"
    release_path = changeset_dir / RELEASE_VERIFICATION_NAME
    release_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    if document["overall_release_status"] != "PASS":
        raise ChangesetPublicationBlocked(
            "Refusing to publish review bundle; mandatory failures: "
            f"{document['mandatory_failures']}, prior_stage_unchanged={prior_stage_unchanged}"
        )

    publish = verify_changeset_01(root, publish_artifacts=True)
    if publish["overall_status"] != "PASS":
        raise ChangesetPublicationBlocked(f"Publication gate failed: {publish['failures']}")

    bundle = build_changeset_01_review_bundle(
        root, generated_at=datetime.now(tz=UTC).isoformat()
    )

    # The archive and its sidecar are final from here on. The attestation only reads them.
    attestation = attest_published_bundle(root, publisher_gate_document=gate_document)
    attestation_path = write_attestation(root, attestation)

    verification = json.loads(
        (changeset_dir / CHANGESET_VERIFICATION_NAME).read_text(encoding="utf-8")
    )
    return {
        "attestation": str(attestation_path),
        "attestation_status": attestation["status"],
        "clean_extraction_failed_checks": attestation["stage02_pre_live_load_gate"][
            "clean_extraction_failed_checks"
        ],
        "release_verification": str(release_path),
        "overall_release_status": document["overall_release_status"],
        "design_gate": design["status"],
        "implementation_plan_gate": plan["status"],
        "changeset_01_gate": publish["overall_status"],
        "stage02_pre_live_load_gate": document["stage02_pre_live_load_gate"]["status"],
        "report_status": verification["report_status"],
        "review_bundle": str(bundle.zip_path),
        "review_bundle_sha256": bundle.zip_sha256,
        "review_bundle_member_count": bundle.member_count,
        "review_bundle_indexed_member_count": bundle.indexed_member_count,
        "prior_stage_unchanged": prior_stage_unchanged,
        "frozen_design_report_match": document["frozen_design_report_match"],
        "frozen_design_verification_match": document["frozen_design_verification_match"],
        "all_frozen_evidence_unchanged": document["all_frozen_evidence_unchanged"],
        "publication_lock_verified": document["publication_lock_verified"],
        "automatic_restore_performed": False,
        "suites": [asdict(suite) for suite in evidence.suites],
    }


def _as_gate_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result["overall_status"],
        "checks_total": result["checks_total"],
        "checks_passed": result["checks_passed"],
        "checks_failed": result["checks_failed"],
        "verified_at": result["verified_at"],
    }


def _gate_pytest(evidence: ReleaseEvidence) -> dict[str, Any]:
    suite = next(
        (item for item in evidence.suites if item.name == "changeset_01_gate_suite"), None
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
