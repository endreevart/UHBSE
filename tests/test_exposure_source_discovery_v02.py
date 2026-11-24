"""Unit and contract tests for exposure-source discovery v0.2."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from human_simulator.exposure_source_discovery_v02.baseline import verify_baseline
from human_simulator.exposure_source_discovery_v02.decisions import semantics_status
from human_simulator.exposure_source_discovery_v02.limitations import reproduce
from human_simulator.exposure_source_discovery_v02.mutations import run_negative_controls
from human_simulator.exposure_source_discovery_v02.policy import SCIENTIFIC_CEILING
from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v02.textutil import CatalogMatcher, classify_sentinel

ROOT = Path(__file__).resolve().parents[1]


def test_baseline_matches_pinned_v01() -> None:
    result = verify_baseline(ROOT)
    assert result["BASELINE_VERIFICATION_STATUS"] == "PASS"


def test_v01_limitations_reproduce() -> None:
    result = reproduce(ROOT)
    assert result["ok"] is True
    assert result["not_a_stage_05_v011_defect"] is True
    assert [item["claim"] for item in result["claims"]] == list(range(1, 9))
    assert all(item["holds"] for item in result["claims"])


def test_sentinels_do_not_treat_short_answers_as_medication() -> None:
    assert classify_sentinel(None) == "NULL"
    assert classify_sentinel("  ") == "EMPTY"
    assert classify_sentinel("нет") == "NEGATIVE_SHORT"
    assert classify_sentinel("да") == "AFFIRMATIVE_SHORT"
    assert classify_sentinel("123") == "NUMERIC_ONLY"
    assert classify_sentinel("магний утром после еды две недели") == "FREE_TEXT_LONG"


def test_catalog_matcher_keeps_methods_separate() -> None:
    matcher = CatalogMatcher(["Магний B6", "Магний", "и"])
    exact = matcher.match_text("магний b6")
    assert exact["exact"] is True
    inside = matcher.match_text("назначено: магний b6 после еды")
    assert inside["exact"] is False
    assert inside["boundary"]
    fingerprint = matcher.fingerprint()
    assert fingerprint["accepted_identity"] is False
    assert fingerprint["common_word_or_short_terms"] >= 1


def test_numeric_patient_id_fails_privacy(tmp_path: Path) -> None:
    (tmp_path / "leak.json").write_text(json.dumps({"patient_id": 15}) + "\n", encoding="utf-8")
    scan = scan_public(tmp_path)
    assert scan["PUBLIC_DATA_MINIMIZATION_STATUS"] == "FAIL"
    assert scan["checks_executed"]["numeric_identifier"] is True


def test_schema_field_name_in_markdown_is_not_a_row(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("Field `patient_id` is a column name, not a value.\n", encoding="utf-8")
    (tmp_path / "counts.json").write_text(json.dumps({"rows_counted": 12, "fraction": 0.5}) + "\n", encoding="utf-8")
    scan = scan_public(tmp_path)
    assert scan["ok"] is True


def test_negative_controls_reject_all(tmp_path: Path) -> None:
    result = run_negative_controls(tmp_path)
    assert result["n_cases"] == 20
    assert result["n_rejected"] == 20
    assert result["NEGATIVE_CONTROL_STATUS"] == "PASS"


def test_scientific_ceiling_and_pending_semantics() -> None:
    assert SCIENTIFIC_CEILING["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
    assert SCIENTIFIC_CEILING["INTERVENTION_RESPONSE_MODEL_STATUS"] == "NOT_STARTED"
    assert SCIENTIFIC_CEILING["CONFIRMED_ADMINISTRATION_MAPPING_COUNT"] == 0
    assert semantics_status(None) == "UNKNOWN_PENDING_HUMAN_REVIEW"
    assert semantics_status([{"decision": None}]) == "UNKNOWN_PENDING_HUMAN_REVIEW"


def test_two_process_replay_is_deterministic() -> None:
    code = (
        "import json; from human_simulator.exposure_source_discovery_v02.textutil import classify_sentinel; "
        "from human_simulator.exposure_source_discovery_v02.limitations import reproduce; "
        "from pathlib import Path; "
        "print(json.dumps({'sentinel': classify_sentinel('нет'), 'limits': reproduce(Path('.'))['ok']}))"
    )
    results = []
    for _ in range(2):
        proc = subprocess.run(
            ["uv", "run", "--frozen", "--no-sync", "python", "-c", code],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr[-500:]
        results.append(proc.stdout.strip())
    assert results[0] == results[1]


def test_v01_package_was_not_given_a_write_api() -> None:
    source = (ROOT / "src/human_simulator/exposure_source_discovery_v02/orchestrator.py").read_text(encoding="utf-8")
    assert "exposure-source-discovery-v0.1" not in source or "verify_baseline" in source
    assert "external-review" not in source
