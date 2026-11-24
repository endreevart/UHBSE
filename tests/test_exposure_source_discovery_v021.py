"""Unit and contract tests for the v0.2.1 accounting correction."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

from human_simulator.exposure_source_discovery_v021.baseline import snapshot
from human_simulator.exposure_source_discovery_v021.classify import (
    classify_subject,
    classify_temporal,
    completed_chain,
    tally,
)
from human_simulator.exposure_source_discovery_v021.defect import reproduce_frozen
from human_simulator.exposure_source_discovery_v021.mutations import numeric_id_scan_fails, run_negative_controls
from human_simulator.exposure_source_discovery_v021.policy import SCIENTIFIC_CEILING, SUBJECT_CATEGORIES, TEMPORAL_CATEGORIES
from human_simulator.exposure_source_discovery_v021.report import count_tokens, render, tokens_match

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src/human_simulator/exposure_source_discovery_v021"


def _rows() -> list[dict]:
    return [
        {"consultation_id": None, "target_found": False},
        {"consultation_id": 1, "target_found": False},
        {"consultation_id": 1, "target_found": True, "created_at_is_null": False, "consultation_date_is_null": False, "order": "before", "user_id_is_null": False, "patient_id_is_null": False, "keys_equal": True},
        {"consultation_id": 1, "target_found": True, "created_at_is_null": False, "consultation_date_is_null": False, "order": "same", "user_id_is_null": False, "patient_id_is_null": False, "keys_equal": False},
        {"consultation_id": 1, "target_found": True, "created_at_is_null": False, "consultation_date_is_null": False, "order": "after", "user_id_is_null": True, "patient_id_is_null": True},
        {"consultation_id": 1, "target_found": True, "created_at_is_null": True, "consultation_date_is_null": False, "order": "before", "user_id_is_null": False, "patient_id_is_null": True},
    ]


def test_frozen_v02_ledger_does_not_close() -> None:
    defect = reproduce_frozen(ROOT)
    four = defect["four_route_sum"]
    total = defect["FEEDBACK_TOTAL_COUNT"]
    assert total == 41407
    assert four == 31271 + 24 + 7 + 8034
    assert defect["residual_outside_four_reported_buckets"] == total - four
    assert defect["residual_category_present_in_json"] is False
    assert defect["V02_TEMPORAL_ACCOUNTING_STATUS"] == "NOT_RECONCILED"
    assert defect["V02_FINAL_REPORT_ACCOUNTING_STATUS"] == "CORRECTION_REQUIRED"
    assert defect["not_a_stage_05_defect"] is True
    assert defect["disagreement_query_includes_only_found_targets"] is True


def test_exclusive_classifier_covers_every_synthetic_row() -> None:
    rows = _rows()
    temporal = tally(rows, classify_temporal)
    subject = tally(rows, classify_subject)
    assert temporal["overlap_count"] == 0
    assert temporal["unclassified_count"] == 0
    assert temporal["sum_categories"] == len(rows)
    assert set(temporal["counts"]) == set(TEMPORAL_CATEGORIES)
    assert subject["unclassified_count"] == 0
    assert set(subject["counts"]) == set(SUBJECT_CATEGORIES)
    assert classify_temporal(rows[1]) == "CONSULTATION_ID_PRESENT_TARGET_NOT_FOUND"
    assert classify_temporal(rows[5]) == "CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE"
    assert completed_chain(rows[1]) is False


def test_negative_controls_and_numeric_id(tmp_path: Path) -> None:
    result = run_negative_controls(tmp_path)
    assert result["previous_v02_cases"] == 20
    assert result["accounting_cases"] == 12
    assert result["n_rejected"] == 32
    assert result["NEGATIVE_CONTROL_STATUS"] == "PASS"
    assert numeric_id_scan_fails(tmp_path) is True


def test_report_tokens_match_the_ledger() -> None:
    ledger = {
        "exclusive": {
            "FEEDBACK_TOTAL_COUNT": 6,
            "categories": {name: {"count": index, "fraction": None} for index, name in enumerate(TEMPORAL_CATEGORIES, start=1)},
            "uncomparable_components": {
                "created_at_null_and_consultation_date_null": 0,
                "created_at_null_and_consultation_date_present": 0,
                "created_at_present_and_consultation_date_missing_or_targets_disagree": 0,
            },
        },
        "subjects": {
            "categories": {name: {"count": index, "fraction": None} for index, name in enumerate(SUBJECT_CATEGORIES, start=1)},
            "equality_denominator": 9,
        },
        "targets": {
            "CONSULTATION_ID_PRESENT_COUNT": 5,
            "CONSULTATION_TARGET_FOUND_COUNT": 4,
            "CONSULTATION_TARGET_NOT_FOUND_COUNT": 1,
            "CONSULTATION_TARGET_MULTIPLE_MATCH_COUNT": 0,
        },
        "route": {
            "candidate_count": 2,
            "denominator": 6,
            "excluded_target_missing_count": 1,
            "excluded_no_prior_recommendation_count": 1,
            "excluded_out_of_order_count": 0,
            "excluded_same_consultation_only_count": 0,
            "interval_feedback_minus_prior_recommendation_days": {"p10": 1, "p50": 2, "p90": 3},
            "interval_consultation_minus_feedback_days": {"p10": 0, "p50": 0, "p90": 1},
            "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": "CANDIDATE_COUNTED_IDENTITY_NOT_ESTABLISHED",
        },
        "temporal_contract": {
            "feedback.created_at": "timestamp without time zone",
            "consultations.date": "date",
            "session_timezone": "UTC",
            "SOURCE_B_TIMEZONE_SEMANTICS_STATUS": "UNKNOWN_SOURCE_TIMEZONE",
        },
    }
    status = {
        "TECHNICAL_DISCOVERY_STATUS": "PASS",
        "V02_TEMPORAL_ACCOUNTING_STATUS": "NOT_RECONCILED",
        "V02_FINAL_REPORT_ACCOUNTING_STATUS": "CORRECTION_REQUIRED",
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS": "NOT_ESTABLISHED",
        "INTERVENTION_RESPONSE_READINESS_STATUS": "NOT_READY",
    }
    defect = status
    text = render(ledger, defect, status)
    tokens = count_tokens(ledger)
    assert tokens_match(text, tokens)
    assert "target_found_same_day=" in text
    assert "NUMERIC_KEY_AGREEMENT_OBSERVED_NOT_IDENTITY_PROOF" in text
    assert "linked consultation disagreements" not in text


def test_algorithm_does_not_embed_a_residual_constant() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py") if path.name != "mutations.py")
    assert "2071" not in source
    tree = ast.parse((PACKAGE / "accounting.py").read_text(encoding="utf-8"))
    sql = "\n".join(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str))
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP ", "TRUNCATE ", "CREATE ", "COPY "):
        assert forbidden not in sql.upper()


def test_scientific_ceiling_and_baselines() -> None:
    assert SCIENTIFIC_CEILING["INTERVENTION_RESPONSE_READINESS_STATUS"] == "NOT_READY"
    assert SCIENTIFIC_CEILING["SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS"] == "NOT_ESTABLISHED"
    current = snapshot(ROOT)
    assert current["stage05"]["STAGE05_BASELINE_VERIFICATION_STATUS"] == "PASS"
    assert current["v02_artifacts"]


def test_two_process_replay() -> None:
    code = (
        "import json; from human_simulator.exposure_source_discovery_v021.classify import classify_temporal; "
        "from human_simulator.exposure_source_discovery_v021.defect import reproduce_frozen; "
        "from pathlib import Path; "
        "row={'consultation_id':1,'target_found':False}; "
        "print(json.dumps({'label': classify_temporal(row), 'residual': reproduce_frozen(Path('.'))['residual_outside_four_reported_buckets']}))"
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
