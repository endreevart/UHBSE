"""Exact Source A component reconciliation (fixes v0.1.1 six-row matches_gap defect)."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_association_v01.policy import SOURCE_A, VERSION

# Accounting regex used in v0.1.1 (intentionally narrower than loader float()).
ACCOUNTING_NUMERIC_REGEX = r"^-?[0-9]+([.,][0-9]+)?$"

# Documented loader-accepted forms that fail ACCOUNTING_NUMERIC_REGEX:
# Python float(stripped.replace(',','.')) accepts leading '+' and trailing '.' after comma→dot.
LOADER_BEYOND_REGEX_EXAMPLES = ("+3", "+10", "+2", "+7", "19,")


def build_component_reconciliation(conn_a: Any, conn_canonical: Any) -> dict[str, Any]:
    """Return exclusive buckets with explained_gap == raw - canonical when resolved."""
    with conn_a.cursor() as cur:
        cur.execute(
            f"""
            SELECT
              COUNT(*)::bigint AS total,
              COUNT(*) FILTER (WHERE bucket = 'orphan')::bigint AS orphan,
              COUNT(*) FILTER (WHERE bucket = 'no_patient')::bigint AS no_patient,
              COUNT(*) FILTER (WHERE bucket = 'empty')::bigint AS empty,
              COUNT(*) FILTER (WHERE bucket = 'non_numeric')::bigint AS non_numeric,
              COUNT(*) FILTER (WHERE bucket = 'numeric')::bigint AS numeric
            FROM (
              SELECT CASE
                WHEN ar.id IS NULL THEN 'orphan'
                WHEN ar.patient_id IS NULL THEN 'no_patient'
                WHEN i.value IS NULL OR btrim(i.value) = '' THEN 'empty'
                WHEN i.value ~ '{ACCOUNTING_NUMERIC_REGEX}' THEN 'numeric'
                ELSE 'non_numeric'
              END AS bucket
              FROM magerya_api.document_analysisresultitem i
              LEFT JOIN magerya_api.document_analysisresult ar
                ON ar.id = i.analysis_result_id
            ) t
            """
        )
        total, orphan, no_pat, empty, nonnum, num = (int(x) for x in cur.fetchone())

    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT
              COUNT(*)::bigint AS total,
              COUNT(*) FILTER (WHERE oc.numeric_value IS NOT NULL)::bigint AS numeric,
              COUNT(*) FILTER (WHERE oc.numeric_value IS NULL)::bigint AS non_numeric
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_A,),
        )
        can_total, can_num, can_non = (int(x) for x in cur.fetchone())

        # Exact origin of surplus numeric vs regex-numeric: raw_value fails accounting regex
        cur.execute(
            f"""
            SELECT
              COUNT(*)::bigint,
              COUNT(*) FILTER (
                WHERE oc.raw_value IS NOT NULL
                  AND btrim(oc.raw_value) <> ''
                  AND oc.raw_value !~ '{ACCOUNTING_NUMERIC_REGEX}'
              )::bigint AS beyond_regex
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND oc.numeric_value IS NOT NULL
            """,
            (SOURCE_A,),
        )
        can_num_check, loader_beyond_regex = (int(x) for x in cur.fetchone())

        cur.execute(
            f"""
            SELECT LEFT(oc.raw_value, 40), COUNT(*)::bigint
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND oc.numeric_value IS NOT NULL
              AND oc.raw_value IS NOT NULL
              AND btrim(oc.raw_value) <> ''
              AND oc.raw_value !~ '{ACCOUNTING_NUMERIC_REGEX}'
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 20
            """,
            (SOURCE_A,),
        )
        beyond_samples = [{"raw_value_prefix": r[0], "n": int(r[1])} for r in cur.fetchall()]

    exclusive_sum = orphan + no_pat + empty + nonnum + num
    gap = total - can_total

    # v0.1.1 defect: counted all nonnum_wp - can_non as "not loaded", but loader_beyond_regex
    # rows were classified non_numeric by regex yet loaded with numeric_value.
    nonnum_loaded_as_text = can_non
    nonnum_loaded_as_numeric_via_broader_parser = loader_beyond_regex
    nonnum_accounted_in_canonical = (
        nonnum_loaded_as_text + nonnum_loaded_as_numeric_via_broader_parser
    )
    nonnum_not_loaded = max(0, nonnum - nonnum_accounted_in_canonical)

    regex_numeric_loaded = can_num - loader_beyond_regex
    numeric_not_loaded = max(0, num - regex_numeric_loaded)

    gap_explained = {
        "empty_values": empty,
        "unsupported_no_patient_or_orphan": orphan + no_pat,
        "non_numeric_not_loaded": nonnum_not_loaded,
        "numeric_regex_not_loaded": numeric_not_loaded,
        "sum": empty + orphan + no_pat + nonnum_not_loaded + numeric_not_loaded,
    }
    gap_explained["matches_gap"] = gap_explained["sum"] == gap

    # Forbidden: PASS when matches_gap is false
    if gap_explained["matches_gap"] and exclusive_sum == total and numeric_not_loaded == 0:
        status = "PASS"
    elif exclusive_sum == total:
        status = "PARTIAL"
    else:
        status = "FAIL"

    if status == "PASS" and not gap_explained["matches_gap"]:
        status = "FAIL"  # hard invariant

    return {
        "version": VERSION,
        "SOURCE_A_COMPONENT_RECONCILIATION_STATUS": status,
        "raw_document_analysisresultitem": total,
        "canonical_source_a_observation_component": can_total,
        "gap": gap,
        "exclusive_raw_buckets": {
            "orphan_no_header": orphan,
            "header_without_patient": no_pat,
            "empty_with_patient": empty,
            "non_numeric_with_patient": nonnum,
            "numeric_with_patient_regex": num,
            "sum": exclusive_sum,
            "sum_equals_raw": exclusive_sum == total,
        },
        "canonical_buckets": {
            "total": can_total,
            "numeric_value_present": can_num,
            "numeric_value_null": can_non,
            "numeric_raw_matches_accounting_regex": can_num_check - loader_beyond_regex,
            "numeric_raw_beyond_accounting_regex": loader_beyond_regex,
        },
        "six_row_discrepancy_origin": {
            "description": (
                "Exactly six canonical components have numeric_value set whose raw_value "
                "fails the v0.1.1 accounting regex but is accepted by loader "
                "float(value.replace(',','.').strip()). "
                "Observed forms include leading '+' and trailing comma ('19,' → '19.')."
            ),
            "count": loader_beyond_regex,
            "samples": beyond_samples,
            "loader_path": "human_simulator.core.load (float after comma→dot)",
            "accounting_regex": ACCOUNTING_NUMERIC_REGEX,
            "examples": list(LOADER_BEYOND_REGEX_EXAMPLES),
        },
        "gap_explained_as": gap_explained,
        "invariant_explained_gap_equals_raw_minus_canonical": gap_explained["matches_gap"],
        "pass_forbidden_when_matches_gap_false": True,
        "v011_defect": {
            "reported_explanation_sum": 213634,
            "actual_gap": 213628,
            "delta": 6,
            "cause": "non_numeric_not_loaded overstated by loader_beyond_regex count",
        },
    }


def assert_reconciliation_status_contract(doc: dict[str, Any]) -> None:
    """Raise if PASS is claimed while matches_gap is false."""
    status = doc.get("SOURCE_A_COMPONENT_RECONCILIATION_STATUS")
    matches = (doc.get("gap_explained_as") or {}).get("matches_gap")
    if status == "PASS" and matches is False:
        raise AssertionError("PASS forbidden when matches_gap=false")
