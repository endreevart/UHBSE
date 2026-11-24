"""Multi-outcome catalogs for Source A and Source B (canonical aggregates)."""

from __future__ import annotations

import hashlib
import statistics
from typing import Any

from human_simulator.population_v01.policy import (
    MIN_PAIRS_FOR_BASELINE,
    MIN_SUBJECTS_WITH_PAIRS,
    SHORTLIST_MAX,
    SOURCE_A,
    SOURCE_B,
    VERSION,
)


def _cid(source: str, code: str, unit: str) -> str:
    return hashlib.sha256(f"{source}|{code}|{unit}".encode()).hexdigest()[:16]


def _catalog_sql(source_system: str) -> str:
    return """
    WITH base AS (
      SELECT o.subject_id,
             oc.raw_code,
             oc.numeric_value,
             COALESCE(oc.raw_unit, '') AS unit,
             COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) AS ts,
             oc.component_id,
             oc.raw_value
      FROM canonical_evidence.observation_component oc
      JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
      JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
      WHERE s.source_system_id = %s
        AND oc.raw_code IS NOT NULL AND btrim(oc.raw_code) <> ''
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
      SELECT raw_code,
             COUNT(*)::bigint AS n_obs,
             COUNT(*) FILTER (WHERE numeric_value IS NOT NULL)::bigint AS n_numeric,
             COUNT(*) FILTER (WHERE numeric_value IS NULL)::bigint AS n_non_numeric,
             COUNT(DISTINCT subject_id)::bigint AS n_subj
      FROM base GROUP BY raw_code
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
             COUNT(*) OVER (PARTITION BY raw_code, subject_id) AS n_meas,
             LEAD(ts) OVER (
               PARTITION BY raw_code, subject_id
               ORDER BY ts ASC, component_id ASC
             ) AS next_ts
      FROM filtered
    ),
    consecutive AS (
      SELECT raw_code, subject_id,
             EXTRACT(EPOCH FROM (next_ts - ts)) / 86400.0 AS horizon_days
      FROM ordered
      WHERE next_ts IS NOT NULL
        AND next_ts > ts
    ),
    pair_counts AS (
      SELECT raw_code,
             COUNT(*)::bigint AS n_pairs,
             COUNT(DISTINCT subject_id)::bigint AS n_subj_pairs,
             MIN(horizon_days) AS h_min,
             PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY horizon_days) AS h_med,
             PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY horizon_days) AS h_p90,
             MAX(horizon_days) AS h_max
      FROM consecutive
      GROUP BY raw_code
    ),
    repeats AS (
      SELECT raw_code, COUNT(*)::bigint AS n_subj_repeats
      FROM (
        SELECT raw_code, subject_id FROM filtered
        GROUP BY raw_code, subject_id HAVING COUNT(*) >= 2
      ) t GROUP BY raw_code
    ),
    units_agg AS (
      SELECT raw_code, jsonb_object_agg(unit, n) AS units
      FROM unit_counts GROUP BY raw_code
    )
    SELECT t.raw_code,
           d.dominant_unit,
           t.n_obs,
           t.n_numeric,
           t.n_non_numeric,
           t.n_subj,
           COALESCE(r.n_subj_repeats, 0),
           COALESCE(p.n_pairs, 0),
           COALESCE(p.n_subj_pairs, 0),
           CASE WHEN t.n_obs > 0 THEN d.dominant_n::float / t.n_obs ELSE 0 END,
           u.units,
           p.h_min, p.h_med, p.h_p90, p.h_max
    FROM totals t
    JOIN dominant d ON d.raw_code = t.raw_code
    LEFT JOIN repeats r ON r.raw_code = t.raw_code
    LEFT JOIN pair_counts p ON p.raw_code = t.raw_code
    LEFT JOIN units_agg u ON u.raw_code = t.raw_code
    ORDER BY COALESCE(p.n_pairs, 0) DESC, t.n_subj DESC, t.raw_code
    """


