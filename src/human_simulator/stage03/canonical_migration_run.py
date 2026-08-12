"""Orchestrate a canonical migration run and publish its schema-only evidence.

This entry point applies DDL to the isolated derived database and records what the schema
looks like afterwards. It never consults the pre-live-load gate, because creating empty
storage touches no source data, and it never reads or writes clinical rows.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.canonical.connection import canonical_connection, postgres_major_version
from human_simulator.canonical.constants import CANONICAL_POSTGRES_VERSION
from human_simulator.canonical.definition_baseline import baseline_path
from human_simulator.canonical.migrations import (
    applied_migrations,
    apply_migrations,
    capture_definition_baseline,
    migration_report,
    verify_permissions,
    verify_schema,
)
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.stage03.changeset_01_baseline import require_baseline
from human_simulator.stage03.changeset_01_constants import (
    CHANGESET_DIR,
    CHANGESET_ID,
    MIGRATION_RESULT_NAME,
    PERMISSION_REPORT_NAME,
)


def run_canonical_migration(
    repo_root: Path,
    *,
    database_override: str | None = None,
    publish_artifacts: bool = True,
) -> dict[str, Any]:
    """Apply migrations, verify the schema contract and permissions, and report."""
    root = repo_root.resolve()
    baseline = require_baseline(root)

    settings = load_canonical_settings(database_override=database_override)
    with canonical_connection(settings) as conn:
        server_major = postgres_major_version(conn)
        report = migration_report(conn, root)

    version_ok = str(server_major) == CANONICAL_POSTGRES_VERSION
    report["postgresql"] = {
        "server_major_version": server_major,
        "planned_major_version": CANONICAL_POSTGRES_VERSION,
        "matches_plan": version_ok,
    }
    report["target"] = settings.safe_target()
    report["baseline_status"] = baseline["status"]
    if not version_ok:
        report["status"] = "FAIL"

    if publish_artifacts:
        target_dir = root / CHANGESET_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / MIGRATION_RESULT_NAME).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (target_dir / PERMISSION_REPORT_NAME).write_text(
            json.dumps(
                {
                    "changeset": CHANGESET_ID,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "target": settings.safe_target(),
                    **report["permission_verification"],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return report


CAPTURE_DATABASE = "uhbse_canonical_baseline_capture"


def capture_schema_definition_baseline(repo_root: Path, *, publish: bool = True) -> dict[str, Any]:
    """Rebuild the pinned definition baseline on a throwaway database, then drop it.

    The baseline may only describe a schema that the accepted, byte-pinned migrations just
    produced from nothing, so it is captured on a database created and dropped by this call
    rather than on the long-lived dev database, which could have drifted.
    """
    root = repo_root.resolve()
    admin = load_canonical_settings(database_override="postgres")
    with canonical_connection(admin) as conn, conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{CAPTURE_DATABASE}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{CAPTURE_DATABASE}"')
    try:
        target = load_canonical_settings(database_override=CAPTURE_DATABASE)
        with canonical_connection(target) as conn:
            apply_migrations(conn, root)
            document = capture_definition_baseline(conn, root)
    finally:
        with canonical_connection(admin) as conn, conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{CAPTURE_DATABASE}" WITH (FORCE)')

    path = baseline_path(root)
    if publish:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "baseline_path": str(path),
        "published": publish,
        "definitions_sha256": document["definitions_sha256"],
        "produced_by_migrations": document["produced_by_migrations"],
    }


def reapply_and_compare(repo_root: Path, *, database_override: str | None = None) -> dict[str, Any]:
    """Prove idempotency: a second run applies nothing and leaves the schema identical."""
    root = repo_root.resolve()
    settings = load_canonical_settings(database_override=database_override)
    with canonical_connection(settings) as conn:
        before_schema = verify_schema(conn, root)
        before_history = applied_migrations(conn)
        second = migration_report(conn, root)
        after_schema = verify_schema(conn, root)
        after_history = applied_migrations(conn)
        permissions = verify_permissions(conn)

    return {
        "changeset": CHANGESET_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "target": settings.safe_target(),
        "applied_in_second_run": second["migration"]["applied_in_this_run"],
        "schema_unchanged": before_schema == after_schema,
        "history_unchanged": before_history == after_history,
        "permissions_status": permissions["status"],
        "status": "PASS"
        if not second["migration"]["applied_in_this_run"]
        and before_schema == after_schema
        and before_history == after_history
        and permissions["status"] == "PASS"
        else "FAIL",
    }
