"""Medication / intervention inventory (aggregates only; no clinical claims)."""

from __future__ import annotations

from typing import Any

from human_simulator.population_v01.policy import SOURCE_A, SOURCE_B, VERSION


def _cols(conn: Any, schema: str, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            """,
            (schema, table),
        )
        return {r[0] for r in cur.fetchall()}


def inventory_source_a_interventions(conn: Any) -> dict[str, Any]:
    schema, table = "magerya_api", "diagnosis_medicineappointments"
    cols = _cols(conn, schema, table)
    if "id" not in cols:
        return {
            "version": VERSION,
            "source_system": SOURCE_A,
            "intervention_data_readiness_status": "FAIL",
            "reason": "diagnosis_medicineappointments missing",
        }

    # Discover related tables
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='magerya_api'
              AND (
                table_name ILIKE '%medicine%'
                OR table_name ILIKE '%drug%'
                OR table_name ILIKE '%prescri%'
                OR table_name ILIKE '%dosage%'
                OR table_name ILIKE '%supplement%'
              )
            ORDER BY table_name
            """
        )
        related = [r[0] for r in cur.fetchall()]

        cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        source_rows = int(cur.fetchone()[0])

        has_patient = "patient_id" in cols
        has_appt = "appointment_id" in cols
        # common optional columns
        time_cols = [c for c in ("created", "updated", "start_date", "end_date", "date") if c in cols]
        text_cols = [
            c
            for c in (
                "medicine",
                "name",
                "drug",
                "title",
                "text",
                "description",
                "dose",
                "dosage",
                "unit",
                "frequency",
                "route",
                "status",
            )
            if c in cols
        ]

        linked_patient = 0
        unique_patients = 0
        if has_patient:
            cur.execute(
                f"""
                SELECT COUNT(*) FILTER (WHERE patient_id IS NOT NULL),
                       COUNT(DISTINCT patient_id) FILTER (WHERE patient_id IS NOT NULL)
                FROM {schema}.{table}
                """
            )
            linked_patient, unique_patients = (int(x) for x in cur.fetchone())

        linked_appt = 0
        if has_appt:
            cur.execute(
                f"SELECT COUNT(*) FILTER (WHERE appointment_id IS NOT NULL) FROM {schema}.{table}"
            )
            linked_appt = int(cur.fetchone()[0])

        with_event_ts = 0
        for tc in time_cols[:1]:
            cur.execute(
                f"SELECT COUNT(*) FILTER (WHERE {tc} IS NOT NULL) FROM {schema}.{table}"
            )
            with_event_ts = int(cur.fetchone()[0])

        # Unique raw medication strings if a text-like column exists
        unique_raw = None
        med_col = next(
            (c for c in ("medicine", "name", "drug", "title", "description", "text") if c in cols),
            None,
        )
        if med_col:
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT NULLIF(btrim({med_col}::text), ''))
                FROM {schema}.{table}
                """
            )
            unique_raw = int(cur.fetchone()[0] or 0)

        # Dose/unit/frequency/route presence if columns exist
        def count_nonnull(col: str) -> int | None:
            if col not in cols:
                return None
            cur.execute(
                f"SELECT COUNT(*) FILTER (WHERE {col} IS NOT NULL AND btrim({col}::text) <> '') FROM {schema}.{table}"
            )
            return int(cur.fetchone()[0])

    return {
        "version": VERSION,
        "source_system": SOURCE_A,
        "intervention_data_readiness_status": "PARTIAL",
        "table": f"{schema}.{table}",
        "columns_present": sorted(cols),
        "related_tables_discovered": related,
        "counts": {
            "source_rows": source_rows,
            "unique_patients": unique_patients,
            "unique_raw_medication_strings_or_codes": unique_raw,
            "records_linked_to_patient": linked_patient,
            "records_linked_to_appointment": linked_appt,
            "records_with_event_timestamp": with_event_ts,
            "records_with_start_date": count_nonnull("start_date"),
            "records_with_end_date": count_nonnull("end_date"),
            "records_with_parseable_dose": count_nonnull("dose") or count_nonnull("dosage"),
            "records_with_dose_unit": count_nonnull("unit"),
            "records_with_frequency": count_nonnull("frequency"),
            "records_with_route": count_nonnull("route"),
            "records_with_duration": None,
            "records_representing_dose_change": None,
            "records_representing_discontinuation": None,
            "records_representing_replacement": None,
            "duplicate_candidates": None,
            "conflicting_same_time_records": None,
            "polypharmacy_periods": None,
            "supplement_candidates": None,
            "unknown_unusable_rows": None,
        },
        "explicit_non_claim": (
            f"{source_rows} medicine-appointment source rows must NOT be presented as "
            f"{source_rows} interventions without verification."
        ),
        "intervention_count_equals_source_rows": False,
        "text_columns_inspected_names_only": text_cols,
        "time_columns": time_cols,
        "values_redacted": True,
    }


def inventory_source_b_interventions(conn_b: Any | None) -> dict[str, Any]:
    if conn_b is None:
        return {
            "version": VERSION,
            "source_system": SOURCE_B,
            "intervention_data_readiness_status": "PARTIAL",
            "reason": "Source B medication structures not confirmed; no invented mapping.",
            "counts": {},
            "mapping_invented": False,
        }
    with conn_b.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type='BASE TABLE'
              AND (
                table_name ILIKE '%medicine%'
                OR table_name ILIKE '%drug%'
                OR table_name ILIKE '%prescri%'
                OR table_name ILIKE '%medication%'
                OR table_name ILIKE '%recept%'
              )
            ORDER BY 1,2
            LIMIT 50
            """
        )
        tables = [{"schema": r[0], "table": r[1]} for r in cur.fetchall()]
    return {
        "version": VERSION,
        "source_system": SOURCE_B,
        "intervention_data_readiness_status": "PARTIAL" if tables else "FAIL",
        "candidate_tables": tables,
        "mapping_invented": False,
        "note": (
            "No Source B medication mapping invented without sufficient evidence. "
            "Inventory limited to schema discovery + table presence."
        ),
        "values_redacted": True,
    }


