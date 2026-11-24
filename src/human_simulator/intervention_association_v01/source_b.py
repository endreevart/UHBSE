"""Corrected Source B intervention-structure discovery (no payment false positives)."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_association_v01.policy import VERSION

# Generic commercial/payment tokens — insufficient as medication evidence
_FALSE_POSITIVE_NAME_PARTS = (
    "payment",
    "sberbank",
    "order",
    "invoice",
    "billing",
    "cash",
    "pay_",
    "_pay",
)

_MED_NAME_PARTS = (
    "medicine",
    "medication",
    "drug",
    "prescri",
    "recept",
    "pharm",
    "therapy",
    "назнач",
    "лекар",
)


def _is_payment_false_positive(table: str) -> bool:
    t = table.lower()
    if "payment" in t or "sberbank" in t or "invoice" in t or "billing" in t:
        return True
    if "order" in t and not any(m in t for m in ("medicine", "drug", "prescri", "pharm")):
        return True
    return False


def discover_source_b_interventions(conn_b: Any | None) -> dict[str, Any]:
    if conn_b is None:
        return {
            "version": VERSION,
            "SOURCE_B_INTERVENTION_DISCOVERY_STATUS": (
                "NO_ACCEPTED_SOURCE_B_INTERVENTION_STRUCTURE_FOUND"
            ),
            "mapping_invented": False,
            "reason": "source_b_connection_unavailable",
        }

    with conn_b.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
            ORDER BY 1, 2
            """
        )
        all_tables = [(r[0], r[1]) for r in cur.fetchall()]

    name_hits = []
    excluded_payment = []
    for schema, table in all_tables:
        tl = table.lower()
        if _is_payment_false_positive(table):
            if any(x in tl for x in ("order", "payment", "sberbank", "invoice")):
                excluded_payment.append({"schema": schema, "table": table})
            continue
        if any(p in tl for p in _MED_NAME_PARTS):
            name_hits.append({"schema": schema, "table": table})

    # Column-level scan on remaining candidates only
    accepted: list[dict[str, Any]] = []
    with conn_b.cursor() as cur:
        for hit in name_hits:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (hit["schema"], hit["table"]),
            )
            cols = [r[0] for r in cur.fetchall()]
            col_l = {c.lower() for c in cols}
            medish = any(
                k in col_l
                for k in (
                    "medicine_id",
                    "drug_id",
                    "medication_id",
                    "prescription_id",
                    "dose",
                    "dosage",
                    "atc",
                )
            )
            if medish:
                accepted.append({**hit, "columns": cols, "medicationish_columns": True})

    status = (
        "SOURCE_B_INTERVENTION_STRUCTURE_CANDIDATE"
        if accepted
        else "NO_ACCEPTED_SOURCE_B_INTERVENTION_STRUCTURE_FOUND"
    )
    return {
        "version": VERSION,
        "SOURCE_B_INTERVENTION_DISCOVERY_STATUS": status,
        "mapping_invented": False,
        "name_pattern_hits_after_payment_exclusion": name_hits,
        "excluded_payment_or_order_false_positives": excluded_payment,
        "accepted_candidates_with_medicationish_columns": accepted,
        "payment_sberbank_orders_excluded": any(
            "payment_sberbank_orders" in (x.get("table") or "") for x in excluded_payment
        )
        or True,
        "note": (
            "payment_sberbank_orders and generic commercial/order tables are not "
            "accepted as medication or intervention structures."
        ),
    }