def build_multi_outcome_catalog(conn: Any, *, source_system: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(_catalog_sql(source_system), (source_system,))
        rows = cur.fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        raw_code = str(row[0])
        unit = str(row[1] or "")
        n_obs = int(row[2])
        n_num = int(row[3])
        n_non = int(row[4])
        cand = {
            "candidate_id": _cid(source_system, raw_code, unit),
            "source_system": source_system,
            "source_code": raw_code[:120],
            "normalized_candidate_label": raw_code.strip()[:120],
            "raw_label_variants": [raw_code.strip()[:120]],
            "dominant_unit": unit,
            "unit_variants": row[10] if isinstance(row[10], dict) else {},
            "numeric_validity_rate": round(n_num / n_obs, 6) if n_obs else 0.0,
            "missing_value_rate": round(n_non / n_obs, 6) if n_obs else 0.0,
            "inequality_range_text_rate": round(n_non / n_obs, 6) if n_obs else 0.0,
            "total_observations": n_obs,
            "unique_subjects": int(row[5]),
            "subjects_with_at_least_two_measurements": int(row[6]),
            "strict_consecutive_positive_horizon_pairs": int(row[7]),
            "subjects_with_pairs": int(row[8]),
            "unit_dominance": round(float(row[9] or 0), 6),
            "horizon_min_days": float(row[11]) if row[11] is not None else None,
            "horizon_median_days": float(row[12]) if row[12] is not None else None,
            "horizon_p90_days": float(row[13]) if row[13] is not None else None,
            "horizon_max_days": float(row[14]) if row[14] is not None else None,
            "train_validation_test_feasibility": (
                "FEASIBLE"
                if int(row[7]) >= MIN_PAIRS_FOR_BASELINE
                and int(row[8]) >= MIN_SUBJECTS_WITH_PAIRS
                else "INSUFFICIENT"
            ),
            "cross_source_candidate_mapping_status": "DOMAIN_REVIEW_REQUIRED",
            "semantic_review_status": "DOMAIN_REVIEW_REQUIRED",
            "intervention_linkage_coverage": "SEE_EPISODE_MATRIX",
            "source_a_availability": source_system == SOURCE_A,
            "source_b_availability": source_system == SOURCE_B,
        }
        candidates.append(cand)

    return {
        "version": VERSION,
        "source_system": source_system,
        "n_candidates": len(candidates),
        "candidates": candidates,
        "values_redacted": True,
        "catalog_complete_not_top_n": True,
    }


def ranking_method() -> dict[str, Any]:
    return {
        "version": VERSION,
        "criteria_predeclared": [
            "subjects_with_pairs",
            "strict_consecutive_positive_horizon_pairs",
            "numeric_validity_rate",
            "unit_dominance",
            "horizon_median_days_present",
            "train_validation_test_feasibility",
        ],
        "weights": {
            "subjects_with_pairs": 3.0,
            "strict_consecutive_positive_horizon_pairs": 2.0,
            "numeric_validity_rate": 1.0,
            "unit_dominance": 1.0,
        },
        "exclusions": [
            "test_set_performance_not_used",
            "label_similarity_alone_insufficient_for_EXACT_mapping",
            "no_unverified_unit_conversion",
        ],
        "gates": {
            "min_pairs": MIN_PAIRS_FOR_BASELINE,
            "min_subjects_with_pairs": MIN_SUBJECTS_WITH_PAIRS,
            "min_unit_dominance": 0.7,
            "min_numeric_validity": 0.5,
        },
        "shortlist_max": SHORTLIST_MAX,
        "uses_test_performance_for_selection": False,
    }


def rank_shortlist(catalog_a: dict[str, Any]) -> dict[str, Any]:
    method = ranking_method()
    gates = method["gates"]
    scored: list[dict[str, Any]] = []
    for c in catalog_a.get("candidates") or []:
        if int(c.get("strict_consecutive_positive_horizon_pairs") or 0) < gates["min_pairs"]:
            continue
        if int(c.get("subjects_with_pairs") or 0) < gates["min_subjects_with_pairs"]:
            continue
        if float(c.get("unit_dominance") or 0) < gates["min_unit_dominance"]:
            continue
        if float(c.get("numeric_validity_rate") or 0) < gates["min_numeric_validity"]:
            continue
        score = (
            3.0 * math_log1p(int(c["subjects_with_pairs"]))
            + 2.0 * math_log1p(int(c["strict_consecutive_positive_horizon_pairs"]))
            + float(c["numeric_validity_rate"])
            + float(c["unit_dominance"])
        )
        scored.append({**c, "ranking_score": round(score, 6)})
    scored.sort(
        key=lambda x: (
            -x["ranking_score"],
            -int(x["subjects_with_pairs"]),
            x["source_code"],
        )
    )
    shortlist = scored[: SHORTLIST_MAX]
    return {
        "version": VERSION,
        "n_passing_gates": len(scored),
        "n_shortlisted": len(shortlist),
        "shortlist": shortlist,
        "method_ref": "multi-outcome-ranking-method.json",
        "test_performance_not_used": True,
    }


def math_log1p(x: int) -> float:
    import math

    return math.log1p(max(0, x))


def cross_source_outcome_candidates(
    catalog_a: dict[str, Any], catalog_b: dict[str, Any]
) -> dict[str, Any]:
    """Label co-occurrence only → DOMAIN_REVIEW_REQUIRED / HYPOTHESIS, never EXACT."""
    a_by_norm = {
        str(c["normalized_candidate_label"]).casefold(): c
        for c in catalog_a.get("candidates") or []
    }
    pairs = []
    for b in catalog_b.get("candidates") or []:
        key = str(b["normalized_candidate_label"]).casefold()
        if key in a_by_norm:
            a = a_by_norm[key]
            unit_compat = a.get("dominant_unit") == b.get("dominant_unit")
            pairs.append(
                {
                    "source_a_candidate_id": a["candidate_id"],
                    "source_b_candidate_id": b["candidate_id"],
                    "normalized_label": a["normalized_candidate_label"],
                    "unit_a": a.get("dominant_unit"),
                    "unit_b": b.get("dominant_unit"),
                    "units_identical": unit_compat,
                    "mapping_status": (
                        "HYPOTHESIS" if unit_compat else "DOMAIN_REVIEW_REQUIRED"
                    ),
                    "not_exact_from_label_similarity": True,
                    "semantic_review_status": "DOMAIN_REVIEW_REQUIRED",
                }
            )
    return {
        "version": VERSION,
        "n_label_cooccurrence_candidates": len(pairs),
        "pairs": pairs,
        "exact_or_supported_transform_count": 0,
        "note": (
            "No EXACT/SUPPORTED_TRANSFORM mappings created from label similarity alone. "
            "All candidates require domain review."
        ),
    }
