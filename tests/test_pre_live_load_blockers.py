"""Registry-level tests for the pre-live-load blockers.

Changeset 01 v0.2 asserted here that a blocker closes when an artifact "documents" a
transformation or a principal, where documenting meant a YAML key existed and a word appeared
nearby. v0.2.2 removed that notion: a blocker closes only under a complete structured contract.
The field-level validation lives in ``test_pre_live_load_gate_hardening.py``; this file covers
the registry itself — what it contains, where each entry comes from, and that reading it writes
nothing.
"""

from __future__ import annotations

from pathlib import Path

from human_simulator.canonical.constants import ROLE_LOADER
from human_simulator.stage03.pre_live_load_blockers import (
    CONFLICTS_ARTIFACT,
    LOADER_PRINCIPAL_BLOCKER,
    MANIFEST_DRIFT_BLOCKER,
    SUBJECT_KEY_BLOCKER,
    SUBJECT_KEY_TRANSFORMATION,
    blockers_document,
    blocking_conflicts,
    evaluate_blockers,
)

EXPECTED_OPEN_BLOCKERS = (
    "canonical_loader_runtime_principal_undefined",
    "encounter_provider_id_population_disagreement",
    "source_subject_key_opacity_undefined",
    "temporal_precision_field_absent_from_model",
)


def _blocker(repo_root: Path, blocker_id: str):
    return next(b for b in evaluate_blockers(repo_root) if b.blocker_id == blocker_id)


def test_all_four_remaining_blockers_are_open_against_the_accepted_artifacts(
    repo_root: Path,
) -> None:
    document = blockers_document(repo_root)
    assert tuple(document["open_blocker_ids"]) == EXPECTED_OPEN_BLOCKERS
    assert document["blocks_first_live_load"] is True
    assert document["required_blockers_present"] is True
    assert document["missing_required_blockers"] == []


def test_no_blocker_blocks_the_schema_only_hardening_migration(repo_root: Path) -> None:
    for blocker in evaluate_blockers(repo_root):
        assert blocker.blocks_schema_migration is False
    assert blockers_document(repo_root)["blocks_schema_only_migration_0004"] is False


def test_conflict_blockers_name_the_artifact_they_came_from(repo_root: Path) -> None:
    recorded = {conflict["id"] for conflict in blocking_conflicts(repo_root)}
    assert recorded, "the two accepted conflicts should still be open"
    for blocker in evaluate_blockers(repo_root):
        if blocker.blocker_id in recorded:
            assert blocker.source == CONFLICTS_ARTIFACT.as_posix()
            assert blocker.blocks_live_load is True


def test_the_manifest_blocker_is_resolved_after_maintenance_01(repo_root: Path) -> None:
    blocker = _blocker(repo_root, MANIFEST_DRIFT_BLOCKER)
    assert blocker.status == "RESOLVED"
    assert blocker.blocks_live_load is False
    assert "all recorded hashes match" in blocker.evidence


def test_the_opacity_blocker_names_the_cleartext_risk(repo_root: Path) -> None:
    blocker = _blocker(repo_root, SUBJECT_KEY_BLOCKER)
    assert blocker.status == "OPEN"
    assert SUBJECT_KEY_TRANSFORMATION in blocker.question
    assert "clear" in blocker.evidence


def test_the_loader_blocker_explains_why_a_nologin_group_role_is_not_enough(
    repo_root: Path,
) -> None:
    blocker = _blocker(repo_root, LOADER_PRINCIPAL_BLOCKER)
    assert blocker.status == "OPEN"
    assert "NOLOGIN" in blocker.evidence
    assert ROLE_LOADER in blocker.question
    assert "SET ROLE" in blocker.question


def test_the_registry_records_how_it_decides(repo_root: Path) -> None:
    document = blockers_document(repo_root)
    assert "no recursive search, no substring matching" in document["validation_method"]
    assert document["subject_key_contract"]["satisfied"] is False
    assert document["loader_runtime_contract"]["satisfied"] is False
    assert document["conflict_registry"]["valid"] is True

    authority = document["contract_authority"]
    assert authority["recursive_search_for_authority"] is False
    assert authority["substring_algorithm_matching"] is False
    for contract in authority["contracts"].values():
        assert contract["definition_count"] == 0
        assert contract["authoritative_path"]


def test_blocker_evaluation_writes_nothing(repo_root: Path) -> None:
    def snapshot() -> dict[str, float]:
        return {
            str(path): path.stat().st_mtime
            for path in sorted((repo_root / "artifacts" / "stage-03").rglob("*"))
            if path.is_file()
        }

    before = snapshot()
    blockers_document(repo_root)
    assert snapshot() == before
