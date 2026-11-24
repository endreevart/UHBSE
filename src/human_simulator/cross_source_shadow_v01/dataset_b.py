"""Source B shadow dataset from canonical (code 53 / пмоль/л)."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_v0121.pairs_b import (
    build_pairs_from_series,
    construct_source_b_pairs,
    fetch_b_t3_series,
    horizon_histogram,
)
from human_simulator.scientific_v02.policy import (
    PREFERRED_B_CODE,
    PREFERRED_B_UNIT,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def build_shadow_b_dataset(conn: Any) -> dict[str, Any]:
    rows = fetch_b_t3_series(conn)
    pairs, exclusions = build_pairs_from_series(rows)
    # Defense: ensure no A subjects
    with conn.cursor() as cur:
        subj = list({p["opaque_subject_key"] for p in pairs})
        a_count = 0
        if subj:
            cur.execute(
                """
                SELECT COUNT(*) FROM canonical_evidence.subject
                WHERE subject_id::text = ANY(%s) AND source_system_id = %s
                """,
                (subj, SOURCE_A_SYSTEM_ID),
            )
            a_count = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s AND oc.raw_code = %s
              AND COALESCE(oc.raw_unit,'') = %s AND oc.numeric_value IS NOT NULL
            """,
            (SOURCE_B_SYSTEM_ID, PREFERRED_B_CODE, PREFERRED_B_UNIT),
        )
        n_numeric = int(cur.fetchone()[0])

    horizons_ok = all(float(p["horizon_days"]) > 0 for p in pairs)
    report = {
        "version": VERSION,
        "source_b_shadow_dataset_status": "BUILT" if pairs else "INSUFFICIENT_DATA",
        "stratum": {
            "source_system": SOURCE_B_SYSTEM_ID,
            "source_catalog_code": PREFERRED_B_CODE,
            "raw_unit": PREFERRED_B_UNIT,
            "provisional": True,
        },
        "n_numeric_components": n_numeric,
        "n_subjects_with_pairs": len({p["opaque_subject_key"] for p in pairs}),
        "n_strict_consecutive_pairs": len(pairs),
        "all_horizons_positive": horizons_ok,
        "source_a_subjects_in_b_pairs": a_count,
        "identity_merge": False,
        "horizon_histogram": horizon_histogram(pairs),
        "exclusions": exclusions,
    }
    accounting = {
        "version": VERSION,
        "n_numeric_components": n_numeric,
        "n_subjects_with_pairs": report["n_subjects_with_pairs"],
        "n_pairs": len(pairs),
        "exclusions": exclusions,
        "pair_definition": "strict_consecutive_neighbors_only",
    }
    provenance = {
        "version": VERSION,
        "source_system": SOURCE_B_SYSTEM_ID,
        "source_a_rows": a_count,
        "raw_identifiers_in_artifact": False,
        "header_only_excluded": True,
        "identity_merge": False,
    }
    return {
        "report": report,
        "accounting": accounting,
        "provenance": provenance,
        "_runtime_pairs": pairs,
    }
