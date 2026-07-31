"""Shared pytest fixtures — disposable SQLite database."""

from __future__ import annotations

from pathlib import Path

import pytest
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
