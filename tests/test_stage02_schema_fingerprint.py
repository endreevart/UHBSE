"""Tests for schema fingerprint comparison."""

from __future__ import annotations

from human_simulator.stage02.schema_fingerprint import _fingerprint_rows_from_sql


def test_fingerprint_deterministic() -> None:
    rows = [("public", "patients", "id", "integer"), ("public", "visits", "id", "integer")]
    a = _fingerprint_rows_from_sql(rows)
    b = _fingerprint_rows_from_sql(list(reversed(rows)))
    assert a["sha256"] == b["sha256"]
    assert a["table_count"] == 2
