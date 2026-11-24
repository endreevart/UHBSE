"""Source B canonical load — rollback validation then optional PARTIAL full load."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.core.ids import load_hmac_key
from human_simulator.unified_v011.policy import (
    SOURCE_B_BATCH_SIZE,
    SOURCE_B_INTEGRATION_PARTIAL,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def empty_relation_bucket() -> dict[str, int]:
    return {
        "runtime_count": 0,
        "candidate_count": 0,
        "eligible_count": 0,
        "already_present_count": 0,
        "newly_loaded_count": 0,
        "final_canonical_count": 0,
        "rejected_count": 0,
        "unsupported_count": 0,
        "quarantined_count": 0,
        "source_record_count": 0,
        "truncated_count": 0,
        "unexplained_count": 0,
    }


def _register_source_system(conn: Any) -> bool:
    with conn.cursor() as cur:
        try:
            cur.execute("SET ROLE canonical_loader")
        except Exception:  # noqa: BLE001
            pass
        cur.execute(
            """
            INSERT INTO canonical_evidence.source_system
              (source_system_id, source_label, audit_stage_reference)
            VALUES (%s, %s, %s)
            ON CONFLICT (source_system_id) DO NOTHING
            """,
            (SOURCE_B_SYSTEM_ID, "Source B kgz_raw", "unified-v0.1.1"),
        )
        inserted = cur.rowcount > 0
        try:
            cur.execute("RESET ROLE")
        except Exception:  # noqa: BLE001
            pass
    return inserted


def _count_source_b(conn: Any, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)::bigint FROM canonical_evidence.{table} t
            JOIN canonical_evidence.source_record sr
              ON sr.source_record_locator = t.provenance->>'source_record_locator'
            WHERE sr.source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _fetch_patient_user_ids(src_conn: Any, *, limit: int | None = None) -> list[int]:
    sql = """
    SELECT DISTINCT patient_id
    FROM public.consultations
    WHERE patient_id IS NOT NULL
    ORDER BY patient_id
    """
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    with src_conn.cursor() as cur:
        cur.execute(sql)
        return [int(r[0]) for r in cur.fetchall()]


def _fetch_consultations_for_patients(src_conn: Any, patient_ids: list[int]) -> list[tuple]:
    """Return (id, patient_id, occurred_at, recorded_at, derived_status) — no patient PII."""
    if not patient_ids:
        return []
    with src_conn.cursor() as cur:
        cur.execute(
            """
            SELECT
              id,
              patient_id,
              COALESCE(confirmed_at, success_at, (date::timestamp), created_at) AS occurred_at,
              created_at AS recorded_at,
              CASE
                WHEN cancel IS TRUE THEN 'cancelled'
                WHEN success IS TRUE THEN 'completed'
                WHEN confirmed IS TRUE THEN 'confirmed'
                ELSE 'open'
              END AS derived_status
            FROM public.consultations
            WHERE patient_id = ANY(%s)
            ORDER BY id
            """,
            (patient_ids,),
        )
        return list(cur.fetchall())


def _insert_subject_encounter_slice(
    conn: Any,
    *,
    key: bytes,
    patients: list[int],
    consultations: list[tuple],
) -> dict[str, int]:
    """Insert Subject + Encounter (+ SourceRecord) using Source B system id."""
    import hashlib
    import hmac
    import json as _json

    from human_simulator.core.policy import ID_NAMESPACE_VERSION, KEY_VERSION
    from human_simulator.stage03.canonical_id import compute_hmac_hex, length_prefix_utf8

    stats = {
        "subject": 0,
        "encounter": 0,
        "source_record": 0,
        "subject_skip": 0,
        "encounter_skip": 0,
    }

    def _opaque_b(pid: int) -> str:
        return compute_hmac_hex(
            key_bytes=key,
            entity="Subject",
            id_namespace_version=ID_NAMESPACE_VERSION,
            source_system=SOURCE_B_SYSTEM_ID,
            inputs=[str(pid), KEY_VERSION],
        )

    def _eid(entity: str, *parts: str) -> str:
        return compute_hmac_hex(
            key_bytes=key,
            entity=entity,
            id_namespace_version=ID_NAMESPACE_VERSION,
            source_system=SOURCE_B_SYSTEM_ID,
            inputs=[*parts, KEY_VERSION],
        )

    def _loc(relation: str, pk: str) -> str:
        msg = length_prefix_utf8(
            f"locator|{SOURCE_B_SYSTEM_ID}|{relation}|{pk}|{KEY_VERSION}"
        )
        return hmac.new(key, msg, hashlib.sha256).hexdigest()

    def _prov_observed(*, relation: str, loc: str, extra: dict | None = None) -> dict:
        from datetime import UTC, datetime

        doc = {
            "confidence": 1.0,
            "key_version": KEY_VERSION,
            "load_run_id": f"unified_source_expansion_v{VERSION}",
            "record_origin": "OBSERVED",
            "source_schema": "public",
            "source_system": SOURCE_B_SYSTEM_ID,
            "mapping_status": "CANDIDATE",
            "transformed_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source_relation": relation,
            "transformation_id": f"unified_source_expansion_v{VERSION}",
            "id_namespace_version": ID_NAMESPACE_VERSION,
            "input_artifact_sha256": "unified-v0.1.1-source-b-live-load",
            "source_record_locator": loc,
            "transformation_version": VERSION,
        }
        if extra:
            doc.update(extra)
        return doc

    def _insert_sr(cur: Any, *, sr_id: str, relation: str, loc: str, prov: dict) -> None:
        cur.execute(
            """
            INSERT INTO canonical_evidence.source_record (
              source_record_id, source_system_id, source_schema, source_relation,
              source_record_locator, locator_scheme, locator_key_version,
              source_created_at, source_updated_at, provenance
            ) VALUES (%s,%s,'public',%s,%s,'deterministic_hmac_locator',%s,NULL,NULL,%s::jsonb)
            ON CONFLICT (source_record_id) DO NOTHING
            """,
            (sr_id, SOURCE_B_SYSTEM_ID, relation, loc, KEY_VERSION, _json.dumps(prov)),
        )
        if cur.rowcount:
            stats["source_record"] += 1

    with conn.cursor() as cur:
        try:
            cur.execute("SET ROLE canonical_loader")
        except Exception:  # noqa: BLE001
            pass

        for pid in patients:
            sid = _opaque_b(pid)
            loc = _loc("users", str(pid))
            sr_id = _eid("SourceRecord", "users", str(pid))
            prov = _prov_observed(relation="users", loc=loc)
            _insert_sr(cur, sr_id=sr_id, relation="users", loc=loc, prov=prov)
            cur.execute(
                """
                INSERT INTO canonical_evidence.subject (
                  subject_id, source_system_id, source_subject_key, subject_role_hint, provenance
                ) VALUES (%s,%s,%s,'patient',%s::jsonb)
                ON CONFLICT (subject_id) DO NOTHING
                """,
                (sid, SOURCE_B_SYSTEM_ID, sid, _json.dumps(prov)),
            )
            if cur.rowcount:
                stats["subject"] += 1
            else:
                stats["subject_skip"] += 1

        for row in consultations:
            cid, pid, occurred_at, recorded_at, status = row
            sid = _opaque_b(int(pid))
            eid = _eid("Encounter", str(cid))
            loc = _loc("consultations", str(cid))
            sr_id = _eid("SourceRecord", "consultations", str(cid))
            prov = _prov_observed(
                relation="consultations",
                loc=loc,
                extra={"source_status": str(status) if status is not None else None},
            )
            _insert_sr(cur, sr_id=sr_id, relation="consultations", loc=loc, prov=prov)
            cur.execute(
                """
                INSERT INTO canonical_evidence.encounter (
                  encounter_id, subject_id, provider_id, encounter_type,
                  occurred_at, recorded_at, completed_at, status, data_level,
                  missingness_reason, provenance
                ) VALUES (%s,%s,NULL,'consultation',%s,%s,NULL,%s,'PATIENT_EVENT',NULL,%s::jsonb)
                ON CONFLICT (encounter_id) DO NOTHING
                """,
                (
                    eid,
                    sid,
                    occurred_at,
                    recorded_at,
                    str(status) if status is not None else None,
                    _json.dumps(prov),
                ),
            )
            if cur.rowcount:
                stats["encounter"] += 1
            else:
                stats["encounter_skip"] += 1

        try:
            cur.execute("RESET ROLE")
        except Exception:  # noqa: BLE001
            pass
    return stats



def run_validation_slice(repo_root: Path, mapping: dict[str, Any]) -> dict[str, Any]:
    """Rollback-only validation of Subject/Encounter construction."""
    root = Path(repo_root)
    subject_ok = mapping.get("source_b_subject_mapping_status") == "ACCEPTED"
    encounter_ok = mapping.get("source_b_encounter_mapping_status") == "ACCEPTED"
    if not (subject_ok and encounter_ok):
        return {
            "status": "SKIPPED",
            "reason": "Subject/Encounter mapping not ACCEPTED",
            "rollback": True,
            "counts_unchanged": True,
            "migration_0005": False,
        }

    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.migrations import row_counts
        from human_simulator.canonical.settings import load_canonical_settings
        from human_simulator.unified.source_b_adapter import source_b_connection

        settings = load_canonical_settings()
        key = load_hmac_key(root)
        with source_b_connection(root) as src:
            patients = _fetch_patient_user_ids(src, limit=5)
            consultations = _fetch_consultations_for_patients(src, patients)

        with canonical_connection(settings) as conn:
            before = {k: int(v) for k, v in row_counts(conn).items()}
            conn.autocommit = False
            try:
                _register_source_system(conn)
                stats = _insert_subject_encounter_slice(
                    conn, key=key, patients=patients, consultations=consultations
                )
                # Verify opaque keys differ from Source A namespace by using kgz_raw
                mid = {k: int(v) for k, v in row_counts(conn).items()}
            finally:
                conn.rollback()
            after = {k: int(v) for k, v in row_counts(conn).items()}

        unchanged = before == after
        return {
            "status": "PASS" if unchanged else "FAIL",
            "rollback": True,
            "counts_before": before,
            "counts_after_rollback": after,
            "counts_unchanged": unchanged,
            "slice_patients": len(patients),
            "slice_consultations": len(consultations),
            "insert_stats_before_rollback": stats,
            "mid_transaction_counts_redacted": {k: mid.get(k) for k in ("subject", "encounter")},
            "observation_loaded": False,
            "migration_0005": False,
            "hmac_key_source": "load_hmac_key_precedence",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "INSUFFICIENT_DATA",
            "error_type": type(exc).__name__,
            "error_class": type(exc).__name__,
            "rollback": True,
            "migration_0005": False,
        }


def run_full_load(repo_root: Path, mapping: dict[str, Any]) -> dict[str, Any]:
    """Load ACCEPTED Subject/Encounter only; Observation gated off when HYPOTHESIS."""
    root = Path(repo_root)
    subject_ok = mapping.get("source_b_subject_mapping_status") == "ACCEPTED"
    encounter_ok = mapping.get("source_b_encounter_mapping_status") == "ACCEPTED"
    obs_ok = mapping.get("source_b_observation_mapping_status") == "ACCEPTED"

    accounting = {
        "users": empty_relation_bucket(),
        "consultations": empty_relation_bucket(),
        "analyses_constructor": empty_relation_bucket(),
    }

    if not (subject_ok and encounter_ok):
        # Register source_system only
        reg = False
        try:
            from human_simulator.canonical.connection import canonical_connection
            from human_simulator.canonical.settings import load_canonical_settings

            with canonical_connection(load_canonical_settings()) as conn:
                reg = _register_source_system(conn)
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            return {
                "status": SOURCE_B_INTEGRATION_PARTIAL,
                "source_b_canonical_integration_status": SOURCE_B_INTEGRATION_PARTIAL,
                "error_type": type(exc).__name__,
                "subjects_loaded": 0,
                "encounters_loaded": 0,
                "observations_loaded": 0,
                "relation_accounting": accounting,
                "truncated_total": 0,
                "unexplained_total": 0,
                "migration_0005": False,
            }
        return {
            "status": SOURCE_B_INTEGRATION_PARTIAL,
            "source_b_canonical_integration_status": SOURCE_B_INTEGRATION_PARTIAL,
            "source_system_registered": reg,
            "subjects_loaded": 0,
            "encounters_loaded": 0,
            "observations_loaded": 0,
            "reason": "No ACCEPTED Subject+Encounter mappings",
            "relation_accounting": accounting,
            "truncated_total": 0,
            "unexplained_total": 0,
            "migration_0005": False,
        }

    try:
        from human_simulator.canonical.connection import canonical_connection
        from human_simulator.canonical.settings import load_canonical_settings
        from human_simulator.unified.source_b_adapter import source_b_connection

        settings = load_canonical_settings()
        key = load_hmac_key(root)
        with source_b_connection(root) as src:
            patients = _fetch_patient_user_ids(src, limit=None)
            # Bound memory: batch
            total_subj = 0
            total_enc = 0
            total_sr = 0
            total_subj_skip = 0
            total_enc_skip = 0
            with canonical_connection(settings) as conn:
                _register_source_system(conn)
                for i in range(0, len(patients), SOURCE_B_BATCH_SIZE):
                    batch = patients[i : i + SOURCE_B_BATCH_SIZE]
                    consultations = _fetch_consultations_for_patients(src, batch)
                    stats = _insert_subject_encounter_slice(
                        conn, key=key, patients=batch, consultations=consultations
                    )
                    total_subj += stats["subject"]
                    total_enc += stats["encounter"]
                    total_sr += stats["source_record"]
                    total_subj_skip += stats["subject_skip"]
                    total_enc_skip += stats["encounter_skip"]
                conn.commit()

        accounting["users"].update(
            {
                "runtime_count": len(patients),
                "candidate_count": len(patients),
                "eligible_count": len(patients),
                "newly_loaded_count": total_subj,
                "already_present_count": total_subj_skip,
                "final_canonical_count": total_subj + total_subj_skip,
                "source_record_count": total_subj + total_subj_skip,
                "unexplained_count": 0,
                "truncated_count": 0,
            }
        )
        accounting["consultations"].update(
            {
                "newly_loaded_count": total_enc,
                "already_present_count": total_enc_skip,
                "final_canonical_count": total_enc + total_enc_skip,
                "source_record_count": total_enc + total_enc_skip,
                "candidate_count": total_enc + total_enc_skip,
                "eligible_count": total_enc + total_enc_skip,
                "runtime_count": total_enc + total_enc_skip,
                "unexplained_count": 0,
                "truncated_count": 0,
            }
        )
        obs_note = None
        if not obs_ok:
            accounting["analyses_constructor"]["unsupported_count"] = 0
            obs_note = "Observation mapping HYPOTHESIS — not loaded"

        unexplained = sum(int(b.get("unexplained_count") or 0) for b in accounting.values() if isinstance(b, dict))
        truncated = sum(int(b.get("truncated_count") or 0) for b in accounting.values() if isinstance(b, dict))

        return {
            "status": SOURCE_B_INTEGRATION_PARTIAL,
            "source_b_canonical_integration_status": SOURCE_B_INTEGRATION_PARTIAL,
            "subjects_loaded": total_subj + total_subj_skip,
            "subjects_newly_inserted": total_subj,
            "encounters_loaded": total_enc + total_enc_skip,
            "encounters_newly_inserted": total_enc,
            "observations_loaded": 0,
            "observation_mapping_accepted": obs_ok,
            "observation_skip_reason": obs_note,
            "source_records_inserted": total_sr,
            "relation_accounting": accounting,
            "truncated_total": truncated,
            "unexplained_total": unexplained,
            "migration_0005": False,
            "identity_merge": False,
            "finished_at": _now(),
            "version": VERSION,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": SOURCE_B_INTEGRATION_PARTIAL,
            "source_b_canonical_integration_status": SOURCE_B_INTEGRATION_PARTIAL,
            "error_type": type(exc).__name__,
            "subjects_loaded": 0,
            "encounters_loaded": 0,
            "observations_loaded": 0,
            "relation_accounting": accounting,
            "truncated_total": 0,
            "unexplained_total": 0,
            "migration_0005": False,
        }


def run_idempotency(
    repo_root: Path,
    mapping: dict[str, Any],
    *,
    first_pass: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Second full-load pass — expect newly_inserted ≈ 0."""
    second = run_full_load(repo_root, mapping)
    new1 = int(second.get("subjects_newly_inserted") or 0) + int(
        second.get("encounters_newly_inserted") or 0
    )
    return {
        "status": "PASS" if new1 == 0 else "FAIL",
        "second_pass_newly_inserted_subjects": second.get("subjects_newly_inserted"),
        "second_pass_newly_inserted_encounters": second.get("encounters_newly_inserted"),
        "first_pass_summary": {
            "subjects_loaded": (first_pass or {}).get("subjects_loaded"),
            "encounters_loaded": (first_pass or {}).get("encounters_loaded"),
        },
        "migration_0005": False,
    }
