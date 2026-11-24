"""Source A medication schema, identity, time and status semantics."""

from __future__ import annotations

from typing import Any

from human_simulator.population_v011.policy import SOURCE_A, VERSION


def _cols(conn: Any, schema: str, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position
            """,
            (schema, table),
        )
        return [r[0] for r in cur.fetchall()]


def profile_medication_semantics(conn_a: Any) -> dict[str, Any]:
    schema = "magerya_api"
    tables = [
        "diagnosis_medicineappointments",
        "diagnosis_medicines",
        "diagnosis_medicinesform",
        "diagnosis_conditionsmedicines",
        "diagnosis_diagnosis_medicines",
        "diagnosis_medicines_conditions",
    ]
    present = {}
    with conn_a.cursor() as cur:
        for t in tables:
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema=%s AND table_name=%s
                """,
                (schema, t),
            )
            if int(cur.fetchone()[0]) == 0:
                continue
            cols = _cols(conn_a, schema, t)
            cur.execute(f"SELECT COUNT(*) FROM {schema}.{t}")
            n = int(cur.fetchone()[0])
            present[t] = {"columns": cols, "n_rows": n}

    ma = present.get("diagnosis_medicineappointments") or {}
    cols = set(ma.get("columns") or [])
    with conn_a.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM magerya_api.diagnosis_medicineappointments")
        source_rows = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE patient_id IS NOT NULL),
              COUNT(DISTINCT patient_id) FILTER (WHERE patient_id IS NOT NULL),
              COUNT(*) FILTER (WHERE medicine_id IS NOT NULL),
              COUNT(DISTINCT medicine_id) FILTER (WHERE medicine_id IS NOT NULL),
              COUNT(*) FILTER (WHERE appointment_date IS NOT NULL),
              COUNT(*) FILTER (WHERE created IS NOT NULL),
              COUNT(*) FILTER (WHERE modified IS NOT NULL),
              COUNT(*) FILTER (WHERE status IS NOT NULL)
            FROM magerya_api.diagnosis_medicineappointments
            """
        )
        (
            linked_patient,
            unique_patients,
            med_id_nn,
            unique_med,
            appt_date_nn,
            created_nn,
            modified_nn,
            status_nn,
        ) = (int(x) for x in cur.fetchone())

        # status distribution (aggregate only)
        status_dist = []
        if "status" in cols:
            cur.execute(
                """
                SELECT COALESCE(status::text, '∅'), COUNT(*)
                FROM magerya_api.diagnosis_medicineappointments
                GROUP BY 1 ORDER BY 2 DESC LIMIT 30
                """
            )
            status_dist = [{"status": r[0], "n": int(r[1])} for r in cur.fetchall()]

        # join to diagnosis_medicines
        join_coverage = None
        med_name_cols = []
        if "diagnosis_medicines" in present and med_id_nn:
            mcols = set(present["diagnosis_medicines"]["columns"])
            med_name_cols = [c for c in ("name", "title", "title_ru", "label", "medicine") if c in mcols]
            cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE m.id IS NOT NULL),
                  COUNT(*) FILTER (WHERE ma.medicine_id IS NOT NULL AND m.id IS NULL)
                FROM magerya_api.diagnosis_medicineappointments ma
                LEFT JOIN magerya_api.diagnosis_medicines m ON m.id = ma.medicine_id
                """
            )
            joined, missing_join = (int(x) for x in cur.fetchone())
            join_coverage = {
                "rows_with_medicine_id_joined": joined,
                "rows_with_medicine_id_unjoined": missing_join,
                "join_rate": round(joined / source_rows, 6) if source_rows else None,
            }

        # time differences appointment_date vs created (days), aggregates only
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (
                WHERE appointment_date IS NOT NULL AND created IS NOT NULL
              ),
              PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (created - appointment_date))/86400.0
              ) FILTER (WHERE appointment_date IS NOT NULL AND created IS NOT NULL),
              COUNT(*) FILTER (
                WHERE appointment_date IS NOT NULL AND created IS NOT NULL
                  AND appointment_date::date > CURRENT_DATE
              ),
              COUNT(*) FILTER (
                WHERE created IS NOT NULL AND created::date > CURRENT_DATE
              )
            FROM magerya_api.diagnosis_medicineappointments
            """
        )
        both_ts, med_delta_days, future_appt, future_created = cur.fetchone()
        both_ts = int(both_ts or 0)
        future_appt = int(future_appt or 0)
        future_created = int(future_created or 0)

        # same-time duplicates
        cur.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT patient_id, medicine_id, appointment_date, COUNT(*) AS n
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND appointment_date IS NOT NULL
              GROUP BY 1,2,3 HAVING COUNT(*) > 1
            ) t
            """
        )
        same_time_dup_groups = int(cur.fetchone()[0])

    # Event time decision
    if appt_date_nn / source_rows >= 0.95 if source_rows else False:
        clinical_event_time_status = "CANDIDATE_ONLY"
        chosen = "appointment_date"
        why = (
            "appointment_date is highly populated and temporally nearer to clinical context "
            "than created; not ACCEPTED_TECHNICAL_TIMESTAMP without domain confirmation that "
            "it represents administration/start rather than scheduling."
        )
    elif created_nn / source_rows >= 0.95 if source_rows else False:
        clinical_event_time_status = "CANDIDATE_ONLY"
        chosen = "created"
        why = (
            "created is populated but is a record-creation timestamp, not automatically "
            "clinical intervention time."
        )
    else:
        clinical_event_time_status = "AMBIGUOUS"
        chosen = None
        why = "No timestamp meets acceptance criteria without domain review."

    # Relationship graph (declared FKs + inferred)
    relationships = []
    with conn_a.cursor() as cur:
        cur.execute(
            """
            SELECT
              tc.table_name, kcu.column_name,
              ccu.table_name AS foreign_table, ccu.column_name AS foreign_column
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'magerya_api'
              AND (
                tc.table_name ILIKE '%%medicine%%'
                OR ccu.table_name ILIKE '%%medicine%%'
              )
            """
        )
        for r in cur.fetchall():
            relationships.append(
                {
                    "source_table": r[0],
                    "source_column": r[1],
                    "target_table": r[2],
                    "target_column": r[3],
                    "fk_declared": True,
                    "evidence_status": "CONFIRMED_SCHEMA",
                }
            )
    # Inferred edges
    relationships.append(
        {
            "source_table": "diagnosis_medicineappointments",
            "source_column": "medicine_id",
            "target_table": "diagnosis_medicines",
            "target_column": "id",
            "fk_declared": any(
                x.get("source_column") == "medicine_id" and x.get("fk_declared")
                for x in relationships
            ),
            "match_rate": (join_coverage or {}).get("join_rate"),
            "evidence_status": "CONFIRMED_DATA" if join_coverage else "HYPOTHESIS",
        }
    )
    relationships.append(
        {
            "source_table": "diagnosis_medicineappointments",
            "source_column": "patient_id",
            "target_table": "account_patient",
            "target_column": "id",
            "fk_declared": False,
            "null_rate": round(1 - linked_patient / source_rows, 6) if source_rows else None,
            "evidence_status": "CONFIRMED_DATA",
        }
    )

    identity = {
        "medicine_id_non_null": med_id_nn,
        "medicine_id_non_null_rate": round(med_id_nn / source_rows, 6) if source_rows else None,
        "unique_medicine_ids": unique_med,
        "join_coverage": join_coverage,
        "medicine_name_columns_available": med_name_cols,
        "active_ingredient_availability": "UNKNOWN_REQUIRES_COLUMN_EVIDENCE",
        "trade_name_availability": "CANDIDATE_IF_NAME_COLUMN" if med_name_cols else "NOT_FOUND",
        "dose_availability": "NOT_FOUND_ON_MEDICINEAPPOINTMENTS",
        "dose_unit_availability": "NOT_FOUND_ON_MEDICINEAPPOINTMENTS",
        "route_availability": "NOT_FOUND_ON_MEDICINEAPPOINTMENTS",
        "frequency_availability": "NOT_FOUND_ON_MEDICINEAPPOINTMENTS",
        "duration_availability": "NOT_FOUND_ON_MEDICINEAPPOINTMENTS",
        "note": (
            "medicine_id is a source identity, not automatically an active ingredient. "
            "Trade names must not be treated as ingredients without evidence."
        ),
    }

    time_sem = {
        "appointment_date_non_null": appt_date_nn,
        "created_non_null": created_nn,
        "modified_non_null": modified_nn,
        "both_appointment_and_created": both_ts,
        "median_created_minus_appointment_days": (
            float(med_delta_days) if med_delta_days is not None else None
        ),
        "future_appointment_date_rows": future_appt,
        "future_created_rows": future_created,
        "same_time_duplicate_groups": same_time_dup_groups,
        "clinical_event_time_status": clinical_event_time_status,
        "chosen_technical_timestamp_candidate": chosen,
        "rationale": why,
        "explicit_non_claim": (
            "created is not used as clinical intervention time merely because it is populated."
        ),
    }

    status_sem = {
        "status_non_null": status_nn,
        "status_distribution_top": status_dist,
        "inferred_transitions": {
            "initiation": "NOT_INFERRED",
            "dose_change": "NOT_INFERRED",
            "discontinuation": "NOT_INFERRED",
            "replacement": "NOT_INFERRED",
            "ongoing_use": "NOT_INFERRED",
        },
        "default_transition_label": "UNKNOWN_RECORDED_MEDICATION_EVENT",
        "note": (
            "Unknown status does not become initiation/discontinuation without evidence."
        ),
    }

    return {
        "version": VERSION,
        "source_system": SOURCE_A,
        "source_a_medication_schema_status": "PASS" if present else "FAIL",
        "tables_present": present,
        "relationship_graph": relationships,
        "source_rows": source_rows,
        "unique_patients": unique_patients,
        "identity": identity,
        "time_semantics": time_sem,
        "status_semantics": status_sem,
        "source_a_medicine_identity_status": (
            "PASS" if med_id_nn / source_rows >= 0.9 else "PARTIAL"
        )
        if source_rows
        else "FAIL",
        "source_a_medication_time_semantics_status": clinical_event_time_status,
        "source_a_medication_status_semantics": "PROFILED_NO_TRANSITION_INFERENCE",
        "values_redacted": True,
    }


