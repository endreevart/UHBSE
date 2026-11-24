"""Horizon-aligned origins with closest-horizon assignment and reuse accounting."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.joint_dependence_rollout_v02.groups import load_split_effective
from human_simulator.joint_dependence_rollout_v02.policy import (
    PREDECLARED_ABSOLUTE_GRID_DAYS,
    SELECTED_OUTCOMES_A,
    SELECTED_OUTCOMES_B,
    SEQ_DIR,
    SOURCE_A,
    SOURCE_B,
    TEST_PARQUET,
    VERSION,
    TestAccessError,
)
from human_simulator.joint_dependence_rollout_v02.times import (
    alignment_contract,
    assign_horizon,
    days_between,
    in_target_window,
)
from human_simulator.natural_history_rollout_v011.sequences import audit_uis_m1, load_series, t0_features


def assert_no_test_parquet(root: Path) -> None:
    if (root / SEQ_DIR / TEST_PARQUET).is_file():
        raise TestAccessError("test parquet present before open-test")


def _align_unique(
    future: list[tuple[Any, float, str]], t0: Any
) -> dict[int, tuple[float, str, float]]:
    """Map each future event to at most one horizon. Return horizon -> (value, target_id, actual_days)."""
    by_h: dict[int, list[tuple[float, Any, str, float, str]]] = defaultdict(list)
    for ts, val, eid in future:
        d = days_between(ts, t0)
        h = assign_horizon(d)
        if h is None:
            continue
        by_h[h].append((abs(d - h), ts, eid, val, d))
    out: dict[int, tuple[float, str, float]] = {}
    used: set[str] = set()
    for h in PREDECLARED_ABSOLUTE_GRID_DAYS:
        cands = [c for c in by_h.get(h, []) if c[2] not in used]
        if not cands:
            continue
        cands.sort(key=lambda x: (x[0], x[1], x[2]))
        _dist, _ts, eid, val, d = cands[0]
        used.add(eid)
        out[h] = (float(val), str(eid), float(d))
    return out


def build_origins(
    series: dict[tuple[str, str], list[tuple[Any, float, str]]],
    split: dict[str, dict[str, str]],
    *,
    roles: set[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    excl: Counter[str] = Counter()
    used_roles: dict[str, set[str]] = defaultdict(set)
    used_landmarks: dict[str, set[str]] = defaultdict(set)
    used_horizons: dict[str, set[int]] = defaultdict(set)
    used_outcomes: dict[str, set[str]] = defaultdict(set)
    align_err: dict[tuple[str, str, int], list[float]] = defaultdict(list)
    n_seq = 0
    n_obs = 0
    for (sid, ok), seq in series.items():
        meta = split.get(sid)
        if not meta or meta["split_role"] not in roles:
            excl["wrong_role_or_unsplit"] += 1
            continue
        ss = meta["source_system"]
        expected = SOURCE_A if ok.startswith("A::") else SOURCE_B
        if ss != expected:
            excl["source_contamination"] += 1
            continue
        n_seq += 1
        n_obs += len(seq)
        if not all(seq[i][0] > seq[i - 1][0] for i in range(1, len(seq))):
            excl["non_increasing"] += 1
            continue
        for i, (t0, v0, t0_id) in enumerate(seq):
            hist_vals = [p[1] for p in seq[: i + 1]]
            hist_days = [days_between(seq[j][0], seq[j - 1][0]) for j in range(1, i + 1)]
            future = seq[i + 1 :]
            if not future:
                excl["no_future_observation"] += 1
                continue
            assigned = _align_unique(future, t0)
            if not assigned:
                excl["unsupported_horizon_no_aligned_target"] += 1
                continue
            t0_iso = t0.isoformat()
            for h, (y, tid, actual_days) in assigned.items():
                used_roles[tid].add(meta["split_role"])
                used_landmarks[tid].add(t0_id)
                used_horizons[tid].add(h)
                used_outcomes[tid].add(ok)
                align_err[(ss, ok, h)].append(actual_days - h)
                feat = t0_features(hist_vals, hist_days, float(h))
                if "actual_days" in feat or "actual_recorded_label_offset_days" in feat:
                    raise RuntimeError("actual label offset leaked into features")
                rows.append(
                    {
                        "source_scoped_subject_id": sid,
                        "effective_overlap_group_id": meta["effective_overlap_group_id"],
                        "split_role": meta["split_role"],
                        "source_system": ss,
                        "outcome_key": ok,
                        "requested_horizon_days": int(h),
                        "requested_prediction_offset_days": int(h),
                        "observed": y,
                        "target_id": tid,
                        "actual_recorded_label_offset_days": actual_days,
                        "alignment_error_days": actual_days - h,
                        "t0_value": float(v0),
                        "t0_iso": t0_iso,
                        "history_values_json": hist_vals,
                        "history_days_json": hist_days,
                        "features": feat,
                        "history_depth": len(hist_vals),
                        "t0_id": t0_id,
                    }
                )
    cross_role = sum(1 for roleset in used_roles.values() if len(roleset) > 1)
    n_dup = 0
    seen: set[tuple[str, str, int]] = set()
    for r in rows:
        key = (r["split_role"], r["target_id"], r["requested_horizon_days"])
        if key in seen:
            n_dup += 1
        seen.add(key)
    multi_landmark = sum(1 for s in used_landmarks.values() if len(s) > 1)
    multi_horizon = sum(1 for s in used_horizons.values() if len(s) > 1)
    multi_outcome = sum(1 for s in used_outcomes.values() if len(s) > 1)
    max_mult = max((len(v) for v in used_landmarks.values()), default=0)
    align_pub = []
    for (ss, ok, h), xs in sorted(align_err.items()):
        ys = sorted(xs)
        align_pub.append(
            {
                "source_system": ss,
                "outcome_key": ok,
                "horizon_days": h,
                "n": len(ys),
                "mean": sum(ys) / len(ys),
                "q05": ys[int(0.05 * (len(ys) - 1))],
                "q50": ys[len(ys) // 2],
                "q95": ys[int(0.95 * (len(ys) - 1))],
            }
        )
    funnel = {
        "subjects": len({r["source_scoped_subject_id"] for r in rows}),
        "effective_groups": len({r["effective_overlap_group_id"] for r in rows}),
        "sequences": n_seq,
        "observations": n_obs,
        "target_rows": len(rows),
        "duplicate_row_identity": n_dup,
        "target_events_in_multiple_landmarks": multi_landmark,
        "target_events_in_multiple_horizons": multi_horizon,
        "target_events_in_multiple_outcomes": multi_outcome,
        "cross_role_target_reuse": cross_role,
        "max_reuse_multiplicity": max_mult,
        "excluded": dict(excl),
    }
    by_role: dict[str, dict[str, int]] = {}
    for role in sorted(roles):
        sub = [r for r in rows if r["split_role"] == role]
        by_role[role] = {
            "subjects": len({r["source_scoped_subject_id"] for r in sub}),
            "effective_groups": len({r["effective_overlap_group_id"] for r in sub}),
            "target_rows": len(sub),
            "grains": len({(r["source_system"], r["outcome_key"]) for r in sub}),
            "cells": len(
                {(r["source_system"], r["outcome_key"], r["requested_horizon_days"]) for r in sub}
            ),
        }
    public = {
        "version": VERSION,
        "roles": sorted(roles),
        "funnel": funnel,
        "by_role": by_role,
        "by_source_subjects": {
            "A": len({r["source_scoped_subject_id"] for r in rows if r["source_system"] == SOURCE_A}),
            "B": len({r["source_scoped_subject_id"] for r in rows if r["source_system"] == SOURCE_B}),
            "not_summed_as_unique_people": True,
        },
        "alignment": alignment_contract(),
        "alignment_error_aggregates": align_pub,
        "unexplained_count": 0,
        "CROSS_ROLE_TARGET_REUSE_STATUS": "PASS" if cross_role == 0 else "FAIL",
        "WITHIN_ROLE_REPEATED_LANDMARK_STATUS": "ACCOUNTED",
        "CROSS_HORIZON_TARGET_REUSE_STATUS": (
            "PREVENTED_CLOSEST_HORIZON" if multi_horizon == 0 else "ACCOUNTED_NONZERO"
        ),
        "TARGET_REUSE_UNCERTAINTY_ACCOUNTING_STATUS": "EFFECTIVE_GROUP_BOOTSTRAP_REQUIRED",
        "TARGET_ALIGNMENT_CONTRACT_STATUS": "WINDOW_ALIGNED_RECORDED_SOURCE_SPECIFIC_OUTCOME",
        "TARGET_ALIGNMENT_ERROR_ACCOUNTING_STATUS": "PUBLISHED_AGGREGATE",
        "REQUESTED_HORIZON_RUNTIME_STATUS": "PASS_REQUEST_PARAMETER_T0_PLUS_H",
        "ok": cross_role == 0,
    }
    return {"rows": rows, "public": public}


def write_origins(root: Path, rows: list[dict[str, Any]], name: str) -> Path:
    out = root / SEQ_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    serial = []
    for r in rows:
        rec = {k: r[k] for k in r if k != "features"}
        rec["features_json"] = json.dumps(r["features"])
        rec["history_values_json"] = json.dumps(r["history_values_json"])
        rec["history_days_json"] = json.dumps(r["history_days_json"])
        serial.append(rec)
    table = pa.Table.from_pylist(serial) if serial else pa.table({"n": pa.array([], type=pa.int64())})
    pq.write_table(table, path, compression="zstd")
    return path


def grain_cell_inventory(origins: list[dict[str, Any]], series_pub: dict[str, Any], uis: dict[str, Any]) -> dict[str, Any]:
    grains = []
    by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in origins:
        label = "A" if r["source_system"] == SOURCE_A else "B"
        by[(label, r["outcome_key"])].append(r)
    for (label, ok), recs in sorted(by.items()):
        roles: dict[str, set[str]] = defaultdict(set)
        for r in recs:
            roles[r["split_role"]].add(r["source_scoped_subject_id"])
        grains.append(
            {
                "source": label,
                "outcome_key": ok,
                "unique_subjects": len({r["source_scoped_subject_id"] for r in recs}),
                "effective_groups": len({r["effective_overlap_group_id"] for r in recs}),
                "target_rows": len(recs),
                "train_subjects": len(roles.get("train") or []),
                "validation_subjects": len(roles.get("validation") or []),
                "n_horizon_cells": len({r["requested_horizon_days"] for r in recs}),
            }
        )
    return {
        "version": VERSION,
        "n_grains": len(grains),
        "n_cells_selected": (len(SELECTED_OUTCOMES_A) + len(SELECTED_OUTCOMES_B))
        * len(PREDECLARED_ABSOLUTE_GRID_DAYS),
        "grains_are_not_cells": True,
        "no_unit_conversion": True,
        "no_a_b_equivalence": True,
        "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS": uis.get(
            "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS"
        ),
        "series_accounting": series_pub,
        "grains": grains,
        "ok": bool(series_pub.get("ok")),
    }


def load_split(root: Path) -> dict[str, dict[str, str]]:
    return load_split_effective(root)
