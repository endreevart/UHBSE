"""Tests for the executable pre-live-load gate.

The gate must fail on the current Stage 02 drift, block every live operation, leave Stage 02
untouched, and never block empty canonical storage creation or migrations.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from human_simulator.stage02.relationship_manifest import MANIFEST_NAME
from human_simulator.stage03.pre_live_load_gate import (
    ALLOWED_WHILE_BLOCKED,
    BLOCKED_LIVE_OPERATIONS,
    GATE_ID,
    LiveLoadBlocked,
    evaluate_pre_live_load_gate,
    require_live_load_authorized,
)

STAGE_02 = Path("artifacts") / "stage-02"
CONTROLLED = (
    "subject-root-analysis.json",
    "identity-linkage-assessment.json",
    MANIFEST_NAME,
)

# Blockers that remain open once the Stage 02 manifest itself is repaired. v0.2.2 added the two
# conflict-derived entries, which the gate now takes straight from accepted-artifact-conflicts.yaml.
OPEN_BLOCKER_IDS = (
    "canonical_loader_runtime_principal_undefined",
    "encounter_provider_id_population_disagreement",
    "source_subject_key_opacity_undefined",
    "temporal_precision_field_absent_from_model",
)


def _stage_02_hashes(root: Path) -> dict[str, str]:
    from human_simulator.stage02.relationship_manifest import sha256_file

    directory = root / STAGE_02
    return {
        path.name: sha256_file(path)
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


def test_gate_id_is_the_required_identifier() -> None:
    assert GATE_ID == "stage02_relationship_integrity_pre_live_load"


def test_gate_fails_with_four_remaining_blockers_after_manifest_repair(repo_root: Path) -> None:
    result = evaluate_pre_live_load_gate(repo_root)
    assert result.status == "FAIL"
    assert not result.passed
    assert "relationship_manifest_hashes_match" not in result.failed_checks
    assert set(result.failed_checks) == set(OPEN_BLOCKER_IDS)


def test_gate_evaluation_does_not_modify_stage_02(repo_root: Path) -> None:
    before = _stage_02_hashes(repo_root)
    evaluate_pre_live_load_gate(repo_root)
    evaluate_pre_live_load_gate(repo_root)
    assert _stage_02_hashes(repo_root) == before


def test_gate_document_claims_no_repair(repo_root: Path) -> None:
    document = evaluate_pre_live_load_gate(repo_root).document()
    assert document["read_only"] is True
    assert document["repairs_performed"] == 0
    assert document["stage_02_modified"] is False
    assert document["known_open_defect"] == sorted(OPEN_BLOCKER_IDS)
    assert json.dumps(document)  # serialisable evidence


@pytest.mark.parametrize("operation", BLOCKED_LIVE_OPERATIONS)
def test_every_live_operation_is_blocked(repo_root: Path, operation: str) -> None:
    with pytest.raises(LiveLoadBlocked) as excinfo:
        require_live_load_authorized(repo_root, operation)
    message = str(excinfo.value)
    assert operation in message
    assert GATE_ID in message


@pytest.mark.parametrize("operation", ALLOWED_WHILE_BLOCKED)
def test_storage_operations_never_consult_the_gate(repo_root: Path, operation: str) -> None:
    with pytest.raises(ValueError, match="must not consult"):
        require_live_load_authorized(repo_root, operation)


def test_unregistered_operations_are_rejected(repo_root: Path) -> None:
    with pytest.raises(ValueError, match="unknown live operation"):
        require_live_load_authorized(repo_root, "some_new_load_step")


def test_blocked_and_allowed_sets_are_disjoint() -> None:
    assert not set(BLOCKED_LIVE_OPERATIONS) & set(ALLOWED_WHILE_BLOCKED)
    assert len(BLOCKED_LIVE_OPERATIONS) == 7
    assert len(ALLOWED_WHILE_BLOCKED) == 4


def test_migration_runner_does_not_import_the_gate() -> None:
    source = Path("src/human_simulator/canonical/migrations.py").read_text(encoding="utf-8")
    runner = Path("src/human_simulator/stage03/canonical_migration_run.py").read_text(
        encoding="utf-8"
    )
    assert "require_live_load_authorized" not in source
    assert "require_live_load_authorized" not in runner


def test_repairing_the_manifest_clears_only_the_manifest_check(
    repo_root: Path, tmp_path: Path
) -> None:
    """The manifest check measures real state, and the other blockers are independent.

    The repair happens only in a throwaway copy; the repository is never touched.
    """
    from human_simulator.stage02.relationship_manifest import write_relationship_manifest

    workspace = tmp_path / "workspace"
    shutil.copytree(repo_root / "artifacts", workspace / "artifacts")
    before = _stage_02_hashes(repo_root)

    write_relationship_manifest(workspace / STAGE_02)
    result = evaluate_pre_live_load_gate(workspace)

    assert "relationship_manifest_hashes_match" not in result.failed_checks
    assert "relationship_manifest_present" not in result.failed_checks
    assert set(result.failed_checks) == set(OPEN_BLOCKER_IDS)
    assert result.status == "FAIL"
    assert _stage_02_hashes(repo_root) == before


def test_gate_fails_closed_when_the_manifest_is_missing(repo_root: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    shutil.copytree(repo_root / "artifacts", workspace / "artifacts")
    (workspace / STAGE_02 / MANIFEST_NAME).unlink()

    result = evaluate_pre_live_load_gate(workspace)
    assert result.status == "FAIL"
    assert "relationship_manifest_present" in result.failed_checks


# --------------------------------------------------------------------------------------
# Reproducibility. The gate must reach the same verdict, for the same reason, from a clean
# extraction of the review bundle as it does in the publisher workspace.
# --------------------------------------------------------------------------------------


def test_the_bundle_carries_every_input_the_gate_reads(repo_root: Path) -> None:
    from human_simulator.stage03.review_dependencies import (
        get_changeset_01_review_bundle_paths,
        get_stage02_relationship_gate_inputs,
    )

    bundled = set(get_changeset_01_review_bundle_paths())
    for required in get_stage02_relationship_gate_inputs():
        assert required in bundled, required
        assert (repo_root / required).is_file(), required


def test_gate_fails_for_the_same_reason_in_a_clean_extraction(
    repo_root: Path, tmp_path: Path
) -> None:
    """A publisher hash mismatch must not degrade into "manifest missing" after extraction."""
    from human_simulator.stage03.review_dependencies import (
        get_changeset_01_review_bundle_paths,
    )

    publisher_result = evaluate_pre_live_load_gate(repo_root)

    extraction = tmp_path / "extracted"
    for relative in get_changeset_01_review_bundle_paths():
        source = repo_root / relative
        if not source.exists():
            continue
        destination = extraction / relative
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    extracted_result = evaluate_pre_live_load_gate(extraction)

    assert extracted_result.status == publisher_result.status == "FAIL"
    assert set(extracted_result.failed_checks) == set(publisher_result.failed_checks)
    assert "relationship_manifest_hashes_match" not in extracted_result.failed_checks
    assert "relationship_manifest_present" not in extracted_result.failed_checks


# --------------------------------------------------------------------------------------
# Pre-live-load blockers recorded by Changeset 01 v0.2
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("blocker_id", OPEN_BLOCKER_IDS)
def test_each_open_blocker_is_reported_as_a_failed_gate_check(
    repo_root: Path, blocker_id: str
) -> None:
    result = evaluate_pre_live_load_gate(repo_root)
    assert blocker_id in result.failed_checks


def test_the_gate_document_records_the_open_blockers(repo_root: Path) -> None:
    document = evaluate_pre_live_load_gate(repo_root).document()
    blockers = document["pre_live_load_blockers"]
    assert sorted(blockers["open_blocker_ids"]) == sorted(OPEN_BLOCKER_IDS)
    assert blockers["blocks_first_live_load"] is True
    assert blockers["blocks_schema_only_migration_0004"] is False


def test_open_blockers_never_block_empty_storage_operations(repo_root: Path) -> None:
    document = evaluate_pre_live_load_gate(repo_root).document()
    assert "canonical_migration_apply" in document["does_not_block"]
    for blocker in document["pre_live_load_blockers"]["blockers"]:
        assert blocker["blocks_schema_only_migration_0004"] is False
