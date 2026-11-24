"""Canonical load with SourceRecord coverage, reject taxonomy, truncation accounting."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from human_simulator.canonical.connection import canonical_connection
from human_simulator.canonical.migrations import row_counts
from human_simulator.canonical.settings import load_canonical_settings
from human_simulator.core import source_a as src
from human_simulator.core.ids import entity_id, load_hmac_key, locator, opaque_subject_key
from human_simulator.core.policy import (
    ID_NAMESPACE_VERSION,
    KEY_VERSION,
    PER_PATIENT_LAB_LIMIT,
    PER_RESULT_ITEM_LIMIT,
    SOURCE_SYSTEM_ID,
    TRANSFORMATION_ID,
    TRANSFORMATION_VERSION,
)

REJECT_CATEGORIES = (
    "MISSING_SOURCE_VALUE",
    "INVALID_NUMERIC_REPRESENTATION",
    "BROKEN_SOURCE_RELATIONSHIP",
    "DATABASE_CONSTRAINT_ERROR",
    "MISSING_SUBJECT",
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _prov(relation: str, loc: str, *, input_sha: str) -> dict[str, Any]:
    return {
        "record_origin": "OBSERVED",
        "source_system": SOURCE_SYSTEM_ID,
        "source_schema": "magerya_api",
        "source_relation": relation,
        "source_record_locator": loc,
        "transformation_id": TRANSFORMATION_ID,
        "transformation_version": TRANSFORMATION_VERSION,
        "transformed_at": _now(),
        "input_artifact_sha256": input_sha,
        "confidence": 1.0,
        "mapping_status": "CANDIDATE",
        "load_run_id": TRANSFORMATION_ID,
        "id_namespace_version": ID_NAMESPACE_VERSION,
        "key_version": KEY_VERSION,
    }


def _insert(conn: Any, sql: str, params: tuple[Any, ...]) -> str:
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return "inserted" if cur.rowcount else "exists"
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}"


def _insert_source_record(
    conn: Any,
    *,
    key: bytes,
    relation: str,
    pk: str,
    created: Any,
    updated: Any,
    input_sha: str,
    stats: dict[str, int],
    write_errors: list[str],
    locators_by_relation: dict[str, set[str]],
) -> str:
    loc = locator(key, relation, pk)
    srid = entity_id(key, "SourceRecord", relation, pk)
    r = _insert(
        conn,
        """
        INSERT INTO canonical_evidence.source_record (
          source_record_id, source_system_id, source_schema, source_relation,
          source_record_locator, locator_scheme, locator_key_version,
          source_created_at, source_updated_at, provenance
        ) VALUES (%s,%s,'magerya_api',%s,%s,'deterministic_hmac_locator',%s,%s,%s,%s::jsonb)
        ON CONFLICT (source_record_id) DO NOTHING
        """,
        (
            srid,
            SOURCE_SYSTEM_ID,
            relation,
            loc,
            KEY_VERSION,
            created,
            updated,
            json.dumps(_prov(relation, loc, input_sha=input_sha)),
        ),
    )
    if r == "inserted":
        stats["source_record"] += 1
    elif r.startswith("error"):
        write_errors.append(r)
        return r
    locators_by_relation.setdefault(relation, set()).add(loc)
    return loc


def load_canonical(
    repo_root: Path,
    *,
    patient_ids: list[int],
    input_sha: str,
    per_patient_limit: int = PER_PATIENT_LAB_LIMIT,
    per_result_limit: int = PER_RESULT_ITEM_LIMIT,
    verify_coverage: bool = True,
) -> dict[str, Any]:
    key = load_hmac_key(repo_root)
    rejects: list[dict[str, str]] = []
    write_errors: list[str] = []
    stats = {
        "source_system": 0,
        "source_record": 0,
        "subject": 0,
        "subject_characteristic": 0,
        "encounter": 0,
        "observation": 0,
        "observation_component": 0,
    }
    locators_by_relation: dict[str, set[str]] = {}
    evidence_locators: list[dict[str, str]] = []

    uncapped = per_patient_limit >= 10**9 and per_result_limit >= 10**9
    with src.source_a_connection(repo_root) as sconn:
        truncation = src.truncation_accounting(
            sconn,
            patient_ids,
            per_patient_limit=per_patient_limit,
            per_result_limit=per_result_limit,
        )
        patients = src.fetch_patients(sconn, patient_ids)
        appointments = src.fetch_appointments(sconn, patient_ids)
        if uncapped:
            labs = src.fetch_analysis_results_uncapped(sconn, patient_ids)
            lab_ids = [int(x["id"]) for x in labs]
            items = src.fetch_analysis_items_uncapped(sconn, lab_ids)
        else:
            labs = src.fetch_analysis_results(sconn, patient_ids, per_patient_limit=per_patient_limit)
            lab_ids = [int(x["id"]) for x in labs]
            items = src.fetch_analysis_items(sconn, lab_ids, per_result_limit=per_result_limit)

    settings = load_canonical_settings()
    with canonical_connection(settings) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SET ROLE canonical_loader")
            except Exception:  # noqa: BLE001
                pass

        counts_before = row_counts(conn)

        r = _insert(
            conn,
            """
            INSERT INTO canonical_evidence.source_system (source_system_id, source_label, audit_stage_reference)
            VALUES (%s, %s, %s)
            ON CONFLICT (source_system_id) DO NOTHING
            """,
            (SOURCE_SYSTEM_ID, "Source A magerya_api", "stage-01"),
        )
        if r == "inserted":
            stats["source_system"] += 1
        elif r.startswith("error"):
            write_errors.append(r)

        subject_map: dict[int, str] = {}
        for p in patients:
            pid = int(p["id"])
            okey = opaque_subject_key(key, pid)
            sid = entity_id(key, "Subject", okey)
            subject_map[pid] = sid
            loc = _insert_source_record(
                conn,
                key=key,
                relation="account_patient",
                pk=str(pid),
                created=p.get("created"),
                updated=p.get("modified"),
                input_sha=input_sha,
                stats=stats,
                write_errors=write_errors,
                locators_by_relation=locators_by_relation,
            )
            if loc.startswith("error"):
                rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "source_record"})
                continue

            r = _insert(
                conn,
                """
                INSERT INTO canonical_evidence.subject (
                  subject_id, source_system_id, source_subject_key, subject_role_hint, provenance
                ) VALUES (%s,%s,%s,'patient',%s::jsonb)
                ON CONFLICT (subject_id) DO NOTHING
                """,
                (sid, SOURCE_SYSTEM_ID, okey, json.dumps(_prov("account_patient", loc, input_sha=input_sha))),
            )
            if r == "inserted":
                stats["subject"] += 1
            elif r.startswith("error"):
                write_errors.append(r)
                rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "subject"})
                continue
            evidence_locators.append({"entity": "subject", "source_relation": "account_patient", "locator": loc})

            if p.get("birthdate") is not None:
                cid = entity_id(key, "SubjectCharacteristic", okey, "source_birthdate")
                r = _insert(
                    conn,
                    """
                    INSERT INTO canonical_evidence.subject_characteristic (
                      characteristic_id, subject_id, characteristic_code, concept_id,
                      raw_code, raw_value, date_value, status, provenance
                    ) VALUES (%s,%s,'source_birthdate',NULL,'birthdate',%s,%s,'CANDIDATE',%s::jsonb)
                    ON CONFLICT (characteristic_id) DO NOTHING
                    """,
                    (
                        cid,
                        sid,
                        str(p["birthdate"]),
                        p["birthdate"],
                        json.dumps(_prov("account_patient", loc, input_sha=input_sha)),
                    ),
                )
                if r == "inserted":
                    stats["subject_characteristic"] += 1
                elif r.startswith("error"):
                    write_errors.append(r)
                    rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "subject_characteristic"})
                if not r.startswith("error"):
                    evidence_locators.append(
                        {
                            "entity": "subject_characteristic",
                            "source_relation": "account_patient",
                            "locator": loc,
                        }
                    )

            if p.get("sex") is not None and str(p["sex"]).strip():
                cid = entity_id(key, "SubjectCharacteristic", okey, "source_sex")
                r = _insert(
                    conn,
                    """
                    INSERT INTO canonical_evidence.subject_characteristic (
                      characteristic_id, subject_id, characteristic_code, concept_id,
                      raw_code, raw_value, categorical_value, status, provenance
                    ) VALUES (%s,%s,'source_sex',NULL,'sex',%s,%s,'CANDIDATE',%s::jsonb)
                    ON CONFLICT (characteristic_id) DO NOTHING
                    """,
                    (
                        cid,
                        sid,
                        str(p["sex"]),
                        str(p["sex"]),
                        json.dumps(_prov("account_patient", loc, input_sha=input_sha)),
                    ),
                )
                if r == "inserted":
                    stats["subject_characteristic"] += 1
                elif r.startswith("error"):
                    write_errors.append(r)
                    rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "subject_characteristic"})
                if not r.startswith("error"):
                    evidence_locators.append(
                        {
                            "entity": "subject_characteristic",
                            "source_relation": "account_patient",
                            "locator": loc,
                        }
                    )

        for a in appointments:
            pid = int(a["patient_id"])
            sid = subject_map.get(pid)
            if not sid:
                rejects.append({"category": "MISSING_SUBJECT", "entity": "encounter"})
                continue
            loc = _insert_source_record(
                conn,
                key=key,
                relation="appointment_appointment",
                pk=str(a["id"]),
                created=a.get("created"),
                updated=a.get("modified"),
                input_sha=input_sha,
                stats=stats,
                write_errors=write_errors,
                locators_by_relation=locators_by_relation,
            )
            if loc.startswith("error"):
                rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "source_record"})
                continue
            eid = entity_id(key, "Encounter", str(a["id"]))
            missing = None if a.get("completed_at") or a.get("created") else "clinical_time_absent"
            r = _insert(
                conn,
                """
                INSERT INTO canonical_evidence.encounter (
                  encounter_id, subject_id, provider_id, encounter_type,
                  occurred_at, recorded_at, completed_at, status, data_level,
                  missingness_reason, provenance
                ) VALUES (%s,%s,NULL,'appointment',%s,%s,%s,%s,'PATIENT_EVENT',%s,%s::jsonb)
                ON CONFLICT (encounter_id) DO NOTHING
                """,
                (
                    eid,
                    sid,
                    a.get("completed_at") or a.get("created"),
                    a.get("created"),
                    a.get("completed_at"),
                    str(a.get("status")) if a.get("status") is not None else None,
                    missing,
                    json.dumps(_prov("appointment_appointment", loc, input_sha=input_sha)),
                ),
            )
            if r == "inserted":
                stats["encounter"] += 1
            elif r.startswith("error"):
                write_errors.append(r)
                rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "encounter"})
                continue
            evidence_locators.append(
                {"entity": "encounter", "source_relation": "appointment_appointment", "locator": loc}
            )

        obs_map: dict[int, str] = {}
        for lab in labs:
            pid = int(lab["patient_id"])
            sid = subject_map.get(pid)
            if not sid:
                rejects.append({"category": "MISSING_SUBJECT", "entity": "observation"})
                continue
            loc = _insert_source_record(
                conn,
                key=key,
                relation="document_analysisresult",
                pk=str(lab["id"]),
                created=lab.get("created"),
                updated=lab.get("modified"),
                input_sha=input_sha,
                stats=stats,
                write_errors=write_errors,
                locators_by_relation=locators_by_relation,
            )
            if loc.startswith("error"):
                rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "source_record"})
                continue
            oid = entity_id(key, "Observation", str(lab["id"]))
            obs_map[int(lab["id"])] = oid
            observed = lab.get("appointment_date") or lab.get("created")
            # Clinical vs system: do not invent clinical time — if only created exists, store as recorded
            # and leave observed_at null when appointment_date/sampling absent? Spec: don't substitute.
            clinical = lab.get("appointment_date") or lab.get("sampling_date")
            miss = None if clinical is not None else "clinical_time_absent"
            r = _insert(
                conn,
                """
                INSERT INTO canonical_evidence.observation (
                  observation_id, subject_id, encounter_id, observed_at, recorded_at,
                  specimen_collected_at, status, data_level, missingness_reason, provenance
                ) VALUES (%s,%s,NULL,%s,%s,%s,%s,'OBSERVATION_HEADER',%s,%s::jsonb)
                ON CONFLICT (observation_id) DO NOTHING
                """,
                (
                    oid,
                    sid,
                    clinical,  # may be null — do not substitute created
                    lab.get("created"),
                    lab.get("sampling_date"),
                    str(lab.get("status")) if lab.get("status") is not None else None,
                    miss,
                    json.dumps(_prov("document_analysisresult", loc, input_sha=input_sha)),
                ),
            )
            if r == "inserted":
                stats["observation"] += 1
            elif r.startswith("error"):
                write_errors.append(r)
                rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "observation"})
                continue
            evidence_locators.append(
                {"entity": "observation", "source_relation": "document_analysisresult", "locator": loc}
            )

        for item in items:
            oid = obs_map.get(int(item["analysis_result_id"]))
            if not oid:
                rejects.append({"category": "BROKEN_SOURCE_RELATIONSHIP", "entity": "observation_component"})
                continue
            raw_val = item.get("value")
            # SourceRecord for every item that is eligible to create evidence OR rejected after SR?
            # Policy: SR for rows that create evidence. Missing values do not create component —
            # still create SR for processed source rows that were candidates (auditability).
            loc = _insert_source_record(
                conn,
                key=key,
                relation="document_analysisresultitem",
                pk=str(item["id"]),
                created=None,
                updated=None,
                input_sha=input_sha,
                stats=stats,
                write_errors=write_errors,
                locators_by_relation=locators_by_relation,
            )
            if loc.startswith("error"):
                rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "source_record"})
                continue

            if raw_val is None or str(raw_val).strip() == "":
                rejects.append({"category": "MISSING_SOURCE_VALUE", "entity": "observation_component"})
                continue

            text_v = str(raw_val)
            num = None
            numeric_invalid = False
            stripped = text_v.replace(",", ".").strip()
            # Detect intentional non-numeric vs failed numeric parse of numeric-looking strings
            try:
                num = float(stripped)
            except ValueError:
                # If string looks like it intended to be numeric but failed
                if any(ch.isdigit() for ch in stripped) and any(
                    ch in stripped for ch in ".,eE+-"
                ):
                    numeric_invalid = True
                num = None
            if numeric_invalid:
                rejects.append(
                    {"category": "INVALID_NUMERIC_REPRESENTATION", "entity": "observation_component"}
                )
                continue

            cid = entity_id(key, "ObservationComponent", str(item["id"]))
            if num is not None:
                r = _insert(
                    conn,
                    """
                    INSERT INTO canonical_evidence.observation_component (
                      component_id, observation_id, raw_code, raw_value, numeric_value,
                      text_value, raw_unit, provenance
                    ) VALUES (%s,%s,%s,%s,%s,NULL,%s,%s::jsonb)
                    ON CONFLICT (component_id) DO NOTHING
                    """,
                    (
                        cid,
                        oid,
                        str(item.get("name") or "unknown"),
                        text_v,
                        num,
                        item.get("unit"),
                        json.dumps(_prov("document_analysisresultitem", loc, input_sha=input_sha)),
                    ),
                )
            else:
                r = _insert(
                    conn,
                    """
                    INSERT INTO canonical_evidence.observation_component (
                      component_id, observation_id, raw_code, raw_value, numeric_value,
                      text_value, raw_unit, provenance
                    ) VALUES (%s,%s,%s,%s,NULL,%s,%s,%s::jsonb)
                    ON CONFLICT (component_id) DO NOTHING
                    """,
                    (
                        cid,
                        oid,
                        str(item.get("name") or "unknown"),
                        text_v,
                        text_v,
                        item.get("unit"),
                        json.dumps(_prov("document_analysisresultitem", loc, input_sha=input_sha)),
                    ),
                )
            if r == "inserted":
                stats["observation_component"] += 1
            elif r.startswith("error"):
                write_errors.append(r)
                rejects.append({"category": "DATABASE_CONSTRAINT_ERROR", "entity": "observation_component"})
                continue
            evidence_locators.append(
                {
                    "entity": "observation_component",
                    "source_relation": "document_analysisresultitem",
                    "locator": loc,
                }
            )

        with conn.cursor() as cur:
            cur.execute("RESET ROLE")
        counts_after = row_counts(conn)

        # Coverage: every evidence row's locator must exist in source_record.
        # Full-table coverage is O(canonical size) and may timeout on large DBs;
        # full-population expand sets verify_coverage=False and uses batch-local checks.
        if verify_coverage:
            coverage = _verify_source_record_coverage(conn)
        else:
            coverage = _verify_batch_locator_coverage(conn, evidence_locators)

    reason_counts = Counter(r["category"] for r in rejects)
    # Denominators
    denom = {
        "lab_items_processed": len(items),
        "appointments_processed": len(appointments),
        "labs_processed": len(labs),
        "patients_processed": len(patients),
    }
    reject_summary = []
    for cat in REJECT_CATEGORIES:
        count = int(reason_counts.get(cat, 0))
        # Choose primary denominator for percentage
        if cat in ("MISSING_SOURCE_VALUE", "INVALID_NUMERIC_REPRESENTATION", "BROKEN_SOURCE_RELATIONSHIP"):
            d = denom["lab_items_processed"] or 1
        elif cat == "MISSING_SUBJECT":
            d = (denom["appointments_processed"] + denom["labs_processed"]) or 1
        else:
            d = (
                denom["patients_processed"]
                + denom["appointments_processed"]
                + denom["labs_processed"]
                + denom["lab_items_processed"]
            ) or 1
        reject_summary.append(
            {
                "category": cat,
                "count": count,
                "denominator": d,
                "percentage": round(100.0 * count / d, 4),
            }
        )

    # Strip internal markers from evidence_locators for report
    clean_evidence = [
        {k: v for k, v in e.items() if not k.startswith("_")} for e in evidence_locators
    ]

    return {
        "inserted": stats,
        "canonical_row_counts_before": counts_before,
        "canonical_row_counts": counts_after,
        "write_errors": write_errors,
        "write_error_count": len(write_errors),
        "subjects_attempted": len(patient_ids),
        "subjects_in_map": len(subject_map),
        "reject_count": len(rejects),
        "reject_categories": reject_summary,
        "reject_reasons": dict(reason_counts),  # legacy key
        "truncation": truncation,
        "source_record_coverage": coverage,
        "source_record_counts_by_relation": {k: len(v) for k, v in locators_by_relation.items()},
        "rejected_rows_in_source_record_coverage": {
            "included": True,
            "explanation": (
                "SourceRecord is created for every processed source row that is a candidate for "
                "evidence (including lab items later classified MISSING_SOURCE_VALUE). "
                "Coverage check verifies each stored evidence row's provenance locator exists in "
                "source_record. Reject-only rows without evidence are counted in SourceRecord "
                "relation totals but are not required to have a paired evidence entity."
            ),
        },
        "opaque_subject_keys_only": True,
        "patient_ids_not_in_report": True,
        "evidence_locator_count": len(clean_evidence),
    }


def _verify_batch_locator_coverage(
    conn: Any, evidence_locators: list[dict[str, Any]]
) -> dict[str, Any]:
    """Verify SourceRecord exists for locators produced in this load batch only."""
    locs = sorted(
        {
            str(e.get("locator"))
            for e in evidence_locators
            if e.get("locator")
        }
    )
    if not locs:
        return {
            "mode": "batch_local",
            "every_evidence_has_source_record": True,
            "missing_total": 0,
            "n_batch_locators": 0,
        }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM unnest(%s::text[]) AS loc(locator)
            WHERE NOT EXISTS (
              SELECT 1 FROM canonical_evidence.source_record sr
              WHERE sr.source_record_locator = loc.locator
            )
            """,
            (locs,),
        )
        missing = int(cur.fetchone()[0])
    return {
        "mode": "batch_local",
        "every_evidence_has_source_record": missing == 0,
        "missing_total": missing,
        "n_batch_locators": len(locs),
    }


