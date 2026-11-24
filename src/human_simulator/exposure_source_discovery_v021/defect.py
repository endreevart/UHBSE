"""Reproduce the v0.2 temporal ledger gap from frozen artifacts. Not a Stage 05 defect."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v021.policy import V02_DIR, V02_SOURCE

FOUR_ROUTES = (
    "feedback_before_linked_consultation",
    "feedback_after_linked_consultation",
    "same_calendar_day_as_linked_consultation",
    "feedback_without_linked_consultation",
)


def _load(root: Path, name: str) -> Any:
    path = root / V02_DIR / name
    if name.endswith(".md"):
        return path.read_text(encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def reproduce_frozen(root: Path) -> dict[str, Any]:
    """Accounting observation only. The residual is computed, not supplied."""
    root = Path(root)
    temporal = _load(root, "source-b-temporal-sequence-audit.json")
    identity = _load(root, "source-b-identity-linkage-audit.json")
    report = _load(root, "discovery-report.md")
    status = _load(root, "status-contract.json")
    source = (root / V02_SOURCE / "source_b.py").read_text(encoding="utf-8")
    routes = temporal["routes"]
    total = int(temporal["feedback_rows"])
    four = {name: int(routes[name]["count"]) for name in FOUR_ROUTES}
    four_sum = sum(four.values())
    residual = total - four_sum
    partial = routes.get("linked_consultation_date_missing")
    partial_count = int(partial["count"]) if isinstance(partial, dict) and "count" in partial else None
    remainder_after_partial = None if partial_count is None else residual - partial_count
    report_mentions = {
        "before": f"feedback before the linked consultation: {four['feedback_before_linked_consultation']}" in report,
        "after": f"feedback after the linked consultation: {four['feedback_after_linked_consultation']}" in report,
        "same_day": "same_calendar_day_as_linked_consultation" in report or "feedback on the same calendar day" in report,
        "consultation_id_null": f"feedback without the linked consultation: {four['feedback_without_linked_consultation']}" in report,
        "date_missing": "linked_consultation_date_missing" in report or "target_found_time_uncomparable" in report,
        "equation": "consultation_id_null" in report and "target_found_time_uncomparable" in report,
    }
    status_text = json.dumps(status, sort_keys=True)
    status_mentions_counts = all(str(count) in status_text for count in four.values()) and str(total) in status_text
    disagreement_sql_is_inner_join = (
        "JOIN public.consultations c ON c.id = f.consultation_id" in source
        and "IS DISTINCT FROM c.patient_id" in source
    )
    found_targets = int(identity["linked_consultation_rows"])
    id_null = int(identity["feedback_without_consultation"])
    implied_dangling = total - id_null - found_targets
    residual_category_in_json = any(
        int(route.get("count", -1)) == residual
        for route in routes.values()
        if isinstance(route, dict)
    ) or (partial_count == residual)
    books_close = four_sum + (partial_count or 0) == total and residual_category_in_json
    return {
        "applies_to": V02_DIR,
        "not_a_stage_05_defect": True,
        "FEEDBACK_TOTAL_COUNT": total,
        "four_reported_routes": four,
        "four_route_sum": four_sum,
        "residual_outside_four_reported_buckets": residual,
        "partial_bucket": {
            "name": "linked_consultation_date_missing" if partial_count is not None else None,
            "count": partial_count,
            "closes_the_ledger": partial_count == residual,
            "remainder_after_adding_partial_bucket": remainder_after_partial,
        },
        "residual_category_present_in_json": residual_category_in_json,
        "residual_category_present_in_report": report_mentions["equation"] or (
            report_mentions["date_missing"] and partial_count == residual
        ),
        "residual_category_present_in_status_contract": status_mentions_counts and residual_category_in_json,
        "report_mentions": report_mentions,
        "disagreement_query_includes_only_found_targets": disagreement_sql_is_inner_join,
        "disagreement_count_published": int(identity["linked_subject_disagreements"]),
        "disagreement_denominator_published": found_targets,
        "disagreement_statement_omits_denominator": "disagreements: 0" in report and "denominator" not in report,
        "consultation_id_present_count_from_frozen_identity": total - id_null,
        "consultation_target_found_count_from_frozen_identity": found_targets,
        "frozen_implied_target_not_found": implied_dangling,
        "present_count_equals_found_count_in_frozen_identity": implied_dangling == 0,
        "exclusive_partition_sums_to_total": books_close,
        "V02_CORE_TEMPORAL_COMPUTATION_STATUS": "PASS" if residual_category_in_json else "NOT_RECONCILED",
        "V02_TEMPORAL_ACCOUNTING_STATUS": "PASS" if books_close else "NOT_RECONCILED",
        "V02_FINAL_REPORT_ACCOUNTING_STATUS": "PASS" if report_mentions["equation"] else "CORRECTION_REQUIRED",
        "meaning_of_residual": "NOT_ASSUMED_PENDING_LIVE_QUERY",
    }


def attach_live_composition(frozen: dict[str, Any], live_categories: dict[str, int]) -> dict[str, Any]:
    """Explain the frozen residual from live exclusive buckets. No expected residual is supplied."""
    unexplained_by_four = (
        live_categories["CONSULTATION_ID_PRESENT_TARGET_NOT_FOUND"]
        + live_categories["CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE"]
    )
    four_live = (
        live_categories["CONSULTATION_TARGET_FOUND_TIME_BEFORE"]
        + live_categories["CONSULTATION_TARGET_FOUND_TIME_AFTER"]
        + live_categories["CONSULTATION_TARGET_FOUND_TIME_SAME_DAY"]
        + live_categories["CONSULTATION_ID_NULL"]
    )
    updated = dict(frozen)
    updated["live_composition_of_rows_outside_the_four_buckets"] = {
        "CONSULTATION_ID_PRESENT_TARGET_NOT_FOUND": live_categories["CONSULTATION_ID_PRESENT_TARGET_NOT_FOUND"],
        "CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE": live_categories["CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE"],
        "sum": unexplained_by_four,
    }
    updated["live_four_bucket_sum"] = four_live
    updated["live_composition_matches_frozen_residual"] = (
        unexplained_by_four == frozen["residual_outside_four_reported_buckets"]
        and four_live == frozen["four_route_sum"]
    )
    updated["meaning_of_residual"] = (
        "LIVE_EXCLUSIVE_BUCKETS"
        if updated["live_composition_matches_frozen_residual"]
        else "LIVE_LEDGER_DIFFERS_FROM_FROZEN_OBSERVATION"
    )
    core_matches = four_live == frozen["four_route_sum"]
    updated["directional_counts_reproduced"] = core_matches
    updated["V02_CORE_TEMPORAL_COMPUTATION_STATUS"] = (
        "PASS" if frozen["residual_category_present_in_json"] and core_matches else "NOT_RECONCILED"
    )
    if frozen["residual_category_present_in_json"] and not frozen["residual_category_present_in_report"]:
        updated["V02_FINAL_REPORT_ACCOUNTING_STATUS"] = "CORRECTION_REQUIRED"
    elif not frozen["exclusive_partition_sums_to_total"]:
        updated["V02_TEMPORAL_ACCOUNTING_STATUS"] = "NOT_RECONCILED"
        updated["V02_FINAL_REPORT_ACCOUNTING_STATUS"] = "CORRECTION_REQUIRED"
    return updated
