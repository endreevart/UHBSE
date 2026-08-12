"""Tests for compare-source-audits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from human_simulator.audit.report import REPORT_STATUS_DRAFT, REPORT_STATUS_FINAL
from human_simulator.stage02.compare_source_audits import (
    CompareSourceAuditsError,
    compare_source_audits,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_min_profile(path: Path, *, database: str, schema: str, relation: str, columns: list[str]) -> None:
    payload = {
        "database": database,
        "relations": [{"schema": schema, "name": relation, "kind": "table"}],
        "columns": [
            {
                "schema": schema,
                "relation": relation,
                "name": column,
                "data_type": "integer" if column.endswith("_id") else "text",
                "nullable": True,
            }
            for column in columns
        ],
        "primary_keys": [],
        "foreign_keys": [],
        "indexes": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_candidates(
    path: Path,
    entity_type: str,
    schema: str,
    relation: str,
    *,
    role: str = "ENTITY",
    data_level: str = "ATTRIBUTE_CONTAINER",
) -> None:
    payload = {
        "entity_types": {
            entity_type: [
                {
                    "schema": schema,
                    "relation": relation,
                    "role": role,
                    "data_level": data_level,
                    "status": "CANDIDATE",
                    "evidence": [{"type": "name_pattern", "detail": "test"}],
                }
            ]
        }
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_stage01_gates(stage01: Path, profile_path: Path) -> None:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["readonly_validation"] = {"safe": True}
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    (stage01 / "source-audit.json").write_text(
        json.dumps(
            {
                "reachable": True,
                "extraction_method": "live_readonly_profile",
                "connection_user": "mg_audit_ro",
                "schema_fingerprint_check": {"fingerprints_match": True},
            }
        ),
        encoding="utf-8",
    )
    from human_simulator.stage01.manifest import write_manifest

    write_manifest(stage01)


def _write_relation_graph(path: Path, schema: str, relation: str) -> None:
    path.write_text(
        "\n".join(
            [
                "# Relation graph",
                "",
                "```mermaid",
                "flowchart LR",
                f'  N0["{schema}.{relation}"]',
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_compare_refuses_when_stage01_not_final(tmp_path: Path) -> None:
    stage01 = tmp_path / "artifacts" / "stage-01"
    stage02 = tmp_path / "artifacts" / "stage-02"
    stage01.mkdir(parents=True)
    stage02.mkdir(parents=True)
    (stage01 / "stage-01-report.md").write_text(f"**Report status:** {REPORT_STATUS_DRAFT}\n", encoding="utf-8")
    (stage01 / "schema-profile.json").write_text("{}", encoding="utf-8")
    (stage01 / "entity-candidates.yaml").write_text("entity_types: {}\n", encoding="utf-8")
    (stage01 / "relation-graph.md").write_text("# graph\n", encoding="utf-8")
    (stage01 / "unknown-semantics.md").write_text("# unknown\n", encoding="utf-8")
    (stage02 / "source-b-audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    with pytest.raises(CompareSourceAuditsError, match="source_a_report_status"):
        compare_source_audits(tmp_path)


def test_compare_refuses_when_source_b_not_pass(tmp_path: Path) -> None:
    stage01 = tmp_path / "artifacts" / "stage-01"
    stage02 = tmp_path / "artifacts" / "stage-02"
    stage01.mkdir(parents=True)
    stage02.mkdir(parents=True)
    (stage01 / "stage-01-report.md").write_text(f"**Report status:** {REPORT_STATUS_FINAL}\n", encoding="utf-8")
    (stage01 / "schema-profile.json").write_text("{}", encoding="utf-8")
    (stage01 / "entity-candidates.yaml").write_text("entity_types: {}\n", encoding="utf-8")
    (stage01 / "relation-graph.md").write_text("# graph\n", encoding="utf-8")
    (stage01 / "unknown-semantics.md").write_text("# unknown\n", encoding="utf-8")
    (stage02 / "source-b-audit.json").write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")

    with pytest.raises(CompareSourceAuditsError, match="source_b_pass"):
        compare_source_audits(tmp_path)


def test_compare_generates_artifacts(tmp_path: Path) -> None:
    stage01 = tmp_path / "artifacts" / "stage-01"
    stage02 = tmp_path / "artifacts" / "stage-02"
    stage01.mkdir(parents=True)
    stage02.mkdir(parents=True)

    _write_min_profile(
        stage01 / "schema-profile.json",
        database="magerya_api",
        schema="magerya_api",
        relation="account_patient",
        columns=["id", "birth_date", "sex"],
    )
    _write_min_profile(
        stage02 / "schema-profile-kgz.json",
        database="kgz_raw",
        schema="public",
        relation="persons",
        columns=["id", "birthdate", "sex"],
    )
    _write_candidates(stage01 / "entity-candidates.yaml", "patients", "magerya_api", "account_patient")
    _write_candidates(stage02 / "entity-candidates-kgz.yaml", "patients", "public", "persons")
    _write_relation_graph(stage01 / "relation-graph.md", "magerya_api", "account_patient")
    (stage01 / "unknown-semantics.md").write_text("# unknown\n", encoding="utf-8")
    (stage01 / "stage-01-report.md").write_text(f"**Report status:** {REPORT_STATUS_FINAL}\n", encoding="utf-8")
    _write_stage01_gates(stage01, stage01 / "schema-profile.json")

    (stage02 / "source-b-audit.json").write_text(
        json.dumps({"status": "PASS", "artifact_hashes": {}, "manifest": "manifest.sha256", "summary": {}}),
        encoding="utf-8",
    )
    _write_relation_graph(stage02 / "relation-graph-kgz.md", "public", "persons")
    (stage02 / "unknown-semantics-kgz.md").write_text("# unknown\n", encoding="utf-8")

    from human_simulator.stage02.classify_second_source import write_manifest

    write_manifest(stage02)

    result = compare_source_audits(tmp_path)
    assert result["status"] == "PASS"
    assert (stage02 / "schema-diff.yaml").exists()
    assert (stage02 / "entity-crosswalk.yaml").exists()
    assert (stage02 / "compare-verification-report.json").exists()

    crosswalk = yaml.safe_load((stage02 / "entity-crosswalk.yaml").read_text(encoding="utf-8"))
    patients = crosswalk["entity_types"]["patients"]["mappings"][0]
    assert patients["candidate_status"] == "CANDIDATE"
    assert patients["confidence"] in {"NAME_MATCH", "STRUCTURAL_MATCH", "HYPOTHESIS", "UNKNOWN"}
    assert patients["confidence"] != "EVIDENCE_BACKED"


def test_curated_crosswalk_is_hypothesis_not_evidence(tmp_path: Path) -> None:
    stage01 = tmp_path / "artifacts" / "stage-01"
    stage02 = tmp_path / "artifacts" / "stage-02"
    stage01.mkdir(parents=True)
    stage02.mkdir(parents=True)

    _write_min_profile(
        stage01 / "schema-profile.json",
        database="magerya_api",
        schema="magerya_api",
        relation="appointment_appointment",
        columns=["id", "patient_id", "doctor_id"],
    )
    _write_min_profile(
        stage02 / "schema-profile-kgz.json",
        database="kgz_raw",
        schema="public",
        relation="consultations",
        columns=["id", "patient_id", "doctor_id"],
    )
    _write_candidates(
        stage01 / "entity-candidates.yaml",
        "visits",
        "magerya_api",
        "appointment_appointment",
        role="EVENT",
        data_level="PATIENT_EVENT",
    )
    _write_candidates(
        stage02 / "entity-candidates-kgz.yaml",
        "visits",
        "public",
        "consultations",
        role="EVENT",
        data_level="PATIENT_EVENT",
    )
    _write_relation_graph(stage01 / "relation-graph.md", "magerya_api", "appointment_appointment")
    (stage01 / "unknown-semantics.md").write_text("# unknown\n", encoding="utf-8")
    (stage01 / "stage-01-report.md").write_text(f"**Report status:** {REPORT_STATUS_FINAL}\n", encoding="utf-8")
    _write_stage01_gates(stage01, stage01 / "schema-profile.json")
    (stage02 / "source-b-audit.json").write_text(json.dumps({"status": "PASS", "summary": {}}), encoding="utf-8")
    _write_relation_graph(stage02 / "relation-graph-kgz.md", "public", "consultations")
    (stage02 / "unknown-semantics-kgz.md").write_text("# unknown\n", encoding="utf-8")
    from human_simulator.stage02.classify_second_source import write_manifest

    write_manifest(stage02)

    compare_source_audits(tmp_path)
    crosswalk = yaml.safe_load((stage02 / "entity-crosswalk.yaml").read_text(encoding="utf-8"))
    mapping = crosswalk["entity_types"]["visits"]["mappings"][0]
    assert mapping["confidence"] == "HYPOTHESIS"
    assert "curated_crosswalk_hypothesis" in mapping["evidence_refs"]


@pytest.mark.skipif(
    not (REPO_ROOT / "artifacts" / "stage-02" / "source-b-audit.json").exists(),
    reason="stage-02 artifacts missing",
)
def test_compare_repo_inputs_in_isolated_copy(tmp_path: Path) -> None:
    """Reproduce the repository comparison without writing to Stage 01/02 in the workspace."""
    import shutil

    from human_simulator.stage03.prior_stage_integrity import snapshot_prior_stage_hashes

    stage01_report = REPO_ROOT / "artifacts" / "stage-01" / "stage-01-report.md"
    if not stage01_report.exists():
        pytest.skip("stage-01 not bootstrapped")
    if f"**Report status:** {REPORT_STATUS_FINAL}" not in stage01_report.read_text(encoding="utf-8"):
        pytest.skip("stage-01 not FINAL")

    before = snapshot_prior_stage_hashes(REPO_ROOT)
    workspace = tmp_path / "workspace"
    for rel in ("artifacts/stage-01", "artifacts/stage-02", "config"):
        source = REPO_ROOT / rel
        if source.is_dir():
            shutil.copytree(source, workspace / rel, dirs_exist_ok=True)

    result = compare_source_audits(workspace)
    assert result["status"] == "PASS"
    assert snapshot_prior_stage_hashes(REPO_ROOT) == before
