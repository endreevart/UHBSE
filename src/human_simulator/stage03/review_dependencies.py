"""Shared Stage 03 review bundle dependency paths."""

from __future__ import annotations

from pathlib import Path

from human_simulator.stage02.relationship_manifest import (
    MANIFEST_NAME,
    RELATIONSHIP_MANIFEST_ARTIFACTS,
)

EXCLUDE_DIR_NAMES = frozenset({"__pycache__", ".pytest_cache", ".venv", ".uv", ".mypy_cache", ".ruff_cache"})
EXCLUDE_FILE_NAMES = frozenset({".DS_Store"})


def get_stage03_design_review_dependencies() -> tuple[str, ...]:
    return (
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "artifacts/stage-03",
        "artifacts/stage-01/schema-profile.json",
        "artifacts/stage-01/stage-01-report.md",
        "artifacts/stage-02/schema-profile-kgz.json",
        "artifacts/stage-02/entity-crosswalk.yaml",
        "artifacts/stage-02/identity-linkage-assessment.json",
        "artifacts/stage-02/subject-root-analysis.json",
        "artifacts/stage-02/verify-stage-02.json",
        "artifacts/stage-02/stage-02-report.md",
        "artifacts/stage-02/stage-02-final-manifest.sha256",
        "src/human_simulator",
        "tests/test_verify_stage_03_design.py",
        "docs/stage-03.md",
        "docs/stage-03-acceptance.md",
        "docs/current-stage.md",
        ".cursor/rules/07-canonical-model.mdc",
        ".cursor/skills/verify-stage-03-design",
        ".cursor/skills/design-canonical-model",
        ".cursor/commands/stage-03-check.md",
        ".cursor/commands/stage-03-start.md",
    )


def get_implementation_review_dependencies() -> tuple[str, ...]:
    return (
        "artifacts/stage-03-implementation",
        "tests/conftest.py",
        "tests/test_verify_implementation_plan.py",
        "tests/test_stage03_contracts.py",
        "tests/test_review_bundle_validation.py",
        "tests/test_implementation_plan_clean_extraction.py",
        "tests/test_prior_stage_integrity.py",
        # Live integration test whose environment probe and isolation are under review.
        "tests/test_assess_source_relationship.py",
        "docs/stage-03-implementation.md",
        "docs/stage-03-implementation-acceptance.md",
        ".cursor/rules/08-canonical-implementation.mdc",
        ".cursor/skills/plan-canonical-implementation",
        ".cursor/skills/verify-implementation-plan",
        ".cursor/commands/stage-03-implementation-plan-start.md",
        ".cursor/commands/stage-03-implementation-plan-check.md",
    )


def get_stage02_relationship_gate_inputs() -> tuple[str, ...]:
    """Every input ``stage02_relationship_integrity_pre_live_load`` reads.

    Without the manifest and all of its listed artifacts, a clean extraction would fail the
    gate with "manifest missing" while the publisher workspace fails with a hash mismatch.
    Two different failure reasons for one defect make the evidence unreproducible, so the
    complete input set travels with the bundle. Nothing here is modified or repaired.
    """
    directory = "artifacts/stage-02"
    return (
        f"{directory}/{MANIFEST_NAME}",
        *(f"{directory}/{name}" for name in RELATIONSHIP_MANIFEST_ARTIFACTS),
    )


def get_changeset_01_review_dependencies() -> tuple[str, ...]:
    """Paths introduced or changed by Stage 03 Implementation Changeset 01.

    Secrets are excluded structurally: only the env *template* is listed, never
    ``canonical-db.env``.
    """
    return (
        "artifacts/stage-03-implementation-changeset-01",
        "migrations/canonical",
        "docker-compose.yml",
        "config/canonical-db.env.template",
        ".gitignore",
        *get_stage02_relationship_gate_inputs(),
        "tests/test_canonical_schema_contract.py",
        "tests/test_canonical_migrations_static.py",
        "tests/test_canonical_migration_integration.py",
        "tests/test_stage02_pre_live_load_gate.py",
        "tests/test_changeset_01_verifier.py",
        "tests/test_changeset_01_review_bundle.py",
        "tests/test_release_pipeline_mandatory_suites.py",
        "tests/test_pre_live_load_blockers.py",
        "tests/test_pre_live_load_gate_hardening.py",
        "tests/test_contract_authority.py",
        "tests/test_publication_isolation.py",
        "docs/stage-03-implementation-changeset-01.md",
        ".cursor/rules/03-readonly-sql.mdc",
        ".cursor/rules/06-data-provenance.mdc",
        ".cursor/commands/stage-03-changeset-01-check.md",
    )


def get_implementation_review_bundle_paths() -> tuple[str, ...]:
    return _merge(
        get_stage03_design_review_dependencies(),
        get_implementation_review_dependencies(),
    )


def get_changeset_01_review_bundle_paths() -> tuple[str, ...]:
    return _merge(
        get_stage03_design_review_dependencies(),
        get_implementation_review_dependencies(),
        get_changeset_01_review_dependencies(),
    )


def _merge(*groups: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for rel in group:
            if rel not in seen:
                seen.add(rel)
                merged.append(rel)
    return tuple(merged)


def should_skip_member(path: Path) -> bool:
    if path.name in EXCLUDE_FILE_NAMES or path.suffix == ".pyc":
        return True
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)


def expand_review_bundle_members(repo_root: Path) -> frozenset[str]:
    members: set[str] = set()
    for rel in get_implementation_review_bundle_paths():
        path = repo_root / rel
        if not path.exists():
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and not should_skip_member(child):
                    members.add(child.relative_to(repo_root).as_posix())
        else:
            if not should_skip_member(path):
                members.add(path.relative_to(repo_root).as_posix())
    return frozenset(members)
