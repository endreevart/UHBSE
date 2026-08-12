"""Read-only canonical database baseline checks for Stage 03 alignment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.migrations import row_counts
from human_simulator.canonical.settings import (
    CanonicalSettingsMissing,
    canonical_settings_available,
    load_canonical_settings,
)

EXPECTED_PILOT_TABLES: tuple[str, ...] = (
    "source_system",
    "source_record",
    "subject",
    "subject_characteristic",
    "encounter",
    "observation",
    "observation_component",
)


@dataclass(frozen=True)
class CanonicalDbBaseline:
    check_passed: bool
    check_status: str
    check_detail: str
    document: dict[str, Any]


def evaluate_canonical_db_baseline() -> CanonicalDbBaseline:
    """Probe canonical DB row counts via the existing connection contract."""
    document: dict[str, Any] = {
        "canonical_db_connections": 0,
        "raw_db_connections": 0,
        "clinical_source_rows_read": 0,
        "canonical_database_is_empty": None,
        "row_counts": None,
        "connection_user": None,
        "exception": None,
    }

    if not canonical_settings_available():
        return CanonicalDbBaseline(
            check_passed=False,
            check_status="NOT_EVALUATED",
            check_detail="canonical connection settings unavailable",
            document=document,
        )

    settings = load_canonical_settings()
    document["connection_user"] = settings.user

    try:
        with canonical_connection(settings) as conn:
            document["canonical_db_connections"] = 1
            counts = row_counts(conn)
    except CanonicalSettingsMissing as error:
        document["exception"] = {"type": error.__class__.__name__, "message": str(error)}
        return CanonicalDbBaseline(
            check_passed=False,
            check_status="EVALUATED",
            check_detail="canonical settings missing at connection time",
            document=document,
        )
    except Exception as error:  # noqa: BLE001
        document["exception"] = {"type": error.__class__.__name__, "message": str(error)}
        return CanonicalDbBaseline(
            check_passed=False,
            check_status="EVALUATED",
            check_detail=f"canonical connection failed: {error.__class__.__name__}",
            document=document,
        )

    missing_tables = sorted(set(EXPECTED_PILOT_TABLES) - set(counts))
    if missing_tables:
        document["row_counts"] = counts
        document["exception"] = {
            "type": "MissingPilotTables",
            "message": f"missing tables: {', '.join(missing_tables)}",
        }
        return CanonicalDbBaseline(
            check_passed=False,
            check_status="EVALUATED",
            check_detail=f"missing pilot tables: {missing_tables}",
            document=document,
        )

    document["row_counts"] = {name: counts[name] for name in EXPECTED_PILOT_TABLES}
    document["canonical_database_is_empty"] = all(
        document["row_counts"][name] == 0 for name in EXPECTED_PILOT_TABLES
    )
    total = sum(document["row_counts"].values())
    return CanonicalDbBaseline(
        check_passed=document["canonical_database_is_empty"] is True,
        check_status="EVALUATED",
        check_detail=f"row_counts_total={total}",
        document=document,
    )
