"""Train-only candidate outcome profiling (v0.1.1)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any


def _stable_code_id(raw_code: str) -> str:
    return hashlib.sha256(f"outcome_candidate|{raw_code}".encode()).hexdigest()[:16]


def profile_candidates(
    conn: Any,
    *,
    train_subject_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Aggregate candidate metrics. If train_subject_keys given, restrict to those subjects."""
    subject_filter_sql = ""
    params: tuple[Any, ...] = ()
    if train_subject_keys is not None:
        # Use ANY(array) with list of subject ids
        subject_filter_sql = " AND o.subject_id = ANY(%s) "
        params = (list(train_subject_keys),)

    sql = f"""
    WITH base AS (
      SELECT o.subject_id,
             oc.raw_code,
             oc.numeric_value,
             COALESCE(oc.raw_unit, '') AS unit,
             COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) AS ts,
             oc.component_id
      FROM canonical_evidence.observation_component oc
      JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
      WHERE oc.raw_code IS NOT NULL AND btrim(oc.raw_code) <> ''
      {subject_filter_sql}
    ),
    unit_counts AS (
      SELECT raw_code, unit, COUNT(*)::bigint AS n
      FROM base GROUP BY raw_code, unit
    ),
    dominant AS (
      SELECT DISTINCT ON (raw_code) raw_code, unit AS dominant_unit, n AS dominant_n
      FROM unit_counts
      ORDER BY raw_code, n DESC, unit ASC
    ),
    totals AS (
      SELECT raw_code, COUNT(*)::bigint AS n_obs FROM base GROUP BY raw_code
    ),
    filtered AS (
      SELECT b.*
      FROM base b
      JOIN dominant d ON d.raw_code = b.raw_code AND b.unit = d.dominant_unit
      WHERE b.numeric_value IS NOT NULL AND b.ts IS NOT NULL
    ),
    ordered AS (
      SELECT *,
             ROW_NUMBER() OVER (
               PARTITION BY raw_code, subject_id
               ORDER BY ts ASC, component_id ASC
             ) AS rn,
             COUNT(*) OVER (PARTITION BY raw_code, subject_id) AS n_meas
      FROM filtered
    ),
    consecutive AS (
      SELECT a.raw_code, a.subject_id
      FROM ordered a
      JOIN ordered b
        ON a.raw_code = b.raw_code
       AND a.subject_id = b.subject_id
       AND b.rn = a.rn + 1
    ),
    pair_counts AS (
      SELECT raw_code,
             COUNT(*)::bigint AS n_pairs,
             COUNT(DISTINCT subject_id)::bigint AS n_subj_pairs
      FROM consecutive
      GROUP BY raw_code
    ),
    subj_stats AS (
      SELECT raw_code, subject_id, MAX(n_meas)::int AS n_meas
      FROM ordered
      GROUP BY raw_code, subject_id
    ),
    agg AS (
      SELECT s.raw_code,
             COUNT(*)::int AS n_subjects,
             SUM(s.n_meas)::bigint AS n_observations_dominant_unit,
             COUNT(*) FILTER (WHERE s.n_meas >= 2)::int AS n_subjects_with_repeats,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY s.n_meas) AS median_measurements_per_subject
      FROM subj_stats s
      GROUP BY s.raw_code
    )
    SELECT a.raw_code,
           a.n_subjects,
           a.n_observations_dominant_unit,
           a.n_subjects_with_repeats,
           a.median_measurements_per_subject,
           t.n_obs AS n_observations_all_units,
           d.dominant_unit,
           d.dominant_n,
           COALESCE(p.n_pairs, 0) AS n_consecutive_pairs,
           COALESCE(p.n_subj_pairs, 0) AS n_subjects_with_pairs
    FROM agg a
    JOIN totals t ON t.raw_code = a.raw_code
    JOIN dominant d ON d.raw_code = a.raw_code
    LEFT JOIN pair_counts p ON p.raw_code = a.raw_code
    WHERE a.n_subjects_with_repeats >= 3
    ORDER BY COALESCE(p.n_pairs, 0) DESC, a.n_subjects_with_repeats DESC, a.raw_code ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        (
            raw_code,
            n_subjects,
            n_obs_dom,
            n_repeat,
            med_per,
            n_obs_all,
            dominant_unit,
            dominant_n,
            n_pairs,
            n_subj_pairs,
        ) = row
        unit_dominance = float(dominant_n) / float(n_obs_all) if n_obs_all else 0.0
        candidates.append(
            {
                "candidate_id": _stable_code_id(str(raw_code)),
                "source_measurement_label": str(raw_code),
                "measurement_identifier_stable": True,
                "medical_interpretation_status": "DOMAIN_REVIEW_PENDING",
                "n_subjects": int(n_subjects),
                "n_observations_dominant_unit": int(n_obs_dom),
                "n_observations_all_units": int(n_obs_all),
                "n_subjects_with_repeats": int(n_repeat),
                "median_measurements_per_subject": float(med_per) if med_per is not None else None,
                "dominant_unit": dominant_unit or None,
                "unit_dominance": round(unit_dominance, 4),
                "numeric_parse_rate_dominant": 1.0,
                "missing_rate_dominant": 0.0,
                "n_consecutive_pairs": int(n_pairs),
                "n_subjects_with_pairs": int(n_subj_pairs),
            }
        )
    profile_hash = hashlib.sha256(
        str(
            [
                (c["candidate_id"], c["n_consecutive_pairs"], c["n_subjects_with_repeats"])
                for c in candidates
            ]
        ).encode()
    ).hexdigest()
    return {
        "source": "canonical_evidence",
        "population": "train_discovery_subjects_only"
        if train_subject_keys is not None
        else "all_subjects",
        "n_train_subjects_scoped": len(train_subject_keys) if train_subject_keys is not None else None,
        "relations_read": [
            "canonical_evidence.observation",
            "canonical_evidence.observation_component",
        ],
        "row_level_values_emitted": False,
        "pair_definition_in_profile": "strict_consecutive_neighbors_only",
        "n_candidates": len(candidates),
        "candidates": candidates,
        "profile_hash": profile_hash,
        "profiled_at": datetime.utcnow().isoformat() + "Z",
    }
