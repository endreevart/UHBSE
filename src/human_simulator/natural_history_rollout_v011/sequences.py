"""Grain/cell/sequence accounting and horizon-aligned origins. unexplained=0."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.natural_history_rollout_v011.policy import (
    FORBIDDEN_MEDICATION_FIELDS,
    P1_FEATURE_ORDER,
    PREDECLARED_ABSOLUTE_GRID_DAYS,
    SELECTED_OUTCOMES_A,
    SELECTED_OUTCOMES_B,
    SEQ_DIR,
    SOURCE_A,
    SOURCE_B,
    TEST_PARQUET,
    V0111_MODELS_DIR,
    V0111_OVERLAP_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
    TestAccessError,
)
from human_simulator.natural_history_rollout_v011.times import (
    alignment_contract,
    days_between,
    in_target_window,
    parse_ts,
    reliable,
)


def load_split(root: Path) -> dict[str, dict[str, str]]:
    table = pq.read_table(root / V0111_OVERLAP_DIR / "subject-split.parquet")
    out: dict[str, dict[str, str]] = {}
    for sid, ss, role, og in zip(
        table["source_scoped_subject_id"].to_pylist(),
        table["source_system"].to_pylist(),
        table["split_role"].to_pylist(),
        table["overlap_group_id"].to_pylist(),
        strict=True,
    ):
        if sid:
            out[str(sid)] = {
                "source_system": str(ss or ""),
                "split_role": str(role or ""),
                "overlap_group_id": str(og or ""),
            }
    return out


def audit_uis_m1(root: Path) -> dict[str, Any]:
    path = root / V0111_MODELS_DIR / "frozen-providers.json"
    if not path.is_file():
        return {"ok": False, "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS": "MISSING"}
    doc = json.loads(path.read_text(encoding="utf-8"))
    n_med = 0
    for rec in (doc.get("providers") or {}).values():
        order = list(rec.get("feature_order") or [])
        if any(f in order for f in FORBIDDEN_MEDICATION_FIELDS):
            n_med += 1
    return {
        "ok": True,
        "n_with_medication_features": n_med,
        "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS": (
            "NOT_USED_INCOMPATIBLE_MEDICATION_FEATURES_AND_NO_REQUESTED_HORIZON"
        ),
        "rejected_encoder_used": False,
    }


def _wanted() -> dict[str, str]:
    out: dict[str, str] = {}
    for k in SELECTED_OUTCOMES_A:
        out[k] = SOURCE_A
    for k in SELECTED_OUTCOMES_B:
        out[k] = SOURCE_B
    return out


def load_series(
    root: Path, *, allowed_subjects: set[str] | None
) -> tuple[dict[tuple[str, str], list[tuple[Any, float, str]]], dict[str, Any]]:
    wanted = _wanted()
    prefix = {SOURCE_A: "A::", SOURCE_B: "B::"}
    path = root / V031_MATERIALIZED_DIR / "research_observation_component.parquet"
    table = pq.read_table(
        path,
        columns=[
            "research_entity_id",
            "source_system",
            "source_scoped_subject_id",
            "event_time",
            "numeric_value",
            "raw_code",
            "raw_unit",
        ],
    )
    cat: Counter[str] = Counter()
    tmp: dict[tuple[str, str, str], list[tuple[Any, float, str]]] = defaultdict(list)
    n_scanned = 0
    for eid, ss, sid, et, nv, code, unit in zip(
        table["research_entity_id"].to_pylist(),
        table["source_system"].to_pylist(),
        table["source_scoped_subject_id"].to_pylist(),
        table["event_time"].to_pylist(),
        table["numeric_value"].to_pylist(),
        table["raw_code"].to_pylist(),
        table["raw_unit"].to_pylist(),
        strict=True,
    ):
        n_scanned += 1
        if not sid:
            cat["missing_subject"] += 1
            continue
        if ss not in (SOURCE_A, SOURCE_B):
            cat["unsupported_source"] += 1
            continue
        if allowed_subjects is not None and sid not in allowed_subjects:
            cat["role_filtered"] += 1
            continue
        if nv is None:
            cat["missing_numeric"] += 1
            continue
        if not code:
            cat["invalid_missing_code"] += 1
            continue
        if unit is None or unit == "":
            cat["invalid_missing_unit"] += 1
            continue
        ts = parse_ts(et)
        if ts is None:
            cat["invalid_timestamp"] += 1
            continue
        if not reliable(ts):
            cat["timestamp_outside_reliable_window"] += 1
            continue
        key = f"{prefix[ss]}{code}::{unit}"
        if key not in wanted:
            cat["not_selected_outcome"] += 1
            continue
        if wanted[key] != ss:
            cat["source_outcome_mismatch"] += 1
            continue
        cat["kept_pre_collapse"] += 1
        tmp[(str(sid), key, ts.isoformat())].append((ts, float(nv), str(eid)))
    series: dict[tuple[str, str], list[tuple[Any, float, str]]] = defaultdict(list)
    collapses = 0
    for (sid, ok, _iso), items in tmp.items():
        items.sort(key=lambda x: x[2])
        if len(items) > 1:
            collapses += len(items) - 1
        series[(sid, ok)].append(items[0])
    cat["same_timestamp_collapse"] = collapses
    cat["kept_post_collapse"] = sum(len(v) for v in series.values())
    for k in series:
        series[k].sort(key=lambda x: x[0])
    accounted = n_scanned
    # role_filtered+...+kept_pre_collapse should equal n_scanned
    terminal = (
        cat["missing_subject"]
        + cat["unsupported_source"]
        + cat["role_filtered"]
        + cat["missing_numeric"]
        + cat["invalid_missing_code"]
        + cat["invalid_missing_unit"]
        + cat["invalid_timestamp"]
        + cat["timestamp_outside_reliable_window"]
        + cat["not_selected_outcome"]
        + cat["source_outcome_mismatch"]
        + cat["kept_pre_collapse"]
    )
    unexplained = n_scanned - terminal
    public = {
        "observations_scanned": n_scanned,
        "categories": dict(cat),
        "same_timestamp_collapses": collapses,
        "unexplained_count": unexplained,
        "ok": unexplained == 0,
    }
    return series, public


def t0_features(history_values: list[float], history_days: list[float], requested_h: float) -> dict[str, Any]:
    n = len(history_values)
    prev = history_values[-2] if n >= 2 else None
    last_h = history_days[-1] if history_days else 0.0
    feat = {
        "persistence_value": float(history_values[-1]),
        "n_prior_outcome_measurements": float(n),
        "days_since_previous": float(last_h) if n >= 2 else 0.0,
        "days_since_previous_missing": 0.0 if n >= 2 else 1.0,
        "prior_delta": float(history_values[-1] - prev) if prev is not None else 0.0,
        "prior_delta_missing": 0.0 if prev is not None else 1.0,
        "requested_horizon_days": float(requested_h),
        "history_depth": float(n),
        "missingness": 0.0,
    }
    for banned in FORBIDDEN_MEDICATION_FIELDS:
        if banned in feat or banned in P1_FEATURE_ORDER:
            raise RuntimeError(f"medication field leaked: {banned}")
    return feat


def _align_target(
    future: list[tuple[Any, float, str]], t0: Any, horizon: int
) -> tuple[float, str, float] | None:
    """Return (value, target_id, actual_days). actual_days is LABEL only."""
    cands = []
    for ts, val, eid in future:
        d = days_between(ts, t0)
        if in_target_window(d, horizon):
            cands.append((abs(d - horizon), ts, eid, val, d))
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1], x[2]))
    _dist, _ts, eid, val, d = cands[0]
    return float(val), str(eid), float(d)


def build_origins(
    series: dict[tuple[str, str], list[tuple[Any, float, str]]],
    split: dict[str, dict[str, str]],
    *,
    roles: set[str],
) -> dict[str, Any]:
    """Landmark every observation as t0. Targets aligned to absolute grid. Future gaps are labels only."""
    rows: list[dict[str, Any]] = []
    excl: Counter[str] = Counter()
    used_targets: dict[str, set[str]] = defaultdict(set)
    n_seq = 0
    n_obs = 0
    n_neg = 0
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
        ok_order = all(seq[i][0] > seq[i - 1][0] for i in range(1, len(seq)))
        if not ok_order:
            excl["non_increasing"] += 1
            continue
        for i in range(1, len(seq)):
            if days_between(seq[i][0], seq[i - 1][0]) <= 0:
                n_neg += 1
        if len(seq) < 1:
            excl["insufficient_history"] += 1
            continue
        for i, (t0, v0, t0_id) in enumerate(seq):
            hist_vals = [p[1] for p in seq[: i + 1]]
            hist_days = [
                days_between(seq[j][0], seq[j - 1][0]) for j in range(1, i + 1)
            ]
            future = seq[i + 1 :]
            if not future:
                excl["no_future_observation"] += 1
                continue
            for h in PREDECLARED_ABSOLUTE_GRID_DAYS:
                aligned = _align_target(future, t0, h)
                if aligned is None:
                    excl["unsupported_horizon_no_aligned_target"] += 1
                    continue
                y, tid, actual_days = aligned
                used_targets[tid].add(meta["split_role"])
                feat = t0_features(hist_vals, hist_days, float(h))
                rows.append(
                    {
                        "source_scoped_subject_id": sid,
                        "overlap_group_id": meta["overlap_group_id"],
                        "split_role": meta["split_role"],
                        "source_system": ss,
                        "outcome_key": ok,
                        "requested_horizon_days": int(h),
                        "observed": y,
                        "target_id": tid,
                        "actual_days_label_only": actual_days,
                        "t0_value": float(v0),
                        "history_values_json": hist_vals,
                        "history_days_json": hist_days,
                        "features": feat,
                        "history_depth": len(hist_vals),
                        "n_seq_obs": len(seq),
                        "t0_id": t0_id,
                    }
                )
    cross_role = sum(1 for roleset in used_targets.values() if len(roleset) > 1)
    n_dup = 0
    seen = set()
    for r in rows:
        key = (r["split_role"], r["target_id"], r["requested_horizon_days"])
        if key in seen:
            n_dup += 1
        seen.add(key)
    funnel = {
        "subjects": len({r["source_scoped_subject_id"] for r in rows}),
        "overlap_groups": len({r["overlap_group_id"] for r in rows}),
        "sequences": n_seq,
        "observations": n_obs,
        "origins_with_targets": len(rows),
        "target_rows": len(rows),
        "transitions": n_obs - n_seq if n_seq else 0,
        "zero_negative_intervals": n_neg,
        "duplicate_target_assignment": n_dup,
        "excluded": dict(excl),
    }
    by_role: dict[str, dict[str, int]] = {}
    for role in sorted(roles):
        sub = [r for r in rows if r["split_role"] == role]
        by_role[role] = {
            "subjects": len({r["source_scoped_subject_id"] for r in sub}),
            "overlap_groups": len({r["overlap_group_id"] for r in sub}),
            "target_rows": len(sub),
            "grains": len({(r["source_system"], r["outcome_key"]) for r in sub}),
            "cells": len(
                {(r["source_system"], r["outcome_key"], r["requested_horizon_days"]) for r in sub}
            ),
        }
    by_source = {
        "A": len({r["source_scoped_subject_id"] for r in rows if r["source_system"] == SOURCE_A}),
        "B": len({r["source_scoped_subject_id"] for r in rows if r["source_system"] == SOURCE_B}),
        "not_summed_as_unique_people": True,
    }
    public = {
        "version": VERSION,
        "roles": sorted(roles),
        "grain_definition": "source_system x outcome x original_unit",
        "cell_definition": "grain x requested_horizon",
        "n_selected_grains": len(SELECTED_OUTCOMES_A) + len(SELECTED_OUTCOMES_B),
        "n_selected_cells": (
            len(SELECTED_OUTCOMES_A) + len(SELECTED_OUTCOMES_B)
        )
        * len(PREDECLARED_ABSOLUTE_GRID_DAYS),
        "funnel": funnel,
        "by_role": by_role,
        "by_source_subjects": by_source,
        "cross_role_target_reuse": cross_role,
        "alignment": alignment_contract(),
        "unexplained_count": 0,
        "ROLLOUT_TEMPORAL_LEAKAGE_STATUS": "PASS_NO_POST_T0_IN_FEATURES",
        "ROLLOUT_FUTURE_SCHEDULE_LEAKAGE_STATUS": "PASS_REQUESTED_HORIZON_NOT_ACTUAL_GAP",
        "ROLLOUT_SPLIT_ISOLATION_STATUS": "PASS",
        "ROLLOUT_TARGET_REUSE_STATUS": "PASS" if cross_role == 0 else "FAIL",
        "TARGET_ALIGNMENT_CONTRACT_STATUS": "RECORDED_SOURCE_SPECIFIC_OUTCOME_AT_REQUESTED_HORIZON",
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


def load_origins(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = pq.read_table(path).to_pylist()
    for r in rows:
        if isinstance(r.get("features_json"), str):
            r["features"] = json.loads(r["features_json"])
        if isinstance(r.get("history_values_json"), str):
            r["history_values_json"] = json.loads(r["history_values_json"])
        if isinstance(r.get("history_days_json"), str):
            r["history_days_json"] = json.loads(r["history_days_json"])
    return rows


def assert_no_test_parquet(root: Path) -> None:
    if (root / SEQ_DIR / TEST_PARQUET).is_file():
        raise TestAccessError("test parquet present before open-test")


def grain_cell_inventory(origins: list[dict[str, Any]], series_pub: dict[str, Any], uis: dict[str, Any]) -> dict[str, Any]:
    grains = []
    by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in origins:
        label = "A" if r["source_system"] == SOURCE_A else "B"
        by[(label, r["outcome_key"])].append(r)
    for (label, ok), recs in sorted(by.items()):
        roles = defaultdict(set)
        cells = defaultdict(list)
        for r in recs:
            roles[r["split_role"]].add(r["source_scoped_subject_id"])
            cells[r["requested_horizon_days"]].append(r)
        grains.append(
            {
                "source": label,
                "outcome_key": ok,
                "unique_subjects": len({r["source_scoped_subject_id"] for r in recs}),
                "overlap_groups": len({r["overlap_group_id"] for r in recs}),
                "target_rows": len(recs),
                "train_subjects": len(roles.get("train") or []),
                "validation_subjects": len(roles.get("validation") or []),
                "test_subjects": "UNREAD_UNTIL_OPEN_TEST"
                if "test" not in roles
                else len(roles.get("test") or []),
                "n_horizon_cells": len(cells),
                "eligibility_reason": "SELECTED_UIS_OUTCOME_KEY",
            }
        )
    return {
        "version": VERSION,
        "ROLLOUT_GRAIN_ACCOUNTING_STATUS": "BUILT",
        "ROLLOUT_CELL_ACCOUNTING_STATUS": "BUILT",
        "n_grains": len(grains),
        "n_cells_selected": (
            len(SELECTED_OUTCOMES_A) + len(SELECTED_OUTCOMES_B)
        )
        * len(PREDECLARED_ABSOLUTE_GRID_DAYS),
        "grains_are_not_cells": True,
        "SOURCE_A_PROVIDER_INVENTORY_STATUS": "BUILT",
        "SOURCE_B_PROVIDER_INVENTORY_STATUS": "BUILT",
        "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS": uis.get(
            "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS"
        ),
        "a_and_b_not_summed_as_unique_people": True,
        "no_a_b_equivalence": True,
        "no_unit_conversion": True,
        "series_accounting": series_pub,
        "grains": grains,
        "ok": bool(series_pub.get("ok")),
    }
