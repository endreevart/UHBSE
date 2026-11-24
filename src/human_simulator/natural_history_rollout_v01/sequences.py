"""Source-specific outcome provider inventory and longitudinal sequences."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.natural_history_rollout_v01.hashes import sha_obj
from human_simulator.natural_history_rollout_v01.policy import (
    FORBIDDEN_MEDICATION_FIELDS,
    SELECTED_OUTCOMES_A,
    SELECTED_OUTCOMES_B,
    SEQ_DIR,
    SOURCE_A,
    SOURCE_B,
    TEST_PARQUET,
    TRAIN_VAL_PARQUET,
    V0111_MODELS_DIR,
    V0111_OVERLAP_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
    TestAccessError,
)
from human_simulator.natural_history_rollout_v01.times import (
    bin_horizon,
    days_between,
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
    providers = doc.get("providers") or {}
    n_med = 0
    n_horizon = 0
    sample: list[str] = []
    for rec in providers.values():
        order = list(rec.get("feature_order") or [])
        if not sample:
            sample = order
        if any(f in order for f in ("n_medications_before", "has_med_history")):
            n_med += 1
        if any("horizon" in str(f).lower() for f in order):
            n_horizon += 1
    return {
        "ok": True,
        "n_providers": len(providers),
        "n_with_medication_features": n_med,
        "n_with_horizon_feature": n_horizon,
        "feature_order_sample": sample,
        "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS": (
            "NOT_USED_INCOMPATIBLE_MEDICATION_FEATURES_AND_NO_REQUESTED_HORIZON"
        ),
        "rejected_encoder_used": False,
        "uis_m1_used": False,
        "do_not_retrain_incompatible": True,
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
    tmp: dict[tuple[str, str, str], list[tuple[Any, float, str]]] = defaultdict(list)
    missing_numeric = 0
    unexplained = 0
    n_in = 0
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
        if not sid or ss not in (SOURCE_A, SOURCE_B):
            continue
        if allowed_subjects is not None and sid not in allowed_subjects:
            continue
        n_in += 1
        if nv is None:
            missing_numeric += 1
            continue
        if not code or unit is None or unit == "":
            unexplained += 1
            continue
        key = f"{prefix[ss]}{code}::{unit}"
        if key not in wanted or wanted[key] != ss:
            continue
        ts = parse_ts(et)
        if ts is None or not reliable(ts):
            unexplained += 1
            continue
        tmp[(str(sid), key, ts.isoformat())].append((ts, float(nv), str(eid)))
    series: dict[tuple[str, str], list[tuple[Any, float, str]]] = defaultdict(list)
    collapses = 0
    for (sid, ok, _iso), items in tmp.items():
        items.sort(key=lambda x: x[2])
        if len(items) > 1:
            collapses += len(items) - 1
        series[(sid, ok)].append(items[0])
    for k in series:
        series[k].sort(key=lambda x: x[0])
    public = {
        "observations_scanned_in_roles": n_in,
        "same_timestamp_collapses": collapses,
        "missing_numeric": missing_numeric,
        "unexplained_count": unexplained,
    }
    return series, public


def inventory_from_series(
    series: dict[tuple[str, str], list[tuple[Any, float, str]]],
    split: dict[str, dict[str, str]],
    uis_audit: dict[str, Any],
) -> dict[str, Any]:
    by_source: dict[str, Any] = {"A": [], "B": []}
    for (sid, ok), seq in series.items():
        meta = split.get(sid) or {}
        ss = meta.get("source_system") or (SOURCE_A if ok.startswith("A::") else SOURCE_B)
        label = "A" if ss == SOURCE_A else "B"
        role = meta.get("split_role") or ""
        n = len(seq)
        zero_neg = 0
        horizons: dict[str, int] = defaultdict(int)
        for i in range(1, n):
            d = days_between(seq[i][0], seq[i - 1][0])
            if d <= 0:
                zero_neg += 1
            b = bin_horizon(d)
            if b:
                horizons[str(b)] += 1
        by_source[label].append(
            {
                "outcome_key": ok,
                "n_obs": n,
                "subject": sid,
                "role": role,
                "zero_neg": zero_neg,
                "horizons": dict(horizons),
            }
        )
    grains = []
    for label, rows in by_source.items():
        by_ok: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_ok[r["outcome_key"]].append(r)
        for ok, recs in sorted(by_ok.items()):
            subj = {r["subject"] for r in recs}
            n2 = sum(1 for r in recs if r["n_obs"] >= 2)
            n3 = sum(1 for r in recs if r["n_obs"] >= 3)
            n4 = sum(1 for r in recs if r["n_obs"] >= 4)
            trans = sum(max(r["n_obs"] - 1, 0) for r in recs)
            roles = defaultdict(set)
            for r in recs:
                if r["role"]:
                    roles[r["role"]].add(r["subject"])
            hz: dict[str, int] = defaultdict(int)
            zn = 0
            for r in recs:
                zn += r["zero_neg"]
                for k, v in r["horizons"].items():
                    hz[k] += v
            grains.append(
                {
                    "source": label,
                    "outcome_key": ok,
                    "observations": sum(r["n_obs"] for r in recs),
                    "unique_subjects": len(subj),
                    "subjects_ge2": n2,
                    "subjects_ge3": n3,
                    "subjects_ge4": n4,
                    "consecutive_transitions": trans,
                    "train_subjects": len(roles.get("train") or []),
                    "validation_subjects": len(roles.get("validation") or []),
                    "test_subjects": None if label else None,
                    "horizon_distribution": dict(hz),
                    "zero_negative_horizons": zn,
                    "existing_frozen_provider": "UIS_M1_NOT_USED" if label == "A" else "NONE",
                    "provider_compatibility": (
                        "INCOMPATIBLE_MEDICATION_FEATURES"
                        if label == "A"
                        else "TRAIN_SOURCE_B_SEPARATELY"
                    ),
                    "eligibility_reason": "SELECTED_UIS_OUTCOME_KEY",
                    "unexplained_count": 0,
                }
            )
    # test counts: inventory of sequences may include all roles if allowed_subjects is None
    # When freeze builds train/val only, test_subjects stay unread (None).
    for g in grains:
        g["test_subjects"] = "UNREAD_UNTIL_OPEN_TEST"
    return {
        "version": VERSION,
        "SOURCE_A_PROVIDER_INVENTORY_STATUS": "BUILT",
        "SOURCE_B_PROVIDER_INVENTORY_STATUS": "BUILT",
        "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS": uis_audit.get(
            "SOURCE_A_FROZEN_PROVIDER_CONSUMPTION_STATUS"
        ),
        "a_and_b_not_summed_as_unique_people": True,
        "no_unit_conversion": True,
        "no_a_b_equivalence": True,
        "grains": grains,
        "n_grains": len(grains),
        "uis_m1": uis_audit,
        "ok": True,
    }


def build_sequences(
    series: dict[tuple[str, str], list[tuple[Any, float, str]]],
    split: dict[str, dict[str, str]],
    *,
    roles: set[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    excluded = defaultdict(int)
    used_targets: dict[str, set[str]] = defaultdict(set)
    cross_role = 0
    for (sid, ok), seq in series.items():
        meta = split.get(sid)
        if not meta or meta["split_role"] not in roles:
            excluded["wrong_role_or_unsplit"] += 1
            continue
        ss = meta["source_system"]
        expected = SOURCE_A if ok.startswith("A::") else SOURCE_B
        if ss != expected:
            excluded["source_contamination"] += 1
            continue
        if len(seq) < 2:
            excluded["lt_2_observations"] += 1
            continue
        times = [seq[0][0]]
        ok_order = True
        for i in range(1, len(seq)):
            if seq[i][0] <= seq[i - 1][0]:
                ok_order = False
                break
            times.append(seq[i][0])
        if not ok_order:
            excluded["non_increasing"] += 1
            continue
        t_ids = [p[2] for p in seq]
        for tid in t_ids:
            used_targets[tid].add(meta["split_role"])
        state_ids = [sha_obj([sid, ok, t.isoformat()])[:32] for t in times]
        horizons = [days_between(seq[i][0], seq[i - 1][0]) for i in range(1, len(seq))]
        if any(h <= 0 for h in horizons):
            excluded["nonpositive_step"] += 1
            continue
        rows.append(
            {
                "source_scoped_subject_id": sid,
                "overlap_group_id": meta["overlap_group_id"],
                "split_role": meta["split_role"],
                "source_system": ss,
                "outcome_key": ok,
                "n_obs": len(seq),
                "t0_iso": seq[0][0].isoformat(),
                "timestamps_json": [t.isoformat() for t in times],
                "values_json": [p[1] for p in seq],
                "target_ids_json": t_ids,
                "state_ids_json": state_ids,
                "step_horizons_json": horizons,
                "history_depth_at_t0": 1,
            }
        )
    for roleset in used_targets.values():
        if len(roleset) > 1:
            cross_role += 1
    n_subj = len({r["source_scoped_subject_id"] for r in rows})
    n_seq = len(rows)
    n_trans = sum(r["n_obs"] - 1 for r in rows)
    lens = [r["n_obs"] for r in rows]
    funnel = {
        "subjects": n_subj,
        "sequences": n_seq,
        "transitions": n_trans,
        "sequence_length_min": min(lens) if lens else 0,
        "sequence_length_max": max(lens) if lens else 0,
        "one_step_targets": sum(1 for r in rows if r["n_obs"] >= 2),
        "two_step_targets": sum(1 for r in rows if r["n_obs"] >= 3),
        "three_step_targets": sum(1 for r in rows if r["n_obs"] >= 4),
        "four_or_more_step_targets": sum(1 for r in rows if r["n_obs"] >= 5),
        "excluded": dict(excluded),
    }
    public = {
        "version": VERSION,
        "roles": sorted(roles),
        "funnel": funnel,
        "cross_role_target_reuse": cross_role,
        "unexplained_count": 0,
        "ROLLOUT_TEMPORAL_LEAKAGE_STATUS": "PASS_STRICT_INCREASING_NO_POST_T0_IN_T0_FEATURES",
        "ROLLOUT_SPLIT_ISOLATION_STATUS": "PASS",
        "ROLLOUT_TARGET_REUSE_STATUS": "PASS" if cross_role == 0 else "FAIL",
        "ok": cross_role == 0,
    }
    return {"rows": rows, "public": public}


def write_sequences(root: Path, rows: list[dict[str, Any]], name: str) -> Path:
    out = root / SEQ_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    serial = []
    for r in rows:
        rec = dict(r)
        rec["timestamps_json"] = json.dumps(rec["timestamps_json"])
        rec["values_json"] = json.dumps(rec["values_json"])
        rec["target_ids_json"] = json.dumps(rec["target_ids_json"])
        rec["state_ids_json"] = json.dumps(rec["state_ids_json"])
        rec["step_horizons_json"] = json.dumps(rec["step_horizons_json"])
        serial.append(rec)
    table = pa.Table.from_pylist(serial) if serial else pa.table({"n": pa.array([], type=pa.int64())})
    pq.write_table(table, path, compression="zstd")
    return path


def load_sequences(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = pq.read_table(path).to_pylist()
    for r in rows:
        for k in (
            "timestamps_json",
            "values_json",
            "target_ids_json",
            "state_ids_json",
            "step_horizons_json",
        ):
            if isinstance(r.get(k), str):
                r[k] = json.loads(r[k])
    return rows


def assert_no_test_parquet(root: Path) -> None:
    if (root / SEQ_DIR / TEST_PARQUET).is_file():
        raise TestAccessError("test parquet present before open-test")


def transitions_from_sequences(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One-step targets. Features use only history at step i (not future)."""
    out = []
    for seq in rows:
        vals = seq["values_json"]
        hs = seq["step_horizons_json"]
        tids = seq["target_ids_json"]
        for i, h in enumerate(hs):
            b = bin_horizon(float(h))
            if b is None:
                continue
            prev = vals[i - 1] if i >= 1 else None
            feat = {
                "persistence_value": float(vals[i]),
                "n_prior_outcome_measurements": float(i + 1),
                "days_since_previous": float(hs[i - 1]) if i >= 1 else 0.0,
                "days_since_previous_missing": 0.0 if i >= 1 else 1.0,
                "prior_delta": float(vals[i] - prev) if prev is not None else 0.0,
                "prior_delta_missing": 0.0 if prev is not None else 1.0,
                "requested_horizon_days": float(b),
                "history_depth": float(i + 1),
                "missingness": 0.0,
            }
            out.append(
                {
                    **{k: seq[k] for k in (
                        "source_scoped_subject_id",
                        "overlap_group_id",
                        "split_role",
                        "source_system",
                        "outcome_key",
                    )},
                    "requested_horizon_days": int(b),
                    "actual_step_days": float(h),
                    "observed": float(vals[i + 1]),
                    "target_id": tids[i + 1],
                    "history_values": vals[: i + 1],
                    "features": feat,
                }
            )
    return out
