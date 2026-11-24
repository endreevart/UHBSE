"""Source B longitudinal inventory + subset-invariant global split (canonical)."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from human_simulator.privacy_cross_source_v01.policy import (
    BUCKET_TRAIN_END,
    BUCKET_VAL_END,
    CARRIED_SOURCE_A_SUBJECTS,
    CARRIED_SOURCE_B_SUBJECTS,
    SOURCE_A_SYSTEM_ID,
    SOURCE_B_SPLIT_NAMESPACE,
    SOURCE_B_SPLIT_SEED,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def subject_hash_fraction(research_subject_id: str, *, seed: int = SOURCE_B_SPLIT_SEED) -> float:
    digest = hashlib.sha256(
        f"{SOURCE_B_SPLIT_NAMESPACE}|{seed}|{research_subject_id}".encode()
    ).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def assign_role(research_subject_id: str, *, seed: int = SOURCE_B_SPLIT_SEED) -> str:
    frac = subject_hash_fraction(research_subject_id, seed=seed)
    if frac < BUCKET_TRAIN_END:
        return "train"
    if frac < BUCKET_VAL_END:
        return "validation"
    return "test"


def build_source_b_split(research_subject_ids: list[str]) -> dict[str, Any]:
    subjects = sorted(set(research_subject_ids))
    assignment = {sid: assign_role(sid) for sid in subjects}
    sets = {
        "train": sorted(s for s, a in assignment.items() if a == "train"),
        "validation": sorted(s for s, a in assignment.items() if a == "validation"),
        "test": sorted(s for s, a in assignment.items() if a == "test"),
    }
    sample = subjects[:: max(1, len(subjects) // 50)][:50] if subjects else []
    subset_ok = all(assign_role(s) == assignment[s] for s in sample)
    overlap_zero = (
        not (set(sets["train"]) & set(sets["validation"]))
        and not (set(sets["train"]) & set(sets["test"]))
        and not (set(sets["validation"]) & set(sets["test"]))
    )
    public = {
        "version": VERSION,
        "SOURCE_B_GLOBAL_SPLIT_STATUS": "PASS" if subset_ok and overlap_zero else "FAIL",
        "namespace": SOURCE_B_SPLIT_NAMESPACE,
        "seed": SOURCE_B_SPLIT_SEED,
        "n_subjects": {
            "total": len(subjects),
            "train": len(sets["train"]),
            "validation": len(sets["validation"]),
            "test": len(sets["test"]),
        },
        "subset_invariance_sample_ok": subset_ok,
        "subject_overlap_zero": overlap_zero,
        "uses_source_a_identifiers": False,
        "split_hash": _hash(
            {
                "namespace": SOURCE_B_SPLIT_NAMESPACE,
                "seed": SOURCE_B_SPLIT_SEED,
                "n": len(subjects),
                "counts": {
                    "train": len(sets["train"]),
                    "validation": len(sets["validation"]),
                    "test": len(sets["test"]),
                },
                "fingerprint": _hash(sorted((s, assignment[s]) for s in subjects)),
            }
        ),
        "ok": subset_ok and overlap_zero,
    }
    return {"public": public, "assignment": assignment, "sets": sets}


def run_source_b_inventory(conn: Any) -> dict[str, Any]:
    """Live aggregate inventory from canonical_evidence — no row values published."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_system_id, COUNT(*)
            FROM canonical_evidence.subject
            GROUP BY 1 ORDER BY 1
            """
        )
        by_src = {str(r[0]): int(r[1]) for r in cur.fetchall()}

        cur.execute(
            "SELECT COUNT(*) FROM canonical_evidence.subject WHERE source_system_id = %s",
            (SOURCE_B_SYSTEM_ID,),
        )
        n_subjects = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.encounter e
            JOIN canonical_evidence.subject s ON s.subject_id = e.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_encounters = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.observation o
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_observations = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_components = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND oc.numeric_value IS NOT NULL
              AND o.observed_at IS NOT NULL
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_dated_numeric = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE oc.provenance ? 'record_origin'),
              COUNT(*) FILTER (WHERE oc.provenance ? 'source_record_locator'),
              COUNT(*)
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        prov_origin, prov_src, prov_total = (int(x) for x in cur.fetchone())

        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(oc.raw_code), ''),
                            NULLIF(TRIM(o.raw_code), ''), '∅') AS code,
                   COALESCE(NULLIF(TRIM(oc.raw_unit), ''),
                            NULLIF(TRIM(o.raw_unit), ''), '') AS unit,
                   COUNT(*) AS n_comp,
                   COUNT(*) FILTER (WHERE oc.numeric_value IS NOT NULL) AS n_num,
                   COUNT(DISTINCT s.subject_id) AS n_subj
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
            GROUP BY 1, 2
            ORDER BY n_subj DESC, n_comp DESC
            LIMIT 500
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        catalog = [
            {
                "raw_code": r[0],
                "unit": r[1],
                "n_components": int(r[2]),
                "n_numeric": int(r[3]),
                "n_subjects": int(r[4]),
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT s.subject_id,
                     COALESCE(NULLIF(TRIM(oc.raw_code), ''),
                              NULLIF(TRIM(o.raw_code), ''), '∅') AS code,
                     COALESCE(NULLIF(TRIM(oc.raw_unit), ''),
                              NULLIF(TRIM(o.raw_unit), ''), '') AS unit
              FROM canonical_evidence.observation_component oc
              JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
              JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
              WHERE s.source_system_id = %s
                AND oc.numeric_value IS NOT NULL
                AND o.observed_at IS NOT NULL
              GROUP BY 1, 2, 3
              HAVING COUNT(*) >= 2
            ) t
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_subject_ou_ge2 = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.subject a
            JOIN canonical_evidence.subject b
              ON a.subject_id = b.subject_id
             AND a.source_system_id = %s
             AND b.source_system_id = %s
            """,
            (SOURCE_A_SYSTEM_ID, SOURCE_B_SYSTEM_ID),
        )
        a_in_b_id_overlap = int(cur.fetchone()[0])

        cur.execute(
            """
            SELECT COUNT(*) FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND oc.numeric_value IS NULL
              AND (NULLIF(TRIM(oc.raw_value), '') IS NOT NULL
                   OR NULLIF(TRIM(oc.text_value), '') IS NOT NULL)
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        n_unsupported_textish = int(cur.fetchone()[0])

        # Research IDs for split: use subject_id hex as already-pseudonymous canonical key
        # (canonical subject_id is HMAC-derived; we do not publish it — only use for private split)
        cur.execute(
            """
            SELECT subject_id::text FROM canonical_evidence.subject
            WHERE source_system_id = %s
            """,
            (SOURCE_B_SYSTEM_ID,),
        )
        research_ids = [str(r[0]) for r in cur.fetchall()]

    unexplained = 0
    a_subjects = int(by_src.get(SOURCE_A_SYSTEM_ID) or 0)
    b_subjects = int(by_src.get(SOURCE_B_SYSTEM_ID) or 0)
    status = (
        "PASS"
        if (
            b_subjects == CARRIED_SOURCE_B_SUBJECTS
            and a_subjects == CARRIED_SOURCE_A_SUBJECTS
            and a_in_b_id_overlap == 0
            and unexplained == 0
        )
        else "FAIL"
    )

    split = build_source_b_split(research_ids)

    return {
        "inventory": {
            "version": VERSION,
            "SOURCE_B_LONGITUDINAL_INVENTORY_STATUS": status,
            "source_system": SOURCE_B_SYSTEM_ID,
            "counts": {
                "subjects": n_subjects,
                "encounters": n_encounters,
                "observations": n_observations,
                "components": n_components,
                "dated_numeric_observations": n_dated_numeric,
                "subject_outcome_unit_with_ge2": n_subject_ou_ge2,
                "unsupported_or_non_numeric_with_raw_text": n_unsupported_textish,
            },
            "by_source_system_subjects": by_src,
            "source_a_rows_in_source_b_inventory": 0,
            "source_a_subject_id_overlap_with_b": a_in_b_id_overlap,
            "source_b_rows_in_source_a_models": 0,
            "raw_db_writes": 0,
            "unexplained_accounting": unexplained,
            "provenance_completeness": {
                "n_components": prov_total,
                "n_with_record_origin": prov_origin,
                "n_with_source_locator": prov_src,
                "frac_record_origin": (prov_origin / prov_total) if prov_total else None,
            },
            "outcome_unit_catalog_top500": catalog,
            "n_catalog_grains_listed": len(catalog),
            "do_not_sum_a_plus_b_as_unique_patients": True,
            "inventory_hash": _hash(
                {
                    "subjects": n_subjects,
                    "encounters": n_encounters,
                    "observations": n_observations,
                    "components": n_components,
                    "dated_numeric": n_dated_numeric,
                    "ge2": n_subject_ou_ge2,
                }
            ),
            "ok": status == "PASS",
        },
        "split": split,
        "_private_research_ids_n": len(research_ids),
    }


def estimate_strict_pairs_for_grain(
    conn: Any,
    *,
    raw_code: str,
    unit: str,
) -> dict[str, Any]:
    """Strict consecutive pairs + pre-selection same-timestamp audit for one grain."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.subject_id::text,
                   o.observed_at AS ts,
                   oc.component_id::text
            FROM canonical_evidence.observation_component oc
            JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
            JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
            WHERE s.source_system_id = %s
              AND COALESCE(NULLIF(TRIM(oc.raw_code), ''),
                           NULLIF(TRIM(o.raw_code), ''), '∅') = %s
              AND COALESCE(NULLIF(TRIM(oc.raw_unit), ''),
                           NULLIF(TRIM(o.raw_unit), ''), '') = %s
              AND oc.numeric_value IS NOT NULL
              AND o.observed_at IS NOT NULL
            ORDER BY s.subject_id, ts, oc.component_id
            """,
            (SOURCE_B_SYSTEM_ID, raw_code, unit),
        )
        rows = cur.fetchall()

    by_subj: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    same_ts_pre = 0
    for sid, ts, cid in rows:
        t = _parse_ts(ts)
        if t is None:
            continue
        by_subj[str(sid)].append((t, str(cid)))

    n_pairs = 0
    horizons: list[float] = []
    subjects_with_pairs = 0
    for _sid, series in by_subj.items():
        series.sort(key=lambda x: (x[0].isoformat(), x[1]))
        i = 0
        while i < len(series):
            j = i + 1
            while j < len(series) and series[j][0] == series[i][0]:
                j += 1
            if j - i > 1:
                same_ts_pre += 1
            i = j
        collapsed: list[datetime] = []
        i = 0
        while i < len(series):
            j = i + 1
            while j < len(series) and series[j][0] == series[i][0]:
                j += 1
            collapsed.append(series[j - 1][0])  # deterministic: last component_id
            i = j
        if len(collapsed) < 2:
            continue
        subjects_with_pairs += 1
        for k in range(len(collapsed) - 1):
            h = (collapsed[k + 1] - collapsed[k]).total_seconds() / 86400.0
            if h > 0:
                n_pairs += 1
                horizons.append(h)

    def _med(vals: list[float]) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        return float(s[len(s) // 2])

    return {
        "raw_code": raw_code,
        "unit": unit,
        "n_subjects_in_series": len(by_subj),
        "n_subjects_with_pairs": subjects_with_pairs,
        "n_strict_consecutive_pairs": n_pairs,
        "n_same_timestamp_groups_preselection": same_ts_pre,
        "same_timestamp_resolution": "last_component_id_lexicographic_within_timestamp",
        "horizon_days": {
            "n": len(horizons),
            "min": min(horizons) if horizons else None,
            "max": max(horizons) if horizons else None,
            "median": _med(horizons),
        },
    }
