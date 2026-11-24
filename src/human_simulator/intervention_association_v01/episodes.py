"""Row-level technical medication episode dataset (workspace-only)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

from human_simulator.intervention_association_v01.hierarchy import build_hierarchy_summary
from human_simulator.intervention_association_v01.policy import (
    HORIZONS_DAYS,
    PRIMARY_HORIZON_DAYS,
    RUNTIME_DIR,
    VERSION,
)

TIMESTAMP_HYPOTHESES = {
    "appointment_date": {
        "column": "appointment_date",
        "status": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
        "role": "primary_candidate",
    },
    "created": {
        "column": "created",
        "status": "RECORD_CREATION_TIMESTAMP_SENSITIVITY_CONTROL",
        "role": "sensitivity_control",
    },
}


def episode_id(
    *,
    opaque_subject_key: str,
    medicine_id: str,
    event_ts: str,
    outcome: str,
    unit: str,
    hypothesis: str,
    horizon_days: int,
) -> str:
    payload = "|".join(
        [
            opaque_subject_key,
            str(medicine_id),
            event_ts,
            outcome,
            unit,
            hypothesis,
            str(horizon_days),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _opaque_map(root: Path, patient_ids: set[int]) -> dict[int, str]:
    from human_simulator.core.ids import load_hmac_key, opaque_subject_key

    key = load_hmac_key(root)
    return {int(pid): opaque_subject_key(key, pid) for pid in patient_ids}


def _fetch_level_counts(conn_a: Any, ts_col: str) -> dict[str, int]:
    with conn_a.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM magerya_api.diagnosis_medicineappointments")
        level0 = int(cur.fetchone()[0])
        cur.execute(
            f"""
            SELECT COUNT(*) FROM magerya_api.diagnosis_medicineappointments
            WHERE patient_id IS NOT NULL AND medicine_id IS NOT NULL AND {ts_col} IS NOT NULL
            """
        )
        level1 = int(cur.fetchone()[0])
        cur.execute(
            f"""
            WITH med AS (
              SELECT id, patient_id, {ts_col} AS event_ts
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND {ts_col} IS NOT NULL AND medicine_id IS NOT NULL
            ),
            lab AS (
              SELECT ar.patient_id,
                     COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts
              FROM magerya_api.document_analysisresult ar
              WHERE ar.patient_id IS NOT NULL
                AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
            ),
            flagged AS (
              SELECT m.id,
                     BOOL_OR(l.lab_ts < m.event_ts) AS has_pre,
                     BOOL_OR(l.lab_ts > m.event_ts) AS has_post
              FROM med m LEFT JOIN lab l ON l.patient_id = m.patient_id
              GROUP BY m.id
            )
            SELECT COUNT(*) FILTER (WHERE has_pre AND has_post) FROM flagged
            """
        )
        level2 = int(cur.fetchone()[0])
        cur.execute(
            f"""
            WITH med AS (
              SELECT id, patient_id, {ts_col} AS event_ts
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND medicine_id IS NOT NULL AND {ts_col} IS NOT NULL
            ),
            items AS (
              SELECT ar.patient_id,
                     COALESCE(NULLIF(TRIM(i.name), ''), '∅') AS outcome,
                     COALESCE(NULLIF(TRIM(i.unit), ''), '') AS unit,
                     COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts
              FROM magerya_api.document_analysisresultitem i
              JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
              WHERE ar.patient_id IS NOT NULL
                AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
                AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
            ),
            linked AS (
              SELECT m.id, m.patient_id, i.outcome, i.unit,
                     BOOL_OR(i.lab_ts < m.event_ts) AS has_pre,
                     BOOL_OR(i.lab_ts > m.event_ts) AS has_post
              FROM med m JOIN items i ON i.patient_id = m.patient_id
              GROUP BY m.id, m.patient_id, i.outcome, i.unit
            )
            SELECT COUNT(*) FILTER (WHERE has_pre AND has_post),
                   COUNT(DISTINCT id) FILTER (WHERE has_pre AND has_post),
                   COUNT(DISTINCT patient_id) FILTER (WHERE has_pre AND has_post)
            FROM linked
            """
        )
        l3_pairs, l3_events, l3_subj = (int(x) for x in cur.fetchone())
        cur.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT patient_id, ({ts_col})::date AS d, COUNT(DISTINCT medicine_id) AS n
              FROM magerya_api.diagnosis_medicineappointments
              WHERE patient_id IS NOT NULL AND {ts_col} IS NOT NULL AND medicine_id IS NOT NULL
              GROUP BY 1, 2 HAVING COUNT(DISTINCT medicine_id) > 1
            ) t
            """
        )
        poly_days = int(cur.fetchone()[0])
    return {
        "level0": level0,
        "level1": level1,
        "level2": level2,
        "level3_pairs": l3_pairs,
        "level3_events": l3_events,
        "level3_subjects": l3_subj,
        "polypharmacy_event_days": poly_days,
    }


def _count_episodes(
    conn_a: Any, *, ts_col: str, horizon_days: int
) -> tuple[int, int, int, int, int]:
    """Aggregate-only Level-4 counts without materialising rows."""
    sql = f"""
    WITH med AS (
      SELECT id, patient_id, {ts_col} AS event_ts, medicine_id
      FROM magerya_api.diagnosis_medicineappointments
      WHERE patient_id IS NOT NULL AND medicine_id IS NOT NULL AND {ts_col} IS NOT NULL
    ),
    poly AS (
      SELECT patient_id, event_ts::date AS d, COUNT(DISTINCT medicine_id) AS n_med
      FROM med GROUP BY 1, 2
    ),
    items AS (
      SELECT ar.patient_id,
             COALESCE(NULLIF(TRIM(i.name), ''), '∅') AS outcome,
             COALESCE(NULLIF(TRIM(i.unit), ''), '') AS unit,
             COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts,
             replace(btrim(i.value), ',', '.')::float AS val
      FROM magerya_api.document_analysisresultitem i
      JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
      WHERE ar.patient_id IS NOT NULL
        AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
        AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
    ),
    ranked AS (
      SELECT m.id AS med_id, m.patient_id, m.event_ts, m.medicine_id,
             i.outcome, i.unit, i.lab_ts, i.val,
             CASE WHEN i.lab_ts < m.event_ts
                   AND i.lab_ts >= m.event_ts - (%s || ' days')::interval THEN 1 ELSE 0 END AS is_pre,
             CASE WHEN i.lab_ts > m.event_ts
                   AND i.lab_ts <= m.event_ts + (%s || ' days')::interval THEN 1 ELSE 0 END AS is_post,
             CASE WHEN i.lab_ts = m.event_ts THEN 1 ELSE 0 END AS is_same
      FROM med m JOIN items i ON i.patient_id = m.patient_id
    ),
    picked AS (
      SELECT med_id, patient_id, event_ts, medicine_id, outcome, unit,
        (ARRAY_AGG(val ORDER BY lab_ts DESC) FILTER (WHERE is_pre=1))[1] AS pre_val,
        (ARRAY_AGG(lab_ts ORDER BY lab_ts DESC) FILTER (WHERE is_pre=1))[1] AS pre_ts,
        (ARRAY_AGG(val ORDER BY lab_ts ASC) FILTER (WHERE is_post=1))[1] AS post_val,
        (ARRAY_AGG(lab_ts ORDER BY lab_ts ASC) FILTER (WHERE is_post=1))[1] AS post_ts,
        BOOL_OR(is_same=1) AS had_same_time
      FROM ranked
      GROUP BY 1,2,3,4,5,6
    ),
    ok AS (
      SELECT p.*, COALESCE(poly.n_med, 1) AS concurrent_med_count
      FROM picked p
      LEFT JOIN poly ON poly.patient_id = p.patient_id AND poly.d = p.event_ts::date
      WHERE p.pre_val IS NOT NULL AND p.post_val IS NOT NULL
        AND p.pre_ts < p.event_ts AND p.event_ts < p.post_ts
    )
    SELECT COUNT(*),
           COUNT(DISTINCT patient_id),
           COUNT(DISTINCT (outcome, unit)),
           COUNT(*) FILTER (WHERE concurrent_med_count > 1),
           COUNT(*) FILTER (WHERE had_same_time)
    FROM ok
    """
    with conn_a.cursor() as cur:
        cur.execute(sql, (str(horizon_days), str(horizon_days)))
        row = cur.fetchone()
    return tuple(int(x or 0) for x in row)  # type: ignore[return-value]


