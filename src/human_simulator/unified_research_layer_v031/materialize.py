"""Materialize private Parquet research datasets (opaque IDs; no raw direct identifiers)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.core.ids import entity_id, load_hmac_key, opaque_subject_key
from human_simulator.core.policy import ID_NAMESPACE_VERSION, KEY_VERSION
from human_simulator.stage03.canonical_id import compute_hmac_hex
from human_simulator.unified_research_layer_v031.policy import (
    MATERIALIZED_DIR,
    REQUIRED_DATASETS,
    VERSION,
)

BATCH = 50_000


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _research_id(key: bytes, entity: str, source_system: str, *parts: str) -> str:
    return compute_hmac_hex(
        key_bytes=key,
        entity=entity,
        id_namespace_version=ID_NAMESPACE_VERSION,
        source_system=source_system,
        inputs=[*parts, KEY_VERSION],
    )


def _write_parquet(path: Path, table: pa.Table) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return table.num_rows


def _empty_table(schema: pa.Schema) -> pa.Table:
    return pa.Table.from_arrays(
        [pa.array([], type=f.type) for f in schema], schema=schema
    )


def _stream_query(conn: Any, sql: str, params: tuple | None = None):
    """Fetch in batches without named cursors (works with autocommit connections)."""
    with conn.cursor() as cur:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        while True:
            rows = cur.fetchmany(BATCH)
            if not rows:
                break
            yield rows


def materialize_all(
    *,
    root: Path,
    conn_canonical: Any,
    conn_a: Any | None,
    conn_b: Any | None,
    canonical_inv: dict[str, Any],
) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / MATERIALIZED_DIR
    out.mkdir(parents=True, exist_ok=True)
    key = load_hmac_key(root)
    counts: dict[str, int] = {}
    reject_reasons: dict[str, list[str]] = {}
    domain_proof: dict[str, Any] = {}

    # ---- subjects from canonical ----
    subj_rows: list[dict[str, Any]] = []
    with conn_canonical.cursor() as cur:
        cur.execute("SET search_path TO canonical_evidence, public")
        cur.execute("SET default_transaction_read_only = on")
        cur.execute(
            """
            SELECT subject_id, source_system_id, source_subject_key, subject_role_hint, provenance
            FROM subject
            """
        )
        for sid, ss, skey, role, prov in cur:
            subj_rows.append(
                {
                    "research_entity_id": sid,
                    "source_system": ss,
                    "source_scoped_subject_id": sid,
                    "source_record_locator": (prov or {}).get("source_record_locator"),
                    "encounter_id": None,
                    "event_id": None,
                    "event_time": None,
                    "timestamp_certainty": "NA",
                    "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                    "data_quality_flags": json.dumps(["canonical_subject"]),
                    "provenance": json.dumps(
                        {
                            "record_origin": (prov or {}).get("record_origin"),
                            "transformation_id": (prov or {}).get("transformation_id"),
                            "source_relation": (prov or {}).get("source_relation"),
                            "id_namespace_version": (prov or {}).get("id_namespace_version"),
                        }
                    ),
                    "privacy_classification": "OPAQUE_IDENTIFIER",
                    "subject_role_hint": role,
                }
            )
    counts["research_subject"] = _write_parquet(
        out / "research_subject.parquet",
        pa.Table.from_pylist(subj_rows)
        if subj_rows
        else _empty_table(
            pa.schema(
                [
                    ("research_entity_id", pa.string()),
                    ("source_system", pa.string()),
                    ("source_scoped_subject_id", pa.string()),
                ]
            )
        ),
    )
    domain_proof["subjects"] = {
        "relation_source": "canonical_evidence.subject",
        "exact_eligible": canonical_inv.get("n_subjects"),
        "materialized": counts["research_subject"],
        "subject_ownership_path": "canonical.subject_id",
    }

    # subject_id lookup by opaque key for A patient_id mapping
    a_subject_by_key = {
        r["source_scoped_subject_id"]: r["research_entity_id"]
        for r in subj_rows
        if r["source_system"] == "magerya_api"
    }
    # actually both fields are subject_id; rebuild map source_subject_key -> subject_id
    a_key_to_sid: dict[str, str] = {}
    b_key_to_sid: dict[str, str] = {}
    with conn_canonical.cursor() as cur:
        cur.execute(
            "SELECT subject_id, source_system_id, source_subject_key FROM canonical_evidence.subject"
        )
        for sid, ss, skey in cur:
            if ss == "magerya_api":
                a_key_to_sid[skey] = sid
            elif ss == "kgz_raw":
                b_key_to_sid[skey] = sid

    # ---- encounters ----
    enc_rows: list[dict[str, Any]] = []
    enc_id_set: set[str] = set()
    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT e.encounter_id, e.subject_id, s.source_system_id, e.encounter_type,
                   e.occurred_at, e.recorded_at, e.status, e.provenance
            FROM canonical_evidence.encounter e
            JOIN canonical_evidence.subject s ON s.subject_id = e.subject_id
            """
        )
        for eid, sid, ss, etype, occurred, recorded, status, prov in cur:
            enc_id_set.add(eid)
            enc_rows.append(
                {
                    "research_entity_id": eid,
                    "source_system": ss,
                    "source_scoped_subject_id": sid,
                    "source_record_locator": (prov or {}).get("source_record_locator"),
                    "encounter_id": eid,
                    "event_id": None,
                    "event_time": occurred.isoformat() if occurred else None,
                    "timestamp_certainty": "OBSERVED" if occurred else "UNKNOWN",
                    "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                    "data_quality_flags": json.dumps(["canonical_encounter"]),
                    "provenance": json.dumps(
                        {
                            "record_origin": (prov or {}).get("record_origin"),
                            "source_relation": (prov or {}).get("source_relation"),
                        }
                    ),
                    "privacy_classification": "OPAQUE_IDENTIFIER",
                    "encounter_type": etype,
                    "recorded_at": recorded.isoformat() if recorded else None,
                    "status": status,
                }
            )
    counts["research_encounter"] = _write_parquet(
        out / "research_encounter.parquet", pa.Table.from_pylist(enc_rows)
    )
    domain_proof["encounters"] = {
        "relation_source": "canonical_evidence.encounter",
        "exact_eligible": canonical_inv.get("n_encounters"),
        "materialized": counts["research_encounter"],
        "subject_ownership_path": "encounter.subject_id -> subject",
        "encounter_ownership_path": "self",
        "event_timestamp_source": "occurred_at|recorded_at",
    }

    # ---- observations (no raw free-text names; lab values allowed privately) ----
    obs_batches: list[pa.Table] = []
    obs_n = 0
    obs_sql = """
        SELECT o.observation_id, o.subject_id, s.source_system_id, o.encounter_id,
               o.observed_at, o.specimen_collected_at, o.result_available_at, o.recorded_at,
               o.status, o.raw_code, o.raw_unit, o.normalized_unit, o.abnormal_flag,
               o.provenance
        FROM canonical_evidence.observation o
        JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
    """
    for rows in _stream_query(conn_canonical, obs_sql):
        batch = []
        for (
            oid,
            sid,
            ss,
            enc,
            observed,
            specimen,
            result_at,
            recorded,
            status,
            raw_code,
            raw_unit,
            norm_unit,
            abnormal,
            prov,
        ) in rows:
            event_time = observed or specimen or result_at or recorded
            batch.append(
                {
                    "research_entity_id": oid,
                    "source_system": ss,
                    "source_scoped_subject_id": sid,
                    "source_record_locator": (prov or {}).get("source_record_locator"),
                    "encounter_id": enc,
                    "event_id": oid,
                    "event_time": event_time.isoformat() if event_time else None,
                    "timestamp_certainty": "OBSERVED" if observed else "DERIVED_FALLBACK",
                    "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                    "data_quality_flags": json.dumps(["canonical_observation"]),
                    "provenance": json.dumps(
                        {
                            "record_origin": (prov or {}).get("record_origin"),
                            "source_relation": (prov or {}).get("source_relation"),
                        }
                    ),
                    "privacy_classification": "CLINICAL_CODE_VALUE_PRIVATE",
                    "raw_code": raw_code,
                    "raw_unit": raw_unit,
                    "normalized_unit": norm_unit,
                    "abnormal_flag": abnormal,
                    "status": status,
                    "observed_at": observed.isoformat() if observed else None,
                    "specimen_collected_at": specimen.isoformat() if specimen else None,
                    "result_available_at": result_at.isoformat() if result_at else None,
                    "recorded_at": recorded.isoformat() if recorded else None,
                }
            )
        if batch:
            t = pa.Table.from_pylist(batch)
            obs_batches.append(t)
            obs_n += t.num_rows
    if obs_batches:
        obs_table = pa.concat_tables(obs_batches, promote_options="default")
    else:
        obs_table = _empty_table(pa.schema([("research_entity_id", pa.string())]))
    counts["research_observation"] = _write_parquet(
        out / "research_observation.parquet", obs_table
    )
    domain_proof["observations"] = {
        "relation_source": "canonical_evidence.observation",
        "exact_eligible": canonical_inv.get("n_observations"),
        "materialized": counts["research_observation"],
        "subject_ownership_path": "observation.subject_id",
        "encounter_ownership_path": "observation.encounter_id",
        "event_timestamp_source": "observed_at>specimen>result>recorded",
        "note": "raw_value omitted from observation header; components hold values",
    }

    # ---- observation components ----
    comp_batches: list[pa.Table] = []
    comp_n = 0
    comp_sql = """
        SELECT c.component_id, c.observation_id, o.subject_id, s.source_system_id,
               o.encounter_id, o.observed_at, c.raw_code, c.raw_unit, c.normalized_unit,
               c.numeric_value, c.abnormal_flag, c.sequence_order, c.provenance,
               (c.text_value IS NOT NULL) AS has_text_value
        FROM canonical_evidence.observation_component c
        JOIN canonical_evidence.observation o ON o.observation_id = c.observation_id
        JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
    """
    for rows in _stream_query(conn_canonical, comp_sql):
        batch = []
        for (
            cid,
            oid,
            sid,
            ss,
            enc,
            observed,
            raw_code,
            raw_unit,
            norm_unit,
            num_val,
            abnormal,
            seq,
            prov,
            has_text,
        ) in rows:
            batch.append(
                {
                    "research_entity_id": cid,
                    "source_system": ss,
                    "source_scoped_subject_id": sid,
                    "source_record_locator": (prov or {}).get("source_record_locator"),
                    "encounter_id": enc,
                    "event_id": oid,
                    "event_time": observed.isoformat() if observed else None,
                    "timestamp_certainty": "INHERITED_FROM_OBSERVATION",
                    "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                    "data_quality_flags": json.dumps(
                        ["canonical_component"]
                        + (["text_value_present_excluded"] if has_text else [])
                    ),
                    "provenance": json.dumps(
                        {
                            "record_origin": (prov or {}).get("record_origin"),
                            "source_relation": (prov or {}).get("source_relation"),
                        }
                    ),
                    "privacy_classification": "CLINICAL_CODE_VALUE_PRIVATE",
                    "observation_id": oid,
                    "raw_code": raw_code,
                    "raw_unit": raw_unit,
                    "normalized_unit": norm_unit,
                    "numeric_value": float(num_val) if num_val is not None else None,
                    "abnormal_flag": abnormal,
                    "sequence_order": seq,
                }
            )
        if batch:
            t = pa.Table.from_pylist(batch)
            comp_batches.append(t)
            comp_n += t.num_rows
    if comp_batches:
        comp_table = pa.concat_tables(comp_batches, promote_options="default")
    else:
        comp_table = _empty_table(pa.schema([("research_entity_id", pa.string())]))
    counts["research_observation_component"] = _write_parquet(
        out / "research_observation_component.parquet", comp_table
    )
    domain_proof["observation_components"] = {
        "relation_source": "canonical_evidence.observation_component",
        "exact_eligible": canonical_inv.get("n_observation_components"),
        "materialized": counts["research_observation_component"],
        "note": "text_value excluded from parquet to reduce free-text leakage risk",
    }

    # ---- medications from Source A ----
    med_rows: list[dict[str, Any]] = []
    med_rejected = 0
    if conn_a is not None:
        with conn_a.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(
                """
                SELECT id, patient_id, medicine_id, appointment_date, status, created, modified
                FROM magerya_api.diagnosis_medicineappointments
                """
            )
            for mid, pid, medicine_id, appt, status, created, modified in cur:
                skey = opaque_subject_key(key, int(pid))
                sid = a_key_to_sid.get(skey)
                if sid is None:
                    med_rejected += 1
                    continue
                rid = _research_id(
                    key, "ResearchMedication", "magerya_api", str(mid)
                )
                event_time = appt or created
                med_rows.append(
                    {
                        "research_entity_id": rid,
                        "source_system": "magerya_api",
                        "source_scoped_subject_id": sid,
                        "source_record_locator": _research_id(
                            key, "Locator", "magerya_api", "diagnosis_medicineappointments", str(mid)
                        ),
                        "encounter_id": None,
                        "event_id": rid,
                        "event_time": event_time.isoformat() if event_time else None,
                        "timestamp_certainty": "OBSERVED" if appt else "TECHNICAL_CREATED",
                        "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                        "data_quality_flags": json.dumps(
                            [
                                "medication_appointment_event",
                                "not_proven_clinical_administration",
                            ]
                        ),
                        "provenance": json.dumps(
                            {
                                "record_origin": "OBSERVED",
                                "source_relation": "diagnosis_medicineappointments",
                                "transformation_id": "unified_research_layer_v031",
                                "transformation_version": VERSION,
                            }
                        ),
                        "privacy_classification": "OPAQUE_IDENTIFIER",
                        "medicine_ref_id": _research_id(
                            key, "MedicineRef", "magerya_api", str(medicine_id)
                        ),
                        "status": status,
                        "administration_claim": "NOT_CLAIMED",
                    }
                )
    counts["research_medication_record"] = _write_parquet(
        out / "research_medication_record.parquet",
        pa.Table.from_pylist(med_rows)
        if med_rows
        else _empty_table(pa.schema([("research_entity_id", pa.string())])),
    )
    reject_reasons["medications"] = (
        [f"unmapped_patient={med_rejected}"] if med_rejected else []
    )
    domain_proof["medications"] = {
        "relation_source": "magerya_api.diagnosis_medicineappointments",
        "exact_eligible": len(med_rows) + med_rejected,
        "materialized": counts["research_medication_record"],
        "rejected": med_rejected,
        "subject_ownership_path": "patient_id -> opaque_subject_key -> canonical.subject",
        "encounter_ownership_path": "none_direct",
        "event_timestamp_source": "appointment_date|created",
        "administration_claim": "NOT_CLAIMED",
        "source_b_structured_medications": "ABSENT",
    }

    # ---- diagnoses: no structured patient facts ----
    counts["research_diagnosis"] = _write_parquet(
        out / "research_diagnosis.parquet",
        _empty_table(
            pa.schema(
                [
                    ("research_entity_id", pa.string()),
                    ("source_system", pa.string()),
                    ("source_scoped_subject_id", pa.string()),
                    ("semantic_tier", pa.string()),
                ]
            )
        ),
    )
    counts["research_condition_history"] = _write_parquet(
        out / "research_condition_history.parquet",
        _empty_table(
            pa.schema(
                [
                    ("research_entity_id", pa.string()),
                    ("source_system", pa.string()),
                    ("source_scoped_subject_id", pa.string()),
                ]
            )
        ),
    )
    domain_proof["diagnoses"] = {
        "relation_source": "magerya_api.diagnosis_diagnosis",
        "catalog_rows_exact": None,  # filled by orchestrator
        "patient_diagnosis_facts_materialized": 0,
        "materialized": 0,
        "unresolved_reason": (
            "diagnosis_diagnosis is REFERENCE_CATALOG (name/description only); "
            "no structured patient/encounter-linked diagnosis fact table confirmed"
        ),
        "source_b_structured_diagnoses": "ABSENT_AFTER_MULTI_SCHEMA_INVENTORY",
        "support_status": "UNRESOLVED_RETAINED",
    }

    # ---- recommendations ----
    rec_rows: list[dict[str, Any]] = []
    rec_rejected = 0
    if conn_a is not None:
        with conn_a.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            # join appointment -> patient for subject ownership
            cur.execute(
                """
                SELECT r.id, r.appointment_id, a.patient_id, r.created, r.modified
                FROM magerya_api.document_recommendation r
                LEFT JOIN magerya_api.appointment_appointment a ON a.id = r.appointment_id
                """
            )
            for rid0, appt_id, pid, created, modified in cur:
                if pid is None:
                    rec_rejected += 1
                    continue
                skey = opaque_subject_key(key, int(pid))
                sid = a_key_to_sid.get(skey)
                if sid is None:
                    rec_rejected += 1
                    continue
                rid = _research_id(key, "ResearchRecommendation", "magerya_api", str(rid0))
                enc = _research_id(key, "Encounter", "magerya_api", str(appt_id)) if appt_id else None
                # prefer canonical encounter if present — use opaque from entity_id pattern
                # appointments already in canonical; encounter_id is entity_id(Encounter,...)
                from human_simulator.core.ids import entity_id as eid_fn

                can_enc = eid_fn(key, "Encounter", str(appt_id)) if appt_id else None
                rec_rows.append(
                    {
                        "research_entity_id": rid,
                        "source_system": "magerya_api",
                        "source_scoped_subject_id": sid,
                        "source_record_locator": _research_id(
                            key, "Locator", "magerya_api", "document_recommendation", str(rid0)
                        ),
                        "encounter_id": can_enc,
                        "event_id": rid,
                        "event_time": created.isoformat() if created else None,
                        "timestamp_certainty": "TECHNICAL_CREATED",
                        "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                        "data_quality_flags": json.dumps(
                            ["patient_recommendation_document_ref", "body_excluded"]
                        ),
                        "provenance": json.dumps(
                            {
                                "record_origin": "OBSERVED",
                                "source_relation": "document_recommendation",
                                "transformation_id": "unified_research_layer_v031",
                                "transformation_version": VERSION,
                            }
                        ),
                        "privacy_classification": "REFERENCE_ONLY_NO_BODY",
                        "recommendation_class": "PATIENT_EVENT",
                        "catalog_vs_patient": "PATIENT_SPECIFIC",
                    }
                )
    if conn_b is not None:
        with conn_b.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(
                """
                SELECT ru.id, ru.consultations_id, c.patient_id, ru.created_at, ru.is_active
                FROM quest_digital.recommendations_user ru
                LEFT JOIN public.consultations c ON c.id = ru.consultations_id
                """
            )
            for rid0, cons_id, uid, created, active in cur:
                if uid is None:
                    rec_rejected += 1
                    continue
                skey = compute_hmac_hex(
                    key_bytes=key,
                    entity="Subject",
                    id_namespace_version=ID_NAMESPACE_VERSION,
                    source_system="kgz_raw",
                    inputs=[str(uid), KEY_VERSION],
                )
                sid = b_key_to_sid.get(skey)
                if sid is None:
                    rec_rejected += 1
                    continue
                rid = _research_id(key, "ResearchRecommendation", "kgz_raw", str(rid0))
                from human_simulator.core.ids import entity_id as eid_fn

                # B encounters use kgz source in canonical — lookup via consultation id HMAC
                can_enc = compute_hmac_hex(
                    key_bytes=key,
                    entity="Encounter",
                    id_namespace_version=ID_NAMESPACE_VERSION,
                    source_system="kgz_raw",
                    inputs=[str(cons_id), KEY_VERSION],
                ) if cons_id else None
                rec_rows.append(
                    {
                        "research_entity_id": rid,
                        "source_system": "kgz_raw",
                        "source_scoped_subject_id": sid,
                        "source_record_locator": _research_id(
                            key, "Locator", "kgz_raw", "recommendations_user", str(rid0)
                        ),
                        "encounter_id": can_enc if can_enc in enc_id_set else None,
                        "event_id": rid,
                        "event_time": created.isoformat() if created else None,
                        "timestamp_certainty": "OBSERVED" if created else "UNKNOWN",
                        "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                        "data_quality_flags": json.dumps(
                            [
                                "patient_recommendation_assignment",
                                "description_text_excluded",
                                f"is_active={bool(active)}",
                            ]
                        ),
                        "provenance": json.dumps(
                            {
                                "record_origin": "OBSERVED",
                                "source_relation": "recommendations_user",
                                "transformation_id": "unified_research_layer_v031",
                                "transformation_version": VERSION,
                            }
                        ),
                        "privacy_classification": "REFERENCE_ONLY_NO_BODY",
                        "recommendation_class": "PATIENT_EVENT",
                        "catalog_vs_patient": "PATIENT_SPECIFIC",
                    }
                )
    counts["research_recommendation"] = _write_parquet(
        out / "research_recommendation.parquet",
        pa.Table.from_pylist(rec_rows)
        if rec_rows
        else _empty_table(pa.schema([("research_entity_id", pa.string())])),
    )
    domain_proof["recommendations"] = {
        "relation_sources": [
            "magerya_api.document_recommendation",
            "quest_digital.recommendations_user",
        ],
        "catalog_excluded_from_patient_event_count": [
            "quest_digital.recommendations_list",
            "quest_digital.recommendations_category",
        ],
        "materialized_patient_events": counts["research_recommendation"],
        "rejected": rec_rejected,
        "body_text_included": False,
    }

    # ---- procedures ----
    proc_rows: list[dict[str, Any]] = []
    if conn_a is not None:
        with conn_a.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            for table, id_col in (
                ("diagnosis_proceduresresult", "procedures_id"),
                ("diagnosis_manipulationsresult", "manipulations_id"),
            ):
                cur.execute(
                    f"""
                    SELECT id, patient_id, appointment_date, status, created, {id_col}
                    FROM magerya_api.{table}
                    """
                )
                for pid_row in cur.fetchall():
                    rid0, pid, appt, status, created, ref_id = pid_row
                    skey = opaque_subject_key(key, int(pid))
                    sid = a_key_to_sid.get(skey)
                    if sid is None:
                        continue
                    rid = _research_id(key, "ResearchProcedure", "magerya_api", table, str(rid0))
                    event_time = appt or created
                    proc_rows.append(
                        {
                            "research_entity_id": rid,
                            "source_system": "magerya_api",
                            "source_scoped_subject_id": sid,
                            "source_record_locator": _research_id(
                                key, "Locator", "magerya_api", table, str(rid0)
                            ),
                            "encounter_id": None,
                            "event_id": rid,
                            "event_time": event_time.isoformat() if event_time else None,
                            "timestamp_certainty": "OBSERVED" if appt else "TECHNICAL_CREATED",
                            "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                            "data_quality_flags": json.dumps([f"source_table={table}"]),
                            "provenance": json.dumps(
                                {
                                    "record_origin": "OBSERVED",
                                    "source_relation": table,
                                    "transformation_id": "unified_research_layer_v031",
                                    "transformation_version": VERSION,
                                }
                            ),
                            "privacy_classification": "OPAQUE_IDENTIFIER",
                            "procedure_ref_id": _research_id(
                                key, "ProcedureRef", "magerya_api", str(ref_id)
                            ),
                            "status": status,
                        }
                    )
    counts["research_procedure"] = _write_parquet(
        out / "research_procedure.parquet",
        pa.Table.from_pylist(proc_rows)
        if proc_rows
        else _empty_table(pa.schema([("research_entity_id", pa.string())])),
    )
    domain_proof["procedures"] = {
        "relation_source": [
            "diagnosis_proceduresresult",
            "diagnosis_manipulationsresult",
        ],
        "materialized": counts["research_procedure"],
        "source_b_structured_procedures": "NOT_CLAIMED",
    }

    # ---- document references (no body/path/name) ----
    doc_rows: list[dict[str, Any]] = []
    if conn_b is not None:
        with conn_b.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(
                """
                SELECT id, user_id, document_type_id, created_at, private
                FROM public.documents
                """
            )
            for did, uid, dtype, created, priv in cur:
                if uid is None:
                    continue
                skey = compute_hmac_hex(
                    key_bytes=key,
                    entity="Subject",
                    id_namespace_version=ID_NAMESPACE_VERSION,
                    source_system="kgz_raw",
                    inputs=[str(uid), KEY_VERSION],
                )
                sid = b_key_to_sid.get(skey)
                if sid is None:
                    continue
                rid = _research_id(key, "ResearchDocument", "kgz_raw", str(did))
                doc_rows.append(
                    {
                        "research_entity_id": rid,
                        "source_system": "kgz_raw",
                        "source_scoped_subject_id": sid,
                        "source_record_locator": _research_id(
                            key, "Locator", "kgz_raw", "documents", str(did)
                        ),
                        "encounter_id": None,
                        "event_id": rid,
                        "event_time": created.isoformat() if created else None,
                        "timestamp_certainty": "TECHNICAL_CREATED",
                        "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                        "data_quality_flags": json.dumps(
                            ["reference_only", "name_path_description_excluded"]
                        ),
                        "provenance": json.dumps(
                            {
                                "record_origin": "OBSERVED",
                                "source_relation": "documents",
                                "transformation_id": "unified_research_layer_v031",
                                "transformation_version": VERSION,
                            }
                        ),
                        "privacy_classification": "REFERENCE_ONLY_NO_BODY",
                        "document_type_ref": str(dtype) if dtype is not None else None,
                        "is_private_flag": bool(priv) if priv is not None else None,
                    }
                )
    # A recommendations already cover document_recommendation refs; add empty-safe write
    counts["research_document_reference"] = _write_parquet(
        out / "research_document_reference.parquet",
        pa.Table.from_pylist(doc_rows)
        if doc_rows
        else _empty_table(pa.schema([("research_entity_id", pa.string())])),
    )
    domain_proof["documents"] = {
        "relation_source": "public.documents",
        "materialized": counts["research_document_reference"],
        "body_included": False,
        "path_included": False,
        "name_included": False,
    }

    # ---- provenance from source_record ----
    prov_batches: list[pa.Table] = []
    prov_sql = """
        SELECT source_record_id, source_system_id, source_schema, source_relation,
               source_record_locator, locator_scheme, source_created_at, source_updated_at,
               provenance
        FROM canonical_evidence.source_record
    """
    prov_schema = pa.schema(
        [
            ("research_entity_id", pa.string()),
            ("source_system", pa.string()),
            ("source_scoped_subject_id", pa.string()),
            ("source_record_locator", pa.string()),
            ("encounter_id", pa.string()),
            ("event_id", pa.string()),
            ("event_time", pa.string()),
            ("timestamp_certainty", pa.string()),
            ("semantic_tier", pa.string()),
            ("data_quality_flags", pa.string()),
            ("provenance", pa.string()),
            ("privacy_classification", pa.string()),
            ("source_schema", pa.string()),
            ("source_relation", pa.string()),
            ("locator_scheme", pa.string()),
            ("source_updated_at", pa.string()),
        ]
    )
    for rows in _stream_query(conn_canonical, prov_sql):
        batch = []
        for (
            srid,
            ss,
            schema,
            relation,
            locator,
            scheme,
            created,
            updated,
            prov,
        ) in rows:
            batch.append(
                {
                    "research_entity_id": srid,
                    "source_system": ss,
                    "source_scoped_subject_id": None,
                    "source_record_locator": locator,
                    "encounter_id": None,
                    "event_id": None,
                    "event_time": created.isoformat() if created else None,
                    "timestamp_certainty": "TECHNICAL",
                    "semantic_tier": "SOURCE_SPECIFIC_SUPPORTED",
                    "data_quality_flags": json.dumps(["canonical_source_record"]),
                    "provenance": json.dumps(
                        {
                            "record_origin": (prov or {}).get("record_origin"),
                            "transformation_id": (prov or {}).get("transformation_id"),
                        }
                    ),
                    "privacy_classification": "OPAQUE_LOCATOR",
                    "source_schema": schema,
                    "source_relation": relation,
                    "locator_scheme": scheme,
                    "source_updated_at": updated.isoformat() if updated else None,
                }
            )
        if batch:
            prov_batches.append(pa.Table.from_pylist(batch, schema=prov_schema))
    prov_table = (
        pa.concat_tables(prov_batches)
        if prov_batches
        else _empty_table(prov_schema)
    )
    counts["research_provenance"] = _write_parquet(
        out / "research_provenance.parquet", prov_table
    )
    domain_proof["provenance"] = {
        "relation_source": "canonical_evidence.source_record",
        "exact_eligible": canonical_inv.get("n_source_records"),
        "materialized": counts["research_provenance"],
    }

    # ---- research_event timeline (union of timed clinical rows) ----
    event_rows: list[dict[str, Any]] = []

    def add_events(rows: list[dict[str, Any]], event_type: str) -> None:
        for r in rows:
            if not r.get("event_time"):
                continue
            event_rows.append(
                {
                    "research_entity_id": _research_id(
                        key,
                        "ResearchEvent",
                        r["source_system"],
                        event_type,
                        r["research_entity_id"],
                    ),
                    "source_system": r["source_system"],
                    "source_scoped_subject_id": r["source_scoped_subject_id"],
                    "source_record_locator": r.get("source_record_locator"),
                    "encounter_id": r.get("encounter_id"),
                    "event_id": r["research_entity_id"],
                    "event_time": r["event_time"],
                    "timestamp_certainty": r.get("timestamp_certainty"),
                    "semantic_tier": r.get("semantic_tier"),
                    "data_quality_flags": r.get("data_quality_flags"),
                    "provenance": r.get("provenance"),
                    "privacy_classification": "OPAQUE_IDENTIFIER",
                    "event_type": event_type,
                    "raw_source_column": None,
                    "timezone": "source_preserved_or_utc",
                    "precision": "timestamp",
                    "semantic_role": event_type,
                    "clinical_or_technical": "clinical_or_workflow",
                    "ambiguity": None,
                }
            )

    add_events(enc_rows, "encounter")
    # observations streamed — read back from parquet for event times only
    obs_pf = pq.read_table(
        out / "research_observation.parquet",
        columns=[
            "research_entity_id",
            "source_system",
            "source_scoped_subject_id",
            "source_record_locator",
            "encounter_id",
            "event_time",
            "timestamp_certainty",
            "semantic_tier",
            "data_quality_flags",
            "provenance",
            "observed_at",
            "specimen_collected_at",
            "result_available_at",
            "recorded_at",
        ],
    )
    for i in range(obs_pf.num_rows):
        event_rows.append(
            {
                "research_entity_id": _research_id(
                    key,
                    "ResearchEvent",
                    obs_pf["source_system"][i].as_py(),
                    "observation",
                    obs_pf["research_entity_id"][i].as_py(),
                ),
                "source_system": obs_pf["source_system"][i].as_py(),
                "source_scoped_subject_id": obs_pf["source_scoped_subject_id"][i].as_py(),
                "source_record_locator": obs_pf["source_record_locator"][i].as_py(),
                "encounter_id": obs_pf["encounter_id"][i].as_py(),
                "event_id": obs_pf["research_entity_id"][i].as_py(),
                "event_time": obs_pf["event_time"][i].as_py(),
                "timestamp_certainty": obs_pf["timestamp_certainty"][i].as_py(),
                "semantic_tier": obs_pf["semantic_tier"][i].as_py(),
                "data_quality_flags": obs_pf["data_quality_flags"][i].as_py(),
                "provenance": obs_pf["provenance"][i].as_py(),
                "privacy_classification": "OPAQUE_IDENTIFIER",
                "event_type": "observation",
                "raw_source_column": "observed_at|specimen_collected_at|result_available_at|recorded_at",
                "timezone": "source_preserved_or_utc",
                "precision": "timestamp",
                "semantic_role": "observation_time",
                "clinical_or_technical": "clinical",
                "ambiguity": None if obs_pf["observed_at"][i].as_py() else "fallback_timestamp",
            }
        )
    add_events(med_rows, "medication_appointment")
    add_events(rec_rows, "recommendation")
    add_events(proc_rows, "procedure")
    add_events(doc_rows, "document_reference")

    counts["research_event"] = _write_parquet(
        out / "research_event.parquet",
        pa.Table.from_pylist(event_rows)
        if event_rows
        else _empty_table(pa.schema([("research_entity_id", pa.string())])),
    )
    domain_proof["events"] = {
        "materialized": counts["research_event"],
        "constituent_types": sorted({e["event_type"] for e in event_rows}),
    }

    # manifests
    manifest = {
        "version": VERSION,
        "created_at": _now(),
        "path": MATERIALIZED_DIR,
        "datasets": {
            name: {
                "file": f"{name}.parquet",
                "rows": counts.get(name, 0),
                "exists": (out / f"{name}.parquet").is_file(),
            }
            for name in REQUIRED_DATASETS
        },
        "total_materialized_rows": sum(counts.values()),
        "patient_rows_written": True,
        "row_level": True,
        "public_zip_includes_rows": False,
        "domain_proof": domain_proof,
        "reject_reasons": reject_reasons,
        "ok": all((out / f"{n}.parquet").is_file() for n in REQUIRED_DATASETS)
        and counts.get("research_subject", 0) > 0
        and counts.get("research_event", 0) > 0,
    }
    (out / "materialization-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest
