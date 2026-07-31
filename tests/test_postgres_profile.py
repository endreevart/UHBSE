from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from human_simulator.audit.postgres_profile import (
    ProfilePostgresError,
    UnsafeConfigurationError,
    _classify_sensitive_columns,
    _run_approved_aggregates,
    _validate_readonly,
    profile_postgres_source,
)
from human_simulator.config.policy import ProfilingPolicy
from human_simulator.config.settings import AuditSettings


def _policy(tmp_path: Path) -> ProfilingPolicy:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "profiling-policy.yaml").write_text(
        "limits:\n  max_rows_sample: 1000\n  max_tables: null\n"
        "pii:\n  never_sample_columns_matching:\n    - '.*phone.*'\n"
        "output:\n  artifacts_dir: artifacts/stage-01\n"
        "  evidence_dir: artifacts/stage-01/evidence\n",
        encoding="utf-8",
    )
    return ProfilingPolicy.from_repo(tmp_path)


def test_classify_sensitive_columns(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    columns = [
        {"schema": "public", "relation": "patients", "name": "phone_mobile", "data_type": "text"},
        {"schema": "public", "relation": "patients", "name": "score", "data_type": "integer"},
    ]
    result = _classify_sensitive_columns(columns, policy)
    assert len(result) == 1
    assert result[0]["column"] == "phone_mobile"
    assert "name_pattern" in result[0]["reasons"]


def test_validate_readonly_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    query_log: list[dict[str, Any]] = []

    def fake_run(engine, log, name, sql, params=None):
        if "transaction_read_only" in sql:
            return [{"transaction_read_only": "on"}]
        if "pg_roles" in sql:
            return [
                {
                    "rolname": "reader",
                    "rolsuper": False,
                    "rolcreatedb": False,
                    "rolcreaterole": False,
                }
            ]
        return []

    monkeypatch.setattr("human_simulator.audit.postgres_profile._run_query", fake_run)
    engine = create_engine("postgresql+psycopg://u:p@localhost/db")
    result = _validate_readonly(engine, query_log)
    assert result["safe"] is True


def test_validate_readonly_unsafe_superuser(monkeypatch: pytest.MonkeyPatch) -> None:
    query_log: list[dict[str, Any]] = []

    def fake_run(engine, log, name, sql, params=None):
        if "transaction_read_only" in sql:
            return [{"transaction_read_only": "on"}]
        if "pg_roles" in sql:
            return [
                {
                    "rolname": "admin",
                    "rolsuper": True,
                    "rolcreatedb": False,
                    "rolcreaterole": False,
                }
            ]
        return []

    monkeypatch.setattr("human_simulator.audit.postgres_profile._run_query", fake_run)
    engine = create_engine("postgresql+psycopg://u:p@localhost/db")
    result = _validate_readonly(engine, query_log)
    assert result["safe"] is False
    assert "superuser" in result["reason"]


def test_run_approved_aggregates_skips_large_table(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = ProfilingPolicy(
        forbidden_operations=(),
        max_rows_sample=100,
        max_tables=None,
        sensitive_column_patterns=(),
        artifacts_dir=Path("artifacts/stage-01"),
        evidence_dir=Path("artifacts/stage-01/evidence"),
    )
    query_log: list[dict[str, Any]] = []
    relations = [{"schema": "public", "name": "visits", "kind": "table"}]
    row_estimates = [{"schema_name": "public", "relation_name": "visits", "estimated_rows": 5000}]
    columns = [{"schema": "public", "relation": "visits", "name": "id", "data_type": "integer"}]

    def fail_run(*args, **kwargs):
        raise AssertionError("aggregate query should not run for large tables")

    monkeypatch.setattr("human_simulator.audit.postgres_profile._run_query", fail_run)
    engine = create_engine("postgresql+psycopg://u:p@localhost/db")
    result = _run_approved_aggregates(engine, relations, row_estimates, columns, policy, query_log)
    assert result[0]["aggregate_status"] == "skipped_large_table"


def test_profile_postgres_source_writes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(tmp_path)
    settings = AuditSettings.from_repo(tmp_path).model_copy(update={"repo_root": tmp_path})
    engine = create_engine("postgresql+psycopg://u:p@localhost/db")
    query_log: list[dict[str, Any]] = []

    def fake_run(engine_obj, log, name, sql, params=None):
        if "transaction_read_only" in sql:
            return [{"transaction_read_only": "on"}]
        if "pg_roles" in sql:
            return [
                {
                    "rolname": "reader",
                    "rolsuper": False,
                    "rolcreatedb": False,
                    "rolcreaterole": False,
                }
            ]
        if "role_table_grants" in sql:
            return []
        if "version()" in sql:
            return [{"version": "PostgreSQL 14.0"}]
        if "database_size_bytes" in sql:
            return [{"database_name": "magerya_api", "connected_role": "reader", "database_size_bytes": 1}]
        if "discover_relations" in name:
            return [{"schema_name": "public", "relation_name": "patients", "relation_kind": "r"}]
        if "discover_columns" in name:
            return [
                {
                    "schema_name": "public",
                    "relation_name": "patients",
                    "column_name": "id",
                    "data_type": "integer",
                    "is_nullable": "NO",
                    "ordinal_position": 1,
                }
            ]
        if "discover_primary_keys" in name:
            return [{"schema_name": "public", "relation_name": "patients", "column_name": "id"}]
        if "discover_foreign_keys" in name:
            return []
        if "discover_indexes" in name:
            return [{"schema_name": "public", "relation_name": "patients", "indexname": "patients_pkey", "indexdef": "..."}]
        if "estimated_row_counts" in name:
            return [
                {
                    "schema_name": "public",
                    "relation_name": "patients",
                    "relation_kind": "r",
                    "estimated_rows": 10,
                }
            ]
        if name.startswith("aggregate_nulls"):
            return [{"row_count": 10, "id_nulls": 0}]
        return []

    monkeypatch.setattr("human_simulator.audit.postgres_profile._run_query", fake_run)
    result = profile_postgres_source(settings, engine, policy)
    artifact = tmp_path / "artifacts/stage-01/schema-profile.json"
    assert artifact.exists()
    assert result["relation_count"] == 1
    assert result["columns"][0]["name"] == "id"
    assert not any("phone" in str(item) for item in result.values())


def test_profile_postgres_source_stops_on_unsafe_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(tmp_path)
    settings = AuditSettings.from_repo(tmp_path).model_copy(update={"repo_root": tmp_path})
    engine = create_engine("postgresql+psycopg://u:p@localhost/db")

    def fake_run(engine_obj, log, name, sql, params=None):
        if "transaction_read_only" in sql:
            return [{"transaction_read_only": "off"}]
        if "pg_roles" in sql:
            return [
                {
                    "rolname": "admin",
                    "rolsuper": True,
                    "rolcreatedb": False,
                    "rolcreaterole": False,
                }
            ]
        return []

    monkeypatch.setattr("human_simulator.audit.postgres_profile._run_query", fake_run)
    with pytest.raises(UnsafeConfigurationError):
        profile_postgres_source(settings, engine, policy)


def test_profile_postgres_source_requires_postgresql(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    settings = AuditSettings.from_repo(tmp_path).model_copy(
        update={"repo_root": tmp_path, "database_url": "sqlite+pysqlite:///:memory:"}
    )
    engine = create_engine(settings.sqlalchemy_url)
    with pytest.raises(ProfilePostgresError):
        profile_postgres_source(settings, engine, policy)
