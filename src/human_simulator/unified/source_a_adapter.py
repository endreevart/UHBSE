"""Thin Source A adapter wrapping core.source_a for full expansion."""

from __future__ import annotations

from typing import Any

from human_simulator.core import source_a as src


def source_a_connection(repo_root: Any):
    return src.source_a_connection(repo_root)


def access_probe(conn: Any) -> dict[str, Any]:
    return src.access_probe(conn)


def relation_counts(conn: Any) -> dict[str, int]:
    return src.relation_counts(conn)


def cohort_eligibility_aggregates(conn: Any) -> dict[str, Any]:
    return src.cohort_eligibility_aggregates(conn)


def select_all_eligible_ids(conn: Any) -> list[int]:
    """All eligible Source A patient ids (appt≥3 AND lab≥1); no subject cap."""
    return src.select_all_eligible_patient_ids(conn)


def select_all_account_patient_ids(conn: Any) -> list[int]:
    """All Source A account_patient ids — canonical population, not scientific cohort."""
    return src.select_all_account_patient_ids(conn)


def fetch_patients(conn: Any, patient_ids: list[int]) -> list[dict[str, Any]]:
    return src.fetch_patients(conn, patient_ids)


def fetch_appointments(conn: Any, patient_ids: list[int]) -> list[dict[str, Any]]:
    return src.fetch_appointments(conn, patient_ids)


def fetch_analysis_results_uncapped(conn: Any, patient_ids: list[int]) -> list[dict[str, Any]]:
    return src.fetch_analysis_results_uncapped(conn, patient_ids)


def fetch_analysis_items_uncapped(conn: Any, result_ids: list[int]) -> list[dict[str, Any]]:
    return src.fetch_analysis_items_uncapped(conn, result_ids)


def truncation_accounting(
    conn: Any,
    patient_ids: list[int],
    *,
    per_patient_limit: int,
    per_result_limit: int,
) -> dict[str, Any]:
    return src.truncation_accounting(
        conn,
        patient_ids,
        per_patient_limit=per_patient_limit,
        per_result_limit=per_result_limit,
    )


SOURCE_SYSTEM_ID = "magerya_api"
