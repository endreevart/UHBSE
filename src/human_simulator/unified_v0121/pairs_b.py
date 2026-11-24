"""Source B strict consecutive pairs for code=53 unit=пмоль/л (aggregates only)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from human_simulator.unified_v0121.policy import (
    MIN_B_PAIRS,
    MIN_B_SUBJECTS_WITH_PAIRS,
    PREFERRED_B_CODE,
    PREFERRED_B_UNIT,
    SOURCE_B_SYSTEM_ID,
    VERSION,
)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def build_pairs_from_series(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Strict consecutive neighbors; horizon > 0; aggregates-friendly pair dicts."""
    exclusions = {
        "non_numeric": 0,
        "header_only_excluded": 0,
        "undefined_unit": 0,
        "wrong_unit": 0,
        "horizon_le_0": 0,
        "single_point_subjects": 0,
    }
    by_subj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        unit = (r.get("raw_unit") or "").strip()
        if unit.lower() in ("", "undefined", "null"):
            exclusions["undefined_unit"] += 1
            continue
        if unit != PREFERRED_B_UNIT:
            exclusions["wrong_unit"] += 1
            continue
        if r.get("numeric_value") is None:
            exclusions["non_numeric"] += 1
            continue
        by_subj[str(r["subject_id"])].append(r)

    pairs: list[dict[str, Any]] = []
    for sid, series in by_subj.items():
        series.sort(
            key=lambda x: (
                _parse_ts(x.get("observed_at")) or datetime.min,
                _parse_ts(x.get("recorded_at")) or datetime.min,
                str(x.get("component_id") or ""),
            )
        )
        if len(series) < 2:
            exclusions["single_point_subjects"] += 1
            continue
        for a, b in zip(series, series[1:]):
            t0 = _parse_ts(a.get("observed_at"))
            t1 = _parse_ts(b.get("observed_at"))
            if t0 is None or t1 is None:
                exclusions["horizon_le_0"] += 1
                continue
            horizon = (t1 - t0).total_seconds() / 86400.0
            if horizon <= 0:
                exclusions["horizon_le_0"] += 1
                continue
            prior_vals = [float(x["numeric_value"]) for x in series if _parse_ts(x.get("observed_at")) and _parse_ts(x.get("observed_at")) < t0]
            y_t0 = float(a["numeric_value"])
            y_t1 = float(b["numeric_value"])
            prior_mean = sum(prior_vals) / len(prior_vals) if prior_vals else None
            prior_last_delta = (y_t0 - prior_vals[-1]) if prior_vals else None
            feats = {
                "y_t0": y_t0,
                "horizon_days": horizon,
                "n_prior_measurements": float(len(prior_vals)),
                "prior_mean": float(prior_mean) if prior_mean is not None else 0.0,
                "prior_last_delta": float(prior_last_delta) if prior_last_delta is not None else 0.0,
                "days_since_first": float(
                    (t0 - (_parse_ts(series[0].get("observed_at")) or t0)).total_seconds() / 86400.0
                ),
                "has_prior_history": 1.0 if prior_vals else 0.0,
                "prior_mean_missing_flag": 0.0 if prior_mean is not None else 1.0,
                "prior_last_delta_missing_flag": 0.0 if prior_last_delta is not None else 1.0,
            }
            if prior_mean is None:
                feats["prior_mean"] = 0.0
            if prior_last_delta is None:
                feats["prior_last_delta"] = 0.0
            pairs.append(
                {
                    "opaque_subject_key": sid,
                    "y_t0": y_t0,
                    "y_t1": y_t1,
                    "horizon_days": horizon,
                    "model_features": feats,
                    "pair_id": f"{a.get('component_id')}|{b.get('component_id')}",
                }
            )
    return pairs, exclusions


