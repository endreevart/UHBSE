"""Tests for Stage 02 restore command guards."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from human_simulator.cli import main
from human_simulator.stage02.restore import RestoreError, restore_second_source
from human_simulator.stage02.settings import KgzRestoreSettings


@pytest.fixture
def kgz_settings(tmp_path: Path) -> KgzRestoreSettings:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sources.example.yaml").write_text(
        """
sources:
  local_kgz:
    host: localhost
    port: 5435
    database: kgz_raw
    user: kgz_raw
dumps:
  kgz: kgz-test.dump
stage02:
  target_database: kgz_raw
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "kgz-test.dump").write_bytes(b"PGDMP" + b"\x01\x0e" + b"\x00" * 50)
    return KgzRestoreSettings.from_repo(tmp_path)


def test_restore_requires_confirm(kgz_settings: KgzRestoreSettings) -> None:
    with pytest.raises(RestoreError, match="--confirm"):
        restore_second_source(kgz_settings, confirm=False)


def test_cli_restore_without_confirm(kgz_settings: KgzRestoreSettings) -> None:
    code = main(["--root", str(kgz_settings.repo_root), "restore-second-source"])
    assert code == 1


@patch("human_simulator.stage02.restore.run_preflight")
def test_restore_blocked_on_partial_preflight(
    mock_preflight: object,
    kgz_settings: KgzRestoreSettings,
) -> None:
    from human_simulator.stage02.preflight import PreflightCheck, PreflightResult

    mock_preflight.return_value = PreflightResult(
        generated_at="2026-01-01T00:00:00+00:00",
        target_database="kgz_raw",
        dump_path=str(kgz_settings.dump_absolute),
        checks=[PreflightCheck("kgz_raw_empty", "SKIP", "deferred", {})],
    )
    with pytest.raises(RestoreError, match="Preflight must be PASS"):
        restore_second_source(kgz_settings, confirm=True)


@patch("human_simulator.stage02.restore._run_pg_restore", return_value=(0, "", ""))
@patch("human_simulator.stage02.restore.collect_database_inventory", return_value={"table_count": 1})
@patch("human_simulator.stage02.restore.create_readonly_audit_user", return_value={"username": "kgz_audit_ro"})
@patch("human_simulator.stage02.restore.verify_readonly_audit_user", return_value={"read_only_ok": True})
@patch("human_simulator.stage02.restore.verify_source_a_unchanged", return_value={"unchanged": True})
@patch("human_simulator.stage02.restore.pg_restore_version_in_container", return_value="pg_restore 14")
@patch("human_simulator.stage02.restore.run_preflight")
@patch("human_simulator.stage02.restore._run_compose_up")
@patch("human_simulator.stage02.restore._assert_database_empty")
def test_restore_with_confirm_mocked(
    _empty: object,
    _compose: object,
    mock_preflight: object,
    _ver: object,
    _sa: object,
    _ro: object,
    _create: object,
    _inv: object,
    _pg: object,
    kgz_settings: KgzRestoreSettings,
) -> None:
    from human_simulator.stage02.preflight import PreflightResult

    mock_preflight.return_value = PreflightResult(
        generated_at="2026-01-01T00:00:00+00:00",
        target_database="kgz_raw",
        dump_path=str(kgz_settings.dump_absolute),
        checks=[],
        dump_metadata={},
        pg_restore_command_redacted="",
        restore_policy="",
    )
    report, _ = restore_second_source(kgz_settings, confirm=True)
    assert report.restore_performed is True
    assert report.pg_restore_exit_code == 0
    assert "***" in report.redacted_url or report.auditor_connection
