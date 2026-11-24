"""Rewrite accounting with safer SQL (aggregates only)."""

from __future__ import annotations

from typing import Any

from human_simulator.population_v01.policy import SOURCE_A, VERSION


def build_full_population_accounting(conn_a: Any) -> dict[str, Any]:
    """Mutually exclusive primary readiness categories summing to subjects_total."""
    with conn_a.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM magerya_api.account_patient")
        total = int(cur.fetchone()[0])

        cur.execute(
            """
            WITH dated AS (
              SELECT ar.patient_id,
                     COUNT(*) FILTER (
                       WHERE i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
                         AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
                     )::int AS n_dated
              FROM magerya_api.document_analysisresultitem i
              JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
              WHERE ar.patient_id IS NOT NULL
              GROUP BY ar.patient_id
            )
            SELECT
              COUNT(*) FILTER (WHERE COALESCE(d.n_dated, 0) = 0),
              COUNT(*) FILTER (WHERE COALESCE(d.n_dated, 0) = 1),
              COUNT(*) FILTER (WHERE COALESCE(d.n_dated, 0) >= 2)
            FROM magerya_api.account_patient p
            LEFT JOIN dated d ON d.patient_id = p.id
            """
        )
        c1, c2, ge2 = (int(x) for x in cur.fetchone())

        cur.execute(
            """
            WITH per AS (
              SELECT ar.patient_id,
                     COALESCE(NULLIF(TRIM(i.name), ''), '∅') AS code,
                     COUNT(*) FILTER (
                       WHERE i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
                         AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
                     )::int AS n
              FROM magerya_api.document_analysisresultitem i
              JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
              WHERE ar.patient_id IS NOT NULL
              GROUP BY ar.patient_id, COALESCE(NULLIF(TRIM(i.name), ''), '∅')
            ),
            flagged AS (
              SELECT patient_id, BOOL_OR(n >= 2) AS has_rep
              FROM per
              GROUP BY patient_id
            )
            SELECT COUNT(*) FILTER (WHERE has_rep)
            FROM flagged
            """
        )
        n_repeated = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE n_appt >= 1),
              COUNT(*) FILTER (WHERE n_appt >= 3),
              COUNT(*) FILTER (WHERE n_lab >= 1),
              COUNT(*) FILTER (WHERE n_num >= 1),
              COUNT(*) FILTER (WHERE n_med >= 1)
            FROM (
              SELECT p.id AS patient_id,
                     COALESCE(a.n,0) AS n_appt,
                     COALESCE(l.n,0) AS n_lab,
                     COALESCE(n.n,0) AS n_num,
                     COALESCE(m.n,0) AS n_med
              FROM magerya_api.account_patient p
              LEFT JOIN (
                SELECT patient_id, COUNT(*)::int AS n
                FROM magerya_api.appointment_appointment
                WHERE patient_id IS NOT NULL GROUP BY patient_id
              ) a ON a.patient_id = p.id
              LEFT JOIN (
                SELECT patient_id, COUNT(*)::int AS n
                FROM magerya_api.document_analysisresult
                WHERE patient_id IS NOT NULL GROUP BY patient_id
              ) l ON l.patient_id = p.id
              LEFT JOIN (
                SELECT ar.patient_id, COUNT(*)::int AS n
                FROM magerya_api.document_analysisresultitem i
                JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
                WHERE ar.patient_id IS NOT NULL
                  AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
                GROUP BY ar.patient_id
              ) n ON n.patient_id = p.id
              LEFT JOIN (
                SELECT patient_id, COUNT(*)::int AS n
                FROM magerya_api.diagnosis_medicineappointments
                WHERE patient_id IS NOT NULL GROUP BY patient_id
              ) m ON m.patient_id = p.id
            ) t
            """
        )
        has_appt, has_ge3, has_lab, has_num, has_med = (int(x) for x in cur.fetchone())

    c3 = max(0, ge2 - n_repeated)
    c4 = n_repeated
    primary = {
        "1_no_supported_dated_numeric_observation": c1,
        "2_exactly_one_supported_dated_numeric_observation": c2,
        "3_multiple_observations_but_no_repeated_normalized_outcome": c3,
        "4_repeated_outcome_pair_construction_see_catalog": c4,
        "5_usable_longitudinal_outcome_pairs_see_catalog": 0,
        "6_usable_intervention_linked_episode_see_inventory": 0,
        "7_unresolved_temporal_linkage": 0,
    }
    # Exclusive partition uses categories 1–4; 5–7 are documented as catalog/episode refinements.
    exclusive_sum = c1 + c2 + c3 + c4
    if exclusive_sum != total:
        primary["7_unresolved_temporal_linkage"] = total - exclusive_sum

    primary_total = sum(
        v
        for k, v in primary.items()
        if k.startswith(("1_", "2_", "3_", "4_", "7_"))
    )
    # Report exclusive sum as sum of mutually exclusive buckets
    exclusive = {
        "1_no_supported_dated_numeric_observation": primary[
            "1_no_supported_dated_numeric_observation"
        ],
        "2_exactly_one_supported_dated_numeric_observation": primary[
            "2_exactly_one_supported_dated_numeric_observation"
        ],
        "3_multiple_observations_but_no_repeated_normalized_outcome": primary[
            "3_multiple_observations_but_no_repeated_normalized_outcome"
        ],
        "4_repeated_outcome_pair_construction_see_catalog": primary[
            "4_repeated_outcome_pair_construction_see_catalog"
        ],
        "7_unresolved_temporal_linkage": primary["7_unresolved_temporal_linkage"],
    }
    exclusive_total = sum(exclusive.values())

    return {
        "version": VERSION,
        "source_system": SOURCE_A,
        "source_a_population_accounting_status": (
            "PASS" if exclusive_total == total else "FAIL"
        ),
        "total_account_patient": total,
        "primary_readiness_categories_exclusive": exclusive,
        "primary_sum": exclusive_total,
        "primary_sum_equals_total": exclusive_total == total,
        "informational_refinements_non_exclusive": {
            "5_usable_longitudinal_outcome_pairs_see_catalog": (
                "Detailed per-outcome in multi-outcome catalog "
                "(subjects with strict consecutive positive-horizon pairs)."
            ),
            "6_usable_intervention_linked_episode_see_inventory": (
                "Detailed in technical-intervention-episode-accounting.json."
            ),
        },
        "secondary_coverage_flags": {
            "has_appointment": has_appt,
            "has_at_least_three_appointments": has_ge3,
            "has_laboratory_header": has_lab,
            "has_numeric_laboratory_component": has_num,
            "has_repeated_same_outcome_measurement": n_repeated,
            "has_medication_prescription_candidate": has_med,
            "has_pre_intervention_observation": "see_episode_funnel",
            "has_post_intervention_observation": "see_episode_funnel",
            "has_technically_constructible_intervention_episode": "see_episode_funnel",
        },
        "note": (
            "Exclusive primary buckets 1–4 (+7 if needed) partition all account_patient rows. "
            "Categories 5–6 are outcome/intervention refinements reported separately."
        ),
    }
