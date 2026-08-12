"""Restore source B from kgz dump (requires explicit confirmation)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import subprocess
from sqlalchemy import create_engine

from human_simulator.stage02.pg_restore_cmd import build_pg_restore_argv
from human_simulator.stage02.post_restore import (
    collect_database_inventory,
    count_restore_messages,
    create_readonly_audit_user,
    pg_restore_version_in_container,
    sanitize_log,
    verify_readonly_audit_user,
    verify_source_a_unchanged,
)
from human_simulator.stage02.preflight import PreflightResult, run_preflight, _count_user_tables
from human_simulator.stage02.settings import KGZ_TARGET_DATABASE, KgzRestoreSettings


class RestoreError(Exception):
    pass


@dataclass
class RestoreReport:
    started_at: str
    completed_at: str | None
    target_database: str
    dump_path: str
    redacted_url: str
    preflight_status: str
    restore_performed: bool
    pg_restore_exit_code: int | None
    message: str
    pg_restore_version_in_container: str | None = None
    pg_restore_message_counts: dict[str, int] = field(default_factory=dict)
    pg_restore_log_excerpt: str = ""
    post_restore_inventory: dict[str, Any] | None = None
    readonly_user: dict[str, Any] | None = None
    readonly_verification: dict[str, Any] | None = None
    source_a_verification: dict[str, Any] | None = None
    auditor_connection: str = ""
    restore_timing: dict[str, Any] = field(default_factory=dict)
    cli_failure_recovery: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _assert_confirm(confirm: bool) -> None:
    if not confirm:
        raise RestoreError("Restore requires explicit confirmation: use --confirm")


def _assert_target_database(settings: KgzRestoreSettings) -> None:
    if settings.pg_database != KGZ_TARGET_DATABASE:
        raise RestoreError(
            f"Target database must be {KGZ_TARGET_DATABASE!r}, got {settings.pg_database!r}"
        )


def _assert_database_empty(settings: KgzRestoreSettings) -> None:
    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    try:
        table_count = _count_user_tables(engine)
    finally:
        engine.dispose()
    if table_count > 0:
        raise RestoreError(
            f"Refusing restore: {settings.pg_database!r} already has {table_count} user table(s)"
        )


def _run_compose_up(repo_root: Path, service: str = "kgz-db") -> None:
    proc = subprocess.run(
        ["docker", "compose", "up", "-d", service],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RestoreError("docker compose up kgz-db failed")


def _run_pg_restore(settings: KgzRestoreSettings) -> tuple[int, str, str]:
    """Run pg_restore via docker compose exec. No DROP/--clean/--create flags."""
    dump = settings.dump_absolute
    cmd = build_pg_restore_argv(settings)
    with dump.open("rb") as dump_file:
        proc = subprocess.run(
            cmd,
            cwd=settings.repo_root,
            stdin=dump_file,
            capture_output=True,
            text=False,
            check=False,
        )
    stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    return proc.returncode, stderr, stdout


def _assert_preflight_pass(preflight: PreflightResult) -> None:
    if preflight.status == "PASS":
        return
    blocked = [
        f"{c.name}={c.status}"
        for c in preflight.checks
        if c.status in {"FAIL", "SKIP", "WARN"}
    ]
    raise RestoreError(
        f"Preflight must be PASS before restore (got {preflight.status}); "
        f"blocked checks: {', '.join(blocked)}"
    )


def restore_second_source(
    settings: KgzRestoreSettings,
    *,
    confirm: bool = False,
    skip_compose_up: bool = False,
) -> tuple[RestoreReport, PreflightResult]:
    """Restore kgz dump into kgz_raw. Caller must pass confirm=True."""
    _assert_confirm(confirm)
    _assert_target_database(settings)

    preflight = run_preflight(settings, include_toc_sample=False)
    _assert_preflight_pass(preflight)

    started = datetime.now(UTC)
    report = RestoreReport(
        started_at=started.isoformat(),
        completed_at=None,
        target_database=settings.pg_database,
        dump_path=str(settings.dump_absolute),
        redacted_url=settings.redacted_url,
        preflight_status=preflight.status,
        restore_performed=False,
        pg_restore_exit_code=None,
        message="Restore started",
        pg_restore_version_in_container=pg_restore_version_in_container(settings.repo_root),
    )

    if not skip_compose_up:
        _run_compose_up(settings.repo_root)

    _assert_database_empty(settings)

    restore_started = datetime.now(UTC)
    exit_code, stderr, stdout = _run_pg_restore(settings)
    restore_completed = datetime.now(UTC)
    report.restore_timing = {
        "restore_timing_not_captured": False,
        "restore_started_at": restore_started.isoformat(),
        "restore_completed_at": restore_completed.isoformat(),
        "restore_duration_seconds": (restore_completed - restore_started).total_seconds(),
    }
    report.pg_restore_exit_code = exit_code
    report.pg_restore_message_counts = count_restore_messages(stderr, stdout)
    report.pg_restore_log_excerpt = sanitize_log(f"{stderr}\n{stdout}")

    log_path = settings.repo_root / settings.artifacts_dir / "restore-pg_restore.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(report.pg_restore_log_excerpt + "\n", encoding="utf-8")

    if exit_code != 0:
        report.message = f"Restore failed with exit code {exit_code}; no retry or cleanup performed"
        report.completed_at = datetime.now(UTC).isoformat()
        report.source_a_verification = verify_source_a_unchanged(settings.repo_root)
        write_restore_report(report, settings.repo_root / settings.artifacts_dir)
        return report, preflight

    report.restore_performed = True
    report.message = "Restore completed"

    admin_engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    try:
        report.post_restore_inventory = collect_database_inventory(admin_engine)
    finally:
        admin_engine.dispose()

    post_started = datetime.now(UTC)
    try:
        report.readonly_user = create_readonly_audit_user(settings)
        settings = KgzRestoreSettings.from_repo(settings.repo_root)
        report.readonly_verification = verify_readonly_audit_user(settings)
        report.auditor_connection = settings.audit_redacted_url
    except Exception as exc:
        report.cli_failure_recovery = {
            "failed_step": "create_readonly_audit_user",
            "error_type": type(exc).__name__,
            "error_summary": str(exc)[:500],
            "recovery": "run: python -m human_simulator.stage02.complete_post_restore",
            "bind_parameter_fix": "CREATE ROLE uses psycopg.sql composable, not SQLAlchemy :pwd bind",
        }
        report.message = "Restore completed; post-restore CLI step failed (see cli_failure_recovery)"
        report.completed_at = datetime.now(UTC).isoformat()
        report.restore_timing["post_restore_started_at"] = post_started.isoformat()
        report.restore_timing["post_restore_completed_at"] = report.completed_at
        report.source_a_verification = verify_source_a_unchanged(settings.repo_root)
        write_restore_report(report, settings.repo_root / settings.artifacts_dir)
        raise RestoreError(f"Post-restore failed: {exc}") from exc

    report.source_a_verification = verify_source_a_unchanged(settings.repo_root)
    report.completed_at = datetime.now(UTC).isoformat()
    report.restore_timing["post_restore_started_at"] = post_started.isoformat()
    report.restore_timing["post_restore_completed_at"] = report.completed_at
    return report, preflight


def write_restore_report(report: RestoreReport, artifacts_dir: Path) -> tuple[Path, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    json_path = artifacts_dir / "restore-report.json"
    md_path = artifacts_dir / "restore-report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_restore_markdown(report), encoding="utf-8")
    return json_path, md_path


def _render_restore_markdown(report: RestoreReport) -> str:
    lines = [
        "# Restore report — source B (kgz)",
        "",
        f"**Started:** {report.started_at}",
        f"**Completed:** {report.completed_at}",
        f"**Target database:** `{report.target_database}`",
        f"**Preflight status:** {report.preflight_status}",
        f"**Restore performed:** {report.restore_performed}",
        f"**pg_restore exit code:** {report.pg_restore_exit_code}",
        f"**pg_restore version (in kgz-db container):** `{report.pg_restore_version_in_container}`",
        f"**Message:** {report.message}",
        "",
    ]
    if report.restore_timing:
        lines.extend(["## Restore timing", ""])
        for key, value in report.restore_timing.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")
    if report.cli_failure_recovery:
        lines.extend(["## CLI failure and recovery", ""])
        for key, value in report.cli_failure_recovery.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")
        lines.extend(["## pg_restore message counts", ""])
        for key, value in report.pg_restore_message_counts.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")
    if report.post_restore_inventory:
        lines.extend(["## Post-restore inventory", ""])
        for key, value in report.post_restore_inventory.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")
    if report.readonly_user:
        lines.extend(["## Read-only audit user", ""])
        for key, value in report.readonly_user.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")
    if report.readonly_verification:
        lines.extend(["## Read-only verification", ""])
        for key, value in report.readonly_verification.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")
    if report.auditor_connection:
        lines.extend(["## Auditor connection (use for profiling B)", "", f"`{report.auditor_connection}`", ""])
    if report.source_a_verification:
        lines.extend(["## Source A verification", ""])
        for key, value in report.source_a_verification.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")
    lines.append("Log excerpt: `artifacts/stage-02/restore-pg_restore.log`")
    return "\n".join(lines) + "\n"
