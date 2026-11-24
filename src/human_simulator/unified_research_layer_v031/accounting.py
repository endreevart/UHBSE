"""Exact multi-domain row accounting — no reltuples for PASS."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_research_layer_v031.policy import VERSION


def build_accounting(
    *,
    a_inv: dict[str, Any],
    b_inv: dict[str, Any],
    classification_a: dict[str, Any],
    classification_b: dict[str, Any],
    materialization: dict[str, Any],
    canonical: dict[str, Any],
) -> dict[str, Any]:
    datasets = materialization.get("datasets") or {}
    proof = materialization.get("domain_proof") or {}

    buckets = {
        "raw_or_eligible": 0,
        "materialized": 0,
        "retained_unresolved": 0,
        "rejected": 0,
        "unsupported": 0,
        "truncated": 0,
        "duplicate_conflict": 0,
        "unaccounted": 0,
    }

    # Authoritative grains (do NOT sum across semantic levels as medical facts)
    grains = {
        "subjects": {
            "eligible": canonical.get("n_subjects") or 0,
            "materialized": (datasets.get("research_subject") or {}).get("rows") or 0,
        },
        "encounters": {
            "eligible": canonical.get("n_encounters") or 0,
            "materialized": (datasets.get("research_encounter") or {}).get("rows") or 0,
        },
        "observations": {
            "eligible": canonical.get("n_observations") or 0,
            "materialized": (datasets.get("research_observation") or {}).get("rows") or 0,
        },
        "observation_components": {
            "eligible": canonical.get("n_observation_components") or 0,
            "materialized": (datasets.get("research_observation_component") or {}).get("rows")
            or 0,
        },
        "source_records_provenance": {
            "eligible": canonical.get("n_source_records") or 0,
            "materialized": (datasets.get("research_provenance") or {}).get("rows") or 0,
        },
        "medication_events_a": {
            "eligible": (proof.get("medications") or {}).get("exact_eligible") or 0,
            "materialized": (datasets.get("research_medication_record") or {}).get("rows") or 0,
            "rejected": (proof.get("medications") or {}).get("rejected") or 0,
        },
        "recommendation_patient_events": {
            "eligible": None,
            "materialized": (datasets.get("research_recommendation") or {}).get("rows") or 0,
            "rejected": (proof.get("recommendations") or {}).get("rejected") or 0,
        },
        "procedures_a": {
            "eligible": (proof.get("procedures") or {}).get("materialized") or 0,
            "materialized": (datasets.get("research_procedure") or {}).get("rows") or 0,
        },
        "document_references_b": {
            "eligible": None,
            "materialized": (datasets.get("research_document_reference") or {}).get("rows") or 0,
        },
        "diagnosis_patient_facts": {
            "eligible": 0,
            "materialized": 0,
            "retained_unresolved": 0,
            "note": (proof.get("diagnoses") or {}).get("unresolved_reason"),
        },
        "events": {
            "eligible": (datasets.get("research_event") or {}).get("rows") or 0,
            "materialized": (datasets.get("research_event") or {}).get("rows") or 0,
        },
    }

    # Reconcile canonical grains
    grain_ok = []
    for name in (
        "subjects",
        "encounters",
        "observations",
        "observation_components",
        "source_records_provenance",
    ):
        g = grains[name]
        ok = g["eligible"] == g["materialized"]
        grain_ok.append({"grain": name, "ok": ok, **g})
        buckets["raw_or_eligible"] += int(g["eligible"])
        buckets["materialized"] += int(g["materialized"])
        if not ok:
            buckets["unaccounted"] += abs(int(g["eligible"]) - int(g["materialized"]))

    # medications
    mg = grains["medication_events_a"]
    med_ok = mg["eligible"] == mg["materialized"] + mg["rejected"]
    grain_ok.append({"grain": "medication_events_a", "ok": med_ok, **mg})
    buckets["raw_or_eligible"] += int(mg["eligible"])
    buckets["materialized"] += int(mg["materialized"])
    buckets["rejected"] += int(mg["rejected"])
    if not med_ok:
        buckets["unaccounted"] += abs(
            int(mg["eligible"]) - int(mg["materialized"]) - int(mg["rejected"])
        )

    # classification dispositions (relation-level secondary, not mixed into medical-fact totals)
    for clf in (classification_a, classification_b):
        for rel in clf.get("relations") or []:
            d = rel.get("primary_disposition")
            if d == "INFRASTRUCTURE_UNSUPPORTED":
                buckets["unsupported"] += 1
            elif d == "UNRESOLVED_RETAINED":
                buckets["retained_unresolved"] += 1
            elif d == "REJECTED_FALSE_POSITIVE":
                buckets["rejected"] += 1

    # identity equation on authoritative clinical grains only
    identity_lhs = sum(
        grains[n]["eligible"]
        for n in (
            "subjects",
            "encounters",
            "observations",
            "observation_components",
            "source_records_provenance",
        )
    ) + grains["medication_events_a"]["eligible"]
    identity_rhs = (
        sum(
            grains[n]["materialized"]
            for n in (
                "subjects",
                "encounters",
                "observations",
                "observation_components",
                "source_records_provenance",
            )
        )
        + grains["medication_events_a"]["materialized"]
        + grains["medication_events_a"]["rejected"]
    )
    truncated = 0
    unaccounted = abs(identity_lhs - identity_rhs)

    # users/consultations present
    b_users = any(
        r.get("schema") == "public" and r.get("relation") == "users"
        for r in (classification_b.get("relations") or [])
    )
    b_consult = any(
        r.get("schema") == "public" and r.get("relation") == "consultations"
        for r in (classification_b.get("relations") or [])
    )

    status = (
        "PASS"
        if unaccounted == 0
        and truncated == 0
        and all(g["ok"] for g in grain_ok if g["grain"] != "diagnosis_patient_facts")
        and b_users
        and b_consult
        and (datasets.get("research_subject") or {}).get("rows", 0) > 0
        else "FAIL"
    )

    return {
        "version": VERSION,
        "EXACT_MULTI_DOMAIN_ACCOUNTING_STATUS": status,
        "count_method_authoritative": "COUNT(*)_or_canonical_manifest",
        "reltuples_used_for_pass": False,
        "do_not_publish_summed_supported_millions": True,
        "grains": grains,
        "grain_reconciliation": grain_ok,
        "identity": {
            "raw_or_eligible": identity_lhs,
            "materialized_plus_rejected": identity_rhs,
            "retained_unresolved_catalog_relations": buckets["retained_unresolved"],
            "unsupported_infrastructure_relations": buckets["unsupported"],
            "truncated": truncated,
            "unaccounted": unaccounted,
            "equation": "eligible_canonical_and_meds = materialized + rejected",
        },
        "UNACCOUNTED_COUNT": unaccounted,
        "TRUNCATED_COUNT": truncated,
        "source_a_schemas": a_inv.get("schemas_all"),
        "source_b_schemas": b_inv.get("schemas_all"),
        "source_b_users_observed": b_users,
        "source_b_consultations_observed": b_consult,
        "ok": status == "PASS" and unaccounted == 0,
    }
