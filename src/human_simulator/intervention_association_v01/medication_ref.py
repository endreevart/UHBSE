"""Medication reference coverage (no ATC/RxNorm purchase; no LLM auto-accept)."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_association_v01.policy import VERSION


def build_medication_reference_report(conn_a: Any) -> dict[str, Any]:
    with conn_a.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='magerya_api' AND table_name='diagnosis_medicines'
            ORDER BY ordinal_position
            """
        )
        med_cols = [r[0] for r in cur.fetchall()]
        cur.execute(
            """
            SELECT
              COUNT(*)::bigint,
              COUNT(*) FILTER (WHERE medicine_id IS NOT NULL)::bigint
            FROM magerya_api.diagnosis_medicineappointments
            """
        )
        n_rows, n_with_id = (int(x) for x in cur.fetchone())
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE m.id IS NOT NULL)::bigint,
              COUNT(*) FILTER (WHERE ma.medicine_id IS NOT NULL AND m.id IS NULL)::bigint
            FROM magerya_api.diagnosis_medicineappointments ma
            LEFT JOIN magerya_api.diagnosis_medicines m ON m.id = ma.medicine_id
            """
        )
        joined, missing = (int(x) for x in cur.fetchone())

        coverage: dict[str, Any] = {}
        for field in (
            "name",
            "title",
            "unit",
            "form",
            "frequency",
            "description",
            "category",
            "reception_frequency",
        ):
            if field not in med_cols and field != "name":
                # try common variants
                variants = [c for c in med_cols if field in c.lower()]
                if not variants and field == "name":
                    variants = [c for c in med_cols if c.lower() in ("name", "title", "title_ru")]
                col = variants[0] if variants else None
            else:
                col = field if field in med_cols else None
            if col is None:
                coverage[field] = {"present_in_schema": False, "non_null_join_rate": None}
                continue
            cur.execute(
                f"""
                SELECT COUNT(*) FILTER (WHERE m.{col} IS NOT NULL AND btrim(m.{col}::text) <> '')
                FROM magerya_api.diagnosis_medicineappointments ma
                JOIN magerya_api.diagnosis_medicines m ON m.id = ma.medicine_id
                """
            )
            nn = int(cur.fetchone()[0])
            coverage[field] = {
                "present_in_schema": True,
                "column": col,
                "non_null_joined_rows": nn,
                "join_rate": round(nn / n_rows, 6) if n_rows else None,
            }

    return {
        "version": VERSION,
        "medicine_id_is_source_a_identity_only": True,
        "inferred_forbidden": [
            "active_ingredient",
            "dose",
            "route",
            "duration",
            "adherence",
            "administration",
            "treatment_start",
            "treatment_discontinuation",
        ],
        "diagnosis_medicines_columns": med_cols,
        "appointment_rows": n_rows,
        "rows_with_medicine_id": n_with_id,
        "joined_to_diagnosis_medicines": joined,
        "medicine_id_unjoined": missing,
        "field_coverage": coverage,
        "future_reference_sources_needed": [
            "ATC",
            "RxNorm",
            "DrugBank_or_licensed_commercial",
            "national_drug_registries",
            "ingredient_strength_form_route_dictionaries",
        ],
        "commercial_db_connected": False,
        "llm_auto_accept_forbidden": True,
    }
