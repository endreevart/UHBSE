"""Source B outcome catalog from loaded ObservationComponents (aggregates only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.unified_v012.policy import FIXED_OUTCOME_LABEL, FIXED_OUTCOME_UNIT, SOURCE_B_SYSTEM_ID


def _source_b_t3_catalog_candidates(repo_root: Path) -> list[dict[str, Any]]:
    """Aggregate-only free/total T3 candidates from analyses_catalog (no patient values)."""
    try:
        from human_simulator.unified.source_b_adapter import source_b_connection

        with source_b_connection(repo_root) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      c.code,
                      left(coalesce(c.name_ru, ''), 80),
                      left(coalesce(c.name_en, ''), 60),
                      coalesce(w.code, w.name, w.code_en, w.name_en),
                      (SELECT COUNT(*)::bigint
                         FROM quest_digital.analyses_constructor ac
                        WHERE ac.catalog_id = c.id) AS n
                    FROM quest_digital.analyses_catalog c
                    LEFT JOIN quest_digital.analyses_weight w ON w.id = c.weight_id
                    WHERE c.name_ru ILIKE '%Т3%'
                       OR c.name_en ILIKE '%T3%'
                       OR c.name_ru ILIKE '%трийодтиронин%'
                    ORDER BY n DESC
                    LIMIT 20
                    """
                )
                rows = cur.fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "source_catalog_code": str(r[0] or "")[:80],
                    "sanitised_label": str(r[1] or "")[:80],
                    "sanitised_label_en": str(r[2] or "")[:60],
                    "unit": r[3],
                    "constructor_row_count": int(r[4] or 0),
                    "domain_review_status": "DOMAIN_REVIEW_PENDING",
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


def build_outcome_catalog(repo_root: Path, *, observations_loaded: bool) -> dict[str, Any]:
    t3_source = _source_b_t3_catalog_candidates(repo_root)
    if not observations_loaded:
        return {
            "status": "NOT_BUILT",
            "source_b_outcome_catalog_status": "NOT_BUILT",
            "reason": "Source B Observations not loaded",
            "outcomes": [],
            "source_b_catalog_t3_candidates": t3_source,
        }
    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings

        with canonical_connection(load_canonical_settings()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      oc.raw_code,
                      oc.raw_unit,
                      COUNT(*)::bigint AS n_components,
                      COUNT(DISTINCT o.observation_id)::bigint AS n_observations,
                      COUNT(DISTINCT o.subject_id)::bigint AS n_subjects,
                      COUNT(*) FILTER (WHERE oc.numeric_value IS NOT NULL)::bigint AS n_numeric,
                      COUNT(*) FILTER (WHERE oc.text_value IS NOT NULL)::bigint AS n_text
                    FROM canonical_evidence.observation_component oc
                    JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
                    JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
                    WHERE s.source_system_id = %s
                    GROUP BY oc.raw_code, oc.raw_unit
                    ORDER BY n_components DESC
                    LIMIT 500
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                rows = cur.fetchall()
                cur.execute(
                    """
                    SELECT
                      COUNT(*)::bigint,
                      COUNT(DISTINCT o.observation_id)::bigint,
                      COUNT(DISTINCT o.subject_id)::bigint
                    FROM canonical_evidence.observation_component oc
                    JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
                    JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
                    WHERE s.source_system_id = %s
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                totals = cur.fetchone()

        outcomes = []
        for r in rows:
            label = str(r[0] or "")
            outcomes.append(
                {
                    "sanitised_label": label[:80],
                    "source_catalog_code": label[:80],
                    "unit": r[1],
                    "components": int(r[2]),
                    "observations": int(r[3]),
                    "subjects": int(r[4]),
                    "numeric_coverage": int(r[5]),
                    "text_coverage": int(r[6]),
                    "domain_review_status": "DOMAIN_REVIEW_PENDING",
                }
            )

        t3_candidates = [
            o
            for o in outcomes
            if FIXED_OUTCOME_LABEL.lower() in (o["sanitised_label"] or "").lower()
            or "t3" in (o["sanitised_label"] or "").lower()
        ]

        return {
            "status": "BUILT",
            "source_b_outcome_catalog_status": "BUILT",
            "totals": {
                "components": int(totals[0]) if totals else 0,
                "observations": int(totals[1]) if totals else 0,
                "subjects": int(totals[2]) if totals else 0,
            },
            "outcome_count_listed": len(outcomes),
            "outcomes": outcomes,
            "fixed_t3_label_candidates": t3_candidates,
            "source_b_catalog_t3_candidates": t3_source,
            "fixed_outcome_target": {
                "label": FIXED_OUTCOME_LABEL,
                "unit": FIXED_OUTCOME_UNIT,
            },
            "no_patient_values": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "INSUFFICIENT_DATA",
            "source_b_outcome_catalog_status": "INSUFFICIENT_DATA",
            "error_type": type(exc).__name__,
            "outcomes": [],
        }
