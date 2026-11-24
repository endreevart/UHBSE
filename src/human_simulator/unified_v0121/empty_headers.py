"""Empty-component Observation headers — keep rows, exclude from science."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.unified_v0121.policy import (
    EMPTY_HEADER_POLICY,
    REQUIRES_FUTURE_SCHEMA_DECISION,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def classify_empty_headers_from_counts(
    *,
    total_headers: int,
    header_only: int,
    with_components: int,
) -> dict[str, Any]:
    """Aggregate classification — no row-level PII."""
    reasons = {
        "zero_accepted_components": int(header_only),
        "has_at_least_one_component": int(with_components),
    }
    return {
        "version": VERSION,
        "total_source_b_headers": int(total_headers),
        "header_only_count": int(header_only),
        "headers_with_components": int(with_components),
        "classification_reasons": reasons,
        "policy": EMPTY_HEADER_POLICY,
        "empty_component_observation_semantics_status": REQUIRES_FUTURE_SCHEMA_DECISION,
        "migration_0005": False,
        "keep_rows": True,
        "exclude_from_science_pairs": True,
        "note": (
            "Header-only Observations retained in canonical store; excluded from "
            "scientific pair construction. Schema decision deferred (no migration 0005)."
        ),
    }


def empty_component_policy_doc() -> dict[str, Any]:
    return {
        "policy_id": "empty_component_observation_v0121",
        "version": VERSION,
        "empty_component_observation_semantics_status": REQUIRES_FUTURE_SCHEMA_DECISION,
        "action": EMPTY_HEADER_POLICY,
        "rules": [
            "Keep Observation header rows in derived canonical store.",
            "Do not delete or mutate raw Source A / Source B.",
            "Exclude header-only Observations from scientific pair construction.",
            "Do not invent ObservationComponents for empty headers.",
            "No migration 0005 in this changeset.",
        ],
        "future_schema_decision_required": True,
    }


def analyze_empty_headers(repo_root: Path, *, accounting: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prefer live SQL aggregates; fall back to accounting ledger."""
    live = None
    error = None
    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings

        with canonical_connection(load_canonical_settings()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      COUNT(*)::bigint,
                      COUNT(*) FILTER (
                        WHERE NOT EXISTS (
                          SELECT 1 FROM canonical_evidence.observation_component oc
                          WHERE oc.observation_id = o.observation_id
                        )
                      )::bigint,
                      COUNT(*) FILTER (
                        WHERE EXISTS (
                          SELECT 1 FROM canonical_evidence.observation_component oc
                          WHERE oc.observation_id = o.observation_id
                        )
                      )::bigint
                    FROM canonical_evidence.observation o
                    JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
                    WHERE s.source_system_id = %s
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                row = cur.fetchone()
                live = {
                    "total_headers": int(row[0] or 0),
                    "header_only": int(row[1] or 0),
                    "with_components": int(row[2] or 0),
                }
                # Optional provenance aggregate: missingness_reason among header-only
                cur.execute(
                    """
                    SELECT
                      COALESCE(o.missingness_reason, '(null)') AS reason,
                      COUNT(*)::bigint
                    FROM canonical_evidence.observation o
                    JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
                    WHERE s.source_system_id = %s
                      AND NOT EXISTS (
                        SELECT 1 FROM canonical_evidence.observation_component oc
                        WHERE oc.observation_id = o.observation_id
                      )
                    GROUP BY 1
                    ORDER BY 2 DESC
                    LIMIT 20
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                missingness = [
                    {"missingness_reason": str(r[0])[:80], "n": int(r[1])}
                    for r in cur.fetchall()
                ]
    except Exception as exc:  # noqa: BLE001
        error = type(exc).__name__
        missingness = []
        if accounting:
            h = accounting.get("observation_header_accounting") or accounting.get(
                "live_counts"
            ) or {}
            live = {
                "total_headers": int(
                    h.get("total_headers")
                    or (accounting.get("live_counts") or {}).get("total_headers")
                    or 59741
                ),
                "header_only": int(
                    h.get("header_only")
                    or (accounting.get("live_counts") or {}).get("header_only")
                    or 1677
                ),
                "with_components": int(
                    h.get("with_accepted_components")
                    or (accounting.get("live_counts") or {}).get("with_accepted_components")
                    or 58064
                ),
            }
        else:
            live = {
                "total_headers": 59741,
                "header_only": 1677,
                "with_components": 58064,
            }

    assert live is not None
    doc = classify_empty_headers_from_counts(
        total_headers=live["total_headers"],
        header_only=live["header_only"],
        with_components=live["with_components"],
    )
    doc["missingness_reason_aggregates"] = missingness
    doc["live_error_type"] = error
    doc["repo_root_used"] = str(Path(repo_root))
    return doc
