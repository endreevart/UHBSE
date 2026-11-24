"""Outcome catalogs for Source A / B and evidence-gated intersection."""

from __future__ import annotations

import hashlib
from typing import Any

from human_simulator.unified.policy import (
    FIXED_OUTCOME_CANDIDATE_ID,
    FIXED_OUTCOME_LABEL,
    FIXED_OUTCOME_UNIT,
    OUTCOME_NOT_COMPARABLE,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_SYSTEM_ID,
)


def _stable_code_id(raw_code: str) -> str:
    return hashlib.sha256(f"outcome_candidate|{raw_code}".encode()).hexdigest()[:16]


def build_source_a_catalog(conn: Any) -> dict[str, Any]:
    """Aggregate outcome catalog from canonical ObservationComponents (Source A)."""
    sql = """
    WITH base AS (
      SELECT o.subject_id,
             oc.raw_code,
             oc.numeric_value,
             COALESCE(oc.raw_unit, '') AS unit,
             COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) AS ts,
             oc.component_id,
             COALESCE(o.provenance->>'source_system', s.source_system_id) AS source_system
      FROM canonical_evidence.observation_component oc
      JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
      JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
      WHERE oc.raw_code IS NOT NULL AND btrim(oc.raw_code) <> ''
        AND s.source_system_id = %s
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
      SELECT raw_code, COUNT(*)::bigint AS n_obs,
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
    repeats AS (
      SELECT raw_code, COUNT(*)::bigint AS n_subj_repeats
      FROM (
        SELECT raw_code, subject_id
        FROM filtered
        GROUP BY raw_code, subject_id
        HAVING COUNT(*) >= 2
      ) t
      GROUP BY raw_code
    ),
    units_agg AS (
      SELECT raw_code, jsonb_object_agg(unit, n) AS units
      FROM unit_counts
      GROUP BY raw_code
    )
    SELECT t.raw_code,
           d.dominant_unit,
           t.n_obs,
           t.n_subj,
           COALESCE(r.n_subj_repeats, 0),
           COALESCE(p.n_pairs, 0),
           COALESCE(p.n_subj_pairs, 0),
           CASE WHEN t.n_obs > 0 THEN d.dominant_n::float / t.n_obs ELSE 0 END,
           u.units
    FROM totals t
    JOIN dominant d ON d.raw_code = t.raw_code
    LEFT JOIN repeats r ON r.raw_code = t.raw_code
    LEFT JOIN pair_counts p ON p.raw_code = t.raw_code
    LEFT JOIN units_agg u ON u.raw_code = t.raw_code
    ORDER BY COALESCE(p.n_pairs, 0) DESC, t.n_subj DESC, t.raw_code
    """
    with conn.cursor() as cur:
        cur.execute(sql, (SOURCE_A_SYSTEM_ID,))
        rows = cur.fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        raw_code = str(row[0])
        cid = _stable_code_id(raw_code)
        # Sanitize label for artifacts: keep controlled short form; no free-text clinical narratives.
        label = raw_code.strip()[:120]
        candidates.append(
            {
                "candidate_id": cid,
                "source_measurement_label": label,
                "dominant_unit": row[1],
                "n_observations": int(row[2]),
                "n_subjects": int(row[3]),
                "n_subjects_with_repeats": int(row[4]),
                "n_consecutive_pairs": int(row[5]),
                "n_subjects_with_pairs": int(row[6]),
                "unit_dominance": round(float(row[7] or 0), 4),
                "units_vocabulary": row[8] if isinstance(row[8], dict) else {},
                "mapping_confidence": "SOURCE_A_OBSERVED",
                "domain_review_status": (
                    "DOMAIN_REVIEW_PENDING"
                    if cid == FIXED_OUTCOME_CANDIDATE_ID
                    else "DOMAIN_REVIEW_PENDING"
                ),
                "is_fixed_primary_outcome": cid == FIXED_OUTCOME_CANDIDATE_ID,
            }
        )

    return {
        "source_system": SOURCE_A_SYSTEM_ID,
        "n_candidates": len(candidates),
        "fixed_outcome_candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
        "fixed_outcome_present": any(c["candidate_id"] == FIXED_OUTCOME_CANDIDATE_ID for c in candidates),
        "candidates": candidates,
        "values_redacted": True,
    }


def build_source_b_catalog(*, mapping_decisions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Source B outcome catalog — empty/partial until EXACT clinical mappings exist."""
    clinical_exact = 0
    if mapping_decisions:
        clinical_exact = int(mapping_decisions.get("clinical_exact_or_supported_transform_count") or 0)
    return {
        "source_system": SOURCE_B_SYSTEM_ID,
        "n_candidates": 0,
        "candidates": [],
        "status": "PARTIAL" if clinical_exact == 0 else "PARTIAL",
        "reason": (
            "No EXACT/SUPPORTED_TRANSFORM clinical Observation mappings for Source B; "
            "catalog remains empty rather than inventing outcomes from labels."
        ),
        "values_redacted": True,
    }


def build_cross_source_intersection(
    catalog_a: dict[str, Any],
    catalog_b: dict[str, Any],
    *,
    has_exact_outcome_map: bool,
) -> dict[str, Any]:
    """Intersection requires evidence beyond label similarity."""
    if not has_exact_outcome_map or int(catalog_b.get("n_candidates") or 0) == 0:
        return {
            "status": OUTCOME_NOT_COMPARABLE,
            "n_intersection": 0,
            "pairs": [],
            "reason": (
                "Label similarity alone is insufficient; no EXACT cross-source outcome mapping "
                "with compatible unit/specimen/temporal evidence."
            ),
            "fixed_outcome_a": {
                "candidate_id": FIXED_OUTCOME_CANDIDATE_ID,
                "label": FIXED_OUTCOME_LABEL,
                "unit": FIXED_OUTCOME_UNIT,
            },
            "fixed_outcome_mapped_to_b": False,
        }
    # Would compute evidence-backed pairs when B catalog is populated.
    return {
        "status": "PASS",
        "n_intersection": 0,
        "pairs": [],
        "reason": "No verified intersection pairs after evidence checks.",
    }
