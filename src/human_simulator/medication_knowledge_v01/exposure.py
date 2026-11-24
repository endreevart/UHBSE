"""Phase 4 — exposure-semantics contract (association ≠ administration ≠ treatment effect)."""

from __future__ import annotations

from typing import Any

from human_simulator.medication_knowledge_v01.policy import VERSION


def build_exposure_semantics_report(conn_a: Any, episode_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    with conn_a.cursor() as cur:
        cur.execute(
            """
            SELECT
              COUNT(*)::bigint,
              COUNT(*) FILTER (WHERE appointment_date IS NOT NULL)::bigint,
              COUNT(*) FILTER (WHERE created IS NOT NULL)::bigint,
              COUNT(*) FILTER (WHERE modified IS NOT NULL)::bigint,
              COUNT(*) FILTER (
                WHERE appointment_date IS NOT NULL AND created IS NOT NULL
                  AND appointment_date::date = created::date
              )::bigint,
              COUNT(*) FILTER (
                WHERE appointment_date IS NOT NULL AND created IS NOT NULL
                  AND appointment_date > created
              )::bigint
            FROM magerya_api.diagnosis_medicineappointments
            WHERE patient_id IS NOT NULL
            """
        )
        n, appt, created, modified, same_day_ts, appt_after_created = (
            int(x) for x in cur.fetchone()
        )
        cur.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT patient_id, appointment_date::date AS d, COUNT(DISTINCT medicine_id) AS n
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND appointment_date IS NOT NULL AND medicine_id IS NOT NULL
              GROUP BY 1,2 HAVING COUNT(DISTINCT medicine_id) > 1
            ) t
            """
        )
        poly_days = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE unit_of_measurement_id IS NOT NULL),
              COUNT(*) FILTER (WHERE form_id IS NOT NULL),
              COUNT(*) FILTER (WHERE reception_frequency_id IS NOT NULL)
            FROM magerya_api.diagnosis_medicines m
            WHERE EXISTS (
              SELECT 1 FROM magerya_api.diagnosis_medicineappointments ma
              WHERE ma.medicine_id = m.id
            )
            """
        )
        dose_form_freq = [int(x) for x in cur.fetchone()]

    layers = {
        "recorded_medication_association": {
            "supported": True,
            "evidence": "diagnosis_medicineappointments rows linked to patients",
        },
        "candidate_medication_event": {
            "supported": True,
            "evidence": "appointment_date technical hypothesis + medicine_id",
            "clinical_time_confirmed": False,
        },
        "candidate_exposure_window": {
            "supported": True,
            "evidence": "pre/post lab windows around event timestamp hypothesis",
            "clinical_exposure_confirmed": False,
        },
        "confirmed_administration": {
            "supported": False,
            "evidence": "no administration/dispense/ingest confirmation fields verified",
        },
        "intervention": {
            "supported": False,
            "note": "ScenarioIntervention identity not activated from these rows",
        },
        "treatment_response": {"supported": False},
        "causal_effect": {"supported": False},
    }

    return {
        "version": VERSION,
        "EXPOSURE_SEMANTICS_STATUS": "CONTRACT_PUBLISHED",
        "separations": {
            "RECORDED_MEDICATION_ASSOCIATION_NE_CONFIRMED_ADMINISTRATION": True,
            "ASSOCIATION_NE_INTERVENTION_RESPONSE": True,
            "PREDICTION_NE_TREATMENT_EFFECT": True,
        },
        "layers": layers,
        "timestamp_comparison": {
            "rows_with_patient": n,
            "appointment_date_nonnull": appt,
            "created_nonnull": created,
            "modified_nonnull": modified,
            "same_calendar_day_appointment_and_created": same_day_ts,
            "appointment_after_created": appt_after_created,
            "appointment_date_status": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
            "created_status": "RECORD_CREATION_TIMESTAMP_SENSITIVITY_CONTROL",
            "promoted_to_clinical_administration_time": False,
        },
        "polypharmacy": {
            "same_day_multi_medicine_patient_days": poly_days,
        },
        "dose_form_route_frequency_availability": {
            "usable_unit_fk": dose_form_freq[0],
            "usable_form_fk": dose_form_freq[1],
            "usable_frequency_fk": dose_form_freq[2],
            "route_field_available": False,
            "dose_value_field_available": False,
        },
        "episode_summary_ref": episode_summary,
        "exposure_confidence_levels": {
            "default_for_source_a_rows": "LOW_TECHNICAL_ASSOCIATION_ONLY",
            "domain_review_required": True,
        },
        "migration_0005": "NOT_RUN",
    }
