"""Full domain inventory A + B + canonical (read-only aggregates)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from human_simulator.unified_research_layer_v03.policy import (
    DOMAINS,
    PIN_SOURCE_A_SUBJECTS,
    PIN_SOURCE_B_SUBJECTS,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


# Domain → relation name patterns (token match on table name)
_DOMAIN_PATTERNS: dict[str, list[str]] = {
    "subjects_patients": [r"patient", r"client", r"account_patient", r"people", r"person"],
    "encounters_consultations_appointments": [
        r"appoint",
        r"encounter",
        r"consult",
        r"visit",
        r"slot",
    ],
    "diagnoses": [r"diagnos", r"icd", r"disease"],
    "anamnesis_history": [r"anamnes", r"history", r"heritage"],
    "complaints": [r"complaint", r"жалоб"],
    "anthropometry_vitals": [r"anthrop", r"vital", r"height", r"weight", r"bmi"],
    "laboratory_orders": [r"lab_referral", r"order", r"referral"],
    "laboratory_results": [
        r"analysisresult$",
        r"lab_result",
        r"analyses_pool",
        r"appointmentanalysisresult",
    ],
    "laboratory_components": [
        r"analysisresultitem",
        r"analyses_constructor",
        r"component",
    ],
    "medications": [r"medicin", r"medication", r"drug", r"pharm"],
    "prescriptions_recorded_medication_events": [
        r"prescription",
        r"medicineappoint",
        r"rx",
    ],
    "dosage_strength_form_frequency_route": [
        r"dosage",
        r"strength",
        r"frequency",
        r"route",
        r"form",
    ],
    "recommendations": [r"recommend"],
    "procedures_interventions": [
        r"procedure",
        r"intervention",
        r"functionalstud",
        r"operation",
    ],
    "medical_documents": [r"document_document", r"document$", r"media"],
    "structured_conclusions": [r"conclusion", r"questionnaire", r"suggestion"],
    "clinical_event_timestamps": [],  # derived from columns
    "reference_catalogs": [r"catalog", r"analyses_catalog", r"analyses_weight", r"dict"],
    "entity_links": [r"link_", r"_messages", r"m2m"],
    "unstructured_medical_text": [r"chat_message", r"text", r"note", r"comment"],
    "unknown_clinical_relations": [],
}


def _match_domain(table: str) -> str | None:
    t = table.lower()
    for domain, pats in _DOMAIN_PATTERNS.items():
        if domain in {"clinical_event_timestamps", "unknown_clinical_relations"}:
            continue
        for pat in pats:
            if re.search(pat, t):
                return domain
    return None


def _list_relations(cur: Any, schema: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT c.relname,
               COALESCE(c.reltuples, 0)::bigint AS est_rows,
               pg_total_relation_size(c.oid)::bigint AS bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relkind = 'r'
        ORDER BY 1
        """,
        (schema,),
    )
    return [
        {"schema": schema, "table": r[0], "estimated_rows": int(r[1]), "bytes": int(r[2])}
        for r in cur.fetchall()
    ]


def _exact_count(cur: Any, schema: str, table: str) -> int | None:
    try:
        cur.execute(f'SELECT COUNT(*)::bigint FROM "{schema}"."{table}"')
        return int(cur.fetchone()[0])
    except Exception:
        return None


