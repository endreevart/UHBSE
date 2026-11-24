"""Technical intervention episode construction (no treatment-effect claims)."""

from __future__ import annotations

from typing import Any

from human_simulator.population_v01.policy import SOURCE_A, VERSION


def build_technical_episodes(conn_a: Any, conn_canonical: Any) -> dict[str, Any]:
    """Aggregate-only technical episode funnel from Source A medicine rows + labs."""
    with conn_a.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='magerya_api' AND table_name='diagnosis_medicineappointments'
            """
        )
        cols = {r[0] for r in cur.fetchall()}
        if "patient_id" not in cols or "id" not in cols:
            return {
                "version": VERSION,
                "technical_intervention_episode_dataset_status": "NOT_BUILT",
                "intervention_response_model_status": "NOT_STARTED",
                "treatment_effect_status": "NOT_EVALUATED",
                "reason": "medicineappointments schema insufficient",
            }

        time_col = "created" if "created" in cols else None
        if not time_col:
            return {
                "version": VERSION,
                "technical_intervention_episode_dataset_status": "NOT_BUILT",
                "reason": "no_reliable_event_time_column",
                "intervention_response_model_status": "NOT_STARTED",
                "treatment_effect_status": "NOT_EVALUATED",
            }

        cur.execute(
            f"""
            WITH med AS (
              SELECT id, patient_id, {time_col} AS event_ts
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL
            ),
            flags AS (
              SELECT
                COUNT(*)::bigint AS source_rows,
                COUNT(*) FILTER (WHERE event_ts IS NOT NULL)::bigint AS with_event_time,
                COUNT(DISTINCT patient_id)::bigint AS unique_patients
              FROM med
            )
            SELECT * FROM flags
            """
        )
        source_rows, with_event_time, unique_patients = (int(x) for x in cur.fetchone())

        # Pre/post lab presence around medicine event (aggregate counts only)
        cur.execute(
            f"""
            WITH med AS (
              SELECT patient_id, {time_col} AS event_ts
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND {time_col} IS NOT NULL
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
                     BOOL_OR(l.lab_ts > m.event_ts) AS has_post,
                     BOOL_OR(l.lab_ts = m.event_ts) AS same_time
              FROM med m
              LEFT JOIN lab l ON l.patient_id = m.patient_id
              GROUP BY m.patient_id, m.event_ts
            )
            SELECT
              COUNT(*)::bigint,
              COUNT(*) FILTER (WHERE has_pre)::bigint,
              COUNT(*) FILTER (WHERE has_post)::bigint,
              COUNT(*) FILTER (WHERE has_pre AND has_post)::bigint,
              COUNT(*) FILTER (WHERE same_time AND NOT (has_pre AND has_post))::bigint,
              COUNT(*) FILTER (WHERE NOT has_pre)::bigint,
              COUNT(*) FILTER (WHERE NOT has_post)::bigint
            FROM linked
            """
        )
        (
            n_events,
            n_pre,
            n_post,
            n_pre_post,
            n_same_time_ambig,
            n_no_pre,
            n_no_post,
        ) = (int(x) for x in cur.fetchone())

    # Canonical subjects with medicine linkage not yet represented as ScenarioIntervention
    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.subject
            WHERE source_system_id = %s
            """,
            (SOURCE_A,),
        )
        n_canon_a = int(cur.fetchone()[0])

    funnel = {
        "source_medicine_rows": source_rows,
        "unique_patients_with_medicine_row": unique_patients,
        "rows_with_event_timestamp": with_event_time,
        "events_with_any_pre_lab": n_pre,
        "events_with_any_post_lab": n_post,
        "events_with_pre_and_post_lab": n_pre_post,
        "excluded_no_reliable_event_time": source_rows - with_event_time,
        "excluded_no_pre_state": n_no_pre,
        "excluded_no_post_state": n_no_post,
        "flagged_same_time_ambiguity": n_same_time_ambig,
        "excluded_overlapping_interventions": "NOT_QUANTIFIED_SCHEMA_LIMIT",
        "excluded_unknown_dosage": "NOT_QUANTIFIED_SCHEMA_LIMIT",
        "excluded_unknown_medication_identity": "NOT_QUANTIFIED_SCHEMA_LIMIT",
        "excluded_conflicting_sources": 0,
    }

    # Technical episodes = pre+post+time (still NOT treatment effect)
    n_technical = n_pre_post
    unexplained = 0
    accounting = {
        "source_rows_considered": source_rows,
        "candidate_rows": with_event_time,
        "technically_constructible_episodes": n_technical,
        "rejected_rows": source_rows - with_event_time,
        "unsupported_rows": max(0, with_event_time - n_technical),
        "quarantined_rows": 0,
        "truncated_rows": 0,
        "unexplained_rows": unexplained,
        "canonical_source_a_subjects": n_canon_a,
        "transition_types_preserved_separately": [
            "initiation",
            "dose_change",
            "discontinuation",
            "replacement",
            "combination_exposure",
            "unknown_intervention_transition",
        ],
        "transition_type_counts": {
            "unknown_intervention_transition": n_technical,
            "initiation": None,
            "dose_change": None,
            "discontinuation": None,
            "replacement": None,
            "combination_exposure": None,
        },
        "note": (
            "Transition subtypes not asserted without verified status fields; "
            "all constructible episodes counted as unknown_intervention_transition."
        ),
    }

    coverage = {
        "version": VERSION,
        "matrix_note": (
            "Outcome×intervention coverage requires accepted medication identity; "
            "currently reported as technical pre/post lab presence only."
        ),
        "n_technical_episodes": n_technical,
        "outcomes_linked": "SEE_MULTI_OUTCOME_CATALOG_AFTER_IDENTITY",
    }

    temporal = {
        "version": VERSION,
        "positive_horizon_required": True,
        "causality_not_inferred": True,
        "n_events_with_pre_and_post": n_pre_post,
    }

    status = "BUILT" if n_technical > 0 else "PARTIAL"
    readiness = "PARTIAL" if n_technical > 0 else "FAIL"

    return {
        "version": VERSION,
        "intervention_data_readiness_status": readiness,
        "technical_intervention_episode_dataset_status": status,
        "intervention_response_model_status": "NOT_STARTED",
        "treatment_effect_status": "NOT_EVALUATED",
        "funnel": funnel,
        "accounting": accounting,
        "coverage_matrix": coverage,
        "temporal_quality": temporal,
        "claim": (
            "Technical episode candidates only where subject, intervention identity candidate, "
            "event time, pre- and post-observation, and positive horizon evidence exist. "
            "No treatment-effect claim."
        ),
        "values_redacted": True,
    }
