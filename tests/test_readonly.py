from pathlib import Path

import pytest

from human_simulator.config.settings import AuditSettings
from human_simulator.db.readonly import ReadOnlyViolationError, assert_readonly
from human_simulator.db.redaction import redact_credentials, redact_phi


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH cte AS (SELECT id FROM t) SELECT id FROM cte",
        "EXPLAIN SELECT id FROM users",
    ],
)
def test_assert_readonly_allows_select(sql: str) -> None:
    assert_readonly(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM users",
        "INSERT INTO t VALUES (1)",
        "DROP TABLE users",
        "UPDATE users SET x = 1",
        "CREATE TABLE t (id INT)",
        "TRUNCATE users",
    ],
)
def test_assert_readonly_blocks_writes(sql: str) -> None:
    with pytest.raises(ReadOnlyViolationError):
        assert_readonly(sql)


def test_settings_from_repo(audit_settings: AuditSettings) -> None:
    assert audit_settings.pg_database == "test_db"
    assert "sqlite" in audit_settings.sqlalchemy_url


def test_redact_credentials() -> None:
    raw = "postgresql://user:secret@localhost:5432/db"
    assert "secret" not in redact_credentials(raw)
    assert "user" in redact_credentials(raw)


def test_redact_phi() -> None:
    raw = "Contact ivan.petrov@example.com or +7 999 123 45 67"
    redacted = redact_phi(raw)
    assert "example.com" not in redacted
    assert "999" not in redacted


def test_settings_redacted_url(audit_settings: AuditSettings) -> None:
    assert "***" in audit_settings.redacted_url
    assert audit_settings.pg_password.get_secret_value() not in audit_settings.redacted_url


def test_load_source_config_from_example() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = AuditSettings.from_repo(root)
    assert settings.pg_database == "magerya_api"
    assert settings.pg_port == 5434
