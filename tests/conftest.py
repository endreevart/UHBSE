"""Shared pytest fixtures — disposable SQLite database."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert
from sqlalchemy.engine import Engine

from human_simulator.config.settings import AuditSettings
from human_simulator.db.session import create_audit_engine

metadata = MetaData()
empty_table = Table(
    "empty_table",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("label", String, nullable=True),
)
null_only = Table(
    "null_only",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("always_null", String, nullable=True),
)
patients = Table(
    "patients",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("score", Integer, nullable=True),
    Column("visit_date_raw", String, nullable=True),
)
unsupported = Table(
    "unsupported",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("unknown_type_col", String, nullable=True),
)


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


# Paths a publication-capable test must never write into. Changeset 01 v0.2 shipped a review
# bundle containing Design evidence that a test had regenerated in the working tree; the fix is
# that anything which publishes runs against a throwaway copy instead.
PROTECTED_WORKSPACE_PATHS: tuple[str, ...] = (
    "artifacts/stage-01",
    "artifacts/stage-02",
    "artifacts/stage-03",
    "artifacts/stage-03-implementation",
    "artifacts/stage-03-implementation-changeset-01",
    "artifacts/external-review",
    "migrations/canonical",
)

# An allowlist rather than an exclusion list. The repository also holds multi-gigabyte database
# dumps and a virtualenv; copying those per test filled the disk, and a forgotten exclusion is a
# silent regression whereas a forgotten inclusion fails loudly.
_ISOLATION_COPIED_DIRS = (
    "src",
    "tests",
    "artifacts",
    "migrations",
    "config",
    "docs",
    ".cursor",
)
_ISOLATION_COPIED_FILES = (
    "pyproject.toml",
    "uv.lock",
    "docker-compose.yml",
    "AGENTS.md",
    ".gitignore",
    "README.md",
)
_ISOLATION_IGNORED = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".DS_Store",
    "*.zip",
    "*.dump",
    "*.env",
)


@pytest.fixture
def isolated_workspace(repo_root: Path, tmp_path: Path) -> Path:
    """A throwaway copy of the workspace for tests that publish.

    Everything a publication touches — Stage 03 evidence, the changeset snapshot, the review
    bundle directory — lives inside the copy, so the test needs no backup-and-restore dance and
    cannot lose a race with a concurrent run. pytest removes the directory afterwards.

    Review archives are not copied: they are large, and a test that needs one should say so.
    """
    import shutil

    destination = tmp_path / "workspace"
    destination.mkdir()
    ignore = shutil.ignore_patterns(*_ISOLATION_IGNORED)
    for name in _ISOLATION_COPIED_DIRS:
        source = repo_root / name
        if source.is_dir():
            shutil.copytree(source, destination / name, ignore=ignore, symlinks=True)
    for name in _ISOLATION_COPIED_FILES:
        source = repo_root / name
        if source.is_file():
            shutil.copy2(source, destination / name)
    # Start with an empty review directory. Copying it would carry over published archives and,
    # worse, the publication lock of the process running this test, which the copy would then
    # honour as a live lock held by a real, live pid.
    review = destination / "artifacts" / "external-review"
    if review.exists():
        shutil.rmtree(review)
    review.mkdir(parents=True)
    return destination


# A contract that satisfies every authority and semantic rule. Tests mutate one field at a time
# from these, so a negative test differs from a passing one only in the thing it is testing.
VALID_SUBJECT_KEY_CONTRACT: dict[str, object] = {
    "transformation_id": "subject_key_from_id",
    "algorithm": "HMAC-SHA256",
    "key_reference": "vault://uhbse/canonical/subject-key",
    "key_version": "v1",
    "namespace": "magerya_api.account_patient",
    "input_encoding": "utf8-decimal-string",
    "output_encoding": "base32-nopad",
    "rotation_policy": {
        "interval": "P365D",
        "procedure": "issue the next key_version and re-key on the next full reload",
        "prior_key_handling": "retained read-only for lineage; never deleted",
    },
    "collision_handling": {
        "action": "abort",
        "detail": "abort the load and quarantine both source records for review",
    },
}

VALID_RUNTIME_CONTRACT: dict[str, object] = {
    "login_principal": "uhbse_loader_svc",
    "group_role": "canonical_loader",
    "group_role_is_nologin": True,
    "credential_source_reference": "vault://uhbse/canonical/loader-credential",
    "connection_path": "canonical-db:5432 over the canonical bridge network only",
    "set_role_flow": "connect as uhbse_loader_svc, then SET ROLE canonical_loader",
    "minimal_grants": ["USAGE", "SELECT", "INSERT"],
    "audit_identity": "session_user uhbse_loader_svc recorded alongside current_role",
    "rotation_and_revocation_procedure": {
        "rotation": "quarterly reissue of the vault credential",
        "revocation": "REVOKE canonical_loader FROM uhbse_loader_svc and disable the credential",
    },
}


def install_authoritative_contract(workspace: Path, contract_key: str, contract: dict) -> Path:
    """Write a contract at its authoritative path and re-seal the owning release manifest.

    Editing a manifest-covered artifact invalidates that manifest, so a test that supplies a
    contract must also re-seal the release, exactly as a real design or plan release would. This
    only ever runs against a throwaway copy of the workspace.
    """
    from human_simulator.stage03.live_load_contracts import CONTRACT_AUTHORITIES

    authority = CONTRACT_AUTHORITIES[contract_key]
    target = workspace / authority.authoritative_path
    document = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    document[contract_key] = contract
    target.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    reseal_manifest(workspace / authority.manifest_path)
    return target


def reseal_manifest(manifest: Path) -> None:
    """Recompute a ``<sha256>  <name>`` manifest in place, as a real release would."""
    import hashlib

    lines = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        _, name = line.split(maxsplit=1)
        sibling = manifest.parent / name.strip()
        digest = hashlib.sha256(sibling.read_bytes()).hexdigest() if sibling.is_file() else "0" * 64
        lines.append(f"{digest}  {name.strip()}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rewrite_conflict_registry(workspace: Path, document: object) -> None:
    """Write the conflict registry and re-seal the changeset manifest that covers it."""
    from human_simulator.stage03.changeset_01_constants import (
        CHANGESET_DIR,
        CHANGESET_MANIFEST_NAME,
    )
    from human_simulator.stage03.conflict_registry import CONFLICTS_ARTIFACT

    path = workspace / CONFLICTS_ARTIFACT
    path.write_text(
        document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )
    reseal_manifest(workspace / CHANGESET_DIR / CHANGESET_MANIFEST_NAME)


@pytest.fixture
def valid_subject_key_contract() -> dict:
    import copy

    return copy.deepcopy(VALID_SUBJECT_KEY_CONTRACT)


@pytest.fixture
def valid_runtime_contract() -> dict:
    import copy

    return copy.deepcopy(VALID_RUNTIME_CONTRACT)


@pytest.fixture
def audit_settings(tmp_path: Path) -> AuditSettings:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sources.example.yaml").write_text(
        "sources:\n  local_stage:\n    host: localhost\n    port: 5434\n"
        "    database: test_db\n    user: test_user\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "test.db"
    return AuditSettings.from_repo(tmp_path).model_copy(
        update={"database_url": _sqlite_url(db_path), "repo_root": tmp_path}
    )


@pytest.fixture
def disposable_engine(audit_settings: AuditSettings) -> Engine:
    setup = create_engine(audit_settings.sqlalchemy_url)
    metadata.create_all(setup)
    with setup.begin() as conn:
        conn.execute(insert(null_only), {"id": 1, "always_null": None})
        conn.execute(
            insert(patients),
            [
                {"id": 1, "score": 10, "visit_date_raw": "2020-01-01"},
                {"id": 2, "score": None, "visit_date_raw": "not-a-date"},
            ],
        )
        conn.execute(insert(unsupported), {"id": 1, "unknown_type_col": "x"})
    setup.dispose()

    engine = create_audit_engine(audit_settings)
    yield engine
    engine.dispose()
