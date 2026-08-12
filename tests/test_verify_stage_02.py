"""Tests for verify-stage-02."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from human_simulator.audit.report import REPORT_STATUS_DRAFT, REPORT_STATUS_FINAL
from human_simulator.stage02.verify_stage_02 import (
    FINAL_MANIFEST_NAME,
    PytestRunResult,
    extract_unresolved_mappings,
    verify_stage_02,
    _parse_pytest_output,
    _run_pytest,
    _verify_final_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_parse_pytest_output_complete_run() -> None:
    parsed = _parse_pytest_output("127 passed in 2.28s")
    assert parsed == {"collected": 127, "passed": 127, "failed": 0, "skipped": 0, "error": 0}


def test_parse_pytest_output_with_skipped() -> None:
    parsed = _parse_pytest_output("126 passed, 1 skipped in 2.00s")
    assert parsed["passed"] == 126
    assert parsed["skipped"] == 1
    assert parsed["collected"] == 127


def test_extract_unresolved_mappings_from_crosswalk_file() -> None:
    crosswalk_path = REPO_ROOT / "artifacts" / "stage-02" / "entity-crosswalk.yaml"
    if not crosswalk_path.exists():
        pytest.skip("entity-crosswalk.yaml unavailable")
    crosswalk = yaml.safe_load(crosswalk_path.read_text(encoding="utf-8"))
    unresolved = extract_unresolved_mappings(crosswalk)
    assert len(unresolved) == 17
    assert "measurements:None->public.profilaxys_analyses" in unresolved
    assert "appointments:magerya_api.appointment_appointment->public.consultations" in unresolved


def test_skipped_test_suite_blocks_final(tmp_path: Path) -> None:
    if not _stage02_ready():
        pytest.skip("Stage 02 artifacts unavailable")

    with patch("human_simulator.stage02.verify_stage_02._publish_final_artifacts"):
        result = verify_stage_02(REPO_ROOT, run_tests=False)

    assert result["status"] == "FAIL"
    assert result["test_result"]["status"] == "SKIPPED"
    assert any(check["name"] == "full_test_suite" and check["status"] == "FAIL" for check in result["checks"])
    assert any(check["name"] == "test_result_not_skipped" and check["status"] == "FAIL" for check in result["checks"])


@pytest.mark.verify_stage02_gate
def test_verify_json_has_no_self_hash(tmp_path: Path) -> None:
    if not _stage02_ready():
        pytest.skip("Stage 02 artifacts unavailable")

    result = verify_stage_02(REPO_ROOT, run_tests=True, publish_artifacts=False)
    assert "final_artifact_hashes" not in result
    assert result.get("final_manifest") == FINAL_MANIFEST_NAME
    assert "verify-stage-02.json" not in result.get("artifact_hashes", {})


@pytest.mark.verify_stage02_gate
def test_gate_count_mismatch_blocks_final() -> None:
    if not _stage02_ready():
        pytest.skip("Stage 02 artifacts unavailable")

    with patch("human_simulator.stage02.verify_stage_02._publish_final_artifacts"):
        result = verify_stage_02(REPO_ROOT, run_tests=True, publish_artifacts=False)

    tampered = dict(result)
    tampered["checks_total"] = result["checks_total"] + 1
    arithmetic = next(check for check in result["checks"] if check["name"] == "checks_arithmetic")
    assert arithmetic["status"] == "PASS"
    assert result["checks_passed"] + result["checks_failed"] == result["checks_total"]
    assert result["checks_total"] == len(result["checks"])
    assert tampered["checks_total"] != len(tampered["checks"])


def test_incomplete_unresolved_list_blocks_final(tmp_path: Path) -> None:
    crosswalk_path = REPO_ROOT / "artifacts" / "stage-02" / "entity-crosswalk.yaml"
    if not crosswalk_path.exists():
        pytest.skip("entity-crosswalk.yaml unavailable")

    crosswalk = yaml.safe_load(crosswalk_path.read_text(encoding="utf-8"))
    truncated = dict(crosswalk)
    truncated["unresolved_mappings"] = crosswalk["unresolved_mappings"][:3]

    with patch(
        "human_simulator.stage02.verify_stage_02._load_yaml",
        side_effect=lambda path: truncated if path.name == "entity-crosswalk.yaml" else yaml.safe_load(path.read_text(encoding="utf-8")),
    ):
        with patch("human_simulator.stage02.verify_stage_02._publish_final_artifacts"):
            result = verify_stage_02(REPO_ROOT, run_tests=False)

    assert result["status"] == "FAIL"
    assert result["reported_unresolved_count"] == 3
    assert any(
        check["name"] == "crosswalk_unresolved_mappings_count" and check["status"] == "FAIL"
        for check in result["checks"]
    )
    assert any(
        check["name"] == "unresolved_mappings_complete" and check["status"] == "FAIL"
        for check in result["checks"]
    )


def test_final_manifest_valid_and_no_self_hash(tmp_path: Path) -> None:
    verify_path = tmp_path / "verify-stage-02.json"
    report_path = tmp_path / "stage-02-report.md"
    manifest_path = tmp_path / FINAL_MANIFEST_NAME
    verify_path.write_text('{"stage":"02"}\n', encoding="utf-8")
    report_path.write_text("# report\n", encoding="utf-8")

    from human_simulator.stage02.verify_stage_02 import _sha256_file

    manifest_path.write_text(
        "\n".join(
            [
                f"{_sha256_file(verify_path)}  verify-stage-02.json",
                f"{_sha256_file(report_path)}  stage-02-report.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ok, detail = _verify_final_manifest(manifest_path, tmp_path)
    assert ok, detail
    assert FINAL_MANIFEST_NAME not in manifest_path.read_text(encoding="utf-8")


@pytest.mark.verify_stage02_gate
def test_checks_total_is_derived_not_hardcoded() -> None:
    if not _stage02_ready():
        pytest.skip("Stage 02 artifacts unavailable")

    result = verify_stage_02(REPO_ROOT, run_tests=True, publish_artifacts=False)
    assert result["checks_total"] == len(result["checks"])
    assert result["checks_passed"] + result["checks_failed"] == result["checks_total"]


@pytest.mark.verify_stage02_gate
def test_live_verify_stage_02_end_to_end() -> None:
    if not _stage02_ready():
        pytest.skip("Stage 02 artifacts unavailable")

    result = verify_stage_02(REPO_ROOT, run_tests=True, publish_artifacts=False)
    stage02 = REPO_ROOT / "artifacts" / "stage-02"

    assert result["status"] == "PASS"
    assert result["checks_failed"] == 0
    assert result["reported_unresolved_count"] == 17
    assert len(result["unresolved_mappings"]) == 17
    assert result["test_result"]["status"] == "PASS"
    assert result["test_result"]["executed"] is True
    assert result["test_result"]["failed"] == 0
    assert (
        result["test_result"]["passed"] + result["test_result"]["skipped"]
        == result["test_result"]["collected"]
    )

    verify_json = json.loads((stage02 / "verify-stage-02.json").read_text(encoding="utf-8"))
    assert verify_json["unresolved_mappings"] == result["unresolved_mappings"]
    assert "final_artifact_hashes" not in verify_json

    report = (stage02 / "stage-02-report.md").read_text(encoding="utf-8")
    assert f"**Report status:** {REPORT_STATUS_FINAL}" in report
    for mapping in result["unresolved_mappings"]:
        assert mapping in report

    manifest_ok, _ = _verify_final_manifest(stage02 / FINAL_MANIFEST_NAME, stage02)
    assert manifest_ok

    second = verify_stage_02(REPO_ROOT, run_tests=True, publish_artifacts=False)
    assert second["status"] == "PASS"
    assert second["checks_total"] == result["checks_total"]


@pytest.mark.verify_stage02_gate
def test_run_pytest_live() -> None:
    pytest_run = _run_pytest(REPO_ROOT)
    assert pytest_run.payload["executed"] is True
    assert pytest_run.payload["collected"] > 0
    assert pytest_run.check.name == "full_test_suite"


def _stage02_ready() -> bool:
    stage02 = REPO_ROOT / "artifacts" / "stage-02"
    required = (
        "compare-verification-report.json",
        "relationship-verification-report.json",
        "entity-crosswalk.yaml",
    )
    if not all((stage02 / name).exists() for name in required):
        return False
    compare = json.loads((stage02 / "compare-verification-report.json").read_text(encoding="utf-8"))
    relationship = json.loads((stage02 / "relationship-verification-report.json").read_text(encoding="utf-8"))
    return compare.get("status") == "PASS" and relationship.get("status") == "PASS"
