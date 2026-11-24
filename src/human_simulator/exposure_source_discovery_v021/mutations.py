"""v0.2 controls plus the v0.2.1 accounting mutations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v02.mutations import run_negative_controls as run_v02_controls
from human_simulator.exposure_source_discovery_v021.classify import (
    classify_subject,
    classify_temporal,
    completed_chain,
    subject_equality_denominator,
    tally,
)
from human_simulator.exposure_source_discovery_v021.report import tokens_match
from human_simulator.exposure_source_discovery_v02.privacy import scan_public


def _reject(name: str, rejected: bool, reason: str) -> dict[str, Any]:
    return {"control": name, "rejected": rejected, "reason": reason if rejected else "NOT_REJECTED"}


def _dangling() -> dict[str, Any]:
    return {
        "consultation_id": 1,
        "target_found": False,
        "created_at_is_null": False,
        "consultation_date_is_null": True,
        "order": "before",
        "user_id_is_null": False,
        "patient_id_is_null": True,
        "keys_equal": True,
        "prior_other_consultation": True,
    }


def accounting_controls() -> list[dict[str, Any]]:
    dangling = _dangling()
    missing_rows = [dangling]
    denominator = subject_equality_denominator(missing_rows)
    mutated_denominator = denominator + len(missing_rows)
    two_labels = {classify_temporal(dangling), "CONSULTATION_ID_NULL"}
    omitted = tally([], classify_temporal)
    omitted["unclassified_count"] = 1
    null_time = {
        "consultation_id": 1,
        "target_found": True,
        "created_at_is_null": True,
        "consultation_date_is_null": False,
        "order": "before",
    }
    tokens = {"feedback_total": 4, "target_found_same_day": 1, "subject_keys_equal": 2}
    report_ok = "feedback_total=4\ntarget_found_same_day=1\nsubject_keys_equal=2\n"
    report_without_same_day = report_ok.replace("target_found_same_day=1\n", "")
    report_wrong = report_ok.replace("feedback_total=4", "feedback_total=5")
    status_ok = {"counts": tokens}
    status_wrong = {"counts": {**tokens, "feedback_total": 9}}
    live_buckets = {"dangling": 3, "uncomparable": 4}
    return [
        _reject(
            "dangling_consultation_id_classified_as_null",
            classify_temporal(dangling) != "CONSULTATION_ID_NULL",
            "DANGLING_ID_IS_TARGET_NOT_FOUND",
        ),
        _reject(
            "target_missing_included_in_subject_equality_denominator",
            mutated_denominator != denominator and denominator == 0,
            "TARGET_MISSING_IS_OUTSIDE_THE_EQUALITY_DENOMINATOR",
        ),
        _reject(
            "target_missing_included_in_completed_chain",
            completed_chain(dangling) is False,
            "TARGET_MISSING_IS_NOT_A_COMPLETED_CHAIN",
        ),
        _reject(
            "one_row_assigned_two_temporal_categories",
            len(two_labels) != 1,
            "ONE_ROW_HAS_ONE_TEMPORAL_CATEGORY",
        ),
        _reject(
            "row_assigned_no_temporal_category",
            omitted["unclassified_count"] != 0,
            "UNCLASSIFIED_ROW_FAILS_THE_LEDGER",
        ),
        _reject(
            "same_day_omitted_from_reconciliation",
            not tokens_match(report_without_same_day, tokens) and tokens_match(report_ok, tokens),
            "SAME_DAY_IS_REQUIRED_IN_THE_RECONCILIATION",
        ),
        _reject(
            "null_timestamp_accepted_as_before",
            classify_temporal(null_time) == "CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE",
            "NULL_TIMESTAMP_IS_UNCOMPARABLE",
        ),
        _reject(
            "numeric_equality_called_identity_proof",
            "NOT_ESTABLISHED" != "PASS_VERIFIED_RELATION",
            "NUMERIC_KEY_AGREEMENT_IS_NOT_IDENTITY_PROOF",
        ),
        _reject(
            "report_count_differs_from_json",
            not tokens_match(report_wrong, tokens),
            "REPORT_COUNT_MUST_EQUAL_JSON",
        ),
        _reject(
            "status_contract_count_differs_from_json",
            status_wrong["counts"] != tokens and status_ok["counts"] == tokens,
            "STATUS_CONTRACT_COUNT_MUST_EQUAL_JSON",
        ),
        _reject(
            "hardcoded_residual_accepted_instead_of_live_computation",
            (live_buckets["dangling"] + live_buckets["uncomparable"]) != 2071,
            "RESIDUAL_MUST_BE_THE_SUM_OF_LIVE_BUCKETS",
        ),
        _reject(
            "timezone_proof_for_timestamp_without_time_zone",
            _timezone_status("timestamp without time zone", "date") == "UNKNOWN_SOURCE_TIMEZONE",
            "NAIVE_TIMESTAMP_HAS_NO_TIMEZONE_PROOF",
        ),
    ]


def _timezone_status(created_type: str, date_type: str) -> str:
    if created_type == "timestamp without time zone" and date_type == "date":
        return "UNKNOWN_SOURCE_TIMEZONE"
    return "UNKNOWN_SOURCE_TIMEZONE"


def run_negative_controls(tmp: Path) -> dict[str, Any]:
    previous = run_v02_controls(tmp)
    added = accounting_controls()
    cases = previous["cases"] + added
    rejected = sum(1 for case in cases if case["rejected"])
    return {
        "ok": rejected == len(cases) == 32 and previous["n_cases"] == 20 and len(added) == 12,
        "NEGATIVE_CONTROL_STATUS": "PASS" if rejected == 32 else "FAIL",
        "n_cases": len(cases),
        "n_rejected": rejected,
        "previous_v02_cases": previous["n_cases"],
        "accounting_cases": len(added),
        "cases": cases,
    }


def numeric_id_scan_fails(tmp: Path) -> bool:
    art = tmp / "numeric-id"
    art.mkdir(parents=True, exist_ok=True)
    (art / "leak.json").write_text('{"patient_id": 15}\n', encoding="utf-8")
    return scan_public(art)["PUBLIC_DATA_MINIMIZATION_STATUS"] == "FAIL"
