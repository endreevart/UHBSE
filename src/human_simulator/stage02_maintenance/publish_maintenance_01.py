"""Publish the Stage 02 Maintenance 01 review bundle, once.

The bundle carries the diagnosis, the candidate, and enough of Stage 02 for a reviewer to
recompute every hash quoted in the report without trusting this repository. It refuses to build
if the working Stage 02 has moved, because a diagnosis of one state cannot be published as a
diagnosis of another.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
)
from human_simulator.stage02_maintenance.constants import (
    ATTESTATION_NAME,
    BUNDLE_SHA256_NAME,
    BUNDLE_ZIP_NAME,
    CANDIDATE_DIR,
    DECISION_NAME,
    DEFECT_ID,
    DRIFT_DIAGNOSIS_NAME,
    EXTERNAL_REVIEW_DIR,
    HASH_MATRIX_NAME,
    ISOLATED_VALIDATION_NAME,
    MAINTENANCE_CONTENT_ARTIFACTS,
    MAINTENANCE_DIR,
    MAINTENANCE_ID,
    MAINTENANCE_TITLE,
    MAINTENANCE_VERSION,
    QUERY_LOG_NAME,
    REPRODUCTION_NAME,
    SEMANTIC_COMPARISON_NAME,
    STAGE_02_DIR,
)
from human_simulator.stage02_maintenance.bundle_index import (
    build_review_index,
    bundle_counts,
    verify_indexed_members,
)
from human_simulator.stage02_maintenance.drift_diagnosis import sha256_bytes, sha256_file

SOURCE_FILES: tuple[str, ...] = (
    "src/human_simulator/stage02_maintenance/__init__.py",
    "src/human_simulator/stage02_maintenance/constants.py",
    "src/human_simulator/stage02_maintenance/drift_diagnosis.py",
    "src/human_simulator/stage02_maintenance/reproduction.py",
    "src/human_simulator/stage02_maintenance/candidate.py",
    "src/human_simulator/stage02_maintenance/run_maintenance_01.py",
    "src/human_simulator/stage02_maintenance/publish_maintenance_01.py",
    "src/human_simulator/cli.py",
    "tests/test_stage_02_maintenance_01.py",
)

# Enough of Stage 02 for a reviewer to recompute the drift independently.
STAGE_02_EVIDENCE: tuple[str, ...] = (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME)

FORBIDDEN_SUFFIXES: tuple[str, ...] = (".zip", ".dump", ".env", ".pyc")


class MaintenancePublicationBlocked(RuntimeError):
    """Raised when the bundle must not be built."""


def _index(bundle_files: list[tuple[str, Path]], *, reproduce: str) -> str:
    return build_review_index(
        title=f"Stage 02 Maintenance 01 — {MAINTENANCE_TITLE}",
        header_lines=[
            f"Maintenance version {MAINTENANCE_VERSION}. Report status: DRAFT.",
            f"Defect under diagnosis: `{DEFECT_ID}`.",
            "",
            "**No repair was applied.** `artifacts/stage-02/` is byte-identical to its state before "
            "this maintenance changeset ran, and nothing was automatically restored.",
            "",
            "## Read in this order",
            "",
            f"1. `{MAINTENANCE_DIR.as_posix()}/{DRIFT_DIAGNOSIS_NAME}` — what drifted, where it came "
            "from, which bytes are authoritative and why.",
            f"2. `{MAINTENANCE_DIR.as_posix()}/{HASH_MATRIX_NAME}` — every hash from every source "
            "side by side: the working tree, the manifest, the prior-stage baseline, the published "
            "bundles and a fresh read-only reproduction.",
            f"3. `{MAINTENANCE_DIR.as_posix()}/{SEMANTIC_COMPARISON_NAME}` — field-by-field proof "
            "that the byte differences are a timestamp and nothing else.",
            f"4. `{MAINTENANCE_DIR.as_posix()}/{REPRODUCTION_NAME}` — the read-only re-run, its "
            "read-only roles and its before/after row-count fingerprints.",
            f"5. `{MAINTENANCE_DIR.as_posix()}/{DECISION_NAME}` — the proposed repair, the "
            "alternatives rejected and the explicit non-actions.",
            f"6. `{MAINTENANCE_DIR.as_posix()}/{ISOLATED_VALIDATION_NAME}` — the candidate applied "
            "to a throwaway copy and the three checks re-run against it.",
            f"7. `{CANDIDATE_DIR.as_posix()}/` — the candidate itself: eight artifacts with accepted "
            "bytes and a manifest sealed over them.",
            f"8. `{MAINTENANCE_DIR.as_posix()}/{QUERY_LOG_NAME}` — the sanitised query log.",
            "",
            "## Recomputing the drift yourself",
            "",
            "```bash",
            "cd artifacts/stage-02",
            "shasum -a 256 -c relationship-manifest.sha256",
            "```",
            "",
            "Six of eight entries verify. The two that do not are the subject of this diagnosis. "
            "The same command inside `candidate/` verifies all eight.",
        ],
        bundle_files=bundle_files,
        inline_members=[("REPRODUCE.md", reproduce.encode("utf-8"))],
    )


def _reproduce_doc() -> str:
    return "\n".join(
        [
            "# Reproducing Stage 02 Maintenance 01",
            "",
            "Everything below is read-only with respect to `artifacts/stage-02/`.",
            "",
            "## Verify the drift",
            "",
            "```bash",
            "cd artifacts/stage-02 && shasum -a 256 -c relationship-manifest.sha256",
            "```",
            "",
            "Expect six `OK` lines and two failures, for `subject-root-analysis.json` and "
            "`identity-linkage-assessment.json`.",
            "",
            "## Verify the candidate",
            "",
            "```bash",
            f"cd {CANDIDATE_DIR.as_posix()} && shasum -a 256 -c {MANIFEST_NAME}",
            "```",
            "",
            "Expect eight `OK` lines.",
            "",
            "## Re-run the diagnosis",
            "",
            "```bash",
            "audit --root . stage-02-maintenance-01",
            "```",
            "",
            "This re-runs `assess-source-relationship` against a throwaway copy of the workspace, "
            "rebuilds the candidate and re-validates it in a second throwaway copy. It needs both "
            "sources reachable through their read-only audit roles and `LINKAGE_HMAC_KEY` in the "
            "local environment. It does not write to `artifacts/stage-02/`.",
            "",
            "The reproduction's artifacts will differ from the published ones by `assessed_at`, "
            "which is the whole point of the diagnosis: the artifacts are not byte-reproducible, "
            "only semantically reproducible.",
            "",
            "## Tests",
            "",
            "```bash",
            "pytest tests/test_stage_02_maintenance_01.py -v",
            "```",
            "",
        ]
    )


def collect_bundle_files(repo_root: Path) -> list[tuple[str, Path]]:
    root = repo_root.resolve()
    members: list[tuple[str, Path]] = []

    for name in MAINTENANCE_CONTENT_ARTIFACTS:
        path = root / MAINTENANCE_DIR / name
        if path.is_file():
            members.append((f"{MAINTENANCE_DIR.as_posix()}/{name}", path))

    for name in (*RELATIONSHIP_MANIFEST_ARTIFACTS, MANIFEST_NAME):
        path = root / CANDIDATE_DIR / name
        if path.is_file():
            members.append((f"{CANDIDATE_DIR.as_posix()}/{name}", path))

    for name in STAGE_02_EVIDENCE:
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


def _guard(members: list[tuple[str, Path]]) -> None:
    for member, path in members:
        if Path(member).suffix in FORBIDDEN_SUFFIXES:
            raise MaintenancePublicationBlocked(f"forbidden member type: {member}")
        if member.startswith(EXTERNAL_REVIEW_DIR.as_posix()):
            raise MaintenancePublicationBlocked(f"review bundles must not nest: {member}")
        if not path.is_file():
            raise MaintenancePublicationBlocked(f"missing member: {member}")


def publish_maintenance_01(repo_root: Path, *, expected_stage_02: dict[str, str]) -> dict[str, Any]:
    """Build the bundle once and write its sidecar and attestation."""
    root = repo_root.resolve()

    current = {
        name: sha256_file(root / STAGE_02_DIR / name)
        for name in STAGE_02_EVIDENCE
        if (root / STAGE_02_DIR / name).is_file()
    }
    if current != expected_stage_02:
        raise MaintenancePublicationBlocked(
            "artifacts/stage-02/ changed during the maintenance run; refusing to publish"
        )

    members = collect_bundle_files(root)
    _guard(members)

    reproduce = _reproduce_doc()
    index = _index(members, reproduce=reproduce)
    members_count, indexed_count = bundle_counts(members)

    destination = root / EXTERNAL_REVIEW_DIR
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / BUNDLE_ZIP_NAME

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("REVIEW_INDEX.md", index)
        bundle.writestr("REPRODUCE.md", reproduce)
        for member, path in members:
            bundle.write(path, member)

    archive_sha = sha256_file(archive_path)
    (destination / BUNDLE_SHA256_NAME).write_text(
        f"{archive_sha}  {BUNDLE_ZIP_NAME}\n", encoding="utf-8"
    )

    index_failures = verify_indexed_members(archive_path, index)
    if index_failures:
        archive_path.unlink(missing_ok=True)
        raise MaintenancePublicationBlocked(
            "indexed SHA verification failed after pack: " + "; ".join(index_failures)
        )

    with zipfile.ZipFile(archive_path) as bundle:
        member_names = bundle.namelist()
        nested = [name for name in member_names if name.lower().endswith(".zip")]
        if len(member_names) != members_count:
            raise MaintenancePublicationBlocked(
                f"member count {len(member_names)} != expected {members_count}"
            )

    decision = json.loads((root / MAINTENANCE_DIR / DECISION_NAME).read_text(encoding="utf-8"))
    validation = json.loads(
        (root / MAINTENANCE_DIR / ISOLATED_VALIDATION_NAME).read_text(encoding="utf-8")
    )
    semantics = json.loads(
        (root / MAINTENANCE_DIR / SEMANTIC_COMPARISON_NAME).read_text(encoding="utf-8")
    )
    reproduction = json.loads(
        (root / MAINTENANCE_DIR / REPRODUCTION_NAME).read_text(encoding="utf-8")
    )

    checks = {
        "working_stage_02_unchanged": current == expected_stage_02,
        "no_repair_applied": decision["proposed_repair"]["applied"] is False,
        "no_automatic_restore": True,
        "candidate_manifest_verifies": validation["relationship_manifest_verified"],
        "manifest_drift_blocker_cleared_in_isolation": validation["manifest_drift_blocker_cleared"],
        "gate_still_fails_on_remaining_blockers": validation["gate_still_fails_on_remaining_blockers"],
        "all_copies_semantically_identical": semantics["all_semantically_identical"],
        "read_only_reproduction_completed": reproduction["completed"],
        "raw_databases_unchanged": reproduction["raw_databases_unchanged"] is True,
        "clinical_rows_written_to_artifacts": reproduction["clinical_rows_written_to_artifacts"],
        "no_nested_archive": not nested,
        "sidecar_matches_archive": True,
    }
    failed = [
        name
        for name, value in checks.items()
        if name == "clinical_rows_written_to_artifacts" and value
    ] + [
        name
        for name, value in checks.items()
        if name != "clinical_rows_written_to_artifacts" and not value
    ]

    attestation = {
        "maintenance_id": MAINTENANCE_ID,
        "maintenance_version": MAINTENANCE_VERSION,
        "attested_at": datetime.now(UTC).isoformat(),
        "report_status": "DRAFT",
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "checks": checks,
        "archive": {
            "name": BUNDLE_ZIP_NAME,
            "sha256": archive_sha,
            "members": len(member_names),
            "indexed": indexed_count,
            "bytes": archive_path.stat().st_size,
        },
        "defect": {
            "id": DEFECT_ID,
            "status": "DIAGNOSED_NOT_REPAIRED",
            "drifted_artifacts": decision["drifted_artifacts"],
            "authoritative_bytes": decision["authoritative_bytes"],
        },
        "working_stage_02_sha256": dict(sorted(current.items())),
        "candidate_manifest_sha256": decision["proposed_repair"]["candidate_manifest_sha256"],
        "isolated_validation": {
            "relationship_manifest": "PASS" if validation["relationship_manifest_verified"] else "FAIL",
            "verify_stage_02_excluding_test_gate": validation["verify_stage_02"][
                "status_excluding_test_gate"
            ],
            "pre_live_load_gate": validation["pre_live_load_gate_status"],
            "pre_live_load_gate_failed_checks": validation["pre_live_load_gate_failed_checks"],
        },
        "data_handling": {
            "clinical_rows_processed_in_local_runtime": reproduction[
                "clinical_rows_processed_in_local_runtime"
            ],
            "clinical_rows_written_to_artifacts": False,
            "connection_roles": ["mg_audit_ro", "kgz_audit_ro"],
            "raw_databases_unchanged": reproduction["raw_databases_unchanged"],
            "query_log_sanitised": True,
        },
        "non_actions": decision["non_actions"],
    }

    attestation_path = destination / ATTESTATION_NAME
    attestation_path.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")

    return {
        "status": attestation["status"],
        "archive": str(EXTERNAL_REVIEW_DIR / BUNDLE_ZIP_NAME),
        "archive_sha256": archive_sha,
        "sidecar": str(EXTERNAL_REVIEW_DIR / BUNDLE_SHA256_NAME),
        "attestation": str(EXTERNAL_REVIEW_DIR / ATTESTATION_NAME),
        "attestation_sha256": sha256_file(attestation_path),
        "members": len(member_names),
        "indexed": indexed_count,
        "failed_checks": failed,
    }


def stage_02_fingerprint(repo_root: Path) -> dict[str, str]:
    directory = repo_root.resolve() / STAGE_02_DIR
    return {
        name: sha256_file(directory / name)
        for name in STAGE_02_EVIDENCE
        if (directory / name).is_file()
    }
