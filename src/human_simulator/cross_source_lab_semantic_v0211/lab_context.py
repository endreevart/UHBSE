"""Lab-context classifiers and mandatory exclusions for metadata probes."""

from __future__ import annotations

import re
from typing import Any

# Token-boundary patterns (not bare substring)
_EXCLUSION_RULES: list[tuple[str, str]] = [
    (r"(^|_)instrumental($|_)", "instrumental_case_not_lab_instrument"),
    (r"(^|_)request_method($|_)", "http_request_method_not_assay"),
    (r"(^|_)acquiring_provider", "payment_acquiring_provider"),
    (r"(^|_)methodologist_", "document_workflow_status_not_assay"),
    (r"(^|_)first_name($|_)", "person_name_field"),
    (r"(^|_)last_name($|_)", "person_name_field"),
    (r"(^|_)patronymic($|_)", "person_name_field"),
    (r"(^|_)post_instrumental($|_)", "person_title_instrumental_case"),
]

_EXCLUDED_TABLES = frozenset(
    {
        "geography_columns",
        "geometry_columns",
        "spatial_ref_sys",
        "logg_apilogentry",
        "authentication_smscode",
        "payment_payment",
        "account_employee",
        "account_patient",
    }
)

_EXCLUDED_SCHEMAS = frozenset({"topology", "tiger"})

_LAB_TOKEN_SPECS: list[tuple[str, str]] = [
    (r"(^|_)specimen($|_)", "specimen"),
    (r"(^|_)biomaterial($|_)", "specimen"),
    (r"(^|_)sample_type($|_)", "specimen"),
    (r"(^|_)material($|_)", "specimen"),
    (r"(^|_)assay($|_)", "assay"),
    (r"(^|_)analyzer($|_)", "analyzer"),
    (r"(^|_)instrument($|_)", "analyzer"),  # only if not instrumental
    (r"(^|_)lab_method($|_)", "assay"),
    (r"(^|_)analysis_method($|_)", "assay"),
    (r"(^|_)ref(erence)?_?range($|_)", "reference_range"),
    (r"(^|_)reference_interval($|_)", "reference_range"),
    (r"(^|_)fasting($|_)", "fasting"),
    (r"(натощак)", "fasting"),
]


def is_excluded_relation(*, schema: str, table: str) -> str | None:
    if schema in _EXCLUDED_SCHEMAS:
        return "excluded_schema"
    if table in _EXCLUDED_TABLES:
        return f"excluded_table:{table}"
    if table.startswith("logg_") or table.startswith("django_"):
        return "infrastructure_logging_or_framework"
    return None


def exclusion_reason_for_column(*, schema: str, table: str, column: str) -> str | None:
    rel = is_excluded_relation(schema=schema, table=table)
    if rel:
        return rel
    col = (column or "").lower()
    for pat, reason in _EXCLUSION_RULES:
        if re.search(pat, col, flags=re.IGNORECASE):
            return reason
    # auth platform without lab context
    if table == "authentication_smscode" and re.search(r"(^|_)platform($|_)", col):
        return "auth_platform_not_analyzer"
    # generic HTTP-ish method columns outside lab seed
    if re.search(r"(^|_)request_method($|_)", col):
        return "http_request_method_not_assay"
    # payment provider
    if "payment" in table and "provider" in col:
        return "payment_provider_not_lab_provider"
    # PostGIS service
    if table in {"geography_columns", "geometry_columns"}:
        return "postgis_service_metadata"
    # bare "method" on non-lab tables is handled by requiring lab route
    return None


def classify_lab_token(column: str) -> str | None:
    """Return semantic role if column token matches lab metadata — exclusions first."""
    col = (column or "").lower()
    if exclusion_reason_for_column(schema="", table="", column=col):
        # re-check without table exclusions using column-only rules
        for pat, _reason in _EXCLUSION_RULES:
            if re.search(pat, col, flags=re.IGNORECASE):
                return None
    # instrumental must never match instrument
    if re.search(r"instrumental", col):
        return None
    for pat, role in _LAB_TOKEN_SPECS:
        if re.search(pat, col, flags=re.IGNORECASE):
            return role
    # bare method only as analysis_method / lab_method already covered;
    # allow (^|_)method($|_) only when not request_method / methodologist
    if re.search(r"(^|_)method($|_)", col) and not re.search(
        r"request_method|methodologist", col
    ):
        return "assay"
    if re.search(r"(^|_)platform($|_)", col):
        return "analyzer"  # only accepted later if lab-route proven
    if re.search(r"(^|_)provider($|_)", col) or re.search(r"(^|_)laboratory($|_)", col):
        return "laboratory_provider"
    return None


def false_positive_examples() -> list[dict[str, Any]]:
    """Canonical false positives from v0.2.1 global substring scan."""
    rows = [
        ("magerya_api", "account_employee", "first_name_instrumental", "instrumental_case_not_lab_instrument"),
        ("magerya_api", "account_employee", "last_name_instrumental", "instrumental_case_not_lab_instrument"),
        ("magerya_api", "account_employee", "patronymic_instrumental", "instrumental_case_not_lab_instrument"),
        ("magerya_api", "account_employee", "post_instrumental", "person_title_instrumental_case"),
        ("magerya_api", "account_patient", "first_name_instrumental", "instrumental_case_not_lab_instrument"),
        ("magerya_api", "account_patient", "last_name_instrumental", "instrumental_case_not_lab_instrument"),
        ("magerya_api", "account_patient", "patronymic_instrumental", "instrumental_case_not_lab_instrument"),
        ("magerya_api", "authentication_smscode", "platform", "auth_platform_not_analyzer"),
        ("magerya_api", "logg_apilogentry", "request_method", "http_request_method_not_assay"),
        ("magerya_api", "payment_payment", "acquiring_provider_id", "payment_acquiring_provider"),
        ("magerya_api", "document_document", "methodologist_document_status", "document_workflow_status_not_assay"),
        ("public", "geography_columns", "f_table_catalog", "postgis_service_metadata"),
        ("public", "geometry_columns", "f_table_catalog", "postgis_service_metadata"),
    ]
    out = []
    for sch, tbl, col, reason in rows:
        role = classify_lab_token(col)
        out.append(
            {
                "schema": sch,
                "table": tbl,
                "column": col,
                "rejection_reason": reason,
                "is_specimen_method_assay_analyzer": False,
                "instrumental_means_lab_instrument": False,
                "request_method_is_lab_method": False,
                "platform_without_lab_context_is_analyzer": False,
                "provider_id_outside_lab_is_lab_provider": False,
                "naive_token_role_if_any": role,
                "must_reject": True,
            }
        )
    return out