def medication_normalization_candidates(inv_a: dict[str, Any]) -> dict[str, Any]:
    n_unique = (inv_a.get("counts") or {}).get("unique_raw_medication_strings_or_codes")
    return {
        "version": VERSION,
        "confidence_levels": [
            "EXACT_SOURCE_CODE",
            "DICTIONARY_MATCH",
            "NORMALIZED_TEXT_CANDIDATE",
            "LLM_CANDIDATE",
            "HYPOTHESIS",
            "UNKNOWN",
        ],
        "n_unique_raw_strings_observed": n_unique,
        "accepted_mappings": [],
        "candidates": [],
        "llm_auto_accept_forbidden": True,
        "deterministic_reproducible_without_llm": True,
        "note": (
            "Normalization layer scaffolded; no LLM-generated mapping accepted automatically. "
            "No patient data sent to external LLM."
        ),
    }


def medication_reference_source_evaluation() -> dict[str, Any]:
    sources = [
        {
            "name": "ATC",
            "purpose": "Anatomical Therapeutic Chemical classification",
            "jurisdiction": "WHO / international",
            "licensing": "Public classification; redistribution of derived products varies",
            "update_mechanism": "Periodic WHO releases",
            "identifiers": ["ATC code"],
            "dose_support": "Limited (DDD)",
            "interaction_support": False,
            "redistribution_restrictions": "Check WHO terms for commercial redistribution",
            "suitability": "Useful hierarchy; not sufficient alone for product-level dosing",
        },
        {
            "name": "RxNorm",
            "purpose": "US normalized drug terminology",
            "jurisdiction": "United States (NLM)",
            "licensing": "UMLS Metathesaurus license required for some uses",
            "update_mechanism": "NLM regular releases",
            "identifiers": ["RxCUI"],
            "dose_support": True,
            "interaction_support": "Indirect via linked sources",
            "redistribution_restrictions": "UMLS license constraints may apply",
            "suitability": "Strong for US product concepts; jurisdiction mismatch for local clinic data",
        },
        {
            "name": "National drug registries (jurisdiction-local)",
            "purpose": "Local authorized medicinal products",
            "jurisdiction": "Clinic country / regional authority",
            "licensing": "Varies; often restricted redistribution",
            "update_mechanism": "Authority publications",
            "identifiers": ["national registration numbers"],
            "dose_support": True,
            "interaction_support": "Varies",
            "redistribution_restrictions": "Often present — do not download/integrate without owner approval",
            "suitability": "Preferred for local product identity when licensed for project use",
        },
        {
            "name": "Active-ingredient catalogs",
            "purpose": "Ingredient-level identity independent of brand",
            "jurisdiction": "Varies",
            "licensing": "Varies",
            "update_mechanism": "Catalog-specific",
            "identifiers": ["INN", "CAS", "local ingredient ids"],
            "dose_support": "Partial",
            "interaction_support": False,
            "redistribution_restrictions": "Check per source",
            "suitability": "Useful bridge from free-text to substance",
        },
        {
            "name": "Dose-form and route dictionaries",
            "purpose": "Normalize form/route vocabulary",
            "jurisdiction": "International / local",
            "licensing": "Often open (EDQM, SNOMED subsets — license-dependent)",
            "update_mechanism": "Periodic",
            "identifiers": ["EDQM", "SNOMED CT ids where licensed"],
            "dose_support": True,
            "interaction_support": False,
            "redistribution_restrictions": "SNOMED requires affiliate license",
            "suitability": "Needed for episode construction quality",
        },
        {
            "name": "Interaction / contraindication sources",
            "purpose": "Safety interaction knowledge",
            "jurisdiction": "Varies",
            "licensing": "Often commercial",
            "update_mechanism": "Vendor",
            "identifiers": ["vendor ids"],
            "dose_support": "Varies",
            "interaction_support": True,
            "redistribution_restrictions": "Typically restricted — owner approval required",
            "suitability": "Deferred; not integrated in this stage",
        },
        {
            "name": "PK/PD reference sources",
            "purpose": "Pharmacokinetic/pharmacodynamic parameters",
            "jurisdiction": "Scientific literature / curated DBs",
            "licensing": "Often restricted or citation-only",
            "update_mechanism": "Literature / vendor",
            "identifiers": ["compound ids"],
            "dose_support": True,
            "interaction_support": "Partial",
            "redistribution_restrictions": "Do not download restricted DBs without owner approval",
            "suitability": "Out of scope for this stage (pkpd_status: NOT_STARTED)",
        },
    ]
    return {
        "version": VERSION,
        "sources": sources,
        "commercial_or_restricted_download_without_owner_approval": False,
        "integration_status": "EVALUATION_ONLY",
    }
