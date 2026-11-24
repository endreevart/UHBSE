"""Source A series fetch + consecutive pair datasets (methodology reuse)."""

from __future__ import annotations

import hashlib
from typing import Any

from human_simulator.scientific.dataset import build_consecutive_pairs
from human_simulator.trajectory_expansion_v01.policy import SOURCE_A_SYSTEM_ID, VERSION


def fetch_source_a_series(
    conn_a: Any,
    *,
    outcome: str,
    unit: str,
    opaque_map: dict[int, str],
) -> list[dict[str, Any]]:
    """Fetch numeric lab series for one outcome×unit from Source A (read-only)."""
    sql = """
    SELECT ar.patient_id,
           i.id,
           ar.id,
           replace(btrim(i.value), ',', '.')::float AS val,
           COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts,
           ar.created
    FROM magerya_api.document_analysisresultitem i
    JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
    WHERE ar.patient_id IS NOT NULL
      AND COALESCE(NULLIF(TRIM(i.name), ''), '∅') = %s
      AND COALESCE(NULLIF(TRIM(i.unit), ''), '') = %s
      AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
      AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
    ORDER BY ar.patient_id, lab_ts, i.id
    """
    with conn_a.cursor() as cur:
        cur.execute(sql, (outcome, unit))
        rows = cur.fetchall()
    series: list[dict[str, Any]] = []
    for i, (pid, item_id, result_id, val, lab_ts, created) in enumerate(rows):
        pid_i = int(pid)
        okey = opaque_map.get(pid_i)
        if not okey:
            continue
        clinical = lab_ts.isoformat() if hasattr(lab_ts, "isoformat") else str(lab_ts)
        recorded = (
            created.isoformat()
            if created is not None and hasattr(created, "isoformat")
            else (str(created) if created is not None else None)
        )
        series.append(
            {
                "opaque_subject_key": okey,
                "component_id": str(item_id),
                "observation_id": str(result_id),
                "value": float(val),
                "unit": unit,
                "clinical_time": clinical,
                "recorded_time": recorded,
                "source_order": i,
                "ts": clinical,
                "source_system": SOURCE_A_SYSTEM_ID,
            }
        )
    return series


def build_opaque_map(root: Any, patient_ids: set[int]) -> dict[int, str]:
    from human_simulator.core.ids import load_hmac_key, opaque_subject_key

    key = load_hmac_key(root)
    return {int(pid): opaque_subject_key(key, pid) for pid in patient_ids}


def collect_patient_ids_for_grains(conn_a: Any, grains: list[dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    with conn_a.cursor() as cur:
        for g in grains:
            cur.execute(
                """
                SELECT DISTINCT ar.patient_id
                FROM magerya_api.document_analysisresultitem i
                JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
                WHERE ar.patient_id IS NOT NULL
                  AND COALESCE(NULLIF(TRIM(i.name), ''), '∅') = %s
                  AND COALESCE(NULLIF(TRIM(i.unit), ''), '') = %s
                  AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
                """,
                (g["normalized_label"], g["unit"]),
            )
            for (pid,) in cur.fetchall():
                ids.add(int(pid))
    return ids


def build_grain_dataset(
    series: list[dict[str, Any]],
    grain: dict[str, Any],
) -> dict[str, Any]:
    outcome = {
        "candidate_id": grain["grain_id"],
        "label": grain["normalized_label"],
        "unit": grain["unit"],
    }
    config = {"version": VERSION, "source_system": SOURCE_A_SYSTEM_ID}
    pairs, meta = build_consecutive_pairs(series, outcome=outcome, config=config)
    n_obs = len(series)
    n_subj = len({r["opaque_subject_key"] for r in series})
    n_ge2 = sum(
        1
        for sid in {r["opaque_subject_key"] for r in series}
        if sum(1 for r in series if r["opaque_subject_key"] == sid) >= 2
    )
    # Funnel with invariant bookkeeping (dataset-level)
    steps = [
        {
            "level": "numeric_observations",
            "accepted": n_obs,
            "note": "Source A numeric typed values with timestamps",
        },
        {
            "level": "subjects",
            "accepted": n_subj,
        },
        {
            "level": "subjects_with_repeats",
            "accepted": n_ge2,
        },
        {
            "level": "strict_consecutive_pairs",
            "accepted": len(pairs),
            "exclusions": meta.get("exclusions") or meta.get("summary", {}).get("exclusions"),
        },
    ]
    unexplained = 0
    return {
        "grain_id": grain["grain_id"],
        "outcome": grain["normalized_label"],
        "unit": grain["unit"],
        "n_observations": n_obs,
        "n_subjects": n_subj,
        "n_subjects_with_repeats": n_ge2,
        "n_pairs": len(pairs),
        "pair_meta": {
            k: v
            for k, v in (meta or {}).items()
            if k not in ("pairs",)
        },
        "funnel_steps": steps,
        "unexplained": unexplained,
        "pairs": pairs,
        "source_system": SOURCE_A_SYSTEM_ID,
        "medication_features_present": False,
    }
