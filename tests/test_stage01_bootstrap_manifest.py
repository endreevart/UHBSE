"""Tests for Stage 01 preliminary bootstrap and manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from human_simulator.stage01.bootstrap_from_dump import (
    PRELIMINARY_DIR_NAME,
    PRELIMINARY_STATUS,
    bootstrap_preliminary_from_dump,
)
from human_simulator.stage01.manifest import STAGE01_MANIFEST_ARTIFACTS, verify_manifest, write_manifest


def test_bootstrap_preliminary_writes_non_final_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dump = tmp_path / "dumps" / "stage_magerya_api.dump"
    dump.parent.mkdir(parents=True)
    dump.write_bytes(b"PGDMP")  # will fail pg_restore unless mocked

    def _fake_profile(*args, **kwargs):
        return {
            "profiled_at": "2026-01-01T00:00:00+00:00",
            "database": "magerya_api",
            "relations": [{"schema": "magerya_api", "name": "account_patient", "kind": "table"}],
            "columns": [],
            "foreign_keys": [],
            "relation_count": 1,
        }

    monkeypatch.setattr(
        "human_simulator.stage01.bootstrap_from_dump.profile_schema_from_dump",
        _fake_profile,
    )

    result = bootstrap_preliminary_from_dump(tmp_path, dump)
    assert result["status"] == PRELIMINARY_STATUS

    prelim_dir = tmp_path / "artifacts" / PRELIMINARY_DIR_NAME
    audit = json.loads((prelim_dir / "source-audit.json").read_text(encoding="utf-8"))
    assert audit["reachable"] is False
    assert audit["readonly_user_only"] is False
    assert audit["status"] == PRELIMINARY_STATUS
    assert (prelim_dir / "stage-01-preliminary-report.json").exists()
    assert not (prelim_dir / "stage-01-report.md").exists()


def test_manifest_roundtrip(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts" / "stage-01"
    artifacts.mkdir(parents=True)
    for name in STAGE01_MANIFEST_ARTIFACTS[:3]:
        (artifacts / name).write_text(f"content-{name}\n", encoding="utf-8")

    hashes = write_manifest(artifacts)
    assert len(hashes) == 3
    ok, detail = verify_manifest(artifacts)
    assert ok, detail

    (artifacts / "source-audit.json").write_text("tampered\n", encoding="utf-8")
    ok, detail = verify_manifest(artifacts)
    assert not ok
    assert "hash mismatch" in detail
