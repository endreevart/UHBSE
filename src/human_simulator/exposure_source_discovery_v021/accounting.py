"""Live read-only feedback ledger. Counts are computed, not supplied."""

from __future__ import annotations

from typing import Any

from human_simulator.exposure_source_discovery_v021.policy import DRUG_CATEGORY_TITLE, SUBJECT_CATEGORIES, TEMPORAL_CATEGORIES


def _fraction(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


_LEDGER_SQL = """
WITH joined AS (
    SELECT
        f.consultation_id IS NULL AS id_null,
        f.created_at IS NULL AS created_null,
        f.created_at AS created_at,
        f.user_id AS user_id,
        f.user_id IS NULL AS user_null,
        count(c.id) AS target_n,
        min(c.date) AS date_min,
        max(c.date) AS date_max,
        min(c.patient_id) AS patient_min,
        max(c.patient_id) AS patient_max,
        bool_or(c.patient_id IS NULL) AS any_patient_null
    FROM public.feedback f
    LEFT JOIN public.consultations c ON c.id = f.consultation_id
    GROUP BY f.id, f.consultation_id, f.created_at, f.user_id
),
marked AS (
    SELECT
        *,
        (NOT id_null AND target_n = 0) AS dangling,
        (target_n >= 1) AS target_found,
        (target_n > 1) AS multiple_targets,
        (
            target_n >= 1
            AND NOT created_null
            AND date_min IS NOT NULL
            AND date_min IS NOT DISTINCT FROM date_max
        ) AS comparable
    FROM joined
)
SELECT
    count(*)::bigint,
    count(*) FILTER (WHERE id_null)::bigint,
    count(*) FILTER (WHERE dangling)::bigint,
    count(*) FILTER (WHERE comparable AND created_at::date < date_min)::bigint,
    count(*) FILTER (WHERE comparable AND created_at::date = date_min)::bigint,
    count(*) FILTER (WHERE comparable AND created_at::date > date_min)::bigint,
    count(*) FILTER (WHERE target_found AND NOT comparable)::bigint,
    count(*) FILTER (WHERE target_found AND created_null AND date_min IS NULL)::bigint,
    count(*) FILTER (WHERE target_found AND created_null AND date_min IS NOT NULL)::bigint,
    count(*) FILTER (WHERE target_found AND NOT created_null AND (date_min IS NULL OR date_min IS DISTINCT FROM date_max))::bigint,
    count(*) FILTER (WHERE multiple_targets)::bigint,
    count(*) FILTER (WHERE NOT target_found)::bigint,
    count(*) FILTER (WHERE target_found AND user_null AND patient_max IS NULL)::bigint,
    count(*) FILTER (WHERE target_found AND user_null AND patient_max IS NOT NULL)::bigint,
    count(*) FILTER (WHERE target_found AND NOT user_null AND (patient_max IS NULL OR any_patient_null))::bigint,
    count(*) FILTER (WHERE target_found AND NOT user_null AND NOT any_patient_null AND patient_min IS NOT NULL AND patient_min = patient_max AND user_id = patient_min)::bigint,
    count(*) FILTER (WHERE target_found AND NOT user_null AND NOT any_patient_null AND patient_min IS NOT NULL AND (user_id IS DISTINCT FROM patient_min OR patient_min IS DISTINCT FROM patient_max))::bigint,
    count(*) FILTER (WHERE temporal_flags <> 1)::bigint,
    count(*) FILTER (WHERE subject_flags <> 1)::bigint
FROM (
    SELECT
        marked.*,
        (
            id_null::int
            + (NOT id_null AND target_n = 0)::int
            + (comparable AND created_at::date < date_min)::int
            + (comparable AND created_at::date = date_min)::int
            + (comparable AND created_at::date > date_min)::int
            + (target_found AND NOT comparable)::int
        ) AS temporal_flags,
        (
            (NOT target_found)::int
            + (target_found AND user_null AND patient_max IS NULL)::int
            + (target_found AND user_null AND patient_max IS NOT NULL)::int
            + (target_found AND NOT user_null AND (patient_max IS NULL OR any_patient_null))::int
            + (target_found AND NOT user_null AND NOT any_patient_null AND patient_min IS NOT NULL AND patient_min = patient_max AND user_id = patient_min)::int
            + (target_found AND NOT user_null AND NOT any_patient_null AND patient_min IS NOT NULL AND (user_id IS DISTINCT FROM patient_min OR patient_min IS DISTINCT FROM patient_max))::int
        ) AS subject_flags
    FROM marked
) ledger
"""

_TIME_SQL = """
SELECT current_setting('TimeZone'),
       current_setting('transaction_read_only')
"""

_COLUMN_SQL = """
SELECT table_name, column_name, data_type, udt_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('feedback', 'consultations')
  AND column_name IN ('created_at', 'date', 'consultation_id', 'user_id', 'patient_id')
ORDER BY table_name, column_name
"""

_ROUTE_SQL = """
WITH drug AS (
    SELECT c.patient_id, c.id AS consultation_id, c.date
    FROM public.consultations c
    JOIN quest_digital.recommendations_user u ON u.consultations_id = c.id
    JOIN quest_digital.recommendations_list l ON l.id = u.recommendations_id
    JOIN quest_digital.recommendations_category cat ON cat.id = l.category_id
    WHERE cat.title = %s AND c.date IS NOT NULL
    GROUP BY c.patient_id, c.id, c.date
),
base AS (
    SELECT
        f.id,
        f.user_id,
        f.consultation_id,
        f.created_at,
        count(c.id) AS target_n,
        min(c.date) AS date_min,
        max(c.date) AS date_max
    FROM public.feedback f
    LEFT JOIN public.consultations c ON c.id = f.consultation_id
    GROUP BY f.id, f.user_id, f.consultation_id, f.created_at
),
prior AS (
    SELECT b.id, max(d.date) AS prior_date
    FROM base b
    JOIN drug d
      ON d.patient_id = b.user_id
     AND b.created_at IS NOT NULL
     AND d.date < b.created_at::date
     AND d.consultation_id IS DISTINCT FROM b.consultation_id
    GROUP BY b.id
),
same_rec AS (
    SELECT b.id
    FROM base b
    JOIN drug d ON d.consultation_id = b.consultation_id
    WHERE b.target_n >= 1
    GROUP BY b.id
),
flags AS (
    SELECT
        b.id,
        b.target_n = 0 AS target_missing,
        (
            b.target_n = 1
            AND b.created_at IS NOT NULL
            AND b.date_min IS NOT NULL
            AND b.date_min = b.date_max
        ) AS comparable,
        b.created_at::date <= b.date_min AS on_or_after_feedback,
        b.created_at::date > b.date_min AS consultation_before_feedback,
        p.id IS NOT NULL AS has_prior,
        s.id IS NOT NULL AS has_same_consultation_rec,
        (p.prior_date IS NOT NULL) AS prior_date_present,
        CASE WHEN p.prior_date IS NULL THEN NULL ELSE (b.created_at::date - p.prior_date) END AS days_since_prior,
        CASE
            WHEN b.created_at IS NULL OR b.date_min IS NULL THEN NULL
            ELSE (b.date_min - b.created_at::date)
        END AS days_until_consultation
    FROM base b
    LEFT JOIN prior p ON p.id = b.id
    LEFT JOIN same_rec s ON s.id = b.id
)
SELECT
    count(*)::bigint,
    count(*) FILTER (WHERE target_missing)::bigint,
    count(*) FILTER (WHERE comparable AND on_or_after_feedback AND has_prior)::bigint,
    count(*) FILTER (WHERE comparable AND on_or_after_feedback AND NOT has_prior)::bigint,
    count(*) FILTER (WHERE comparable AND consultation_before_feedback AND has_prior)::bigint,
    count(*) FILTER (WHERE has_same_consultation_rec AND NOT has_prior)::bigint,
    count(*) FILTER (WHERE target_missing AND has_prior)::bigint,
    percentile_cont(0.1) WITHIN GROUP (ORDER BY days_since_prior) FILTER (WHERE comparable AND on_or_after_feedback AND has_prior),
    percentile_cont(0.5) WITHIN GROUP (ORDER BY days_since_prior) FILTER (WHERE comparable AND on_or_after_feedback AND has_prior),
    percentile_cont(0.9) WITHIN GROUP (ORDER BY days_since_prior) FILTER (WHERE comparable AND on_or_after_feedback AND has_prior),
    percentile_cont(0.1) WITHIN GROUP (ORDER BY days_until_consultation) FILTER (WHERE comparable AND on_or_after_feedback AND has_prior),
    percentile_cont(0.5) WITHIN GROUP (ORDER BY days_until_consultation) FILTER (WHERE comparable AND on_or_after_feedback AND has_prior),
    percentile_cont(0.9) WITHIN GROUP (ORDER BY days_until_consultation) FILTER (WHERE comparable AND on_or_after_feedback AND has_prior)
FROM flags
"""


def _categories(pairs: list[tuple[str, int]], total: int) -> dict[str, dict[str, Any]]:
    return {
        name: {"count": count, "fraction": _fraction(count, total)}
        for name, count in pairs
    }


def collect(conn: Any, log: Any, fingerprint: str) -> dict[str, Any]:
    zone = log.run(conn, "b_session_timezone", "kgz_raw", _TIME_SQL)[0]
    columns = log.run(conn, "b_temporal_column_types", "kgz_raw", _COLUMN_SQL)
    column_map = {
        f"{table}.{column}": {"data_type": data_type, "udt_name": udt, "nullable": nullable == "YES"}
        for table, column, data_type, udt, nullable in columns
    }
    row = log.run(conn, "b_feedback_exclusive_ledger", "kgz_raw", _LEDGER_SQL)[0]
    (
        total, id_null, dangling, before, same_day, after, uncomparable,
        uncomp_both_null, uncomp_created_null, uncomp_date_null,
        multiple, subject_not_run, both_null, user_null, patient_null, equal, unequal,
        temporal_overlap, subject_overlap,
    ) = (int(value) for value in row)
    temporal = {
        "CONSULTATION_ID_NULL": id_null,
        "CONSULTATION_ID_PRESENT_TARGET_NOT_FOUND": dangling,
        "CONSULTATION_TARGET_FOUND_TIME_BEFORE": before,
        "CONSULTATION_TARGET_FOUND_TIME_SAME_DAY": same_day,
        "CONSULTATION_TARGET_FOUND_TIME_AFTER": after,
        "CONSULTATION_TARGET_FOUND_TIME_UNCOMPARABLE": uncomparable,
    }
    subject = {
        "SUBJECT_COMPARISON_NOT_RUN_TARGET_MISSING": subject_not_run,
        "BOTH_SUBJECT_KEYS_NULL": both_null,
        "FEEDBACK_USER_ID_NULL": user_null,
        "CONSULTATION_PATIENT_ID_NULL": patient_null,
        "SUBJECT_KEYS_BOTH_PRESENT_EQUAL": equal,
        "SUBJECT_KEYS_BOTH_PRESENT_UNEQUAL": unequal,
    }
    present = total - id_null
    found = before + same_day + after + uncomparable
    route = log.run(conn, "b_prior_recommendation_candidate_route", "kgz_raw", _ROUTE_SQL, (DRUG_CATEGORY_TITLE,))[0]
    candidate = int(route[2])
    no_prior = int(route[3])
    prior_out_of_order = int(route[4])
    same_only = int(route[5])
    prior_on_missing_target = int(route[6])
    created_type = column_map.get("feedback.created_at", {}).get("data_type")
    date_type = column_map.get("consultations.date", {}).get("data_type")
    timezone_status = (
        "UNKNOWN_SOURCE_TIMEZONE"
        if created_type == "timestamp without time zone" and date_type == "date"
        else "UNKNOWN_SOURCE_TIMEZONE"
    )
    temporal_sum = sum(temporal.values())
    subject_sum = sum(subject.values())
    target_ok = (
        id_null + present == total
        and found + dangling == present
        and multiple == 0
        and temporal_overlap == 0
        and temporal_sum == total
    )
    return {
        "schema_fingerprint": fingerprint,
        "temporal_contract": {
            "feedback.created_at": created_type,
            "consultations.date": date_type,
            "column_catalog": column_map,
            "session_timezone": zone[0],
            "timezone_metadata_on_columns": "none: timestamp without time zone and date carry no zone",
            "comparison_rule": "created_at::date compared with consultations.date; no AT TIME ZONE conversion",
            "null_rule": "a found target with null created_at, null consultation date, or disagreeing target dates is UNCOMPARABLE",
            "same_day_rule": "calendar dates are equal after the cast above",
            "timezone_proof": False,
            "SOURCE_B_TIMEZONE_SEMANTICS_STATUS": timezone_status,
        },
        "exclusive": {
            "FEEDBACK_TOTAL_COUNT": total,
            "categories": _categories(list(temporal.items()), total),
            "sum_exclusive_categories": temporal_sum,
            "overlap_count": temporal_overlap,
            "unclassified_count": total - temporal_sum,
            "uncomparable_components": {
                "created_at_null_and_consultation_date_null": uncomp_both_null,
                "created_at_null_and_consultation_date_present": uncomp_created_null,
                "created_at_present_and_consultation_date_missing_or_targets_disagree": uncomp_date_null,
                "component_sum": uncomp_both_null + uncomp_created_null + uncomp_date_null,
            },
            "FEEDBACK_TEMPORAL_EXCLUSIVE_ACCOUNTING_STATUS": "PASS"
            if temporal_sum == total and temporal_overlap == 0 and total - temporal_sum == 0
            else "FAIL",
        },
        "targets": {
            "FEEDBACK_TOTAL_COUNT": total,
            "CONSULTATION_ID_NULL_COUNT": id_null,
            "CONSULTATION_ID_PRESENT_COUNT": present,
            "CONSULTATION_TARGET_FOUND_COUNT": found,
            "CONSULTATION_TARGET_NOT_FOUND_COUNT": dangling,
            "CONSULTATION_TARGET_MULTIPLE_MATCH_COUNT": multiple,
            "null_plus_present_equals_total": id_null + present == total,
            "found_plus_missing_equals_present": found + dangling == present,
            "CONSULTATION_TARGET_ACCOUNTING_STATUS": "PASS" if target_ok else (
                "CONFLICT_MULTIPLE_TARGET" if multiple else "FAIL"
            ),
        },
        "subjects": {
            "FEEDBACK_TOTAL_COUNT": total,
            "categories": _categories(list(subject.items()), total),
            "sum_subject_comparison_categories": subject_sum,
            "overlap_count": subject_overlap,
            "unclassified_count": total - subject_sum,
            "equality_denominator": equal + unequal,
            "phrase": "NUMERIC_KEY_AGREEMENT_OBSERVED_NOT_IDENTITY_PROOF",
            "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS": "NOT_ESTABLISHED",
            "SUBJECT_KEY_COMPARISON_ACCOUNTING_STATUS": "PASS"
            if subject_sum == total and subject_overlap == 0
            else "FAIL",
        },
        "route": {
            "denominator": int(route[0]),
            "candidate_count": candidate,
            "candidate_fraction": _fraction(candidate, int(route[0])),
            "excluded_target_missing_count": int(route[1]),
            "excluded_no_prior_recommendation_count": no_prior,
            "excluded_out_of_order_count": prior_out_of_order,
            "excluded_same_consultation_only_count": same_only,
            "prior_recommendation_on_missing_target_count": prior_on_missing_target,
            "identity_assumption_status": "NOT_ESTABLISHED",
            "uses_unverified_user_id_equals_patient_id": True,
            "same_consultation_recommendation_is_not_prior": True,
            "missing_target_is_not_a_completed_chain": True,
            "verified_exposure": False,
            "interval_feedback_minus_prior_recommendation_days": {
                "n": candidate, "p10": _num(route[7]), "p50": _num(route[8]), "p90": _num(route[9]),
            },
            "interval_consultation_minus_feedback_days": {
                "n": candidate, "p10": _num(route[10]), "p50": _num(route[11]), "p90": _num(route[12]),
            },
            "exclusive_funnel_sums_to_denominator": (
                int(route[1]) + uncomparable + after + no_prior + candidate == int(route[0])
            ),
            "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": "CANDIDATE_COUNTED_IDENTITY_NOT_ESTABLISHED",
        },
        "category_order": {"temporal": list(TEMPORAL_CATEGORIES), "subject": list(SUBJECT_CATEGORIES)},
    }
