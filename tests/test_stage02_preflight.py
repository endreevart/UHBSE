"""Tests for Stage 02 restore preflight."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from human_simulator.stage02.dump_inspect import DumpInspectError, inspect_dump
from human_simulator.stage02.preflight import run_preflight, write_preflight_artifacts
from human_simulator.stage02.settings import KgzRestoreSettings


@pytest.fixture
def kgz_settings(tmp_path: Path) -> KgzRestoreSettings:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sources.example.yaml").write_text(
        """
sources:
  local_stage:
    host: localhost
    port: 5434
    database: magerya_api
    user: magerya_api
  local_kgz:
    host: localhost
    port: 5435
    database: kgz_raw
    user: kgz_raw
dumps:
  kgz: kgz-test.dump
stage02:
  target_database: kgz_raw
  artifacts_dir: artifacts/stage-02
""".strip(),
        encoding="utf-8",
    )
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        """
services:
  mg-db:
    ports: ["5434:5432"]
  kgz-db:
    ports: ["5435:5432"]
volumes:
  mg-db-data: {}
  kgz-db-data: {}
""".strip(),
        encoding="utf-8",
    )
    dump = tmp_path / "kgz-test.dump"
    dump.write_bytes(b"PGDMP" + b"\x01\x0e" + b"\x00" * 100)
    return KgzRestoreSettings.from_repo(tmp_path)


def test_inspect_dump_requires_pgdmp_header(tmp_path: Path) -> None:
    bad = tmp_path / "bad.dump"
    bad.write_bytes(b"NOTPG")
    with pytest.raises(DumpInspectError, match="unsupported dump format"):
        inspect_dump(bad)


@patch("human_simulator.stage02.preflight.inspect_dump")
@patch("human_simulator.stage02.preflight.pg_restore_list")
@patch("human_simulator.stage02.preflight._port_open", return_value=False)
def test_preflight_passes_without_db(
    _port: object,
    mock_list: object,
    mock_inspect: object,
    kgz_settings: KgzRestoreSettings,
) -> None:
    from human_simulator.stage02.dump_inspect import DumpMetadata, TocAnalysis

    toc = TocAnalysis(
        header_toc_entries=788,
        listed_active_entries=783,
        comment_lines=10,
        dump_extensions=("pg_stat_statements",),
        discrepancy=5,
        explanation="test",
    )
    mock_list.return_value = (0, "; TOC Entries: 788\n1; TABLE\n", toc)
    mock_inspect.return_value = DumpMetadata(
        path=kgz_settings.dump_absolute,
        size_bytes=105,
        sha256="abc123",
        format_label="postgresql_custom",
        archive_version="1.14",
        toc_entry_count=783,
        toc_header_count=788,
        toc_comment_lines=10,
        dump_extensions=("pg_stat_statements",),
        pg_restore_version="pg_restore (PostgreSQL) 16.0",
        pg_restore_list_exit_code=0,
    )
    result = run_preflight(kgz_settings)
    names = {c.name: c.status for c in result.checks}
    assert names["dump_exists"] == "PASS"
    assert names["dump_format"] == "PASS"
    assert names["kgz_raw_empty"] == "SKIP"
    assert names["source_a_unchanged"] == "PASS"
    assert names["pg_restore_command"] == "PASS"
    assert result.status in {"PARTIAL", "FAIL"}


@patch("human_simulator.stage02.preflight.inspect_dump")
@patch("human_simulator.stage02.preflight.pg_restore_list")
@patch("human_simulator.stage02.preflight._port_open", return_value=True)
@patch("human_simulator.stage02.preflight.create_engine")
def test_preflight_fails_when_kgz_not_empty(
    mock_engine: object,
    _port: object,
    mock_list: object,
    mock_inspect: object,
    kgz_settings: KgzRestoreSettings,
) -> None:
    from human_simulator.stage02.dump_inspect import DumpMetadata, TocAnalysis

    toc = TocAnalysis(788, 1, 1, ("pg_stat_statements",), 787, "test")
    mock_list.return_value = (0, "1; TABLE public foo\n", toc)
    mock_inspect.return_value = DumpMetadata(
        path=kgz_settings.dump_absolute,
        size_bytes=105,
        sha256="abc123",
        format_label="postgresql_custom",
        archive_version="1.14",
        toc_entry_count=1,
        toc_header_count=788,
        toc_comment_lines=1,
        dump_extensions=("pg_stat_statements",),
        pg_restore_version="pg_restore (PostgreSQL) 16.0",
        pg_restore_list_exit_code=0,
    )
    conn = mock_engine.return_value.connect.return_value.__enter__.return_value
    conn.execute.return_value.scalar_one.return_value = 5

    result = run_preflight(kgz_settings)
    kgz_check = next(c for c in result.checks if c.name == "kgz_raw_empty")
    assert kgz_check.status == "FAIL"
    assert result.status == "FAIL"


def test_write_preflight_artifacts(kgz_settings: KgzRestoreSettings) -> None:
    from human_simulator.stage02.dump_inspect import DumpMetadata, TocAnalysis

    toc = TocAnalysis(788, 783, 10, ("pg_stat_statements",), 5, "test")
    with patch("human_simulator.stage02.preflight.inspect_dump") as mock_inspect:
        mock_inspect.return_value = DumpMetadata(
            path=kgz_settings.dump_absolute,
            size_bytes=105,
            sha256="abc123",
            format_label="postgresql_custom",
            archive_version="1.14",
            toc_entry_count=783,
            toc_header_count=788,
            toc_comment_lines=10,
            dump_extensions=("pg_stat_statements",),
            pg_restore_version="pg_restore (PostgreSQL) 16.0",
            pg_restore_list_exit_code=0,
        )
        with patch("human_simulator.stage02.preflight.pg_restore_list", return_value=(0, "1; x\n", toc)):
            with patch("human_simulator.stage02.preflight._port_open", return_value=False):
                result = run_preflight(kgz_settings)
    artifacts = kgz_settings.repo_root / kgz_settings.artifacts_dir
    json_path, md_path = write_preflight_artifacts(result, artifacts)
    assert json_path.exists()
    assert md_path.exists()
    assert "kgz_raw" in md_path.read_text(encoding="utf-8")
