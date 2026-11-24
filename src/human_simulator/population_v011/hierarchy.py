"""Medication event hierarchy Levels 0–5 (replaces overstated 1,996 episodes)."""

from __future__ import annotations

from typing import Any

from human_simulator.population_v011.policy import (
    MIN_LEVEL5_EPISODES,
    MIN_LEVEL5_SUBJECTS,
    MIN_TEST_EPISODES,
    MIN_TEST_SUBJECTS,
    VERSION,
)


def build_event_hierarchy(conn_a: Any, med_profile: dict[str, Any]) -> dict[str, Any]:
    """Aggregate-only hierarchy; no patient IDs published."""
    time_status = (med_profile.get("time_semantics") or {}).get("clinical_event_time_status")
    ts_col = (med_profile.get("time_semantics") or {}).get(
        "chosen_technical_timestamp_candidate"
    ) or "appointment_date"

    with conn_a.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM magerya_api.diagnosis_medicineappointments")
        level0 = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM magerya_api.diagnosis_medicineappointments
            WHERE patient_id IS NOT NULL
            """
        )
        level0_linked = int(cur.fetchone()[0])

        # Level 1: medicine_id + timestamp candidate
        cur.execute(
            f"""
            SELECT COUNT(*) FROM magerya_api.diagnosis_medicineappointments
            WHERE patient_id IS NOT NULL
              AND medicine_id IS NOT NULL
              AND {ts_col} IS NOT NULL
            """
        )
        level1 = int(cur.fetchone()[0])

        # Level 2: pre/post any dated lab around event (reproduces prior 1996-style window)
        # Use appointment_date preferentially for windowing when chosen; else created
        cur.execute(
            f"""
            WITH med AS (
              SELECT id, patient_id, {ts_col} AS event_ts, medicine_id
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND {ts_col} IS NOT NULL
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
            SELECT COUNT(*) FILTER (WHERE has_pre AND has_post)
            FROM flagged
            """
        )
        level2 = int(cur.fetchone()[0])

        # Also compute with created for reinterpretation of v0.1 1996 figure
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
            SELECT COUNT(*) FILTER (WHERE has_pre AND has_post)
            FROM flagged
            """
        )
        level2_created_window = int(cur.fetchone()[0])

        # Level 3: same outcome (item name) before and after with numeric values
        cur.execute(
            f"""
            WITH med AS (
              SELECT id, patient_id, {ts_col} AS event_ts
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL
                AND medicine_id IS NOT NULL
                AND {ts_col} IS NOT NULL
            ),
            items AS (
              SELECT ar.patient_id,
                     COALESCE(NULLIF(TRIM(i.name), ''), '∅') AS outcome,
                     COALESCE(NULLIF(TRIM(i.unit), ''), '') AS unit,
                     COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts,
                     i.value
              FROM magerya_api.document_analysisresultitem i
              JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
              WHERE ar.patient_id IS NOT NULL
                AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
                AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
            ),
            linked AS (
              SELECT m.id, m.patient_id, m.event_ts, i.outcome, i.unit,
                     BOOL_OR(i.lab_ts < m.event_ts) AS has_pre,
                     BOOL_OR(i.lab_ts > m.event_ts) AS has_post
              FROM med m
              JOIN items i ON i.patient_id = m.patient_id
              GROUP BY m.id, m.patient_id, m.event_ts, i.outcome, i.unit
            )
            SELECT COUNT(*) FILTER (WHERE has_pre AND has_post),
                   COUNT(DISTINCT id) FILTER (WHERE has_pre AND has_post),
                   COUNT(DISTINCT patient_id) FILTER (WHERE has_pre AND has_post)
            FROM linked
            """
        )
        level3_pairs, level3_events, level3_subjects = (int(x) for x in cur.fetchone())

        # Level 4: medication-specific = level3 events (already require medicine_id)
        level4_events = level3_events
        level4_subjects = level3_subjects

        # Overlap / polypharmacy: concurrent distinct medicine_id same patient same day
        cur.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT patient_id, ({ts_col})::date AS d, COUNT(DISTINCT medicine_id) AS n_med
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND {ts_col} IS NOT NULL AND medicine_id IS NOT NULL
              GROUP BY 1,2
              HAVING COUNT(DISTINCT medicine_id) > 1
            ) t
            """
        )
        poly_days = int(cur.fetchone()[0])

    # Level 5 gates — technical modeling episodes
    # Without accepted clinical event time ACCEPTED, Level 5 = 0
    if time_status == "ACCEPTED_TECHNICAL_TIMESTAMP" and level4_events >= MIN_LEVEL5_EPISODES:
        level5 = level4_events
        level5_subjects = level4_subjects
    else:
        level5 = 0
        level5_subjects = 0

    levels = {
        "level_0_source_medication_row": level0,
        "level_0_with_patient_link": level0_linked,
        "level_1_timestamped_medication_event_candidate": level1,
        "level_2_pre_post_event_window": level2,
        "level_3_outcome_specific_event_episode_pairs": level3_pairs,
        "level_3_outcome_specific_event_episodes": level3_events,
        "level_3_subjects": level3_subjects,
        "level_4_medication_specific_outcome_episodes": level4_events,
        "level_4_subjects": level4_subjects,
        "level_5_intervention_associated_modeling_episodes": level5,
        "level_5_subjects": level5_subjects,
    }

    # Monotonicity on event counts (use event-level where applicable)
    chain = [
        level0,
        level1,
        level2,
        level3_events,
        level4_events,
        level5,
    ]
    mono = all(chain[i] >= chain[i + 1] for i in range(len(chain) - 1))

    reinterpretation = {
        "v01_reported_pre_post_windows": 1996,
        "recomputed_level2_using_created": level2_created_window,
        "recomputed_level2_using_candidate_timestamp": level2,
        "candidate_timestamp": ts_col,
        "correct_label_for_v01_1996": "level_2_pre_post_event_window",
        "not_an_intervention_episode": True,
        "not_treatment_effect": True,
        "note": (
            "The v0.1 figure of ~1,996 is a Level-2 pre/post laboratory window around a "
            "medication row timestamp (created), NOT a verified intervention episode."
        ),
    }

    gates = {
        "technical_event_timestamp_accepted": time_status == "ACCEPTED_TECHNICAL_TIMESTAMP",
        "clinical_event_time_status": time_status,
        "min_level5_subjects": MIN_LEVEL5_SUBJECTS,
        "min_level5_episodes": MIN_LEVEL5_EPISODES,
        "min_test_subjects": MIN_TEST_SUBJECTS,
        "min_test_episodes": MIN_TEST_EPISODES,
        "level5_subjects": level5_subjects,
        "level5_episodes": level5,
        "cohort_gate_pass": (
            level5_subjects >= MIN_LEVEL5_SUBJECTS and level5 >= MIN_LEVEL5_EPISODES
        ),
        "failed_gates": [],
    }
    if not gates["technical_event_timestamp_accepted"]:
        gates["failed_gates"].append("technical_event_timestamp_not_ACCEPTED")
    if not gates["cohort_gate_pass"]:
        gates["failed_gates"].append("level5_cohort_below_predeclared_minimum")

    return {
        "version": VERSION,
        "levels": levels,
        "hierarchy_monotonic": mono,
        "terminology": {
            "intervention_episode_allowed_below_level_4": False,
            "level_2_label": "pre_post_event_window",
            "level_5_label": "intervention_associated_modeling_episode",
            "not_treatment_effect": True,
        },
        "reinterpretation_of_v01_1996": reinterpretation,
        "overlap_polypharmacy": {
            "patient_days_with_gt1_distinct_medicine_id": poly_days,
        },
        "modeling_gates": gates,
        "causal_interpretation_allowed": False,
        "treatment_effect_estimated": False,
        "clinical_response_claimed": False,
        "technical_event_window_status": "BUILT",
        "outcome_specific_episode_status": "BUILT" if level3_events else "NOT_BUILT",
        "medication_specific_episode_status": "BUILT" if level4_events else "NOT_BUILT",
        "intervention_modeling_dataset_status": (
            "BUILT" if level5 > 0 else "NOT_BUILT_GATES_FAILED"
        ),
    }
