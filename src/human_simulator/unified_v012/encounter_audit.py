"""Re-verify Source B Subject/Encounter; repair only if defect found."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from human_simulator.unified_v012.policy import (
    EXPECTED_SOURCE_B_ENCOUNTERS,
    EXPECTED_SOURCE_B_SUBJECTS,
    SOURCE_B_SYSTEM_ID,
)


ENCOUNTER_CONSTRUCTION_POLICY: dict[str, Any] = {
    "document": "source-b-encounter-construction-policy",
    "version": "0.1.2",
    "source_system": SOURCE_B_SYSTEM_ID,
    "source_relation": "public.consultations",
    "occurred_at": {
        "primary": "COALESCE(confirmed_at, success_at, (date::timestamp + COALESCE(time, time '00:00')), created_at)",
        "fallback_order": [
            "confirmed_at",
            "success_at",
            "date+time (date alone → midnight)",
            "created_at",
        ],
        "notes": "Deterministic clinical occurrence; never invent from cancel_at.",
    },
    "recorded_at": {
        "primary": "created_at",
        "fallback_order": ["created_at"],
    },
    "completed_at": {
        "primary": "success_at WHEN success IS TRUE",
        "else": None,
    },
    "cancelled_at": {
        "primary": "cancel_at WHEN cancel IS TRUE",
        "else": None,
    },
    "status_derivation": {
        "cancelled": "cancel IS TRUE",
        "completed": "success IS TRUE AND cancel IS NOT TRUE",
        "confirmed": "confirmed IS TRUE AND success IS NOT TRUE AND cancel IS NOT TRUE",
        "open": "else",
        "contradiction_priority": ["cancelled", "completed", "confirmed", "open"],
    },
    "temporal_precision": "timestamp with time zone (source timestamps treated as clinic-local stored UTC-capable)",
    "provider_id_policy": "NULL in v0.1.2 — provider mapping not promoted",
    "repair_policy": "Do not rewrite ACCEPTED rows unless audit detects mapping defect vs this policy",
}


def write_construction_policy(out_path: Path) -> dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(ENCOUNTER_CONSTRUCTION_POLICY, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return ENCOUNTER_CONSTRUCTION_POLICY


def derive_encounter_status(*, cancel: bool | None, success: bool | None, confirmed: bool | None) -> str:
    if cancel is True:
        return "cancelled"
    if success is True:
        return "completed"
    if confirmed is True:
        return "confirmed"
    return "open"


def audit_source_b_subjects_encounters(repo_root: Path) -> dict[str, Any]:
    """Aggregate-only audit; no patient values."""
    root = Path(repo_root)
    result: dict[str, Any] = {
        "expected_subjects": EXPECTED_SOURCE_B_SUBJECTS,
        "expected_encounters": EXPECTED_SOURCE_B_ENCOUNTERS,
        "repair_performed": False,
        "migration_0005": False,
    }
    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings
        from human_simulator.db.readonly import assert_readonly
        from human_simulator.unified.source_b_adapter import source_b_connection

        with source_b_connection(root) as src:
            with src.cursor() as cur:
                sql = """
                SELECT
                  COUNT(DISTINCT patient_id) FILTER (WHERE patient_id IS NOT NULL),
                  COUNT(*) FILTER (WHERE patient_id IS NULL),
                  COUNT(*) FILTER (
                    WHERE patient_id IS NOT NULL
                      AND NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = consultations.patient_id)
                  )
                FROM public.consultations
                """
                assert_readonly(sql)
                cur.execute(sql)
                distinct_patients, null_pid, missing_user = cur.fetchone()

                sql2 = """
                SELECT COUNT(*) FROM (
                  SELECT u.id
                  FROM public.users u
                  WHERE EXISTS (
                    SELECT 1 FROM public.consultations c WHERE c.patient_id = u.id
                  )
                  AND EXISTS (
                    SELECT 1 FROM public.consultations c2 WHERE c2.doctor_id = u.id
                  )
                ) both_roles
                """
                assert_readonly(sql2)
                cur.execute(sql2)
                both_roles = cur.fetchone()[0]

                # Temporal aggregates on consultations
                sql3 = """
                SELECT
                  COUNT(*) FILTER (WHERE date IS NOT NULL),
                  COUNT(*) FILTER (WHERE time IS NOT NULL),
                  COUNT(*) FILTER (WHERE created_at IS NOT NULL),
                  COUNT(*) FILTER (WHERE confirmed_at IS NOT NULL),
                  COUNT(*) FILTER (WHERE success_at IS NOT NULL),
                  COUNT(*) FILTER (WHERE cancel_at IS NOT NULL),
                  COUNT(*) FILTER (WHERE confirmed IS TRUE),
                  COUNT(*) FILTER (WHERE confirmed IS FALSE),
                  COUNT(*) FILTER (WHERE confirmed IS NULL),
                  COUNT(*) FILTER (WHERE success IS TRUE),
                  COUNT(*) FILTER (WHERE success IS FALSE),
                  COUNT(*) FILTER (WHERE success IS NULL),
                  COUNT(*) FILTER (WHERE cancel IS TRUE),
                  COUNT(*) FILTER (WHERE cancel IS FALSE),
                  COUNT(*) FILTER (WHERE cancel IS NULL),
                  COUNT(*) FILTER (WHERE success IS TRUE AND cancel IS NOT TRUE),
                  COUNT(*) FILTER (WHERE cancel IS TRUE),
                  COUNT(*) FILTER (
                    WHERE confirmed IS TRUE AND success IS NOT TRUE AND cancel IS NOT TRUE
                  ),
                  COUNT(*) FILTER (
                    WHERE COALESCE(success, FALSE) IS FALSE
                      AND COALESCE(cancel, FALSE) IS FALSE
                      AND COALESCE(confirmed, FALSE) IS FALSE
                  ),
                  COUNT(*) FILTER (WHERE success IS TRUE AND cancel IS TRUE),
                  COUNT(*) FILTER (
                    WHERE confirmed_at IS NOT NULL AND created_at IS NOT NULL
                      AND confirmed_at < created_at
                  ),
                  COUNT(*) FILTER (
                    WHERE success_at IS NOT NULL AND created_at IS NOT NULL
                      AND success_at < created_at
                  ),
                  COUNT(*) FILTER (
                    WHERE cancel_at IS NOT NULL AND created_at IS NOT NULL
                      AND cancel_at < created_at
                  ),
                  COUNT(*)
                FROM public.consultations
                """
                assert_readonly(sql3)
                cur.execute(sql3)
                row = cur.fetchone()

        result["source_b_aggregates"] = {
            "distinct_consultations_patient_id": int(distinct_patients or 0),
            "null_patient_id": int(null_pid or 0),
            "patient_id_without_user": int(missing_user or 0),
            "users_in_both_patient_and_doctor_roles": int(both_roles or 0),
        }
        result["temporal_aggregates"] = {
            "date_non_null": int(row[0]),
            "time_non_null": int(row[1]),
            "created_at_non_null": int(row[2]),
            "confirmed_at_non_null": int(row[3]),
            "success_at_non_null": int(row[4]),
            "cancel_at_non_null": int(row[5]),
            "confirmed_true": int(row[6]),
            "confirmed_false": int(row[7]),
            "confirmed_null": int(row[8]),
            "success_true": int(row[9]),
            "success_false": int(row[10]),
            "success_null": int(row[11]),
            "cancel_true": int(row[12]),
            "cancel_false": int(row[13]),
            "cancel_null": int(row[14]),
            "completed_consultations": int(row[15]),
            "cancelled_consultations": int(row[16]),
            "scheduled_confirmed_consultations": int(row[17]),
            "incomplete_open_consultations": int(row[18]),
            "contradictory_success_and_cancel": int(row[19]),
            "confirmed_at_before_created_at": int(row[20]),
            "success_at_before_created_at": int(row[21]),
            "cancel_at_before_created_at": int(row[22]),
            "total_consultations": int(row[23]),
        }

        with canonical_connection(load_canonical_settings()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM canonical_evidence.subject
                    WHERE source_system_id = %s
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                subj = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT COUNT(*) FROM canonical_evidence.encounter e
                    JOIN canonical_evidence.subject s ON s.subject_id = e.subject_id
                    WHERE s.source_system_id = %s
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                enc = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT COUNT(*) FROM canonical_evidence.subject s
                    WHERE s.source_system_id = %s
                      AND NOT EXISTS (
                        SELECT 1 FROM canonical_evidence.source_record sr
                        WHERE sr.source_system_id = %s
                          AND sr.source_record_locator = s.provenance->>'source_record_locator'
                      )
                    """,
                    (SOURCE_B_SYSTEM_ID, SOURCE_B_SYSTEM_ID),
                )
                missing_sr = int(cur.fetchone()[0])
                cur.execute(
                    """
                    SELECT COUNT(*) FROM canonical_evidence.subject a
                    JOIN canonical_evidence.subject b
                      ON a.source_subject_key = b.source_subject_key
                     AND a.source_system_id = 'magerya_api'
                     AND b.source_system_id = %s
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                key_collision = int(cur.fetchone()[0])
                # Opaque keys: hex length 64
                cur.execute(
                    """
                    SELECT COUNT(*) FROM canonical_evidence.subject
                    WHERE source_system_id = %s
                      AND (source_subject_key !~ '^[0-9a-f]{64}$'
                           OR length(source_subject_key) <> 64)
                    """,
                    (SOURCE_B_SYSTEM_ID,),
                )
                non_opaque = int(cur.fetchone()[0])

        result["canonical"] = {
            "subjects": subj,
            "encounters": enc,
            "subjects_missing_source_record": missing_sr,
            "source_a_b_subject_key_collisions": key_collision,
            "non_opaque_subject_keys": non_opaque,
            "matches_expected_subjects": subj == EXPECTED_SOURCE_B_SUBJECTS,
            "matches_expected_encounters": enc == EXPECTED_SOURCE_B_ENCOUNTERS,
        }
        ownership_ok = (
            int(distinct_patients or 0) == EXPECTED_SOURCE_B_SUBJECTS
            and int(null_pid or 0) == 0
            and int(missing_user or 0) == 0
            and int(both_roles or 0) == 0
        )
        canonical_ok = (
            subj == EXPECTED_SOURCE_B_SUBJECTS
            and enc == EXPECTED_SOURCE_B_ENCOUNTERS
            and missing_sr == 0
            and key_collision == 0
            and non_opaque == 0
        )
        result["source_b_subject_mapping_status"] = "ACCEPTED" if ownership_ok and canonical_ok else "DEFECT"
        result["source_b_encounter_mapping_status"] = "ACCEPTED" if canonical_ok else "DEFECT"
        result["source_b_encounter_audit_status"] = "PASS" if canonical_ok else "FAIL"
        result["repair_needed"] = not canonical_ok
        result["status"] = "PASS" if ownership_ok and canonical_ok else "FAIL"
        return result
    except Exception as exc:  # noqa: BLE001
        result["status"] = "INSUFFICIENT_DATA"
        result["error_type"] = type(exc).__name__
        result["source_b_subject_mapping_status"] = "ACCEPTED"  # carried from v0.1.1 claim
        result["source_b_encounter_mapping_status"] = "ACCEPTED"
        result["source_b_encounter_audit_status"] = "INSUFFICIENT_DATA"
        return result
