"""Tests for Stage 01 gate verification."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from human_simulator.audit.report import write_draft_stage_01_report
from human_simulator.audit.verify import verify_stage, verify_stage_01


def _write_minimal_artifacts(artifacts_dir: Path) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "source-audit.json").write_text(
        json.dumps({"reachable": True, "database": "magerya_api"}),
        encoding="utf-8",
    )
    (artifacts_dir / "schema-profile.json").write_text(
        json.dumps(
            {
                "database": "magerya_api",
                "relation_count": 1,
                "column_count": 1,
                "relations": [{"schema": "public", "name": "patients", "kind": "table"}],
                "readonly_validation": {"safe": True},
            }
        ),
        encoding="utf-8",
    )
    (artifacts_dir / "entity-candidates.yaml").write_text(
        yaml.safe_dump(
            {
                "entity_types": {
                    "patients": [
                        {
                            "schema": "public",
                            "relation": "patients",
                            "status": "CONFIRMED",
                            "evidence": [{"type": "foreign_key", "detail": "fk"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (artifacts_dir / "relation-graph.md").write_text("# graph\n", encoding="utf-8")
    (artifacts_dir / "unknown-semantics.md").write_text("## Unknown\n\n- x — **UNKNOWN**\n", encoding="utf-8")
    evidence = artifacts_dir / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "query-index.json").write_text("[]", encoding="utf-8")
    (artifacts_dir / "profiling-query-log.json").write_text("[]", encoding="utf-8")
    write_draft_stage_01_report(artifacts_dir)


def test_verify_stage_01_fail_without_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docs").mkdir()
    (repo / "docs" / "current-stage.md").write_text("# Current stage\n\n**Stage:** 01\n", encoding="utf-8")
    result = verify_stage_01(repo, run_tests=False)
    assert result["status"] == "FAIL"
    assert result["failures"]


def test_verify_stage_01_partial_with_core_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "current-stage.md").write_text("# Current stage\n\nStage 01\n", encoding="utf-8")
    artifacts = repo / "artifacts" / "stage-01"
    _write_minimal_artifacts(artifacts)

    result = verify_stage_01(repo, run_tests=False)
    assert result["status"] in {"PARTIAL", "PASS"}
    assert (artifacts / "verify-result.json").exists()


def test_verify_stage_01_generates_report_on_pass(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "current-stage.md").write_text("# Current stage\n\nStage 01\n", encoding="utf-8")
    artifacts = repo / "artifacts" / "stage-01"
    _write_minimal_artifacts(artifacts)

    def fake_evaluate_all(repo_root, artifacts_dir, run_tests=True):
        from human_simulator.audit.verify import CriterionResult

        return [
            CriterionResult(
                criterion_id="test.pass",
                section="Test",
                description="all good",
                status="pass",
                missing_artifact=None,
                reason="ok",
                required_action="none",
                human_clarification_needed=False,
            )
        ]

    monkeypatch.setattr("human_simulator.audit.verify._evaluate_all_criteria", fake_evaluate_all)
    result = verify_stage_01(repo, run_tests=False)
    assert result["status"] == "PASS"
    assert (artifacts / "stage-01-report.md").exists()
    report = (artifacts / "stage-01-report.md").read_text(encoding="utf-8")
    assert "**Report status:** FINAL" in report
    assert "Stage 01 gate reached" in report


def test_verify_stage_wrapper_reports_missing(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts" / "stage-01"
    artifacts.mkdir(parents=True)
    result = verify_stage(artifacts)
    assert result["passed"] is False
    assert result["status"] in {"FAIL", "PARTIAL"}


def test_failure_includes_required_fields(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docs").mkdir()
    (repo / "docs" / "current-stage.md").write_text("Stage 01", encoding="utf-8")
    result = verify_stage_01(repo, run_tests=False)
    failure = result["failures"][0]
    assert "missing_artifact" in failure
    assert "reason" in failure
    assert "required_action" in failure
    assert "human_clarification_needed" in failure
