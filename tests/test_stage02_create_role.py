"""Regression tests for CREATE ROLE bind parameter fix."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from human_simulator.stage02.post_restore import create_readonly_audit_user
from human_simulator.stage02.settings import KgzRestoreSettings


@pytest.fixture
def kgz_admin_settings(tmp_path) -> KgzRestoreSettings:
    (tmp_path / "db-kgz.env").write_text(
        "POSTGRES_USER=kgz_raw\nPOSTGRES_PASSWORD=adminpass\nPOSTGRES_DB=kgz_raw\n"
        "KGZ_AUDIT_PASSWORD=auditpass\n",
        encoding="utf-8",
    )
    return KgzRestoreSettings(repo_root=tmp_path, pg_password="adminpass", audit_password="auditpass")


@patch("human_simulator.stage02.post_restore.create_engine")
def test_create_role_uses_psycopg_sql_not_text_bind(
    mock_create_engine: MagicMock,
    kgz_admin_settings: KgzRestoreSettings,
) -> None:
    mock_conn = MagicMock()
    mock_raw = MagicMock()
    mock_cursor = MagicMock()
    mock_create_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.connection.driver_connection = mock_raw
    mock_raw.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.execute.return_value.scalar_one_or_none.return_value = None
    mock_conn.execute.return_value.fetchall.return_value = [("public",)]

    create_readonly_audit_user(kgz_admin_settings)

    assert mock_cursor.execute.called
    executed = mock_cursor.execute.call_args[0][0]
    assert "CREATE ROLE" in str(executed)
    assert ":pwd" not in str(executed)
    assert "PASSWORD" in str(executed)

    for call in mock_conn.execute.call_args_list:
        sql_text = str(call[0][0])
        assert "PASSWORD :pwd" not in sql_text
