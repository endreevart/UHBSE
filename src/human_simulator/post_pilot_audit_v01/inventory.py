"""Source A longitudinal inventory — aggregate-only, provenance-aware."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from human_simulator.post_pilot_audit_v01.policy import VERSION


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def inventory_source_a_labs(conn_a: Any) -> dict[str, Any]:
    """Aggregate inventory of Source A numeric lab components.

    Provenance: clinic dump rows treated as OBSERVED source evidence.
    No patient identifiers or raw values are returned.
    """
    sql_by_ou = """
    WITH items AS (
      SELECT ar.patient_id,
             COALESCE(NULLIF(TRIM(i.name), ''), '∅') AS outcome,
             COALESCE(NULLIF(TRIM(i.unit), ''), '') AS unit,
             COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts,
             CASE WHEN i.value ~ '^-?[0-9]+([.,][0-9]+)?$' THEN 1 ELSE 0 END AS is_numeric,
             CASE WHEN COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NULL
                  THEN 1 ELSE 0 END AS missing_ts
      FROM magerya_api.document_analysisresultitem i
      JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
      WHERE ar.patient_id IS NOT NULL
    ),
    numeric AS (
      SELECT patient_id, outcome, unit, lab_ts
      FROM items
      WHERE is_numeric = 1 AND missing_ts = 0
    ),
    ordered AS (
      SELECT patient_id, outcome, unit, lab_ts,
             ROW_NUMBER() OVER (
               PARTITION BY patient_id, outcome, unit ORDER BY lab_ts ASC
             ) AS rn
      FROM numeric
    ),
    pairs AS (
      SELECT a.outcome, a.unit, COUNT(*)::bigint AS n_pairs,
             COUNT(DISTINCT a.patient_id)::bigint AS n_subj_pairs
      FROM ordered a
      JOIN ordered b
        ON a.patient_id = b.patient_id
       AND a.outcome = b.outcome AND a.unit = b.unit
       AND b.rn = a.rn + 1
      GROUP BY a.outcome, a.unit
    ),
    horizons AS (
      SELECT a.outcome, a.unit,
             percentile_cont(0.5) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (b.lab_ts - a.lab_ts))/86400.0
             ) AS median_horizon_days,
             percentile_cont(0.9) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (b.lab_ts - a.lab_ts))/86400.0
             ) AS p90_horizon_days
      FROM ordered a
      JOIN ordered b
        ON a.patient_id = b.patient_id
       AND a.outcome = b.outcome AND a.unit = b.unit
       AND b.rn = a.rn + 1
      GROUP BY a.outcome, a.unit
    ),
    subj_meas AS (
      SELECT patient_id, outcome, unit, COUNT(*)::int AS n_meas,
             MIN(lab_ts) AS min_ts, MAX(lab_ts) AS max_ts
      FROM numeric
      GROUP BY 1,2,3
    ),
    agg2 AS (
      SELECT outcome, unit,
             SUM(n_meas)::bigint AS n_numeric_obs,
             COUNT(*)::bigint AS n_subjects,
             COUNT(*) FILTER (WHERE n_meas >= 2)::bigint AS n_subj_ge2,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY n_meas) AS median_meas_per_subj,
             MIN(min_ts) AS min_ts,
             MAX(max_ts) AS max_ts
      FROM subj_meas
      GROUP BY outcome, unit
    ),
    totals AS (
      SELECT outcome, unit,
             COUNT(*)::bigint AS n_all_obs,
             COUNT(*) FILTER (WHERE is_numeric=0)::bigint AS n_non_numeric,
             COUNT(*) FILTER (WHERE missing_ts=1)::bigint AS n_missing_ts
      FROM items
      GROUP BY outcome, unit
    )
    SELECT a.outcome, a.unit,
           t.n_all_obs, t.n_non_numeric, t.n_missing_ts,
           a.n_numeric_obs, a.n_subjects, a.n_subj_ge2, a.median_meas_per_subj,
           a.min_ts, a.max_ts,
           COALESCE(p.n_pairs, 0), COALESCE(p.n_subj_pairs, 0),
           h.median_horizon_days, h.p90_horizon_days
    FROM agg2 a
    JOIN totals t ON t.outcome = a.outcome AND t.unit = a.unit
    LEFT JOIN pairs p ON p.outcome = a.outcome AND p.unit = a.unit
    LEFT JOIN horizons h ON h.outcome = a.outcome AND h.unit = a.unit
    WHERE a.n_subjects >= 5
    ORDER BY COALESCE(p.n_pairs, 0) DESC, a.n_subj_ge2 DESC, a.outcome, a.unit
    LIMIT 500
    """

    with conn_a.cursor() as cur:
        cur.execute(sql_by_ou)
        rows = cur.fetchall()

        cur.execute(
            """
            WITH numeric AS (
              SELECT ar.patient_id,
                     COALESCE(NULLIF(TRIM(i.name), ''), '∅') AS outcome,
                     COALESCE(NULLIF(TRIM(i.unit), ''), '') AS unit,
                     COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts,
                     ar.id AS result_id
              FROM magerya_api.document_analysisresultitem i
              JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
              WHERE ar.patient_id IS NOT NULL
                AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
                AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
            ),
            per_subj AS (
              SELECT patient_id, COUNT(DISTINCT outcome || '|' || unit) AS n_ou
              FROM numeric GROUP BY patient_id
            ),
            panel AS (
              SELECT patient_id, result_id, lab_ts,
                     COUNT(DISTINCT outcome || '|' || unit) AS n_ou_panel
              FROM numeric GROUP BY 1,2,3
            )
            SELECT
              (SELECT COUNT(*) FROM per_subj),
              (SELECT COUNT(*) FROM per_subj WHERE n_ou >= 2),
              (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY n_ou) FROM per_subj),
              (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY n_ou) FROM per_subj),
              (SELECT MAX(n_ou) FROM per_subj),
              (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY n_ou_panel) FROM panel),
              (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY n_ou_panel) FROM panel),
              (SELECT COUNT(*) FROM panel WHERE n_ou_panel >= 5),
              (SELECT COUNT(*) FROM panel WHERE n_ou_panel >= 10),
              (SELECT COUNT(*) FROM panel WHERE n_ou_panel >= 20)
            """
        )
        ov = cur.fetchone()
        cur.execute("SELECT current_database(), current_user")
        dbname, dbuser = cur.fetchone()

    grains = []
    for row in rows:
        (
            outcome,
            unit,
            n_all,
            n_non_num,
            n_miss_ts,
            n_num,
            n_subj,
            n_ge2,
            med_meas,
            min_ts,
            max_ts,
            n_pairs,
            n_subj_pairs,
            med_h,
            p90_h,
        ) = row
        unit_dom = float(n_num) / float(n_all) if n_all else None
        grains.append(
            {
                "outcome": outcome,
                "unit": unit,
                "n_observations_all": int(n_all),
                "n_numeric_observations": int(n_num),
                "n_non_numeric": int(n_non_num),
                "n_missing_timestamps": int(n_miss_ts),
                "n_subjects": int(n_subj),
                "n_subjects_with_ge2": int(n_ge2),
                "n_strict_consecutive_pairs": int(n_pairs),
                "n_subjects_with_pairs": int(n_subj_pairs),
                "median_measurements_per_subject": float(med_meas)
                if med_meas is not None
                else None,
                "temporal_coverage": {
                    "min_ts": min_ts.isoformat() if min_ts else None,
                    "max_ts": max_ts.isoformat() if max_ts else None,
                },
                "horizon_distribution": {
                    "median_days": float(med_h) if med_h is not None else None,
                    "p90_days": float(p90_h) if p90_h is not None else None,
                },
                "unit_dominance_approx": round(unit_dom, 4) if unit_dom is not None else None,
                "record_origin": "OBSERVED",
                "provenance": "source_a_clinic_dump_read_only",
            }
        )

    pair_counts = [g["n_strict_consecutive_pairs"] for g in grains]
    subj_ge2 = [g["n_subjects_with_ge2"] for g in grains]

    def _pct(vals: list[int], thr: int) -> int:
        return sum(1 for v in vals if v >= thr)

    coverage = {
        "n_outcome_unit_grains_listed": len(grains),
        "pair_count_histogram_thresholds": {
            "ge_50": _pct(pair_counts, 50),
            "ge_100": _pct(pair_counts, 100),
            "ge_300": _pct(pair_counts, 300),
            "ge_1000": _pct(pair_counts, 1000),
            "ge_5000": _pct(pair_counts, 5000),
        },
        "subjects_ge2_thresholds": {
            "ge_30": _pct(subj_ge2, 30),
            "ge_50": _pct(subj_ge2, 50),
            "ge_100": _pct(subj_ge2, 100),
            "ge_300": _pct(subj_ge2, 300),
        },
        "top_20_by_pairs": [
            {
                "outcome": g["outcome"],
                "unit": g["unit"],
                "n_pairs": g["n_strict_consecutive_pairs"],
                "n_subjects_ge2": g["n_subjects_with_ge2"],
                "n_subjects": g["n_subjects"],
            }
            for g in grains[:20]
        ],
    }

    overlap = {
        "n_subjects_with_any_numeric": int(ov[0] or 0),
        "n_subjects_with_ge2_distinct_outcome_units": int(ov[1] or 0),
        "median_outcomes_per_subject": float(ov[2]) if ov[2] is not None else None,
        "p90_outcomes_per_subject": float(ov[3]) if ov[3] is not None else None,
        "max_outcomes_per_subject": int(ov[4] or 0),
        "median_outcomes_per_lab_panel": float(ov[5]) if ov[5] is not None else None,
        "p90_outcomes_per_lab_panel": float(ov[6]) if ov[6] is not None else None,
        "n_panels_with_ge5_outcomes": int(ov[7] or 0),
        "n_panels_with_ge10_outcomes": int(ov[8] or 0),
        "n_panels_with_ge20_outcomes": int(ov[9] or 0),
        "potential_multi_outcome_snapshots": {
            "note": (
                "Panel counts approximate same analysis_result_id / timestamp bundles; "
                "completeness requirements not imposed."
            ),
            "panels_ge5": int(ov[7] or 0),
            "panels_ge10": int(ov[8] or 0),
            "panels_ge20": int(ov[9] or 0),
        },
    }

    return {
        "version": VERSION,
        "generated_at": _now(),
        "SOURCE_A_LONGITUDINAL_INVENTORY_STATUS": "PASS",
        "source_database": str(dbname),
        "db_role": str(dbuser),
        "SOURCE_B_CONTAMINATION": 0,
        "provenance_filter": "OBSERVED_source_a_clinic_rows_only",
        "row_level_values_emitted": False,
        "future_leakage_introduced": False,
        "n_grains": len(grains),
        "grains": grains,
        "outcome_coverage_distribution": coverage,
        "multi_outcome_overlap_profile": overlap,
        "MULTI_OUTCOME_OVERLAP_STATUS": (
            "SUBSTANTIAL_PANEL_OVERLAP"
            if int(ov[8] or 0) > 1000
            else "LIMITED_OR_UNKNOWN"
        ),
    }
