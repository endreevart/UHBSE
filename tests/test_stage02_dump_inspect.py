"""Tests for TOC analysis and pg_restore command builder."""

from __future__ import annotations

from human_simulator.stage02.dump_inspect import analyze_toc_list
from human_simulator.stage02.pg_restore_cmd import (
    RESTORE_FORBIDDEN_FLAGS,
    RESTORE_REQUIRED_FLAGS,
    build_pg_restore_argv,
    build_redacted_pg_restore_command,
)
from human_simulator.stage02.settings import KgzRestoreSettings


SAMPLE_TOC = """
;
; Archive created at 2023-12-04 08:21:14 MSK
;     TOC Entries: 788
;
7; 2615 673534 SCHEMA - quest_digital magerya_base
2; 3079 234346 EXTENSION - pg_stat_statements
5096; 0 0 COMMENT - EXTENSION pg_stat_statements
205; 1259 673535 TABLE public abac_rules magerya_base
""".strip()


def test_analyze_toc_discrepancy() -> None:
    toc = analyze_toc_list(SAMPLE_TOC)
    assert toc.header_toc_entries == 788
    assert toc.listed_active_entries == 4
    assert toc.discrepancy == 784
    assert "pg_stat_statements" in toc.dump_extensions


def test_pg_restore_argv_flags(tmp_path) -> None:
    settings = KgzRestoreSettings(repo_root=tmp_path)
    argv = build_pg_restore_argv(settings)
    for flag in RESTORE_REQUIRED_FLAGS:
        assert flag in argv
    for flag in RESTORE_FORBIDDEN_FLAGS:
        assert flag not in argv


def test_redacted_command(tmp_path) -> None:
    settings = KgzRestoreSettings(repo_root=tmp_path)
    cmd = build_redacted_pg_restore_command(settings)
    assert "kgz_raw" in cmd
    assert "--no-privileges" in cmd
    assert "--clean" not in cmd