def build_normalization_layer(med_profile: dict[str, Any]) -> dict[str, Any]:
    identity = med_profile.get("identity") or {}
    n_unique = identity.get("unique_medicine_ids") or 0
    return {
        "version": VERSION,
        "medication_normalization_status": "PARTIAL",
        "layers": [
            "SourceMedicationRecord",
            "SourceMedicationConcept",
            "NormalizedMedicationCandidate",
            "ActiveIngredientCandidate",
        ],
        "source_medication_concepts": {
            "n_unique_medicine_id": n_unique,
            "confidence_default": "EXACT_SOURCE_ID",
            "note": "medicine_id retained as source identity only",
        },
        "normalized_medication_candidates": {
            "n_accepted": 0,
            "n_hypothesis": n_unique,
            "llm_auto_accept_forbidden": True,
        },
        "active_ingredient_candidates": {
            "n": 0,
            "note": "No automatic trade-name→ingredient mapping",
        },
        "reference_bindings": {
            "ATC": "EVALUATION_ONLY",
            "RxNorm": "EVALUATION_ONLY_UMLS_LICENSE_CONSTRAINTS",
            "national_registries": "OWNER_APPROVAL_REQUIRED_BEFORE_INTEGRATION",
            "commercial_download": False,
        },
        "confidence_levels": [
            "EXACT_SOURCE_ID",
            "EXACT_REFERENCE_ID",
            "DETERMINISTIC_TEXT_NORMALIZATION",
            "REFERENCE_DICTIONARY_MATCH",
            "ACTIVE_INGREDIENT_CANDIDATE",
            "LLM_CANDIDATE",
            "HYPOTHESIS",
            "UNKNOWN",
        ],
    }
