"""Preflight checks before kgz dump restore."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from sqlalchemy import text
from sqlalchemy.engine import Engine, create_engine

from human_simulator.stage02.dump_inspect import (
    DumpInspectError,
    DumpMetadata,
    TocAnalysis,
    analyze_toc_list,
    inspect_dump,
    pg_restore_list,
    pg_restore_version_major,
)
from human_simulator.stage02.pg_restore_cmd import (
    RESTORE_FORBIDDEN_FLAGS,
    RESTORE_REQUIRED_FLAGS,
    build_pg_restore_argv,
    build_redacted_pg_restore_command,
)
from human_simulator.stage02.settings import KGZ_TARGET_DATABASE, KgzRestoreSettings, SourceABaseline

CheckStatus = Literal["PASS", "FAIL", "SKIP", "WARN"]


@dataclass
class PreflightCheck:
    name: str
    status: CheckStatus
    message: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class PreflightResult:
    generated_at: str
    target_database: str
    dump_path: str
    checks: list[PreflightCheck]
    dump_metadata: dict[str, object] | None = None
    pg_restore_toc_sample: list[str] = field(default_factory=list)
    pg_restore_command_redacted: str = ""
    restore_policy: str = ""

    @property
    def status(self) -> Literal["PASS", "FAIL", "PARTIAL"]:
        if any(c.status == "FAIL" for c in self.checks):
            return "FAIL"
        if any(c.status in {"SKIP", "WARN"} for c in self.checks):
            return "PARTIAL"
        return "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "target_database": self.target_database,
            "dump_path": self.dump_path,
            "status": self.status,
            "checks": [asdict(c) for c in self.checks],
            "dump_metadata": self.dump_metadata,
            "pg_restore_toc_sample": self.pg_restore_toc_sample,
            "pg_restore_command_redacted": self.pg_restore_command_redacted,
            "restore_policy": self.restore_policy,
        }


def _check_dump_exists(settings: KgzRestoreSettings) -> PreflightCheck:
    path = settings.dump_absolute
    if path.is_file():
        return PreflightCheck("dump_exists", "PASS", "Dump file found", {"path": str(path)})
    return PreflightCheck("dump_exists", "FAIL", "Dump file missing", {"path": str(path)})


def _check_dump_format(metadata: DumpMetadata | None) -> PreflightCheck:
    if metadata is None:
        return PreflightCheck("dump_format", "FAIL", "Dump metadata unavailable", {})
    return PreflightCheck(
        "dump_format",
        "PASS",
        "PostgreSQL custom format (PGDMP)",
        {"format": metadata.format_label, "archive_version": metadata.archive_version},
    )


def _check_dump_sha256(metadata: DumpMetadata | None) -> PreflightCheck:
    if metadata is None:
        return PreflightCheck("dump_sha256", "FAIL", "Cannot compute SHA-256", {})
    return PreflightCheck(
        "dump_sha256",
        "PASS",
        "SHA-256 computed",
        {"sha256": metadata.sha256},
    )


def _check_dump_size(metadata: DumpMetadata | None) -> PreflightCheck:
    if metadata is None:
        return PreflightCheck("dump_size", "FAIL", "Cannot read dump size", {})
    return PreflightCheck(
        "dump_size",
        "PASS",
        "Dump size recorded",
        {"size_bytes": metadata.size_bytes, "size_human": _human_size(metadata.size_bytes)},
    )


def _human_size(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} B"
        num /= 1024
    return f"{num:.1f} PB"


def _check_pg_restore_compat(metadata: DumpMetadata | None) -> PreflightCheck:
    if metadata is None:
        return PreflightCheck("pg_restore_compat", "FAIL", "Cannot verify pg_restore compatibility", {})
    major = pg_restore_version_major(metadata.pg_restore_version)
    details: dict[str, object] = {
        "pg_restore_version": metadata.pg_restore_version,
        "archive_version": metadata.archive_version,
        "pg_restore_list_exit_code": metadata.pg_restore_list_exit_code,
        "toc_entry_count": metadata.toc_entry_count,
    }
    if metadata.pg_restore_list_exit_code != 0:
        return PreflightCheck("pg_restore_compat", "FAIL", "pg_restore --list failed", details)
    if major is not None and major < 14:
        return PreflightCheck(
            "pg_restore_compat",
            "WARN",
            "pg_restore major version below 14; verify manually",
            details,
        )
    return PreflightCheck("pg_restore_compat", "PASS", "pg_restore --list succeeded", details)


def _check_disk_space(settings: KgzRestoreSettings, metadata: DumpMetadata | None) -> PreflightCheck:
    if metadata is None:
        return PreflightCheck("disk_space", "FAIL", "Cannot estimate required disk space", {})
    required = int(metadata.size_bytes * settings.disk_space_multiplier)
    usage = shutil.disk_usage(settings.dump_absolute.parent)
    details = {
        "required_bytes": required,
        "required_human": _human_size(required),
        "free_bytes": usage.free,
        "free_human": _human_size(usage.free),
        "multiplier": settings.disk_space_multiplier,
    }
    if usage.free >= required:
        return PreflightCheck("disk_space", "PASS", "Sufficient free disk space", details)
    return PreflightCheck("disk_space", "FAIL", "Insufficient free disk space", details)


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_port_5435(settings: KgzRestoreSettings, repo_root: Path) -> PreflightCheck:
    host = settings.pg_host
    port = settings.pg_port
    open_ = _port_open(host, port)
    details: dict[str, object] = {"host": host, "port": port, "port_open": open_}

    if not open_:
        return PreflightCheck(
            "port_5435",
            "PASS",
            "Port available for kgz-db binding",
            details,
        )

    compose_port = subprocess.run(
        ["docker", "compose", "port", "kgz-db", "5432"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    ps = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "kgz-db", "--format", "{{.Name}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    details["docker_compose_port"] = compose_port.stdout.strip()
    details["docker_container_name"] = ps.stdout.strip()

    expected_suffix = f":{port}"
    port_mapping_ok = compose_port.returncode == 0 and compose_port.stdout.strip().endswith(expected_suffix)
    container_ok = ps.returncode == 0 and "human-simulator-kgz-db" in ps.stdout

    details["expected_service"] = "kgz-db"
    details["expected_container"] = "human-simulator-kgz-db"
    details["port_mapping_ok"] = port_mapping_ok
    details["container_running_ok"] = container_ok

    if port_mapping_ok and container_ok:
        return PreflightCheck(
            "port_5435",
            "PASS",
            "Port 5435 belongs to expected kgz-db service",
            details,
        )
    return PreflightCheck(
        "port_5435",
        "FAIL",
        "Port is open but not mapped to expected kgz-db container",
        details,
    )


def _count_user_tables(engine: Engine) -> int:
    """Count base tables not owned by installed extensions (PostGIS bootstrap excluded)."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT count(*)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r'
                  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                  AND NOT EXISTS (
                    SELECT 1
                    FROM pg_depend d
                    JOIN pg_extension e ON e.oid = d.refobjid
                    WHERE d.classid = 'pg_class'::regclass
                      AND d.objid = c.oid
                      AND d.objsubid = 0
                  )
                """
            )
        )
        return int(result.scalar_one())


def _check_kgz_raw_empty(settings: KgzRestoreSettings) -> PreflightCheck:
    if settings.pg_database != KGZ_TARGET_DATABASE:
        return PreflightCheck(
            "kgz_raw_empty",
            "FAIL",
            f"Target database must be {KGZ_TARGET_DATABASE!r}",
            {"configured_database": settings.pg_database},
        )
    if not _port_open(settings.pg_host, settings.pg_port):
        return PreflightCheck(
            "kgz_raw_empty",
            "SKIP",
            "kgz-db not reachable; empty-database check deferred until service is up",
            {"redacted_url": settings.redacted_url},
        )
    try:
        engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
        try:
            table_count = _count_user_tables(engine)
        finally:
            engine.dispose()
    except Exception as exc:
        return PreflightCheck(
            "kgz_raw_empty",
            "SKIP",
            "Could not connect to kgz-db (check db-kgz.env credentials when service is running)",
            {"redacted_url": settings.redacted_url, "error_type": type(exc).__name__},
        )
    if table_count == 0:
        return PreflightCheck(
            "kgz_raw_empty",
            "PASS",
            "Target database is empty (no non-extension user tables)",
            {"table_count": table_count, "database": settings.pg_database},
        )
    return PreflightCheck(
        "kgz_raw_empty",
        "FAIL",
        "Target database is not empty; restore refused",
        {"table_count": table_count, "database": settings.pg_database},
    )


def _connect_engine(settings: KgzRestoreSettings) -> Engine | None:
    if not _port_open(settings.pg_host, settings.pg_port):
        return None
    try:
        return create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    except Exception:
        return None


def _check_target_postgresql_version(settings: KgzRestoreSettings) -> PreflightCheck:
    engine = _connect_engine(settings)
    if engine is None:
        return PreflightCheck(
            "target_postgresql_version",
            "SKIP",
            "kgz-db not reachable",
            {"redacted_url": settings.redacted_url},
        )
    try:
        with engine.connect() as conn:
            version = str(conn.execute(text("SHOW server_version")).scalar_one())
            full_version = str(conn.execute(text("SELECT version()")).scalar_one())
            db_name = str(conn.execute(text("SELECT current_database()")).scalar_one())
    finally:
        engine.dispose()

    return PreflightCheck(
        "target_postgresql_version",
        "PASS",
        "Target PostgreSQL version recorded",
        {
            "server_version": version,
            "version_string": full_version.split(",")[0],
            "current_database": db_name,
            "redacted_url": settings.redacted_url,
        },
    )


def _check_dump_extensions_available(
    settings: KgzRestoreSettings,
    metadata: DumpMetadata | None,
) -> PreflightCheck:
    if metadata is None or not metadata.dump_extensions:
        return PreflightCheck(
            "dump_extensions_available",
            "FAIL",
            "No extensions found in dump TOC",
            {},
        )
    engine = _connect_engine(settings)
    if engine is None:
        return PreflightCheck(
            "dump_extensions_available",
            "SKIP",
            "kgz-db not reachable",
            {"required_extensions": list(metadata.dump_extensions)},
        )
    required = list(metadata.dump_extensions)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM pg_available_extensions WHERE name = ANY(:names)"),
                {"names": required},
            ).fetchall()
            installed = conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = ANY(:names)"),
                {"names": required},
            ).fetchall()
    finally:
        engine.dispose()

    available = {str(r[0]) for r in rows}
    already_installed = {str(r[0]) for r in installed}
    missing = [name for name in required if name not in available]
    details = {
        "required_extensions": required,
        "available_extensions": sorted(available),
        "already_installed": sorted(already_installed),
        "missing_from_available": missing,
    }
    if missing:
        return PreflightCheck(
            "dump_extensions_available",
            "FAIL",
            f"Extensions not available on target: {', '.join(missing)}",
            details,
        )
    return PreflightCheck(
        "dump_extensions_available",
        "PASS",
        "All dump extensions available on target (including pg_stat_statements if present)",
        details,
    )


def _check_toc_entry_discrepancy(toc: TocAnalysis | None) -> PreflightCheck:
    if toc is None:
        return PreflightCheck("toc_entry_discrepancy", "FAIL", "TOC analysis unavailable", {})
    details = {
        "header_toc_entries": toc.header_toc_entries,
        "listed_active_entries": toc.listed_active_entries,
        "comment_lines": toc.comment_lines,
        "discrepancy": toc.discrepancy,
        "explanation": toc.explanation,
    }
    return PreflightCheck(
        "toc_entry_discrepancy",
        "PASS",
        "TOC header vs list discrepancy explained",
        details,
    )


def _check_pg_restore_command(settings: KgzRestoreSettings) -> PreflightCheck:
    argv = build_pg_restore_argv(settings)
    forbidden_present = [f for f in RESTORE_FORBIDDEN_FLAGS if f in argv]
    missing_required = [f for f in RESTORE_REQUIRED_FLAGS if f not in argv]
    redacted = build_redacted_pg_restore_command(settings)
    details = {
        "command_redacted": redacted,
        "forbidden_flags_absent": RESTORE_FORBIDDEN_FLAGS,
        "required_flags_present": RESTORE_REQUIRED_FLAGS,
        "forbidden_found": forbidden_present,
        "missing_required": missing_required,
    }
    if forbidden_present or missing_required:
        return PreflightCheck(
            "pg_restore_command",
            "FAIL",
            "pg_restore command flags invalid",
            details,
        )
    return PreflightCheck(
        "pg_restore_command",
        "PASS",
        "pg_restore command uses --no-owner and --no-privileges; no --clean/--create/--drop",
        details,
    )


def _check_restore_policy() -> PreflightCheck:
    policy = (
        "audit restore-second-source --confirm refuses restore when preflight status "
        "is FAIL or PARTIAL (any SKIP/FAIL/WARN check)."
    )
    return PreflightCheck(
        "restore_policy",
        "PASS",
        policy,
        {"requires_preflight_status": "PASS"},
    )


def _read_compose_service(repo_root: Path, service: str) -> dict[str, object]:
    compose_path = repo_root / "docker-compose.yml"
    if not compose_path.exists():
        return {}
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    return data.get("services", {}).get(service, {}) or {}


def _check_source_a_unchanged(repo_root: Path, baseline: SourceABaseline) -> PreflightCheck:
    mg = _read_compose_service(repo_root, baseline.compose_service)
    ports = mg.get("ports") or []
    port_ok = any(str(baseline.compose_port_mapping) in str(p) for p in ports)

    kgz = _read_compose_service(repo_root, "kgz-db")
    kgz_ports = kgz.get("ports") or []
    kgz_isolated = any("5435:5432" in str(p) for p in kgz_ports)

    details: dict[str, object] = {
        "expected_host": baseline.pg_host,
        "expected_port": baseline.pg_port,
        "expected_database": baseline.pg_database,
        "expected_user": baseline.pg_user,
        "compose_mg_db_port_mapping_ok": port_ok,
        "compose_kgz_db_isolated": kgz_isolated,
    }

    failures: list[str] = []
    if not port_ok:
        failures.append("mg-db port mapping changed")
    if not kgz_isolated:
        failures.append("kgz-db not configured on 5435:5432")

    current = SourceABaseline.from_repo(repo_root)
    if current.pg_database != baseline.pg_database:
        failures.append("source A database name changed in config")
    if current.pg_port != baseline.pg_port:
        failures.append("source A port changed in config")

    if failures:
        details["failures"] = failures
        return PreflightCheck("source_a_unchanged", "FAIL", "; ".join(failures), details)

    return PreflightCheck(
        "source_a_unchanged",
        "PASS",
        "Source A configuration unchanged; kgz-db isolated on port 5435",
        details,
    )


def run_preflight(
    settings: KgzRestoreSettings,
    *,
    include_toc_sample: bool = True,
    toc_sample_lines: int = 20,
) -> PreflightResult:
    baseline = SourceABaseline.from_repo(settings.repo_root)
    checks: list[PreflightCheck] = []
    metadata: DumpMetadata | None = None
    toc_analysis: TocAnalysis | None = None
    toc_sample: list[str] = []

    exists = _check_dump_exists(settings)
    checks.append(exists)

    if exists.status == "PASS":
        try:
            metadata = inspect_dump(settings.dump_absolute)
        except DumpInspectError as exc:
            checks.append(
                PreflightCheck("dump_inspect", "FAIL", str(exc), {})
            )
        else:
            list_rc, toc_stdout, toc_analysis = pg_restore_list(settings.dump_absolute)
            if list_rc != 0:
                checks.append(PreflightCheck("dump_inspect", "FAIL", "pg_restore --list failed", {}))
            elif include_toc_sample:
                toc_sample = toc_stdout.splitlines()[:toc_sample_lines]

    checks.extend(
        [
            _check_dump_format(metadata),
            _check_dump_sha256(metadata),
            _check_dump_size(metadata),
            _check_pg_restore_compat(metadata),
            _check_disk_space(settings, metadata),
            _check_toc_entry_discrepancy(toc_analysis),
            _check_port_5435(settings, settings.repo_root),
            _check_kgz_raw_empty(settings),
            _check_target_postgresql_version(settings),
            _check_dump_extensions_available(settings, metadata),
            _check_source_a_unchanged(settings.repo_root, baseline),
            _check_pg_restore_command(settings),
            _check_restore_policy(),
        ]
    )

    dump_meta_dict: dict[str, object] | None = None
    if metadata:
        dump_meta_dict = {
            "path": str(metadata.path),
            "size_bytes": metadata.size_bytes,
            "sha256": metadata.sha256,
            "format_label": metadata.format_label,
            "archive_version": metadata.archive_version,
            "toc_entry_count": metadata.toc_entry_count,
            "toc_header_count": metadata.toc_header_count,
            "dump_extensions": list(metadata.dump_extensions),
            "pg_restore_version": metadata.pg_restore_version,
        }

    redacted_cmd = build_redacted_pg_restore_command(settings)
    restore_policy = (
        "restore-second-source requires preflight status PASS; any FAIL, SKIP, or WARN blocks restore."
    )

    return PreflightResult(
        generated_at=datetime.now(UTC).isoformat(),
        target_database=settings.pg_database,
        dump_path=str(settings.dump_absolute),
        checks=checks,
        dump_metadata=dump_meta_dict,
        pg_restore_toc_sample=toc_sample,
        pg_restore_command_redacted=redacted_cmd,
        restore_policy=restore_policy,
    )


def write_preflight_artifacts(result: PreflightResult, artifacts_dir: Path) -> tuple[Path, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    json_path = artifacts_dir / "restore-preflight.json"
    md_path = artifacts_dir / "restore-preflight.md"

    json_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_preflight_markdown(result), encoding="utf-8")
    return json_path, md_path


def render_preflight_markdown(result: PreflightResult) -> str:
    lines = [
        "# Restore preflight — source B (kgz)",
        "",
        f"**Generated:** {result.generated_at}",
        f"**Target database:** `{result.target_database}` (explicit, not from dump TOC)",
        f"**Dump path:** `{result.dump_path}`",
        f"**Overall preflight status:** **{result.status}**",
        "",
        "## Checks",
        "",
        "| Check | Status | Message |",
        "|-------|--------|---------|",
    ]
    for check in result.checks:
        lines.append(f"| `{check.name}` | {check.status} | {check.message} |")

    lines.extend(["", "## Check details", ""])
    for check in result.checks:
        if not check.details:
            continue
        lines.append(f"### `{check.name}`")
        lines.append("")
        for key, value in check.details.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")

    if result.dump_metadata:
        lines.extend(["## Dump metadata", ""])
        for key, value in result.dump_metadata.items():
            lines.append(f"- **{key}:** `{value}`")
        lines.append("")

    if result.pg_restore_command_redacted:
        lines.extend(
            [
                "## Planned pg_restore (redacted credentials)",
                "",
                "```bash",
                result.pg_restore_command_redacted,
                "```",
                "",
                f"Forbidden flags (absent): {', '.join(RESTORE_FORBIDDEN_FLAGS)}",
                f"Required flags (present): {', '.join(RESTORE_REQUIRED_FLAGS)}",
                "",
            ]
        )

    if result.restore_policy:
        lines.extend(["## Restore policy", "", result.restore_policy, ""])

    if result.pg_restore_toc_sample:
        lines.extend(["## pg_restore --list (sample, first entries)", "", "```"])
        lines.extend(result.pg_restore_toc_sample)
        lines.append("```")
        lines.append("")

    lines.extend(
        [
            "## Next step",
            "",
            "Restore is **not** executed by preflight. After review, run in order:",
            "",
            "```bash",
            "cp db-kgz.env.example db-kgz.env   # set POSTGRES_PASSWORD locally (once)",
            "docker compose up -d kgz-db",
            "audit --root . restore-preflight",
            "audit --root . restore-second-source --confirm",
            "```",
            "",
            "Restore refuses non-empty `kgz_raw`, requires `--confirm`, and blocks on any preflight FAIL/SKIP/WARN.",
        ]
    )
    return "\n".join(lines) + "\n"
