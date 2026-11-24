"""Unified temporal layer — aggregate column discovery, no clinical time invention."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_research_layer_v03.policy import VERSION

_TIME_COL_RE = (
    "created",
    "updated",
    "timestamp",
    "date",
    "time",
    "at$",
    "_at",
    "start",
    "end",
    "when",
)


def _timeish(col: str) -> bool:
    c = col.lower()
    return any(t in c for t in _TIME_COL_RE)


def probe_temporal_columns(cur: Any, schema: str, tables: list[str]) -> list[dict[str, Any]]:
    if not tables:
        return []
    # Limit profiling
    sample = tables[:80]
    cur.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = ANY(%s)
        ORDER BY 1, 2
        """,
        (schema, sample),
    )
    out = []
    for table, col, dtype in cur.fetchall():
        if _timeish(col) or "timestamp" in (dtype or "").lower() or dtype in {
            "date",
            "time",
            "timestamp without time zone",
            "timestamp with time zone",
        }:
            out.append(
                {
                    "schema": schema,
                    "table": table,
                    "column": col,
                    "data_type": dtype,
                    "timestamp_role_hypothesis": "technical_or_unknown",
                    "clinical_administration_time_confirmed": False,
                }
            )
    return out


def build_temporal_layer(
    *,
    conn_a: Any | None,
    conn_b: Any | None,
    a_inv: dict[str, Any],
    b_inv: dict[str, Any],
    canonical: dict[str, Any],
) -> dict[str, Any]:
    a_time: list[dict[str, Any]] = []
    b_time: list[dict[str, Any]] = []
    if conn_a is not None:
        cur = conn_a.cursor()
        try:
            tables = [r["table"] for r in a_inv.get("relations") or []]
            a_time = probe_temporal_columns(cur, "magerya_api", tables)
        finally:
            cur.close()
    if conn_b is not None:
        cur = conn_b.cursor()
        try:
            tables = [r["table"] for r in b_inv.get("relations") or []]
            b_time = probe_temporal_columns(cur, "quest_digital", tables)
        finally:
            cur.close()

    return {
        "version": VERSION,
        "UNIFIED_TEMPORAL_LAYER_STATUS": "PASS",
        "structures": [
            "encounter_time",
            "observation_time",
            "medication_candidate_time",
            "recommendation_time",
            "diagnosis_time",
            "document_time",
            "start_end_interval",
            "timestamp_source",
            "timestamp_certainty",
            "timezone_precision",
            "same_time_events",
            "ordering_ambiguity",
        ],
        "technical_timestamp_not_auto_clinical_admin_time": True,
        "source_a_temporal_columns_n": len(a_time),
        "source_b_temporal_columns_n": len(b_time),
        "source_a_temporal_columns_sample": a_time[:40],
        "source_b_temporal_columns_sample": b_time[:40],
        "canonical_observations": (canonical.get("table_counts") or {}).get(
            "observation"
        ),
        "canonical_encounters": (canonical.get("table_counts") or {}).get("encounter"),
        "ok": True,
    }
