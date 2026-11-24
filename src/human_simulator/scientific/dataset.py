"""Strict consecutive longitudinal pair builder (v0.1.1)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from human_simulator.scientific.policy import RUNTIME_DIR, SCIENTIFIC_VERSION


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def sort_key(row: dict[str, Any]) -> tuple:
    """clinical time → recorded time → source_order → locator."""
    clinical = _parse_ts(row.get("clinical_time") or row.get("ts"))
    recorded = _parse_ts(row.get("recorded_time"))
    epoch_min = datetime.min.replace(tzinfo=clinical.tzinfo) if clinical else datetime.min
    return (
        clinical or epoch_min,
        recorded or epoch_min,
        int(row.get("source_order") or 0),
        str(row.get("component_id") or ""),
    )


def fetch_measurement_series(
    conn: Any,
    *,
    raw_code: str,
    dominant_unit: str,
    subject_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    sql = """
    SELECT o.subject_id,
           oc.component_id,
           oc.observation_id,
           oc.numeric_value::float,
           COALESCE(oc.raw_unit, ''),
           o.observed_at,
           o.specimen_collected_at,
           o.recorded_at
    FROM canonical_evidence.observation_component oc
    JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
    WHERE oc.raw_code = %s
      AND COALESCE(oc.raw_unit, '') = %s
      AND oc.numeric_value IS NOT NULL
    ORDER BY o.subject_id, oc.component_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (raw_code, dominant_unit))
        rows = cur.fetchall()
    series: list[dict[str, Any]] = []
    for i, (sid, cid, oid, val, unit, observed, specimen, recorded) in enumerate(rows):
        sid_s = str(sid)
        if subject_keys is not None and sid_s not in subject_keys:
            continue
        clinical = observed or specimen or recorded
        if clinical is None:
            continue
        series.append(
            {
                "opaque_subject_key": sid_s,
                "component_id": str(cid),
                "observation_id": str(oid),
                "value": float(val),
                "unit": unit,
                "clinical_time": clinical.isoformat() if hasattr(clinical, "isoformat") else str(clinical),
                "recorded_time": recorded.isoformat() if recorded is not None and hasattr(recorded, "isoformat") else (
                    str(recorded) if recorded is not None else None
                ),
                "source_order": i,
                "ts": clinical.isoformat() if hasattr(clinical, "isoformat") else str(clinical),
            }
        )
    return series


