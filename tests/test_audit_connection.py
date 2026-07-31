import json

from human_simulator.audit.connection import connection_check
from human_simulator.config.settings import AuditSettings


def test_connection_check(disposable_engine, audit_settings: AuditSettings) -> None:
    result = connection_check(audit_settings, disposable_engine)
    assert result["reachable"] is True
    assert result["duration_ms"] >= 0
    assert "secret" not in json.dumps(result)
    assert audit_settings.pg_password.get_secret_value() not in json.dumps(result)