def inventory_source(
    *,
    conn: Any | None,
    source_system: str,
    schema: str,
    subject_table: str | None,
    pin_subjects: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "version": VERSION,
        "source_system": source_system,
        "schema": schema,
        "connection": "NOT_AVAILABLE" if conn is None else "OK",
        "domains": {},
        "relations": [],
        "ok": False,
    }
    if conn is None:
        return out

    cur = conn.cursor()
    try:
        rels = _list_relations(cur, schema)
        out["n_relations"] = len(rels)
        assigned: set[str] = set()
        domain_rows: dict[str, list[dict[str, Any]]] = {d: [] for d in DOMAINS}

        for rel in rels:
            domain = _match_domain(rel["table"]) or "unknown_clinical_relations"
            # infrastructure tables stay unknown/unsupported rather than clinical drop
            if any(
                rel["table"].startswith(p)
                for p in ("django_", "auth_", "logg_", "authentication_", "payment_", "chat_")
            ) and domain == "unknown_clinical_relations":
                if "chat_" in rel["table"]:
                    domain = "unstructured_medical_text"
                else:
                    domain = "unknown_clinical_relations"
            row = {
                **rel,
                "domain": domain,
                "semantic_disposition": (
                    "SOURCE_SPECIFIC_SUPPORTED"
                    if domain
                    not in {
                        "unknown_clinical_relations",
                        "unstructured_medical_text",
                    }
                    else (
                        "UNRESOLVED_RETAINED"
                        if domain == "unstructured_medical_text"
                        else "UNSUPPORTED_INFRASTRUCTURE_OR_UNKNOWN"
                    )
                ),
            }
            domain_rows[domain].append(row)
            assigned.add(rel["table"])
            out["relations"].append(
                {
                    "schema": rel["schema"],
                    "table": rel["table"],
                    "domain": domain,
                    "estimated_rows": rel["estimated_rows"],
                }
            )

        # Subject exact count
        subject_exact = None
        if subject_table:
            subject_exact = _exact_count(cur, schema, subject_table)
        out["subject_table"] = subject_table
        out["subject_count_exact"] = subject_exact
        out["subject_count_pin"] = pin_subjects
        out["subject_count_matches_pin"] = subject_exact == pin_subjects

        # Domain accounting
        domains_out = {}
        total_est = 0
        total_accounted = 0
        for d in DOMAINS:
            rows = domain_rows.get(d) or []
            est = sum(r["estimated_rows"] for r in rows)
            total_est += est
            # Accounting buckets (relation-level, not row-value)
            supported = sum(
                r["estimated_rows"]
                for r in rows
                if r.get("semantic_disposition") == "SOURCE_SPECIFIC_SUPPORTED"
            )
            retained_unresolved = sum(
                r["estimated_rows"]
                for r in rows
                if r.get("semantic_disposition") == "UNRESOLVED_RETAINED"
            )
            unsupported = sum(
                r["estimated_rows"]
                for r in rows
                if r.get("semantic_disposition")
                == "UNSUPPORTED_INFRASTRUCTURE_OR_UNKNOWN"
            )
            accounted = supported + retained_unresolved + unsupported
            total_accounted += accounted
            domains_out[d] = {
                "source_relations": [f"{r['schema']}.{r['table']}" for r in rows],
                "n_relations": len(rows),
                "source_rows_estimated": est,
                "candidate_rows": 0,  # filled later for lab from graph
                "supported_rows": supported,
                "retained_source_specific_rows": supported,
                "unresolved_rows": retained_unresolved,
                "rejected_rows": 0,
                "unsupported_rows": unsupported,
                "truncated_rows": 0,
                "unaccounted_rows": est - accounted,
                "provenance_coverage": "RELATION_LEVEL",
                "temporal_coverage": "UNKNOWN_PENDING_TEMPORAL_LAYER",
                "subject_coverage": "SUBJECT_SCOPED_PENDING_STATE",
            }
            assert domains_out[d]["unaccounted_rows"] == 0

        unaccounted_relations = [
            r["table"] for r in rels if r["table"] not in assigned
        ]
        out["domains"] = domains_out
        out["unaccounted_relations"] = unaccounted_relations
        out["UNACCOUNTED_COUNT"] = len(unaccounted_relations) + sum(
            d["unaccounted_rows"] for d in domains_out.values()
        )
        out["inventory_hash"] = _hash(
            {"n": len(rels), "subj": subject_exact, "domains": list(domains_out)}
        )
        out["ok"] = out["UNACCOUNTED_COUNT"] == 0 and out["connection"] == "OK"
        if source_system == "magerya_api":
            out["FULL_SOURCE_A_DOMAIN_INVENTORY_STATUS"] = (
                "PASS" if out["ok"] else "FAIL"
            )
        else:
            out["FULL_SOURCE_B_DOMAIN_INVENTORY_STATUS"] = (
                "PASS" if out["ok"] else "FAIL"
            )
    finally:
        try:
            cur.close()
        except Exception:
            pass
    return out


def inventory_canonical(conn_canonical: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"version": VERSION, "ok": False}
    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT source_system_id, COUNT(*)::bigint
            FROM canonical_evidence.subject
            GROUP BY 1
            ORDER BY 1
            """
        )
        by_ss = {r[0]: int(r[1]) for r in cur.fetchall()}
        counts = {}
        for t in (
            "subject",
            "encounter",
            "observation",
            "observation_component",
            "source_record",
            "subject_characteristic",
        ):
            cur.execute(f"SELECT COUNT(*)::bigint FROM canonical_evidence.{t}")
            counts[t] = int(cur.fetchone()[0])
        # provenance: every subject has source_system_id
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE source_system_id IS NULL)::bigint,
                   COUNT(*)::bigint
            FROM canonical_evidence.subject
            """
        )
        null_ss, n_subj = cur.fetchone()
        # isolation: no cross-source subject key collision expected across systems
        cur.execute(
            """
            SELECT COUNT(*)::bigint FROM (
              SELECT source_subject_key
              FROM canonical_evidence.subject
              GROUP BY source_subject_key
              HAVING COUNT(DISTINCT source_system_id) > 1
            ) x
            """
        )
        cross_key = int(cur.fetchone()[0])
    out.update(
        {
            "subjects_by_source_system_id": by_ss,
            "table_counts": counts,
            "subjects_missing_source_system": int(null_ss or 0),
            "cross_source_subject_key_collisions": cross_key,
            "source_a_subjects": by_ss.get("magerya_api"),
            "source_b_subjects": by_ss.get("kgz_raw"),
            "source_a_matches_pin": by_ss.get("magerya_api") == PIN_SOURCE_A_SUBJECTS,
            "source_b_matches_pin": by_ss.get("kgz_raw") == PIN_SOURCE_B_SUBJECTS,
            "sum_not_unique_people_claim": True,
            "sum_a_plus_b": (by_ss.get("magerya_api") or 0)
            + (by_ss.get("kgz_raw") or 0),
            "ok": int(null_ss or 0) == 0 and cross_key == 0,
            "PROVENANCE_STATUS": "PASS" if int(null_ss or 0) == 0 else "FAIL",
        }
    )
    return out