def iter_materialised_episodes(
    conn_a: Any,
    *,
    ts_col: str,
    horizon_days: int,
) -> Iterator[dict[str, Any]]:
    """Yield Level-4 episodes with strict pre < event < post within horizon."""
    sql = f"""
    WITH med AS (
      SELECT id, patient_id, {ts_col} AS event_ts, medicine_id
      FROM magerya_api.diagnosis_medicineappointments
      WHERE patient_id IS NOT NULL AND medicine_id IS NOT NULL AND {ts_col} IS NOT NULL
    ),
    poly AS (
      SELECT patient_id, event_ts::date AS d, COUNT(DISTINCT medicine_id) AS n_med
      FROM med
      GROUP BY 1, 2
    ),
    items AS (
      SELECT ar.patient_id,
             COALESCE(NULLIF(TRIM(i.name), ''), '∅') AS outcome,
             COALESCE(NULLIF(TRIM(i.unit), ''), '') AS unit,
             COALESCE(ar.sampling_date, ar.appointment_date, ar.created) AS lab_ts,
             replace(btrim(i.value), ',', '.')::float AS val,
             i.id AS item_id
      FROM magerya_api.document_analysisresultitem i
      JOIN magerya_api.document_analysisresult ar ON ar.id = i.analysis_result_id
      WHERE ar.patient_id IS NOT NULL
        AND i.value ~ '^-?[0-9]+([.,][0-9]+)?$'
        AND COALESCE(ar.sampling_date, ar.appointment_date, ar.created) IS NOT NULL
    ),
    ranked AS (
      SELECT m.id AS med_id, m.patient_id, m.event_ts, m.medicine_id,
             i.outcome, i.unit, i.lab_ts, i.val, i.item_id,
             CASE WHEN i.lab_ts < m.event_ts
                   AND i.lab_ts >= m.event_ts - (%s || ' days')::interval
                  THEN 1 ELSE 0 END AS is_pre,
             CASE WHEN i.lab_ts > m.event_ts
                   AND i.lab_ts <= m.event_ts + (%s || ' days')::interval
                  THEN 1 ELSE 0 END AS is_post,
             CASE WHEN i.lab_ts = m.event_ts THEN 1 ELSE 0 END AS is_same
      FROM med m
      JOIN items i ON i.patient_id = m.patient_id
    ),
    picked AS (
      SELECT med_id, patient_id, event_ts, medicine_id, outcome, unit,
        (ARRAY_AGG(val ORDER BY lab_ts DESC) FILTER (WHERE is_pre=1))[1] AS pre_val,
        (ARRAY_AGG(lab_ts ORDER BY lab_ts DESC) FILTER (WHERE is_pre=1))[1] AS pre_ts,
        (ARRAY_AGG(item_id ORDER BY lab_ts DESC) FILTER (WHERE is_pre=1))[1] AS pre_item,
        (ARRAY_AGG(val ORDER BY lab_ts ASC) FILTER (WHERE is_post=1))[1] AS post_val,
        (ARRAY_AGG(lab_ts ORDER BY lab_ts ASC) FILTER (WHERE is_post=1))[1] AS post_ts,
        (ARRAY_AGG(item_id ORDER BY lab_ts ASC) FILTER (WHERE is_post=1))[1] AS post_item,
        COUNT(*) FILTER (WHERE is_pre=1) AS n_prior_in_window,
        COUNT(*) FILTER (WHERE is_same=1) AS n_same_time,
        BOOL_OR(is_same=1) AS had_same_time
      FROM ranked
      GROUP BY 1,2,3,4,5,6
    )
    SELECT p.med_id, p.patient_id, p.event_ts, p.medicine_id, p.outcome, p.unit,
           p.pre_val, p.pre_ts, p.pre_item, p.post_val, p.post_ts, p.post_item,
           p.n_prior_in_window, p.n_same_time, p.had_same_time,
           COALESCE(poly.n_med, 1) AS concurrent_med_count
    FROM picked p
    LEFT JOIN poly ON poly.patient_id = p.patient_id AND poly.d = p.event_ts::date
    WHERE p.pre_val IS NOT NULL AND p.post_val IS NOT NULL
      AND p.pre_ts < p.event_ts AND p.event_ts < p.post_ts
    """
    with conn_a.cursor() as cur:
        cur.execute(sql, (str(horizon_days), str(horizon_days)))
        while True:
            rows = cur.fetchmany(5000)
            if not rows:
                break
            for row in rows:
                yield {
                    "med_id": int(row[0]),
                    "patient_id": int(row[1]),
                    "event_ts": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
                    "medicine_id": str(row[3]),
                    "outcome": str(row[4]),
                    "unit": str(row[5]),
                    "pre_value": float(row[6]),
                    "pre_ts": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
                    "pre_item_id": int(row[8]) if row[8] is not None else None,
                    "post_value": float(row[9]),
                    "post_ts": row[10].isoformat() if hasattr(row[10], "isoformat") else str(row[10]),
                    "post_item_id": int(row[11]) if row[11] is not None else None,
                    "n_prior_measurements": int(row[12] or 0),
                    "n_same_time": int(row[13] or 0),
                    "had_same_time": bool(row[14]),
                    "concurrent_med_count": int(row[15] or 1),
                    "horizon_days": horizon_days,
                }


