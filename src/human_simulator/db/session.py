"""SQLAlchemy engine and session helpers."""

from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from human_simulator.config.settings import AuditSettings
from human_simulator.db.readonly import ReadOnlyViolationError, assert_readonly


def create_audit_engine(settings: AuditSettings, *, url: str | None = None) -> Engine:
    target_url = url or settings.sqlalchemy_url
    connect_args: dict[str, object] = {}
    if target_url.startswith("postgresql"):
        options = (
            f"-c default_transaction_read_only=on "
            f"-c statement_timeout={settings.statement_timeout_ms} "
            f"-c lock_timeout={settings.lock_timeout_ms}"
        )
        connect_args["options"] = options

    engine = create_engine(target_url, connect_args=connect_args)

    @event.listens_for(engine, "before_cursor_execute")
    def _enforce_readonly(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if not statement.lstrip().upper().startswith(("SELECT", "WITH", "EXPLAIN", "SHOW")):
            try:
                assert_readonly(statement)
            except ReadOnlyViolationError:
                raise
        else:
            assert_readonly(statement)

    return engine


def ping(engine: Engine) -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
