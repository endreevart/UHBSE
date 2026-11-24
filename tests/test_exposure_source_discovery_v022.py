"""Unit and contract tests for v0.2.2 owner decision ingestion."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from human_simulator.exposure_source_discovery_v02.privacy import scan_public
from human_simulator.exposure_source_discovery_v022.contract import field_statuses, stage_statuses, violations
from human_simulator.exposure_source_discovery_v022.decisions import (
    answer_record,
    build_decisions,
    reviewer_digest,
    validate_all,
)
from human_simulator.exposure_source_discovery_v022.mutations import (
    EXPECTED_CASES,
    run_negative_controls,
    synthetic_evidence,
)
from human_simulator.exposure_source_discovery_v022.policy import ANSWERS, DECIDING_CERTAINTIES, SCIENTIFIC_CEILING

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/human_simulator/exposure_source_discovery_v022"
SCHEMA = json.loads((ROOT / "artifacts/exposure-source-discovery-v0.2/semantic-decision.schema.json").read_text())
V021 = {
    "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": "CANDIDATE_COUNTED_IDENTITY_NOT_ESTABLISHED",
    "counts": {"candidate_count": 3, "candidate_denominator": 5},
}


def test_only_deciding_answers_become_schema_valid_decisions() -> None:
    record = answer_record(ANSWERS)
    decisions = build_decisions(record)
    deciding = [a for a in record if a["certainty"] in DECIDING_CERTAINTIES]
    assert len(decisions) == len(deciding)
    assert {d["evidence_sha256"] for d in decisions} == {a["answer_sha256"] for a in deciding}
    result = validate_all(decisions, record, SCHEMA)
    assert result["ok"], result
    assert all(d["reviewer_digest"] == reviewer_digest() for d in decisions)


def test_negative_controls(tmp_path: Path) -> None:
    result = run_negative_controls(tmp_path, SCHEMA)
    assert result["baseline_accepted"] is True
    assert result["privacy_rejects_numeric_identifier"] is True
    assert result["n_cases"] == EXPECTED_CASES
    assert result["n_rejected"] == EXPECTED_CASES, [c for c in result["cases"] if not c["rejected"]]
    assert result["NEGATIVE_CONTROL_STATUS"] == "PASS"


def test_statuses_keep_recall_caveat_and_ceiling() -> None:
    record = answer_record(ANSWERS)
    evidence = synthetic_evidence()
    status = stage_statuses(record, evidence, V021)
    fields = field_statuses(record, evidence, {"SOURCE_A_CODE_EVIDENCE_STATUS": "AVAILABLE"})
    assert status["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"] == "OWNER_STATED_RECALL_UNCERTAIN_NOT_DATA_PROOF"
    assert status["SOURCE_B_TIMEZONE_SEMANTICS_STATUS"] == "OWNER_STATED_EUROPE_MOSCOW"
    assert status["SOURCE_B_TEMPORAL_SEQUENCE_STATUS"] == "CANDIDATE_COUNTED_SEQUENCE_SEMANTICS_OWNER_CONFIRMED"
    assert status["SOURCE_A_ACTIVITY_SECTION_STATUS"] == "LIKELY_LIFESTYLE_NOT_MEDICATION"
    assert status["SOURCE_B_CANDIDATE_CHAIN_COUNT"] == 3
    for key, value in SCIENTIFIC_CEILING.items():
        assert status[key] == value
    assert not violations(status, build_decisions(record), record, fields)
    unknown = {f["answer_key"] for f in fields if f.get("answer_key") and f["status"] == "UNKNOWN"}
    assert unknown == {"B6", "B8", "B9", "B10"}


def test_evidence_sql_is_read_only() -> None:
    tree = ast.parse((PACKAGE / "evidence.py").read_text(encoding="utf-8"))
    sql = "\n".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str))
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP ", "TRUNCATE ", "CREATE ", "COPY ", "SELECT *"):
        assert forbidden not in sql.upper()


def test_written_decisions_pass_privacy_scan(tmp_path: Path) -> None:
    record = answer_record(ANSWERS)
    (tmp_path / "owner-answer-record.json").write_text(json.dumps({"answers": record}, ensure_ascii=False))
    (tmp_path / "owner-decisions.json").write_text(json.dumps({"responses": build_decisions(record)}))
    assert scan_public(tmp_path)["PUBLIC_DATA_MINIMIZATION_STATUS"] == "PASS_AGGREGATE_ONLY"