def build_episode_datasets(root: Path, conn_a: Any) -> dict[str, Any]:
    """Materialise workspace-only episodes; publish only aggregates."""
    root = Path(root).resolve()
    out_dir = root / RUNTIME_DIR / "episodes"
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries: dict[str, Any] = {}
    same_time_excluded_total = 0

    for hyp_name, hyp in TIMESTAMP_HYPOTHESES.items():
        ts_col = hyp["column"]
        counts = _fetch_level_counts(conn_a, ts_col)
        hyp_summary: dict[str, Any] = {
            "timestamp_hypothesis": hyp_name,
            "timestamp_status": hyp["status"],
            "role": hyp["role"],
            "level_counts": counts,
            "horizons": {},
        }
        for horizon in HORIZONS_DAYS:
            # Full row-level materialisation only for primary horizon (workspace-only).
            # Other horizons: aggregate SQL counts for sensitivity (no jsonl).
            if horizon != PRIMARY_HORIZON_DAYS:
                n_ep, n_subj, n_ou, poly_flags, same_time = _count_episodes(
                    conn_a, ts_col=ts_col, horizon_days=horizon
                )
                hyp_summary["horizons"][str(horizon)] = {
                    "n_episodes": n_ep,
                    "n_subjects": n_subj,
                    "n_outcome_units": n_ou,
                    "polypharmacy_episodes": poly_flags,
                    "same_time_seen_but_pre_post_strict": same_time,
                    "workspace_path": None,
                    "materialised": False,
                    "in_review_zip": False,
                }
                continue

            path = out_dir / f"episodes_{hyp_name}_h{horizon}.jsonl"
            n_ep = 0
            same_time = 0
            poly_flags = 0
            outcomes: set[tuple[str, str]] = set()
            patient_ids: set[int] = set()
            raw_rows: list[dict[str, Any]] = []

            for raw in iter_materialised_episodes(
                conn_a, ts_col=ts_col, horizon_days=horizon
            ):
                patient_ids.add(raw["patient_id"])
                raw_rows.append(raw)

            opaque = _opaque_map(root, patient_ids)
            subj_keys: set[str] = set()
            from datetime import datetime

            def _parse(ts: str) -> datetime:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))

            with path.open("w", encoding="utf-8") as fh:
                for raw in raw_rows:
                    okey = opaque[raw["patient_id"]]
                    pre_loc = (
                        hashlib.sha256(f"item:{raw['pre_item_id']}".encode()).hexdigest()[:16]
                        if raw["pre_item_id"] is not None
                        else None
                    )
                    post_loc = (
                        hashlib.sha256(f"item:{raw['post_item_id']}".encode()).hexdigest()[:16]
                        if raw["post_item_id"] is not None
                        else None
                    )
                    med_loc = hashlib.sha256(f"med:{raw['med_id']}".encode()).hexdigest()[:16]
                    eid = episode_id(
                        opaque_subject_key=okey,
                        medicine_id=raw["medicine_id"],
                        event_ts=raw["event_ts"],
                        outcome=raw["outcome"],
                        unit=raw["unit"],
                        hypothesis=hyp_name,
                        horizon_days=horizon,
                    )
                    pre_dt = _parse(raw["pre_ts"])
                    ev_dt = _parse(raw["event_ts"])
                    post_dt = _parse(raw["post_ts"])
                    assert pre_dt < ev_dt < post_dt
                    days_pre = (ev_dt - pre_dt).total_seconds() / 86400.0
                    days_post = (post_dt - ev_dt).total_seconds() / 86400.0
                    poly = int(raw["concurrent_med_count"] > 1)
                    if raw["had_same_time"]:
                        same_time += 1
                    if poly:
                        poly_flags += 1
                    ep = {
                        "episode_id": eid,
                        "opaque_subject_key": okey,
                        "medicine_id": raw["medicine_id"],
                        "medicine_id_hash": hashlib.sha256(
                            raw["medicine_id"].encode()
                        ).hexdigest()[:16],
                        "medication_event_locator_hash": med_loc,
                        "timestamp_hypothesis": hyp_name,
                        "event_ts": raw["event_ts"],
                        "outcome": raw["outcome"],
                        "unit": raw["unit"],
                        "pre_value": raw["pre_value"],
                        "pre_ts": raw["pre_ts"],
                        "post_value": raw["post_value"],
                        "post_ts": raw["post_ts"],
                        "pre_locator_hash": pre_loc,
                        "post_locator_hash": post_loc,
                        "n_prior_measurements": raw["n_prior_measurements"],
                        "prior_slope": None,
                        "days_since_previous": days_pre,
                        "pre_to_event_days": days_pre,
                        "event_to_post_days": days_post,
                        "horizon_days": horizon,
                        "polypharmacy_flag": poly,
                        "concurrent_med_count": raw["concurrent_med_count"],
                        "same_time_measurement_seen": raw["had_same_time"],
                        "exclusion_reason": None,
                    }
                    fh.write(json.dumps(ep, sort_keys=True) + "\n")
                    n_ep += 1
                    subj_keys.add(okey)
                    outcomes.add((raw["outcome"], raw["unit"]))

            same_time_excluded_total += same_time
            hyp_summary["horizons"][str(horizon)] = {
                "n_episodes": n_ep,
                "n_subjects": len(subj_keys),
                "n_outcome_units": len(outcomes),
                "polypharmacy_episodes": poly_flags,
                "same_time_seen_but_pre_post_strict": same_time,
                "workspace_path": str(path.relative_to(root)),
                "materialised": True,
                "in_review_zip": False,
            }
            hyp_summary["primary"] = hyp_summary["horizons"][str(horizon)]

        # Hierarchy for primary horizon
        prim = hyp_summary["horizons"][str(PRIMARY_HORIZON_DAYS)]
        hyp_summary["hierarchy"] = build_hierarchy_summary(
            level0=counts["level0"],
            level1=counts["level1"],
            level2=counts["level2"],
            level3_pairs=counts["level3_pairs"],
            level3_events=counts["level3_events"],
            level3_subjects=counts["level3_subjects"],
            level4_episodes=prim["n_episodes"],
            level4_subjects=prim["n_subjects"],
            level5_episodes=0,  # filled after gates/split
            level5_subjects=0,
            timestamp_hypothesis=hyp_name,
            timestamp_status=hyp["status"],
            polypharmacy_event_days=counts["polypharmacy_event_days"],
            same_time_excluded=prim["same_time_seen_but_pre_post_strict"],
        )
        summaries[hyp_name] = hyp_summary

    status = "BUILT" if any(
        s["horizons"][str(PRIMARY_HORIZON_DAYS)]["n_episodes"] > 0 for s in summaries.values()
    ) else "NOT_BUILT"

    return {
        "version": VERSION,
        "MEDICATION_EPISODE_DATASET_STATUS": status,
        "MEDICATION_EVENT_TIMESTAMP_STATUS": (
            "TECHNICAL_HYPOTHESES_EVALUATED_DOMAIN_CONFIRMATION_PENDING"
        ),
        "workspace_only": True,
        "not_in_review_zip": True,
        "hypotheses": summaries,
        "same_time_policy": "excluded_from_pre_and_post_selection; flagged if observed",
        "strict_temporal_order": "pre < event < post",
        "population": "full Source A account_patient considered via medicine rows",
    }
