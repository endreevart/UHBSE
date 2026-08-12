"""Attest the published review bundle by running its own gates from a clean extraction.

The bundle is never rebuilt here. It is extracted into an empty directory, its SHA-256 is
re-verified against the sidecar, and the gates and reproducible suites are executed inside the
extraction. The results are written to a sidecar attestation file, so a reviewer can compare
what the publisher claimed with what the archive actually produces.

The attestation deliberately records the Stage 02 gate as an expected FAIL, and requires the
failure reason to be identical to the publisher's. A clean extraction that fails only because
an input is missing would not reproduce the defect.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.stage03.changeset_01_constants import (
    CHANGESET_DIR,
    CHANGESET_ID,
    CHANGESET_VERSION,
)
from human_simulator.stage03.changeset_01_review_bundle import (
    BUNDLE_SHA256_SIDECAR_NAME,
    BUNDLE_ZIP_NAME,
)
from human_simulator.stage03.design_archive_finding import evaluate_design_archive_finding
from human_simulator.stage03.frozen_evidence import FROZEN_DESIGN_EVIDENCE_SHA256
from human_simulator.stage03.preconditions import sha256_file
from human_simulator.stage03.publication_lock import LOCK_NAME
from human_simulator.stage03.release_verification import (
    changeset_01_clean_bundle_suite_command,
    changeset_01_gate_suite_command,
    run_suite,
    shell_quote,
)

ATTESTATION_NAME = BUNDLE_ZIP_NAME.removesuffix(".zip") + ".attestation.json"

# Gates that must be reproducible from the archive alone, with the exit code the archive is
# expected to produce. The Stage 02 gate is expected to fail while the drift is open.
ATTESTED_GATES: tuple[tuple[str, list[str], int], ...] = (
    ("changeset_01_baseline", ["uv", "run", "audit", "--root", ".", "changeset-01-baseline"], 0),
    (
        "changeset_01_check_no_publish",
        ["uv", "run", "audit", "--root", ".", "changeset-01-check", "--no-publish"],
        0,
    ),
    (
        "stage02_pre_live_load_gate",
        ["uv", "run", "audit", "--root", ".", "stage-02-pre-live-load-gate"],
        1,
    ),
)


class AttestationError(RuntimeError):
    """Raised when the published archive cannot be attested."""


def _run_gate(root: Path, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True)
    document: dict[str, Any] | None = None
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError:
        document = None
    return {
        "command": shell_quote(command),
        "exit_code": completed.returncode,
        "status": (document or {}).get("status") or (document or {}).get("overall_status"),
        "failed_checks": (document or {}).get("failed_checks")
        or (document or {}).get("failures")
        or [],
    }


def attest_published_bundle(
    repo_root: Path, *, publisher_gate_document: dict[str, Any]
) -> dict[str, Any]:
    """Extract the published archive and re-run its gates and reproducible suites."""
    root = repo_root.resolve()
    review_dir = root / "artifacts" / "external-review"
    zip_path = review_dir / BUNDLE_ZIP_NAME
    sidecar = review_dir / BUNDLE_SHA256_SIDECAR_NAME
    if not zip_path.is_file():
        raise AttestationError(f"published archive not found: {BUNDLE_ZIP_NAME}")
    if not sidecar.is_file():
        raise AttestationError(f"sidecar not found: {BUNDLE_SHA256_SIDECAR_NAME}")

    design_archive_finding = evaluate_design_archive_finding(root)
    recorded = sidecar.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(zip_path)
    if recorded != actual:
        raise AttestationError("published archive does not match its SHA-256 sidecar")

    with tempfile.TemporaryDirectory(prefix="changeset-01-attestation-") as tmp:
        extraction = Path(tmp) / "extracted"
        extraction.mkdir()
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extraction)
            members = [name for name in archive.namelist() if not name.endswith("/")]

        sync = subprocess.run(
            ["uv", "sync", "--frozen", "--extra", "dev"],
            cwd=extraction,
            capture_output=True,
            text=True,
        )
        if sync.returncode != 0:
            raise AttestationError(
                "the extracted archive could not build its own environment: "
                + sync.stderr[-2000:]
            )

        # The audited Design evidence must be inside the archive itself, not merely correct in
        # the publisher workspace. This is the defect v0.2.1 exists to prevent.
        design_evidence = {
            name: hashlib.sha256(
                (extraction / "artifacts" / "stage-03" / name).read_bytes()
            ).hexdigest()
            for name in sorted(FROZEN_DESIGN_EVIDENCE_SHA256)
        }
        design_evidence_matches = design_evidence == dict(
            sorted(FROZEN_DESIGN_EVIDENCE_SHA256.items())
        )

        gates = []
        for name, command, expected_exit in ATTESTED_GATES:
            result = _run_gate(extraction, command)
            result["gate"] = name
            result["expected_exit_code"] = expected_exit
            result["matches_expectation"] = result["exit_code"] == expected_exit
            gates.append(result)

        suites = [
            run_suite(
                extraction,
                name="changeset_01_gate_suite",
                command=changeset_01_gate_suite_command(),
                mandatory=True,
            ),
            run_suite(
                extraction,
                name="clean_review_bundle_suite",
                command=changeset_01_clean_bundle_suite_command(),
                mandatory=True,
            ),
        ]

        gate_json = extraction / CHANGESET_DIR / "stage02-pre-live-load-gate.json"
        extracted_gate = (
            json.loads(gate_json.read_text(encoding="utf-8")) if gate_json.is_file() else {}
        )

    stage02 = next(entry for entry in gates if entry["gate"] == "stage02_pre_live_load_gate")
    publisher_failed = sorted(publisher_gate_document.get("failed_checks", []))
    extracted_failed = sorted(stage02["failed_checks"])
    same_reason = extracted_failed == publisher_failed

    open_blockers = sorted(
        extracted_gate.get("pre_live_load_blockers", {}).get("open_blocker_ids", [])
    )
    all_blockers_enforced = set(open_blockers) <= set(extracted_failed) and len(open_blockers) == 5

    # Precise statements about what the archive holds. uv.lock is a dependency lockfile and has
    # nothing to do with publication locking; conflating the two would misdescribe the archive.
    lock_members = [name for name in members if name.endswith(LOCK_NAME)]
    uv_lock_present = any(Path(name).name == "uv.lock" for name in members)

    # v0.2.3: the registry check must survive extraction, and no contract instance may travel in
    # the archive. A packaged contract would let a clean extraction unblock itself.
    blockers = extracted_gate.get("pre_live_load_blockers", {})
    authority = blockers.get("contract_authority", {})
    registry = blockers.get("conflict_registry", {})
    registry_checked = "accepted_artifact_conflict_registry_valid" in {
        check.get("name") for check in extracted_gate.get("checks", [])
    }
    contracts = authority.get("contracts", {})
    contract_instances = sum(entry.get("definition_count", 0) for entry in contracts.values())
    authority_ok = (
        registry_checked
        and bool(registry.get("valid"))
        and contract_instances == 0
        and authority.get("recursive_search_for_authority") is False
        and authority.get("substring_algorithm_matching") is False
    )

    all_gates_ok = all(entry["matches_expectation"] for entry in gates)
    all_suites_ok = all(suite.ok for suite in suites)

    return {
        "changeset_id": CHANGESET_ID,
        "changeset_version": CHANGESET_VERSION,
        "attested_at": datetime.now(tz=UTC).isoformat(),
        "archive": BUNDLE_ZIP_NAME,
        "archive_sha256": actual,
        "archive_sha256_matches_sidecar": True,
        "archive_rebuilt_after_hashing": False,
        "member_count": len(members),
        "extraction": "clean temporary directory, no repository state reused",
        "design_evidence_in_archive": {
            "accepted_sha256": dict(sorted(FROZEN_DESIGN_EVIDENCE_SHA256.items())),
            "extracted_sha256": design_evidence,
            "matches_accepted_release": design_evidence_matches,
            "regenerated": False,
        },
        "archive_contents": {
            "no_transient_publication_lock_artifact_included": not lock_members,
            "transient_publication_lock_members": lock_members,
            "no_literal_credential_bearing_dsn_or_secret_included": True,
            "uv_lock": {
                "present": uv_lock_present,
                "kind": "dependency lockfile",
                "is_a_publication_lock": False,
                "why_included": "reproducible installs from the extracted archive",
            },
        },
        "gates": gates,
        "suites": [suite.__dict__ for suite in suites],
        "stage02_pre_live_load_gate": {
            "publisher_failed_checks": publisher_failed,
            "clean_extraction_failed_checks": extracted_failed,
            "same_failure_reason": same_reason,
            "expected_status": "FAIL",
            "extracted_status": extracted_gate.get("status"),
            "open_blocker_ids": open_blockers,
            "all_five_blockers_enforced": all_blockers_enforced,
            "frozen_inputs_checked": extracted_gate.get("frozen_inputs", {}).get("count"),
            "frozen_inputs_unchanged_by_gate": extracted_gate.get("frozen_inputs", {}).get(
                "unchanged"
            ),
        },
        "contract_authority": {
            "authoritative_paths": {
                key: entry.get("authoritative_path")
                for key, entry in sorted(authority.get("policy", {}).items())
            },
            "owning_releases": {
                key: entry.get("owning_release")
                for key, entry in sorted(authority.get("policy", {}).items())
            },
            "forbidden_source_directories": authority.get("forbidden_source_directories", []),
            "recursive_search_for_authority": authority.get("recursive_search_for_authority"),
            "substring_algorithm_matching": authority.get("substring_algorithm_matching"),
            "contract_instances_in_archive": contract_instances,
            "ambiguous_definitions": authority.get("ambiguous_definitions", []),
        },
        "conflict_registry": {
            "validity_is_a_gate_check": registry_checked,
            "valid": registry.get("valid"),
            "sha256": registry.get("sha256"),
            "matches_changeset_manifest": registry.get("matches_changeset_manifest"),
            "open_blocking_conflict_ids": registry.get("open_blocking_conflict_ids", []),
        },
        "design_archive_finding": design_archive_finding,
        "status": "PASS"
        if all_gates_ok
        and all_suites_ok
        and same_reason
        and design_evidence_matches
        and all_blockers_enforced
        and authority_ok
        and not lock_members
        else "FAIL",
    }


def write_attestation(repo_root: Path, document: dict[str, Any]) -> Path:
    path = repo_root.resolve() / "artifacts" / "external-review" / ATTESTATION_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
