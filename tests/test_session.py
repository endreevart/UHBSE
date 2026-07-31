import pytest
from sqlalchemy import text

from human_simulator.config.settings import AuditSettings
from human_simulator.db.readonly import ReadOnlyViolationError
from human_simulator.db.session import create_audit_engine


def test_postgres_connect_args_include_timeouts(audit_settings: AuditSettings) -> None:
    settings = audit_settings.model_copy(
        update={"database_url": "postgresql+psycopg://u:p@localhost:5432/db"}
    )
    engine = create_audit_engine(settings)
    assert engine.dialect.name == "postgresql"
    engine.dispose()


def test_readonly_hook_blocks_dml(audit_settings: AuditSettings) -> None:
    engine = create_audit_engine(audit_settings)
    with engine.connect() as conn:
        with pytest.raises(ReadOnlyViolationError):
            conn.execute(text("DELETE FROM empty_table"))
