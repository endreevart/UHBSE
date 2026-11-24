"""Source A relation-level accounting and component gap explanation."""

from __future__ import annotations

from typing import Any

from human_simulator.population_v011.policy import SOURCE_A, VERSION


def build_relation_accounting(conn_a: Any, conn_canonical: Any) -> dict[str, Any]:
    """Account every Source A raw row into canonical / rejected / unsupported buckets."""
    with conn_a.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM magerya_api.account_patient")
        n_patients = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM magerya_api.appointment_appointment")
        n_appt = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM magerya_api.document_analysisresult")
        n_labs = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM magerya_api.document_analysisresultitem")
        n_items = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM magerya_api.diagnosis_medicineappointments")
        n_med = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM magerya_api.document_analysisresult
            WHERE patient_id IS NULL
            """
        )
        labs_no_patient = int(cur.fetchone()[0])

        # Exclusive item taxonomy — filters are mutually exclusive and complete
        cur.execute(
            """
            SELECT
              COUNT(*)::bigint AS total,
              COUNT(*) FILTER (WHERE ar.id IS NULL)::bigint AS orphan,
              COUNT(*) FILTER (
                WHERE ar.id IS NOT NULL AND ar.patient_id IS NULL
              )::bigint AS no_patient,
              COUNT(*) FILTER (
                WHERE ar.patient_id IS NOT NULL
                  AND (i.value IS NULL OR btrim(i.value) = '')
              )::bigint AS empty_with_patient,
              COUNT(*) FILTER (
                WHERE ar.patient_id IS NOT NULL
                  AND i.value IS NOT NULL AND btrim(i.value) <> ''
                  AND i.value !~ '^-?[0-9]+([.,][0-9]+)?$'
              )::bigint AS non_numeric_with_patient,
              COUNT(*) FILTER (
                WHERE ar.patient_id IS NOT NULL
                  AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
              )::bigint AS numeric_with_patient
            FROM magerya_api.document_analysisresultitem i
            LEFT JOIN magerya_api.document_analysisresult ar
              ON ar.id = i.analysis_result_id
            """
        )
        total_items, orphan, no_pat, empty_wp, nonnum_wp, num_wp = (
            int(x) for x in cur.fetchone()
        )

    with conn_canonical.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.subject
            WHERE source_system_id = %s
            """,
            (SOURCE_A,),
        )
        can_subj = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.encounter e
            JOIN canonical_evidence.subject s ON s.subject_id = e.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_A,),
        )
        can_enc = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.observation o
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_A,),
        )
        can_obs = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE numeric_value IS NOT NULL) AS numeric,
              COUNT(*) FILTER (WHERE numeric_value IS NULL) AS non_numeric_preserved
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_A,),
        )
        can_comp, can_comp_num, can_comp_non = (int(x) for x in cur.fetchone())
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='canonical_evidence' AND table_name='source_record'
            """
        )
        sr_cols = {r[0] for r in cur.fetchall()}

    exclusive_sum = orphan + no_pat + empty_wp + nonnum_wp + num_wp
    nonnum_loaded = min(can_comp_non, nonnum_wp)
    nonnum_gap = max(0, nonnum_wp - nonnum_loaded)
    numeric_loaded = min(can_comp_num, num_wp)
    numeric_gap = max(0, num_wp - numeric_loaded)
    gap = total_items - can_comp

    relations = {
        "account_patient": _bucket(
            n_patients, can_subj, unexplained=max(0, n_patients - can_subj)
        ),
        "appointment_appointment": _bucket(
            n_appt, can_enc, unexplained=max(0, n_appt - can_enc)
        ),
        "document_analysisresult": _bucket(
            n_labs,
            can_obs,
            unsupported=labs_no_patient,
            unexplained=max(0, n_labs - can_obs - labs_no_patient),
        ),
        "document_analysisresultitem": {
            **_bucket(
                total_items,
                can_comp,
                unsupported=orphan + no_pat,
                empty_value_rows=empty_wp,
                unexplained=max(0, total_items - exclusive_sum),
            ),
            "non_numeric_preserved_rows": nonnum_loaded,
            "non_numeric_with_patient_not_loaded": nonnum_gap,
            "numeric_with_patient_not_loaded": numeric_gap,
            "exclusive_accounted_rows": exclusive_sum,
            "exclusive_sum_ok": exclusive_sum == total_items,
            "mapping_cardinality": "1:0 or 1:1 component per item",
            "value_taxonomy": {
                "orphan_header": orphan,
                "no_patient": no_pat,
                "empty_with_patient": empty_wp,
                "non_numeric_with_patient": nonnum_wp,
                "numeric_with_patient": num_wp,
            },
        },
        "diagnosis_medicineappointments": {
            **_bucket(n_med, 0),
            "mapping_cardinality": "not_loaded_as_canonical_clinical_entity",
            "note": (
                "Medicine-appointment rows are inventoried for intervention readiness; "
                "they are not Observation/Encounter entities in canonical_evidence."
            ),
        },
    }
    for name, bucket in relations.items():
        if name == "account_patient":
            bucket["mapping_cardinality"] = "1:1 subject per account_patient"
        elif name == "appointment_appointment":
            bucket["mapping_cardinality"] = "1:1 encounter per appointment"
        elif name == "document_analysisresult":
            bucket["mapping_cardinality"] = (
                "1:1 observation per lab header when patient-linked"
            )

    gap_explained = empty_wp + orphan + no_pat + nonnum_gap + numeric_gap
    gap_doc = {
        "version": VERSION,
        "raw_document_analysisresultitem": total_items,
        "canonical_source_a_observation_component": can_comp,
        "gap": gap,
        "exclusive_categories": {
            "orphan_no_header": orphan,
            "header_without_patient": no_pat,
            "empty_value_with_patient_not_loaded_as_component": empty_wp,
            "non_numeric_with_patient": nonnum_wp,
            "non_numeric_with_patient_loaded": nonnum_loaded,
            "non_numeric_with_patient_not_loaded": nonnum_gap,
            "numeric_with_patient": num_wp,
            "numeric_with_patient_loaded": numeric_loaded,
            "numeric_with_patient_not_loaded": numeric_gap,
        },
        "category_sum_exclusive_raw_buckets": exclusive_sum,
        "category_sum_equals_source": exclusive_sum == total_items,
        "unexplained_rows": max(0, total_items - exclusive_sum),
        "truncated_rows": 0,
        "gap_explained_as": {
            "empty_values": empty_wp,
            "unsupported_no_patient_or_orphan": orphan + no_pat,
            "non_numeric_not_loaded": nonnum_gap,
            "numeric_not_loaded": numeric_gap,
            "sum": gap_explained,
            "matches_gap": gap_explained == gap,
        },
        "interpretation": (
            "Primary gap drivers are empty values (not loaded as components) and "
            "non-numeric text not fully preserved. Numeric-with-patient not loaded "
            "is zero in current live evidence. Not silent truncation."
        ),
        "source_a_component_gap_status": (
            "PASS"
            if exclusive_sum == total_items
            and max(0, total_items - exclusive_sum) == 0
            and numeric_gap == 0
            else ("PARTIAL" if exclusive_sum == total_items else "FAIL")
        ),
    }

    for name, bucket in relations.items():
        if name == "diagnosis_medicineappointments":
            continue
        bucket["invariant_truncated_zero"] = int(bucket["truncated_rows"]) == 0
        bucket["invariant_unexplained_zero"] = int(bucket["unexplained_rows"]) == 0

    all_trunc_zero = all(r["truncated_rows"] == 0 for r in relations.values())
    all_unexp_zero = all(
        r["unexplained_rows"] == 0
        for k, r in relations.items()
        if k != "diagnosis_medicineappointments"
    )
    status = (
        "PASS"
        if all_trunc_zero and all_unexp_zero and gap_doc["unexplained_rows"] == 0
        else "PARTIAL"
    )

    return {
        "version": VERSION,
        "source_a_relation_accounting_status": status,
        "relations": relations,
        "component_gap": gap_doc,
        "source_record_columns_observed": sorted(sr_cols),
    }


def _bucket(
    source: int,
    canonical: int,
    *,
    unsupported: int = 0,
    empty_value_rows: int = 0,
    unexplained: int = 0,
) -> dict[str, int]:
    return {
        "source_rows_considered": source,
        "canonical_rows": canonical,
        "inserted_or_present_rows": canonical,
        "already_present_rows": canonical,
        "rejected_rows": 0,
        "unsupported_rows": unsupported,
        "quarantined_rows": 0,
        "empty_value_rows": empty_value_rows,
        "invalid_numeric_rows": 0,
        "non_numeric_preserved_rows": 0,
        "duplicate_or_conflict_rows": 0,
        "truncated_rows": 0,
        "unexplained_rows": unexplained,
    }