def horizon_histogram(pairs: list[dict[str, Any]]) -> dict[str, int]:
    buckets = (
        ("lt_1d", 0.0, 1.0),
        ("1_7d", 1.0, 7.0),
        ("7_30d", 7.0, 30.0),
        ("30_90d", 30.0, 90.0),
        ("90_365d", 90.0, 365.0),
        ("365_730d", 365.0, 730.0),
        ("gt_730d", 730.0, float("inf")),
    )
    out = {name: 0 for name, _, _ in buckets}
    for p in pairs:
        h = float(p["horizon_days"])
        for name, lo, hi in buckets:
            if lo <= h < hi:
                out[name] += 1
                break
    return out


def technical_min_sample_gate(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    n_subjects = len({p["opaque_subject_key"] for p in pairs})
    n_pairs = len(pairs)
    pass_gate = n_subjects >= MIN_B_SUBJECTS_WITH_PAIRS and n_pairs >= MIN_B_PAIRS
    return {
        "n_subjects_with_pairs": n_subjects,
        "n_pairs": n_pairs,
        "min_subjects": MIN_B_SUBJECTS_WITH_PAIRS,
        "min_pairs": MIN_B_PAIRS,
        "pass": pass_gate,
        "threshold_class": "ENGINEERING_ONLY_NOT_CLINICAL",
    }


def fetch_b_t3_series(conn: Any) -> list[dict[str, Any]]:
    """Numeric components only; excludes header-only by join."""
    sql = """
    SELECT o.subject_id,
           oc.component_id,
           oc.numeric_value::float,
           COALESCE(oc.raw_unit, ''),
           o.observed_at,
           o.recorded_at
    FROM canonical_evidence.observation_component oc
    JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
    JOIN canonical_evidence.subject s ON s.subject_id = o.subject_id
    WHERE s.source_system_id = %s
      AND oc.raw_code = %s
      AND COALESCE(oc.raw_unit, '') = %s
      AND oc.numeric_value IS NOT NULL
    ORDER BY o.subject_id, o.observed_at NULLS LAST, o.recorded_at NULLS LAST, oc.component_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (SOURCE_B_SYSTEM_ID, PREFERRED_B_CODE, PREFERRED_B_UNIT))
        rows = cur.fetchall()
    return [
        {
            "subject_id": str(r[0]),
            "component_id": str(r[1]),
            "numeric_value": float(r[2]),
            "raw_unit": r[3],
            "observed_at": r[4],
            "recorded_at": r[5],
        }
        for r in rows
    ]


def construct_source_b_pairs(conn: Any | None = None) -> dict[str, Any]:
    """Build pairs; publish aggregates only (no subject keys in artifact)."""
    rows: list[dict[str, Any]] = []
    error = None
    if conn is not None:
        try:
            rows = fetch_b_t3_series(conn)
        except Exception as exc:  # noqa: BLE001
            error = type(exc).__name__

    pairs, exclusions = build_pairs_from_series(rows) if rows else ([], {
        "non_numeric": 0,
        "header_only_excluded": 0,
        "undefined_unit": 0,
        "wrong_unit": 0,
        "horizon_le_0": 0,
        "single_point_subjects": 0,
        "no_live_series": 0 if rows else 1,
    })
    gate = technical_min_sample_gate(pairs)
    status = "BUILT" if pairs else "INSUFFICIENT_DATA"
    if error:
        status = "INSUFFICIENT_DATA"
    return {
        "version": VERSION,
        "status": status,
        "source_b_pair_construction_status": status,
        "stratum": {"raw_code": PREFERRED_B_CODE, "raw_unit": PREFERRED_B_UNIT},
        "exclusion_reasons": exclusions,
        "horizon_histogram": horizon_histogram(pairs),
        "technical_min_sample_gate": gate,
        "n_input_rows": len(rows),
        "live_error_type": error,
        "subject_keys_omitted": True,
        "pair_ids_omitted": True,
        # Runtime-only for transfer scoring
        "_runtime_pairs": pairs,
    }


def sanitize_pairs_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k != "_runtime_pairs"}
    return out
