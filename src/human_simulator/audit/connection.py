"""Connection check for audit sources."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.engine import Engine

from human_simulator.config.settings import AuditSettings
from human_simulator.db.session import ping


def connection_check(settings: AuditSettings, engine: Engine) -> dict[str, Any]:
    started = time.perf_counter()
    reachable = ping(engine)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "source_id": "local_stage",
        "reachable": reachable,
        "duration_ms": duration_ms,
        "database": settings.pg_database,
        "host": settings.pg_host,
        "port": settings.pg_port,
        "redacted_url": settings.redacted_url,
    }
