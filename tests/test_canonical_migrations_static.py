"""Static tests for the canonical migration files. No database required."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from human_simulator.canonical.constants import (
    CANONICAL_DATABASE,
    CANONICAL_PORT,
    CANONICAL_ROLES,
    CANONICAL_SCHEMA,
    CANONICAL_VOLUME,
    DOWN_MIGRATIONS_SUPPORTED,
    EXPECTED_TABLE_OWNER,
    FORBIDDEN_CANONICAL_TARGET_DATABASES,
    FROZEN_MIGRATION_FILENAMES,
    HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES,
    HARDENING_MIGRATION_FILENAME,
    ORIGIN_SPECIFIC_REQUIRED_PROVENANCE_FIELDS,
    PROVENANCE_BEARING_TABLES,
    RAW_SOURCE_PORTS,
)
from human_simulator.canonical.definition_baseline import (
    BASELINE_PATH,
    PINNED_SECTIONS,
    DefinitionBaselineError,
    load_baseline,
)
from human_simulator.canonical.migrations import (
    MigrationError,
    discover_migrations,
    forbidden_tokens_in_migrations,
    migration_immutability,
)
from human_simulator.canonical.schema_contract import PILOT_TABLES
from human_simulator.canonical.settings import (
    CanonicalIsolationError,
    CanonicalSettingsMissing,
    assert_canonical_target_allowed,
    assert_raw_target_allowed,
    load_canonical_settings,
    missing_canonical_prerequisites,
)
from human_simulator.stage03.changeset_01_constants import RAW_RELATION_TOKENS

MIGRATIONS_DIR = Path("migrations") / "canonical"


@pytest.fixture
def migration_text(repo_root: Path) -> str:
    return "\n".join(
        item.path.read_text(encoding="utf-8") for item in discover_migrations(repo_root)
    )


def test_migrations_are_contiguous_and_named_consistently(repo_root: Path) -> None:
    migrations = discover_migrations(repo_root)
    assert [item.version for item in migrations] == ["0001", "0002", "0003", "0004"]
    assert all(len(item.sha256) == 64 for item in migrations)


def test_published_migrations_still_match_their_accepted_bytes(repo_root: Path) -> None:
    """0001-0003 were accepted with v0.1 and may never be edited again."""
    result = migration_immutability(repo_root)
    assert result["violations"] == []
    assert result["status"] == "PASS"
    assert result["observed_sha256"] == result["accepted_sha256"]
    assert set(result["accepted_sha256"]) == set(FROZEN_MIGRATION_FILENAMES)


def test_immutability_detection_catches_an_edited_migration(repo_root: Path, tmp_path: Path) -> None:
    import shutil

    workspace = tmp_path / "edited"
    shutil.copytree(repo_root / "migrations", workspace / "migrations")
    target = workspace / MIGRATIONS_DIR / "0003_pilot_grants.sql"
    target.write_text(target.read_text(encoding="utf-8") + "\n-- edited\n", encoding="utf-8")

    result = migration_immutability(workspace)
    assert result["status"] == "FAIL"
    assert any("0003_pilot_grants.sql" in problem for problem in result["violations"])


def test_schema_corrections_live_only_in_the_new_forward_only_migration(repo_root: Path) -> None:
    """The hardening constraints must not appear in any frozen migration."""
    hardening = (repo_root / MIGRATIONS_DIR / HARDENING_MIGRATION_FILENAME).read_text(
        encoding="utf-8"
    )
    frozen = "\n".join(
        (repo_root / MIGRATIONS_DIR / name).read_text(encoding="utf-8")
        for name in FROZEN_MIGRATION_FILENAMES
    )
    for suffix in HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES:
        assert suffix in hardening
        assert suffix not in frozen
    for name in (
        "subject_characteristic_status_matches_provenance",
        "source_record_provenance_matches_columns",
    ):
        assert name in hardening
        assert name not in frozen


def test_the_hardening_migration_creates_no_table_and_moves_no_row(repo_root: Path) -> None:
    sql = (repo_root / MIGRATIONS_DIR / HARDENING_MIGRATION_FILENAME).read_text(encoding="utf-8")
    assert "CREATE TABLE" not in sql
    assert "CREATE SCHEMA" not in sql
    assert forbidden_tokens_in_migrations(repo_root) == {}


def test_every_provenance_bearing_table_is_hardened(repo_root: Path) -> None:
    sql = (repo_root / MIGRATIONS_DIR / HARDENING_MIGRATION_FILENAME).read_text(encoding="utf-8")
    for table in PROVENANCE_BEARING_TABLES:
        assert f"'{table}'" in sql
    assert set(PROVENANCE_BEARING_TABLES) == {
        table.name for table in PILOT_TABLES if table.requires_provenance
    }


def test_the_contract_declares_every_hardened_constraint() -> None:
    for table in PILOT_TABLES:
        if not table.requires_provenance:
            continue
        for suffix in HARDENED_PROVENANCE_CONSTRAINT_SUFFIXES:
            assert f"{table.name}{suffix}" in table.check_constraints


def test_origin_specific_rules_match_the_accepted_provenance_contract(repo_root: Path) -> None:
    contract = yaml.safe_load(
        (repo_root / "artifacts" / "stage-03" / "provenance-contract.yaml").read_text(
            encoding="utf-8"
        )
    )
    accepted = {
        origin: tuple(rule["additionally_requires"])
        for origin, rule in contract["origin_specific_rules"].items()
    }
    assert accepted == ORIGIN_SPECIFIC_REQUIRED_PROVENANCE_FIELDS

    sql = (repo_root / MIGRATIONS_DIR / HARDENING_MIGRATION_FILENAME).read_text(encoding="utf-8")
    for origin, fields in accepted.items():
        assert f"'{origin}'" in sql
        for name in fields:
            assert f"'{name}'" in sql


def test_the_definition_baseline_is_committed_and_self_consistent(repo_root: Path) -> None:
    document = load_baseline(repo_root)
    assert document["schema"] == CANONICAL_SCHEMA
    declared = {item.path.name: item.sha256 for item in discover_migrations(repo_root)}
    assert document["produced_by_migrations"] == declared
    definitions = document["definitions"]
    assert set(definitions) == set(PINNED_SECTIONS)
    for table in PILOT_TABLES:
        assert table.name in definitions["constraint_definitions"]
        assert definitions["table_owners"][table.name] == EXPECTED_TABLE_OWNER


def test_the_definition_baseline_pins_real_expressions_not_placeholders(repo_root: Path) -> None:
    definitions = load_baseline(repo_root)["definitions"]["constraint_definitions"]
    checks = [
        value
        for table in definitions.values()
        for value in table.values()
        if value.startswith("CHECK")
    ]
    assert checks
    assert not any(value.replace(" ", "") == "CHECK(true)" for value in checks)
    assert any("jsonb_strip_nulls" in value for value in checks)


def test_a_tampered_baseline_is_rejected(repo_root: Path, tmp_path: Path) -> None:
    import json
    import shutil

    workspace = tmp_path / "tampered"
    (workspace / BASELINE_PATH).parent.mkdir(parents=True)
    shutil.copy2(repo_root / BASELINE_PATH, workspace / BASELINE_PATH)
    document = json.loads((workspace / BASELINE_PATH).read_text(encoding="utf-8"))
    document["definitions"]["table_owners"]["subject"] = "someone_else"
    (workspace / BASELINE_PATH).write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(DefinitionBaselineError, match="fingerprint"):
        load_baseline(workspace)


def test_migration_discovery_rejects_a_gap(tmp_path: Path) -> None:
    directory = tmp_path / MIGRATIONS_DIR
    directory.mkdir(parents=True)
    (directory / "0001_first.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (directory / "0003_third.sql").write_text("SELECT 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="contiguous"):
        discover_migrations(tmp_path)


def test_migration_discovery_rejects_a_bad_filename(tmp_path: Path) -> None:
    directory = tmp_path / MIGRATIONS_DIR
    directory.mkdir(parents=True)
    (directory / "first.sql").write_text("SELECT 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="NNNN_name.sql"):
        discover_migrations(tmp_path)


def test_migrations_contain_no_data_manipulation(repo_root: Path) -> None:
    assert forbidden_tokens_in_migrations(repo_root) == {}


def test_forbidden_token_detection_actually_catches_an_insert(tmp_path: Path) -> None:
    directory = tmp_path / MIGRATIONS_DIR
    directory.mkdir(parents=True)
    (directory / "0001_bad.sql").write_text(
        "INSERT INTO canonical_evidence.subject (subject_id) VALUES ('x');\n", encoding="utf-8"
    )
    assert forbidden_tokens_in_migrations(tmp_path) == {"0001_bad.sql": ["INSERT INTO"]}


def test_migrations_reference_no_raw_relation(migration_text: str) -> None:
    for token in RAW_RELATION_TOKENS:
        assert token not in migration_text


def test_migrations_are_idempotent_by_construction(migration_text: str) -> None:
    assert "CREATE SCHEMA IF NOT EXISTS" in migration_text
    for table in PILOT_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {CANONICAL_SCHEMA}.{table.name}" in migration_text
    assert migration_text.count("CREATE INDEX IF NOT EXISTS") >= 5


def test_no_down_migration_is_authored(repo_root: Path) -> None:
    assert DOWN_MIGRATIONS_SUPPORTED is False
    assert list((repo_root / MIGRATIONS_DIR).glob("*down*.sql")) == []


def test_down_migration_absence_is_justified_by_the_accepted_plan(repo_root: Path) -> None:
    pipeline = yaml.safe_load(
        (repo_root / "artifacts" / "stage-03-implementation" / "pipeline-plan.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert pipeline["rollback"]["scope"] == "current_run_staging_only"
    assert pipeline["rollback"]["published_records"] == "never_deleted_by_rollback"


def test_no_migration_contains_a_password_or_secret(migration_text: str) -> None:
    upper = migration_text.upper()
    for token in ("PASSWORD", "SECRET", "ENCRYPTED", "postgresql://".upper()):
        assert token not in upper


def test_every_role_is_created_nologin(repo_root: Path) -> None:
    sql = (repo_root / MIGRATIONS_DIR / "0001_roles_and_schema.sql").read_text(encoding="utf-8")
    for role in CANONICAL_ROLES:
        assert f"'{role}'" in sql
    assert "NOLOGIN" in sql
    assert "NOSUPERUSER" in sql


def test_schema_is_owned_by_the_owner_role_and_public_is_revoked(repo_root: Path) -> None:
    sql = (repo_root / MIGRATIONS_DIR / "0001_roles_and_schema.sql").read_text(encoding="utf-8")
    assert f"CREATE SCHEMA IF NOT EXISTS {CANONICAL_SCHEMA} AUTHORIZATION canonical_owner" in sql
    assert f"REVOKE ALL ON SCHEMA {CANONICAL_SCHEMA} FROM PUBLIC" in sql
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in sql


def test_loader_and_validator_grants_are_least_privilege(repo_root: Path) -> None:
    sql = (repo_root / MIGRATIONS_DIR / "0003_pilot_grants.sql").read_text(encoding="utf-8")
    assert (
        f"GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA {CANONICAL_SCHEMA} TO canonical_loader" in sql
    )
    assert f"GRANT SELECT ON ALL TABLES IN SCHEMA {CANONICAL_SCHEMA} TO canonical_validator_ro" in sql
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
        assert f"GRANT {privilege}" not in sql
        assert f"{privilege} ON ALL TABLES IN SCHEMA {CANONICAL_SCHEMA} TO canonical_loader" not in sql
    assert "TO canonical_migrator" in (
        (repo_root / MIGRATIONS_DIR / "0001_roles_and_schema.sql").read_text(encoding="utf-8")
    )


def test_migrator_receives_no_table_privileges(repo_root: Path) -> None:
    sql = (repo_root / MIGRATIONS_DIR / "0003_pilot_grants.sql").read_text(encoding="utf-8")
    assert "TABLES IN SCHEMA canonical_evidence TO canonical_migrator" not in sql


def test_apply_requires_an_autocommit_connection(repo_root: Path) -> None:
    from human_simulator.canonical.migrations import apply_migrations

    class NotAutocommit:
        autocommit = False

    with pytest.raises(MigrationError, match="autocommit"):
        apply_migrations(NotAutocommit(), repo_root)


@pytest.mark.parametrize("database", FORBIDDEN_CANONICAL_TARGET_DATABASES)
def test_canonical_tooling_refuses_raw_databases(database: str) -> None:
    with pytest.raises(CanonicalIsolationError):
        assert_canonical_target_allowed(database, CANONICAL_PORT)


@pytest.mark.parametrize("port", RAW_SOURCE_PORTS)
def test_canonical_tooling_refuses_raw_ports(port: int) -> None:
    with pytest.raises(CanonicalIsolationError):
        assert_canonical_target_allowed("uhbse_canonical_dev", port)


def test_raw_tooling_refuses_the_canonical_database() -> None:
    with pytest.raises(CanonicalIsolationError):
        assert_raw_target_allowed(CANONICAL_DATABASE)


def test_canonical_settings_require_runtime_credentials() -> None:
    with pytest.raises(CanonicalSettingsMissing):
        load_canonical_settings({})
    assert missing_canonical_prerequisites({}) == [
        "CANONICAL_DB_ADMIN_PASSWORD",
        "CANONICAL_DB_ADMIN_USER",
    ]


def test_missing_prerequisite_labels_carry_no_values() -> None:
    env = {"CANONICAL_DB_ADMIN_USER": "someone"}
    labels = missing_canonical_prerequisites(env)
    assert labels == ["CANONICAL_DB_ADMIN_PASSWORD"]
    assert all("someone" not in label for label in labels)


def test_settings_never_expose_a_password_in_the_safe_target() -> None:
    settings = load_canonical_settings(
        {
            "CANONICAL_DB_HOST": "localhost",
            "CANONICAL_DB_PORT": str(CANONICAL_PORT),
            "CANONICAL_DB_NAME": CANONICAL_DATABASE,
            "CANONICAL_DB_ADMIN_USER": "canonical_admin",
            "CANONICAL_DB_ADMIN_PASSWORD": "not-a-real-password",
        }
    )
    assert "not-a-real-password" not in settings.safe_target()
    assert settings.safe_target() == f"localhost:{CANONICAL_PORT}/{CANONICAL_DATABASE}"


def test_explicit_env_argument_never_falls_back_to_the_runtime_file() -> None:
    """An explicit mapping is authoritative, so tests can never pick up local credentials."""
    assert missing_canonical_prerequisites({}) == [
        "CANONICAL_DB_ADMIN_PASSWORD",
        "CANONICAL_DB_ADMIN_USER",
    ]


def test_runtime_env_file_is_parsed_without_exporting_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from human_simulator.canonical.settings import read_runtime_env_file, resolve_setting_source

    (tmp_path / "canonical-db.env").write_text(
        "# comment\n"
        "CANONICAL_DB_ADMIN_USER=canonical_admin\n"
        'CANONICAL_DB_ADMIN_PASSWORD="not-a-real-password"\n'
        "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CANONICAL_DB_ADMIN_USER", raising=False)
    monkeypatch.delenv("CANONICAL_DB_ADMIN_PASSWORD", raising=False)

    values = read_runtime_env_file()
    assert values["CANONICAL_DB_ADMIN_USER"] == "canonical_admin"
    assert values["CANONICAL_DB_ADMIN_PASSWORD"] == "not-a-real-password"
    assert "CANONICAL_DB_ADMIN_PASSWORD" not in os.environ
    assert missing_canonical_prerequisites() == []
    assert resolve_setting_source()["CANONICAL_DB_ADMIN_USER"] == "canonical_admin"


def test_process_environment_wins_over_the_runtime_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from human_simulator.canonical.settings import resolve_setting_source

    (tmp_path / "canonical-db.env").write_text(
        "CANONICAL_DB_ADMIN_USER=from_file\nCANONICAL_DB_ADMIN_PASSWORD=x\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CANONICAL_DB_ADMIN_USER", "from_process")
    assert resolve_setting_source()["CANONICAL_DB_ADMIN_USER"] == "from_process"


def test_env_template_declares_the_planned_topology_without_secrets(repo_root: Path) -> None:
    template = (repo_root / "config" / "canonical-db.env.template").read_text(encoding="utf-8")
    assert f"CANONICAL_DB_PORT={CANONICAL_PORT}" in template
    assert f"CANONICAL_DB_NAME={CANONICAL_DATABASE}" in template
    for line in template.splitlines():
        if line.startswith(("POSTGRES_PASSWORD=", "CANONICAL_DB_ADMIN_PASSWORD=")):
            assert line.endswith("=PLACEHOLDER_SET_LOCALLY")


def test_env_file_is_not_committed(repo_root: Path) -> None:
    assert not (repo_root / "canonical-db.env").exists() or "canonical-db.env" in (
        repo_root / ".gitignore"
    ).read_text(encoding="utf-8").splitlines()


def test_compose_isolates_canonical_from_raw_services(repo_root: Path) -> None:
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    canonical = compose["services"]["canonical-db"]
    assert canonical["image"] == "postgres:16"
    assert f"{CANONICAL_PORT}:5432" in canonical["ports"]
    assert f"{CANONICAL_VOLUME}:/var/lib/postgresql/data" in canonical["volumes"]
    assert CANONICAL_VOLUME in compose["volumes"]
    assert canonical["networks"] == ["canonical-net"]

    for name, service in compose["services"].items():
        if name == "canonical-db":
            continue
        assert "canonical-net" not in (service.get("networks") or [])
