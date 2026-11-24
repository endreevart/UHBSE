"""Source B schema, sentinels, identity and temporal routes. Aggregates only."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from human_simulator.exposure_source_discovery_v02.db import _now

from human_simulator.exposure_source_discovery_v02.textutil import classify_sentinel, quantiles

TABLES = (
    ("public", "feedback"),
    ("public", "consultations"),
    ("public", "questionnaire"),
    ("quest_digital", "recommendations_user"),
    ("quest_digital", "recommendations_list"),
    ("quest_digital", "recommendations_category"),
)
SENTINEL_FIELDS = (
    "drugs", "vitamins", "change_drugs", "decline_drugs", "positive_changes",
    "complaints", "outside_doctor_medicine", "drugs_first",
)
DRUG_CATEGORY = "Препараты"


def _definition(text: str) -> dict[str, Any]:
    value = text or ""
    if len(value) <= 160 and "@" not in value:
        return {"definition": value}
    return {
        "definition_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "definition_length": len(value),
    }


def _days(value: Any) -> float:
    days = getattr(value, "days", None)
    return float(days if days is not None else value)


def _constraints(conn: Any, log: Any) -> list[dict[str, str]]:
    rows = log.run(
        conn,
        "b_constraints",
        "kgz_raw",
        """
        SELECT n.nspname, c.relname, con.contype, pg_get_constraintdef(con.oid)
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE (n.nspname, c.relname) IN (
            ('public','feedback'), ('public','consultations'), ('public','questionnaire'),
            ('quest_digital','recommendations_user'), ('quest_digital','recommendations_list'),
            ('quest_digital','recommendations_category')
        )
          AND con.contype IN ('f', 'u', 'c')
        ORDER BY 1, 2, 4
        """,
    )
    kind = {"f": "FOREIGN_KEY", "u": "UNIQUE", "c": "CHECK"}
    return [
        {"schema": schema, "relation": rel, "type": kind.get(ctype, ctype), **_definition(definition)}
        for schema, rel, ctype, definition in rows
    ]


def _columns(conn: Any, log: Any) -> list[dict[str, Any]]:
    rows = log.run(
        conn,
        "b_columns",
        "kgz_raw",
        """
        SELECT c.table_schema, c.table_name, c.column_name, c.data_type, c.udt_name, c.is_nullable,
               c.column_default IS NOT NULL,
               col_description((c.table_schema || '.' || c.table_name)::regclass, c.ordinal_position)
        FROM information_schema.columns c
        WHERE (c.table_schema, c.table_name) IN (
            ('public','feedback'), ('public','consultations'), ('public','questionnaire'),
            ('quest_digital','recommendations_user'), ('quest_digital','recommendations_list'),
            ('quest_digital','recommendations_category')
        )
        ORDER BY 1, 2, c.ordinal_position
        """,
    )
    out = []
    for schema, rel, column, data_type, udt, nullable, has_default, comment in rows:
        item = {
            "schema": schema,
            "relation": rel,
            "column": column,
            "data_type": data_type,
            "udt_name": udt,
            "nullable": nullable == "YES",
            "has_default": bool(has_default),
        }
        if comment:
            text = str(comment)
            if len(text) <= 80 and "@" not in text:
                item["comment"] = text
            else:
                item["comment_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                item["comment_length"] = len(text)
        out.append(item)
    return out


def schema_contract(conn: Any, log: Any, fingerprint: str) -> dict[str, Any]:
    columns = _columns(conn, log)
    constraints = _constraints(conn, log)
    user_fk = [
        item for item in constraints
        if item["relation"] == "feedback" and item["type"] == "FOREIGN_KEY" and "user_id" in item.get("definition", "")
    ]
    patient_fk = [
        item for item in constraints
        if item["relation"] == "consultations" and item["type"] == "FOREIGN_KEY" and "patient_id" in item.get("definition", "")
    ]
    return {
        "source_system": "kgz_raw",
        "schema_fingerprint": fingerprint,
        "columns": columns,
        "constraints": constraints,
        "feedback_user_id_foreign_key": user_fk,
        "consultations_patient_id_foreign_key": patient_fk,
        "documented_crosswalk": None,
        "application_code": {
            "status": "NOT_FOUND_IN_REPOSITORY",
            "searched": "repository working tree",
            "human_or_domain_acceptance": False,
        },
        "timezone_contract": {
            "feedback.created_at": "timestamp without time zone",
            "consultations.date": "date",
            "consultations.created_at": "timestamp without time zone",
            "recommendations_user.created_at": "timestamp without time zone",
            "zone": "UNKNOWN",
            "comparisons": "naive, not a verified civil-time contract",
        },
        "SOURCE_B_FEEDBACK_SCHEMA_STATUS": "SCHEMA_CAPTURED_SEMANTICS_UNKNOWN",
    }


def sentinel_profile(conn: Any, log: Any) -> dict[str, Any]:
    fields = {}
    for column in SENTINEL_FIELDS:
        counts = {name: 0 for name in (
            "NULL", "EMPTY", "NEGATIVE_SHORT", "AFFIRMATIVE_SHORT", "BOOLEAN_LIKE",
            "NUMERIC_ONLY", "PLACEHOLDER", "FREE_TEXT_SHORT", "FREE_TEXT_LONG", "OTHER",
        )}
        total = 0
        sql = f"SELECT {column} FROM public.feedback"
        started, clock = _now(), time.monotonic()
        with conn.cursor(name=f"b_sent_{column}") as cur:
            cur.itersize = 5000
            cur.execute(sql)
            for (value,) in cur:
                total += 1
                counts[classify_sentinel(value)] += 1
        conn.commit()
        log.note_stream(f"b_sentinel_{column}", "kgz_raw", sql, total, started, clock)
        fields[column] = {
            "rows": total,
            "classes": counts,
            "fractions": {name: round(count / total, 4) if total else None for name, count in counts.items()},
            "semantic_status": "UNKNOWN_PENDING_HUMAN_REVIEW",
        }
    explained = {}
    for column, profile in fields.items():
        short = profile["classes"]["NEGATIVE_SHORT"] + profile["classes"]["PLACEHOLDER"] + profile["classes"]["EMPTY"] + profile["classes"]["NULL"]
        explained[column] = {
            "null_empty_negative_or_placeholder_fraction": round(short / profile["rows"], 4) if profile["rows"] else None,
            "non_empty_is_not_a_medication_description": True,
        }
    return {
        "source_system": "kgz_raw",
        "fields": fields,
        "fill_explanation": explained,
        "SOURCE_B_FEEDBACK_SENTINEL_ACCOUNTING_STATUS": "COUNTED_MEANING_UNKNOWN",
    }


def identity_audit(conn: Any, log: Any, schema: dict[str, Any]) -> dict[str, Any]:
    counts = log.run(
        conn,
        "b_identity_counts",
        "kgz_raw",
        """
        SELECT
          (SELECT count(*) FROM public.feedback),
          (SELECT count(DISTINCT user_id) FROM public.feedback),
          (SELECT count(*) FROM public.consultations),
          (SELECT count(DISTINCT patient_id) FROM public.consultations),
          (SELECT count(*) FROM public.feedback WHERE consultation_id IS NULL),
          (SELECT count(*) FROM public.feedback f JOIN public.consultations c ON c.id = f.consultation_id),
          (SELECT count(*) FROM public.feedback f JOIN public.consultations c ON c.id = f.consultation_id
            WHERE f.user_id IS DISTINCT FROM c.patient_id),
          (SELECT count(*) FROM public.feedback f JOIN public.consultations c ON c.id = f.consultation_id
            WHERE f.user_id = c.patient_id)
        """,
    )[0]
    card = log.run(
        conn,
        "b_identity_cardinality",
        "kgz_raw",
        """
        WITH per_feedback_key AS (
            SELECT user_id, count(*) AS n FROM public.feedback GROUP BY user_id
        ),
        per_consult_key AS (
            SELECT patient_id, count(*) AS n FROM public.consultations GROUP BY patient_id
        )
        SELECT
          (SELECT count(*) FROM per_feedback_key WHERE n = 1),
          (SELECT count(*) FROM per_feedback_key WHERE n > 1),
          (SELECT count(*) FROM per_consult_key WHERE n = 1),
          (SELECT count(*) FROM per_consult_key WHERE n > 1)
        """,
    )[0]
    linked = counts[5]
    conflicts = counts[6]
    agrees = counts[7]
    has_fk = bool(schema["feedback_user_id_foreign_key"]) and bool(schema["consultations_patient_id_foreign_key"])
    if conflicts:
        status = "FAIL_CONFLICT"
    elif has_fk and schema["documented_crosswalk"]:
        status = "PASS_VERIFIED_RELATION"
    else:
        status = "NOT_ESTABLISHED"
    return {
        "source_system": "kgz_raw",
        "equality_used_as_verification": False,
        "feedback_rows": counts[0],
        "distinct_feedback_user_keys": counts[1],
        "consultation_rows": counts[2],
        "distinct_consultation_patient_keys": counts[3],
        "feedback_without_consultation": counts[4],
        "linked_consultation_rows": linked,
        "linked_subject_disagreements": conflicts,
        "linked_subject_agreements": agrees,
        "agreement_is_not_schema_proof": True,
        "feedback_keys_with_one_row": card[0],
        "feedback_keys_with_many_rows": card[1],
        "consultation_keys_with_one_row": card[2],
        "consultation_keys_with_many_rows": card[3],
        "foreign_key_on_feedback_user_id": bool(schema["feedback_user_id_foreign_key"]),
        "foreign_key_on_consultations_patient_id": bool(schema["consultations_patient_id_foreign_key"]),
        "documented_crosswalk": False,
        "SOURCE_B_SUBJECT_IDENTITY_LINKAGE_STATUS": status,
    }


def _route(count: int, total: int, sample: list[float], identity: str, out_of_order: int = 0) -> dict[str, Any]:
    negatives = sum(1 for value in sample if value < 0)
    zeros = sum(1 for value in sample if value == 0)
    return {
        "count": count,
        "fraction": round(count / total, 4) if total else None,
        "interval_days": quantiles(sample),
        "negative_intervals_in_sample": negatives,
        "zero_intervals_in_sample": zeros,
        "sample_size": len(sample),
        "out_of_order_count": out_of_order,
        "identity_verification_tier": identity,
    }


def _sql_interval(count: int, p10: Any, p50: Any, p90: Any, negatives: int, zeros: int) -> dict[str, Any]:
    def num(value: Any) -> float | None:
        return None if value is None else float(value)
    return {
        "interval_days": {"n": count, "p10": num(p10), "p50": num(p50), "p90": num(p90)},
        "negative_intervals_in_sample": negatives,
        "zero_intervals_in_sample": zeros,
        "sample_size": count,
    }


def temporal_audit(conn: Any, log: Any, identity_status: str) -> dict[str, Any]:
    """Naive timestamps. Identity-dependent routes stay at the identity tier."""
    total = log.run(conn, "b_feedback_total", "kgz_raw", "SELECT count(*) FROM public.feedback")[0][0]
    linked = log.run(
        conn,
        "b_temporal_linked_direction",
        "kgz_raw",
        """
        SELECT
          count(*) FILTER (WHERE f.consultation_id IS NULL),
          count(*) FILTER (WHERE c.id IS NOT NULL AND f.created_at::date < c.date),
          count(*) FILTER (WHERE c.id IS NOT NULL AND f.created_at::date > c.date),
          count(*) FILTER (WHERE c.id IS NOT NULL AND f.created_at::date = c.date),
          count(*) FILTER (WHERE c.id IS NOT NULL AND c.date IS NULL)
        FROM public.feedback f
        LEFT JOIN public.consultations c ON c.id = f.consultation_id
        """,
    )[0]
    gaps = log.run(
        conn,
        "b_temporal_linked_gaps",
        "kgz_raw",
        """
        SELECT (f.created_at::date - c.date)
        FROM public.feedback f
        JOIN public.consultations c ON c.id = f.consultation_id
        WHERE c.date IS NOT NULL AND f.created_at IS NOT NULL
        """,
    )
    gap_values = [_days(row[0]) for row in gaps]
    before = [value for value in gap_values if value < 0]
    after = [value for value in gap_values if value > 0]
    # Drug recommendations use the catalog title, not an accepted mapping.
    # Subject equality here is only the unverified numeric probe.
    probe = log.run(
        conn,
        "b_temporal_unverified_subject_probe",
        "kgz_raw",
        """
        WITH drug AS (
            SELECT c.patient_id, c.id AS consultation_id, c.date
            FROM public.consultations c
            JOIN quest_digital.recommendations_user u ON u.consultations_id = c.id
            JOIN quest_digital.recommendations_list l ON l.id = u.recommendations_id
            JOIN quest_digital.recommendations_category cat ON cat.id = l.category_id
            WHERE cat.title = %s AND c.date IS NOT NULL
            GROUP BY c.patient_id, c.id, c.date
        ),
        prior AS (
            SELECT f.id
            FROM public.feedback f
            JOIN drug d
              ON d.patient_id = f.user_id
             AND d.date < f.created_at::date
             AND d.consultation_id IS DISTINCT FROM f.consultation_id
            GROUP BY f.id
        ),
        on_linked AS (
            SELECT f.id
            FROM public.feedback f
            JOIN drug d ON d.consultation_id = f.consultation_id
            GROUP BY f.id
        ),
        candidate AS (
            SELECT p.id
            FROM prior p
            JOIN public.feedback f ON f.id = p.id
            JOIN public.consultations c ON c.id = f.consultation_id
            WHERE c.date IS NOT NULL
              AND f.created_at IS NOT NULL
              AND f.created_at::date <= c.date
        ),
        prior_gaps AS (
            SELECT f.id, (f.created_at::date - max(d.date)) AS days
            FROM public.feedback f
            JOIN drug d
              ON d.patient_id = f.user_id
             AND d.date < f.created_at::date
             AND d.consultation_id IS DISTINCT FROM f.consultation_id
            WHERE f.created_at IS NOT NULL
            GROUP BY f.id, f.created_at
        ),
        candidate_gaps AS (
            SELECT g.days
            FROM prior_gaps g
            JOIN public.feedback f ON f.id = g.id
            JOIN public.consultations c ON c.id = f.consultation_id
            WHERE c.date IS NOT NULL
              AND f.created_at::date <= c.date
        )
        SELECT
          (SELECT count(*) FROM prior),
          (SELECT count(*) FROM on_linked),
          (SELECT count(*) FROM candidate),
          (SELECT percentile_cont(0.1) WITHIN GROUP (ORDER BY days) FROM prior_gaps),
          (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY days) FROM prior_gaps),
          (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY days) FROM prior_gaps),
          (SELECT count(*) FILTER (WHERE days < 0) FROM prior_gaps),
          (SELECT count(*) FILTER (WHERE days = 0) FROM prior_gaps),
          (SELECT percentile_cont(0.1) WITHIN GROUP (ORDER BY days) FROM candidate_gaps),
          (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY days) FROM candidate_gaps),
          (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY days) FROM candidate_gaps),
          (SELECT count(*) FILTER (WHERE days < 0) FROM candidate_gaps),
          (SELECT count(*) FILTER (WHERE days = 0) FROM candidate_gaps)
        """,
        (DRUG_CATEGORY,),
    )[0]
    tier = identity_status if identity_status == "PASS_VERIFIED_RELATION" else "NOT_ESTABLISHED"
    routes = {
        "feedback_before_linked_consultation": _route(linked[1], total, before, "FK_CONSULTATION_ONLY"),
        "feedback_after_linked_consultation": _route(linked[2], total, after, "FK_CONSULTATION_ONLY", out_of_order=linked[2]),
        "feedback_without_linked_consultation": _route(linked[0], total, [], "NOT_APPLICABLE"),
        "same_calendar_day_as_linked_consultation": {
            **_route(linked[3], total, [], "FK_CONSULTATION_ONLY"),
            "interval_days": {"n": linked[3], "p10": 0, "p50": 0, "p90": 0} if linked[3] else quantiles([]),
            "zero_intervals_in_sample": linked[3],
            "sample_size": linked[3],
            "interval_is_zero_by_construction": True,
            "out_of_order_count": 0,
        },
        "linked_consultation_date_missing": {"count": linked[4], "fraction": round(linked[4] / total, 4) if total else None},
        "earlier_drug_recommendation_same_unverified_subject": {
            **_route(probe[0], total, [], tier),
            **_sql_interval(probe[0], probe[3], probe[4], probe[5], probe[6], probe[7]),
            "uses_unverified_user_id_equals_patient_id": True,
            "not_a_verified_prior_exposure": True,
            "out_of_order_count": probe[6],
        },
        "drug_recommendation_on_linked_consultation": {
            **_route(probe[1], total, [], "FK_CONSULTATION_ONLY"),
            "this_is_not_a_prior_recommendation": True,
            "interval_not_applicable_same_consultation": True,
        },
        "candidate_between_unverified_prior_recommendation_and_linked_consultation": {
            **_route(probe[2], total, [], tier),
            **_sql_interval(probe[2], probe[8], probe[9], probe[10], probe[11], probe[12]),
            "route": "unverified prior drug recommendation -> feedback created -> linked consultation on or after feedback",
            "verified": False,
            "out_of_order_count": probe[11],
        },
    }
    return {
        "source_system": "kgz_raw",
        "timezone_contract": "naive_timestamp_without_time_zone",
        "verified_civil_time": False,
        "feedback_rows": total,
        "routes": routes,
        "out_of_order_relative_to_linked_consultation": linked[2],
        "SOURCE_B_TEMPORAL_SEQUENCE_STATUS": "CANDIDATE_COUNTED_IDENTITY_NOT_ESTABLISHED"
        if tier != "PASS_VERIFIED_RELATION"
        else "COUNTED",
    }
