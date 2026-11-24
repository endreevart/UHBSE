"""Temporal classification — SQL types + curated roles; no substring false positives."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_research_layer_v031.policy import VERSION

TIMESTAMP_TYPES = frozenset(
    {
        "timestamp without time zone",
        "timestamp with time zone",
        "date",
        "time without time zone",
        "time with time zone",
    }
)

# Known false positives from v0.3 substring matching
FALSE_POSITIVE_COLUMNS = frozenset(
    {
        "appointment_price_at_clinic",
        "appointment_price_at_clinic_id",
        "perform_at_clinic",
        "power_attorney",
        "recommendation_notes",
        "service_price_at_clinic_id",
        "service_price_online_at_clinic_id",
    }
)


def is_timestamp_column(column: str, data_type: str) -> bool:
    col = column.lower()
    dtype = (data_type or "").lower()
    if col in FALSE_POSITIVE_COLUMNS or "price_at_clinic" in col:
        return False
    if col.endswith("_at_clinic") or col.endswith("_at_clinic_id"):
        return False
    if dtype in TIMESTAMP_TYPES or dtype.startswith("timestamp") or dtype == "date":
        return True
    # name heuristics only if type is already temporal — never upgrade non-temporal types
    return False


def classify_temporal_columns(cur: Any, schema: str, tables: list[str]) -> list[dict[str, Any]]:
    if not tables:
        return []
    cur.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = ANY(%s)
        ORDER BY 1, 2
        """,
        (schema, tables),
    )
    out = []
    rejected = []
    for table, col, dtype in cur.fetchall():
        if col.lower() in FALSE_POSITIVE_COLUMNS or "price_at_clinic" in col.lower():
            if any(t in col.lower() for t in ("_at", "date", "time")):
                rejected.append(
                    {
                        "schema": schema,
                        "table": table,
                        "column": col,
                        "data_type": dtype,
                        "reason": "false_positive_control",
                    }
                )
            continue
        if is_timestamp_column(col, dtype):
            role = "technical_or_unknown"
            clinical = False
            cl = col.lower()
            if cl in {"appointment_date", "observed_at", "specimen_collected_at", "occurred_at", "date"}:
                role = "clinical_event_candidate"
                clinical = True
            elif cl in {"created", "created_at", "modified", "updated_at"}:
                role = "technical_audit"
            out.append(
                {
                    "schema": schema,
                    "table": table,
                    "column": col,
                    "data_type": dtype,
                    "timestamp_role": role,
                    "clinical_or_technical": "clinical" if clinical else "technical",
                    "clinical_administration_time_confirmed": False,
                }
            )
    return {"accepted": out, "rejected_false_positives": rejected}


def build_temporal_report(
    *,
    conn_a: Any | None,
    conn_b: Any | None,
    a_inv: dict[str, Any],
    b_inv: dict[str, Any],
    event_rows: int,
) -> dict[str, Any]:
    a_res: dict[str, Any] = {"accepted": [], "rejected_false_positives": []}
    b_res: dict[str, Any] = {"accepted": [], "rejected_false_positives": []}
    if conn_a is not None:
        cur = conn_a.cursor()
        try:
            tables = [
                r["relation"]
                for r in (a_inv.get("relations") or [])
                if r.get("schema") == "magerya_api" and r.get("kind") in {"table", "partitioned_table"}
            ][:120]
            a_res = classify_temporal_columns(cur, "magerya_api", tables)
        finally:
            cur.close()
    if conn_b is not None:
        cur = conn_b.cursor()
        try:
            tables = [
                r["relation"]
                for r in (b_inv.get("relations") or [])
                if r.get("schema") in {"public", "quest_digital"}
                and r.get("kind") in {"table", "partitioned_table"}
            ][:120]
            # probe both schemas
            pub = [t for t in tables if any(
                r["relation"] == t and r["schema"] == "public" for r in (b_inv.get("relations") or [])
            )]
            qd = [t for t in tables if any(
                r["relation"] == t and r["schema"] == "quest_digital" for r in (b_inv.get("relations") or [])
            )]
            b_pub = classify_temporal_columns(cur, "public", pub[:80])
            b_qd = classify_temporal_columns(cur, "quest_digital", qd[:80])
            b_res = {
                "accepted": b_pub["accepted"] + b_qd["accepted"],
                "rejected_false_positives": b_pub["rejected_false_positives"]
                + b_qd["rejected_false_positives"],
            }
        finally:
            cur.close()

    status = "PASS" if event_rows > 0 else "FAIL_NO_EVENT_ROWS"
    return {
        "version": VERSION,
        "UNIFIED_TEMPORAL_EVENT_LAYER_STATUS": status,
        "materialized_event_rows": event_rows,
        "classification_rule": "sql_data_type_primary_plus_curated_role",
        "substring_only_upgrade_forbidden": True,
        "false_positive_controls": sorted(FALSE_POSITIVE_COLUMNS),
        "a_timestamp_columns": a_res.get("accepted") or [],
        "b_timestamp_columns": b_res.get("accepted") or [],
        "rejected_false_positives": (a_res.get("rejected_false_positives") or [])
        + (b_res.get("rejected_false_positives") or []),
        "ok": status == "PASS",
    }
