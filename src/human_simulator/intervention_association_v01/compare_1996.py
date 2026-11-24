"""Executable comparison: v0.1 ~1,996 vs v0.1.1 created-window 4,408."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_association_v01.policy import VERSION


def compare_1996_vs_4408(conn_a: Any) -> dict[str, Any]:
    """Reproduce both queries and explain the grouping difference."""
    with conn_a.cursor() as cur:
        # v0.1: GROUP BY patient_id, created — collapses concurrent medicine rows
        cur.execute(
            """
            WITH med AS (
              SELECT patient_id, created AS event_ts
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND created IS NOT NULL
            ),
            lab AS (
              SELECT ar.patient_id,
                     COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts
              FROM magerya_api.document_analysisresult ar
              WHERE ar.patient_id IS NOT NULL
                AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
            ),
            linked AS (
              SELECT m.patient_id, m.event_ts,
                     BOOL_OR(l.lab_ts < m.event_ts) AS has_pre,
                     BOOL_OR(l.lab_ts > m.event_ts) AS has_post
              FROM med m
              LEFT JOIN lab l ON l.patient_id = m.patient_id
              GROUP BY m.patient_id, m.event_ts
            )
            SELECT COUNT(*) FILTER (WHERE has_pre AND has_post) FROM linked
            """
        )
        v01_patient_ts = int(cur.fetchone()[0])

        # v0.1.1 Level-2 style: one row per medicine appointment id
        cur.execute(
            """
            WITH med AS (
              SELECT id, patient_id, created AS event_ts
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND created IS NOT NULL
            ),
            lab AS (
              SELECT ar.patient_id,
                     COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts
              FROM magerya_api.document_analysisresult ar
              WHERE ar.patient_id IS NOT NULL
                AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
            ),
            flagged AS (
              SELECT m.id,
                     BOOL_OR(l.lab_ts < m.event_ts) AS has_pre,
                     BOOL_OR(l.lab_ts > m.event_ts) AS has_post
              FROM med m
              LEFT JOIN lab l ON l.patient_id = m.patient_id
              GROUP BY m.id
            )
            SELECT COUNT(*) FILTER (WHERE has_pre AND has_post) FROM flagged
            """
        )
        v011_row_id = int(cur.fetchone()[0])

        # Concurrent rows at same patient+created that inflate row-id count
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE n_rows > 1) AS multi_row_groups,
              COALESCE(SUM(n_rows) FILTER (WHERE n_rows > 1), 0) AS rows_in_multi_groups,
              COALESCE(SUM(n_rows - 1) FILTER (WHERE n_rows > 1), 0) AS extra_rows_beyond_group
            FROM (
              SELECT patient_id, created, COUNT(*) AS n_rows
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND created IS NOT NULL
              GROUP BY patient_id, created
            ) t
            """
        )
        multi_groups, rows_in_multi, extra = (int(x or 0) for x in cur.fetchone())

        # appointment_date Level-2 row-id for contrast
        cur.execute(
            """
            WITH med AS (
              SELECT id, patient_id, appointment_date AS event_ts
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND appointment_date IS NOT NULL
            ),
            lab AS (
              SELECT ar.patient_id,
                     COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts
              FROM magerya_api.document_analysisresult ar
              WHERE ar.patient_id IS NOT NULL
                AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
            ),
            flagged AS (
              SELECT m.id,
                     BOOL_OR(l.lab_ts < m.event_ts) AS has_pre,
                     BOOL_OR(l.lab_ts > m.event_ts) AS has_post
              FROM med m
              LEFT JOIN lab l ON l.patient_id = m.patient_id
              GROUP BY m.id
            )
            SELECT COUNT(*) FILTER (WHERE has_pre AND has_post) FROM flagged
            """
        )
        appt_row_id = int(cur.fetchone()[0])

    return {
        "version": VERSION,
        "v01_approx_1996": {
            "count": v01_patient_ts,
            "query_grain": "patient_id + created timestamp",
            "collapses_concurrent_medication_rows": True,
            "timestamp_column": "created",
        },
        "v011_created_4408": {
            "count": v011_row_id,
            "query_grain": "diagnosis_medicineappointments.id",
            "collapses_concurrent_medication_rows": False,
            "timestamp_column": "created",
        },
        "appointment_date_row_id_level2": {
            "count": appt_row_id,
            "query_grain": "diagnosis_medicineappointments.id",
            "timestamp_column": "appointment_date",
        },
        "concurrent_created_groups": {
            "multi_row_groups": multi_groups,
            "rows_in_multi_groups": rows_in_multi,
            "extra_rows_beyond_one_per_group": extra,
        },
        "explanation": (
            "v0.1 counted distinct (patient_id, created) pairs with any pre and post lab "
            f"({v01_patient_ts}). v0.1.1 counted distinct medicine-appointment row ids with "
            f"pre/post ({v011_row_id}). Concurrent medication rows sharing the same "
            "patient_id+created inflate the row-id count relative to the patient-timestamp grain."
        ),
        "difference": v011_row_id - v01_patient_ts,
    }