def fetch_eligible_subjects(conn: Any) -> dict[str, Any]:
    """Candidate-agnostic subjects with ≥2 dated numeric observations (any code)."""
    sql = """
    SELECT o.subject_id, COUNT(*)::bigint AS n
    FROM canonical_evidence.observation_component oc
    JOIN canonical_evidence.observation o ON o.observation_id = oc.observation_id
    WHERE oc.numeric_value IS NOT NULL
      AND COALESCE(o.observed_at, o.specimen_collected_at, o.recorded_at) IS NOT NULL
    GROUP BY o.subject_id
    HAVING COUNT(*) >= 2
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    subjects = sorted(str(r[0]) for r in rows)
    return {
        "n_eligible_subjects": len(subjects),
        "opaque_subject_keys": subjects,  # runtime only — not for publication
        "definition": "any_subject_with_ge2_dated_numeric_observation_components",
    }


def build_consecutive_pairs(
    series: list[dict[str, Any]],
    *,
    outcome: dict[str, Any],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build pairs only between consecutive valid observations (i, i+1)."""
    by_subj: dict[str, list[dict[str, Any]]] = {}
    for row in series:
        by_subj.setdefault(row["opaque_subject_key"], []).append(row)

    exclusions: dict[str, int] = {
        "missing_timestamp": 0,
        "zero_horizon": 0,
        "negative_horizon": 0,
        "incompatible_unit": 0,
        "duplicate_same_timestamp_collapsed": 0,
        "all_forward_combinations_forbidden": 0,  # informational: never generated
    }
    pairs: list[dict[str, Any]] = []
    feature_list = [
        "y_t0",
        "horizon_days",
        "n_prior_measurements",
        "prior_mean",
        "prior_last_delta",
        "days_since_first",
        "has_prior_history",
        "prior_mean_missing_flag",
        "prior_last_delta_missing_flag",
    ]

    for sid, rows in sorted(by_subj.items()):
        ordered = sorted(rows, key=sort_key)
        # collapse exact duplicate clinical_time+value, keep first by ordering
        collapsed: list[dict[str, Any]] = []
        seen_ts_val: set[tuple[str, float]] = set()
        for r in ordered:
            key = (r.get("clinical_time") or r.get("ts"), r["value"])
            if key[0] is None:
                exclusions["missing_timestamp"] += 1
                continue
            if key in seen_ts_val:
                exclusions["duplicate_same_timestamp_collapsed"] += 1
                continue
            seen_ts_val.add(key)
            if "clinical_time" not in r:
                r = {**r, "clinical_time": r["ts"]}
            collapsed.append(r)

        # STRICT consecutive neighbors only
        for i in range(len(collapsed) - 1):
            a, b = collapsed[i], collapsed[i + 1]
            if not a.get("clinical_time") or not b.get("clinical_time"):
                exclusions["missing_timestamp"] += 1
                continue
            if a["unit"] != b["unit"]:
                exclusions["incompatible_unit"] += 1
                continue
            t0 = _parse_ts(a["clinical_time"])
            t1 = _parse_ts(b["clinical_time"])
            assert t0 is not None and t1 is not None
            if t1 == t0:
                exclusions["zero_horizon"] += 1
                continue
            if t1 < t0:
                exclusions["negative_horizon"] += 1
                continue
            history = collapsed[:i]
            prior_vals = [r["value"] for r in history]
            y_t0 = a["value"]
            horizon_days = (t1 - t0).total_seconds() / 86400.0
            first_ts = _parse_ts(collapsed[0]["clinical_time"])
            assert first_ts is not None
            prior_mean = sum(prior_vals) / len(prior_vals) if prior_vals else None
            prior_last_delta = (y_t0 - prior_vals[-1]) if prior_vals else None
            features = {
                "y_t0": y_t0,
                "horizon_days": horizon_days,
                "n_prior_measurements": float(len(prior_vals)),
                "prior_mean": prior_mean,
                "prior_last_delta": prior_last_delta,
                "days_since_first": (t0 - first_ts).total_seconds() / 86400.0,
                "has_prior_history": 1.0 if prior_vals else 0.0,
                "prior_mean_imputed": prior_mean is None,
                "prior_last_delta_imputed": prior_last_delta is None,
                "imputation_method": "none_missing_left_null_with_flags",
                "feature_max_timestamp": a["clinical_time"],
                "prediction_cutoff": a["clinical_time"],
                "label_timestamp": b["clinical_time"],
            }
            model_features = {
                "y_t0": y_t0,
                "horizon_days": horizon_days,
                "n_prior_measurements": float(len(prior_vals)),
                "prior_mean": prior_mean if prior_mean is not None else 0.0,
                "prior_last_delta": prior_last_delta if prior_last_delta is not None else 0.0,
                "days_since_first": (t0 - first_ts).total_seconds() / 86400.0,
                "has_prior_history": 1.0 if prior_vals else 0.0,
                "prior_mean_missing_flag": 1.0 if prior_mean is None else 0.0,
                "prior_last_delta_missing_flag": 1.0 if prior_last_delta is None else 0.0,
            }
            pairs.append(
                {
                    "pair_id": hashlib.sha256(
                        f"{sid}|{a['component_id']}|{b['component_id']}|consecutive".encode()
                    ).hexdigest()[:24],
                    "opaque_subject_key": sid,
                    "t0": a["clinical_time"],
                    "t1": b["clinical_time"],
                    "y_t0": y_t0,
                    "y_t1": b["value"],
                    "horizon_days": horizon_days,
                    "unit": a["unit"],
                    "neighbor_index": i,
                    "pair_kind": "strict_consecutive",
                    "features": features,
                    "model_features": model_features,
                    "provenance": {
                        "t0_component_id": a["component_id"],
                        "t1_component_id": b["component_id"],
                        "t0_observation_id": a["observation_id"],
                        "t1_observation_id": b["observation_id"],
                        "outcome_candidate_id": outcome.get("candidate_id"),
                        "source_measurement_label": outcome.get("source_measurement_label"),
                        "mapping_status": "DOMAIN_REVIEW_PENDING",
                        "scientific_version": SCIENTIFIC_VERSION,
                    },
                }
            )

    schema = {
        "row_fields": [
            "pair_id",
            "opaque_subject_key",
            "t0",
            "t1",
            "y_t0",
            "y_t1",
            "horizon_days",
            "unit",
            "neighbor_index",
            "pair_kind",
            "model_features",
            "provenance",
        ],
        "feature_list": feature_list,
        "pair_definition": "strict_consecutive_neighbors_only",
        "version": SCIENTIFIC_VERSION,
    }
    horizons = [p["horizon_days"] for p in pairs]
    summary = {
        "n_subjects_in_series": len(by_subj),
        "n_observations_after_filter": len(series),
        "n_pairs": len(pairs),
        "n_subjects_with_pairs": len({p["opaque_subject_key"] for p in pairs}),
        "pair_definition": "strict_consecutive_neighbors_only",
        "horizon_days": _horizon_stats(horizons),
        "exclusions_by_reason": exclusions,
        "units": sorted({p["unit"] for p in pairs}),
        "date_coverage": _date_coverage(pairs),
        "feature_list": feature_list,
        "dataset_schema_hash": _sha(schema),
        "dataset_build_configuration_hash": _sha(config),
        "missingness": {
            "prior_mean_null_pairs": sum(1 for p in pairs if p["features"]["prior_mean_imputed"]),
            "prior_last_delta_null_pairs": sum(
                1 for p in pairs if p["features"]["prior_last_delta_imputed"]
            ),
        },
    }
    return pairs, {"schema": schema, "summary": summary, "config": config}


# Back-compat alias used by older imports/tests during transition
build_pairs = build_consecutive_pairs


def _horizon_stats(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"n": 0}
    vals = sorted(vals)
    return {
        "n": len(vals),
        "min": vals[0],
        "median": vals[len(vals) // 2],
        "max": vals[-1],
        "mean": sum(vals) / len(vals),
    }


def _date_coverage(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    if not pairs:
        return {}
    t0s = sorted(p["t0"] for p in pairs)
    t1s = sorted(p["t1"] for p in pairs)
    return {"t0_min": t0s[0], "t0_max": t0s[-1], "t1_min": t1s[0], "t1_max": t1s[-1]}


def write_runtime_dataset(repo_root: Path, pairs: list[dict[str, Any]], meta: dict[str, Any]) -> Path:
    out = repo_root / RUNTIME_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / "longitudinal_pairs.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for p in pairs:
            fh.write(json.dumps(p, sort_keys=True, default=str) + "\n")
    (out / "dataset_meta.json").write_text(
        json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return path


def detect_raw_subject_id_leak(text: str) -> bool:
    lowered = text.lower()
    return '"patient_id"' in lowered or "raw patient" in lowered


def count_all_forward_pairs(n_obs: int) -> int:
    """How many pairs all-forward combinations would create (for negative tests)."""
    return n_obs * (n_obs - 1) // 2 if n_obs >= 2 else 0


def count_consecutive_pairs(n_obs: int) -> int:
    return max(0, n_obs - 1)