def _verify_source_record_coverage(conn: Any) -> dict[str, Any]:
    """Every source-backed evidence row must have matching SourceRecord locator."""
    checks: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        queries = [
            (
                "subject",
                """
                SELECT COUNT(*) FROM canonical_evidence.subject s
                WHERE NOT EXISTS (
                  SELECT 1 FROM canonical_evidence.source_record sr
                  WHERE sr.source_record_locator = s.provenance->>'source_record_locator'
                )
                """,
            ),
            (
                "subject_characteristic",
                """
                SELECT COUNT(*) FROM canonical_evidence.subject_characteristic c
                WHERE NOT EXISTS (
                  SELECT 1 FROM canonical_evidence.source_record sr
                  WHERE sr.source_record_locator = c.provenance->>'source_record_locator'
                )
                """,
            ),
            (
                "encounter",
                """
                SELECT COUNT(*) FROM canonical_evidence.encounter e
                WHERE NOT EXISTS (
                  SELECT 1 FROM canonical_evidence.source_record sr
                  WHERE sr.source_record_locator = e.provenance->>'source_record_locator'
                )
                """,
            ),
            (
                "observation",
                """
                SELECT COUNT(*) FROM canonical_evidence.observation o
                WHERE NOT EXISTS (
                  SELECT 1 FROM canonical_evidence.source_record sr
                  WHERE sr.source_record_locator = o.provenance->>'source_record_locator'
                )
                """,
            ),
            (
                "observation_component",
                """
                SELECT COUNT(*) FROM canonical_evidence.observation_component oc
                WHERE NOT EXISTS (
                  SELECT 1 FROM canonical_evidence.source_record sr
                  WHERE sr.source_record_locator = oc.provenance->>'source_record_locator'
                )
                """,
            ),
        ]
        missing_total = 0
        for name, sql in queries:
            cur.execute(sql)
            missing = int(cur.fetchone()[0])
            missing_total += missing
            checks.append({"entity": name, "missing_source_record": missing, "ok": missing == 0})
        cur.execute(
            """
            SELECT source_relation, COUNT(*)::bigint
            FROM canonical_evidence.source_record
            GROUP BY source_relation ORDER BY source_relation
            """
        )
        by_rel = {r[0]: int(r[1]) for r in cur.fetchall()}
    return {
        "every_evidence_has_source_record": missing_total == 0,
        "missing_total": missing_total,
        "per_entity": checks,
        "source_record_counts_by_relation": by_rel,
    }
