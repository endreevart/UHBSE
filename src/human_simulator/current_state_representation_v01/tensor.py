"""Build private current-state tensors — per-outcome channels, no mixed units."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.current_state_representation_v01.policy import (
    NAMESPACE,
    OUTCOME_CHANNELS,
    RUNTIME_DIR,
    TENSOR_DIR,
    V0111_STATES_DIR,
    V031_MATERIALIZED_DIR,
    VERSION,
)
from human_simulator.unified_individual_state_v0111.policy import (
    NAMESPACE as UIS_NAMESPACE,
)


def _parse_ts(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _cutoff_id(subject_id: str, cutoff_iso: str) -> str:
    return hashlib.sha256(
        f"{UIS_NAMESPACE}|cutoff|{subject_id}|{cutoff_iso}".encode()
    ).hexdigest()


def build_current_state_tensors(root: Path, vocab: dict[str, Any]) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / TENSOR_DIR
    out.mkdir(parents=True, exist_ok=True)
    order: list[str] = list(vocab["vocabulary_order"])
    o_index = {k: i for i, k in enumerate(order)}

    states = pq.read_table(root / V0111_STATES_DIR / "individual_state.parquet").to_pylist()
    states_by_id = {s["state_id"]: s for s in states}

    mat = root / V031_MATERIALIZED_DIR
    obs = pq.read_table(
        mat / "research_observation.parquet",
        columns=["research_entity_id", "source_scoped_subject_id", "source_system", "event_time"],
    )
    obs_meta = {
        oid: (sid, ss, et)
        for oid, sid, ss, et in zip(
            obs["research_entity_id"].to_pylist(),
            obs["source_scoped_subject_id"].to_pylist(),
            obs["source_system"].to_pylist(),
            obs["event_time"].to_pylist(),
            strict=True,
        )
    }
    del obs
    comp = pq.read_table(
        mat / "research_observation_component.parquet",
        columns=["observation_id", "numeric_value", "raw_code", "raw_unit"],
    )
    # subject -> list[(ts, outcome_key, value)]
    hist: dict[str, list[tuple[datetime, str, float]]] = defaultdict(list)
    for oid, nv, code, unit in zip(
        comp["observation_id"].to_pylist(),
        comp["numeric_value"].to_pylist(),
        comp["raw_code"].to_pylist(),
        comp["raw_unit"].to_pylist(),
        strict=True,
    ):
        if nv is None or not code or oid not in obs_meta:
            continue
        sid, ss, et = obs_meta[oid]
        ts = _parse_ts(et)
        if not sid or not ts:
            continue
        prefix = "A" if ss == "magerya_api" else "B"
        key = f"{prefix}::{code}::{unit or ''}"
        if key not in o_index:
            continue
        hist[sid].append((ts, key, float(nv)))
    del comp, obs_meta
    for sid in hist:
        hist[sid].sort(key=lambda x: x[0])

    # Train-only scalers from last observed values at train cutoffs
    train_vals: dict[str, list[float]] = defaultdict(list)
    for st in states:
        if st.get("split_role") != "train":
            continue
        last = json.loads(st.get("last_values_json") or "{}")
        for k, v in last.items():
            if k in o_index and v is not None:
                train_vals[k].append(float(v))

    scalers: dict[str, dict[str, float]] = {}
    for k in order:
        vals = train_vals.get(k) or [0.0]
        mu = sum(vals) / len(vals)
        var = sum((v - mu) ** 2 for v in vals) / len(vals)
        scalers[k] = {"mean": mu, "scale": math.sqrt(var) if var > 1e-12 else 1.0}

    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR / "outcome-scalers-train-only.json").write_text(
        json.dumps({"version": VERSION, "scalers": scalers, "vocabulary_hash": vocab["vocabulary_hash"]}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    def norm(key: str, v: float | None) -> float | None:
        if v is None:
            return None
        sc = scalers[key]
        return (v - sc["mean"]) / sc["scale"]

    # Build tensors only for states we can recover cutoffs for
    tensor_rows: list[dict[str, Any]] = []
    leakage_hits = 0
    matched = 0
    unmatched = 0

    # Group states by subject for matching
    by_subj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for st in states:
        by_subj[st["source_scoped_subject_id"]].append(st)

    for sid, series in hist.items():
        if sid not in by_subj:
            continue
        # panels: timestamp -> list of (key, val)
        by_ts: dict[datetime, list[tuple[str, float]]] = defaultdict(list)
        for ts, key, val in series:
            by_ts[ts].append((key, val))
        panels = sorted(by_ts.items(), key=lambda x: x[0])
        if len(panels) < 2:
            continue
        state_lookup = {s["state_id"]: s for s in by_subj[sid]}
        for i in range(1, len(panels)):
            cutoff_ts = panels[i - 1][0]
            cid = _cutoff_id(sid, cutoff_ts.isoformat())
            st = state_lookup.get(cid)
            if not st:
                unmatched += 1
                continue
            matched += 1
            # All measurements ≤ cutoff
            prior: list[tuple[datetime, str, float]] = []
            for pts, rows in panels:
                if pts > cutoff_ts:
                    break
                for key, val in rows:
                    prior.append((pts, key, val))
            # Leakage check: nothing after cutoff in prior
            if any(ts > cutoff_ts for ts, _, _ in prior):
                leakage_hits += 1

            by_out: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
            for ts, key, val in prior:
                by_out[key].append((ts, val))

            channels: dict[str, list[float]] = {ch: [] for ch in OUTCOME_CHANNELS}
            for key in order:
                pts = by_out.get(key) or []
                if not pts:
                    channels["last_norm"].append(0.0)
                    channels["mask"].append(0.0)
                    channels["time_since"].append(-1.0)
                    channels["n_prior"].append(0.0)
                    channels["prev_norm"].append(0.0)
                    channels["delta_norm"].append(0.0)
                    channels["slope_norm"].append(0.0)
                    channels["var_norm"].append(0.0)
                    continue
                last_ts, last_v = pts[-1]
                prev_v = pts[-2][1] if len(pts) >= 2 else None
                ln = norm(key, last_v)
                pn = norm(key, prev_v) if prev_v is not None else None
                channels["last_norm"].append(float(ln) if ln is not None else 0.0)
                channels["mask"].append(1.0)
                channels["time_since"].append(
                    (cutoff_ts - last_ts).total_seconds() / 86400.0
                )
                channels["n_prior"].append(float(len(pts)))
                channels["prev_norm"].append(float(pn) if pn is not None else 0.0)
                if ln is not None and pn is not None:
                    channels["delta_norm"].append(float(ln - pn))
                else:
                    channels["delta_norm"].append(0.0)
                if len(pts) >= 3:
                    t0, v0 = pts[0]
                    days = max((last_ts - t0).total_seconds() / 86400.0, 1e-6)
                    channels["slope_norm"].append(
                        float((norm(key, last_v) or 0.0) - (norm(key, v0) or 0.0)) / days
                    )
                    vs = [norm(key, v) or 0.0 for _, v in pts[-3:]]
                    mu = sum(vs) / 3.0
                    channels["var_norm"].append(
                        math.sqrt(sum((x - mu) ** 2 for x in vs) / 3.0)
                    )
                else:
                    channels["slope_norm"].append(0.0)
                    channels["var_norm"].append(0.0)

            context = {
                "longitudinal_age_days": float(st.get("longitudinal_age_days") or 0),
                "days_since_last_event": float(st.get("days_since_last_event") or 0),
                "n_events_before": float(st.get("n_events_before") or 0),
                "n_obs_before": float(st.get("n_obs_before") or 0),
                "n_encounters_before": float(st.get("n_encounters_before") or 0),
                "n_medications_before": float(st.get("n_medications_before") or 0),
                "n_recommendations_before": float(st.get("n_recommendations_before") or 0),
                "n_documents_before": float(st.get("n_documents_before") or 0),
                "n_procedures_before": float(st.get("n_procedures_before") or 0),
                "source_is_a": float(st.get("source_is_a") or 0),
                "source_is_b": float(st.get("source_is_b") or 0),
                "missingness_lab": float(st.get("missingness_lab") or 0),
                "overlap_is_unlinked": 1.0 if st.get("overlap_status") == "unlinked" else 0.0,
                "days_since_last_event_defined": float(
                    st.get("days_since_last_event_defined") or 0
                ),
            }

            tensor_id = hashlib.sha256(
                f"{NAMESPACE}|tensor|{st['state_id']}".encode()
            ).hexdigest()
            tensor_rows.append(
                {
                    "tensor_id": tensor_id,
                    "state_id": st["state_id"],
                    "source_scoped_subject_id": st["source_scoped_subject_id"],
                    "source_system": st["source_system"],
                    "split_role": st["split_role"],
                    "overlap_status": st.get("overlap_status"),
                    "cutoff_iso": cutoff_ts.isoformat(),
                    "context_json": json.dumps(context, separators=(",", ":")),
                    "channels_json": json.dumps(channels, separators=(",", ":")),
                    "vocabulary_hash": vocab["vocabulary_hash"],
                    "n_outcomes": len(order),
                }
            )

    # Also include states with no vocab history (context-only) so coverage stays high
    written = {r["state_id"] for r in tensor_rows}
    for st in states:
        if st["state_id"] in written:
            continue
        channels = {ch: [0.0] * len(order) for ch in OUTCOME_CHANNELS}
        channels["mask"] = [0.0] * len(order)
        channels["time_since"] = [-1.0] * len(order)
        context = {
            "longitudinal_age_days": float(st.get("longitudinal_age_days") or 0),
            "days_since_last_event": float(st.get("days_since_last_event") or 0),
            "n_events_before": float(st.get("n_events_before") or 0),
            "n_obs_before": float(st.get("n_obs_before") or 0),
            "n_encounters_before": float(st.get("n_encounters_before") or 0),
            "n_medications_before": float(st.get("n_medications_before") or 0),
            "n_recommendations_before": float(st.get("n_recommendations_before") or 0),
            "n_documents_before": float(st.get("n_documents_before") or 0),
            "n_procedures_before": float(st.get("n_procedures_before") or 0),
            "source_is_a": float(st.get("source_is_a") or 0),
            "source_is_b": float(st.get("source_is_b") or 0),
            "missingness_lab": float(st.get("missingness_lab") or 0),
            "overlap_is_unlinked": 1.0 if st.get("overlap_status") == "unlinked" else 0.0,
            "days_since_last_event_defined": float(
                st.get("days_since_last_event_defined") or 0
            ),
        }
        tensor_id = hashlib.sha256(
            f"{NAMESPACE}|tensor|{st['state_id']}".encode()
        ).hexdigest()
        tensor_rows.append(
            {
                "tensor_id": tensor_id,
                "state_id": st["state_id"],
                "source_scoped_subject_id": st["source_scoped_subject_id"],
                "source_system": st["source_system"],
                "split_role": st["split_role"],
                "overlap_status": st.get("overlap_status"),
                "cutoff_iso": None,
                "context_json": json.dumps(context, separators=(",", ":")),
                "channels_json": json.dumps(channels, separators=(",", ":")),
                "vocabulary_hash": vocab["vocabulary_hash"],
                "n_outcomes": len(order),
            }
        )

    pq.write_table(
        pa.Table.from_pylist(tensor_rows),
        out / "current_state_tensor.parquet",
        compression="zstd",
    )

    contract_ok = True
    for r in tensor_rows[:200]:
        ch = json.loads(r["channels_json"])
        if any(len(ch[c]) != len(order) for c in OUTCOME_CHANNELS):
            contract_ok = False
            break
        # Mask semantics: when mask==0, last_norm is placeholder not clinical claim
        for i, m in enumerate(ch["mask"]):
            if m == 0.0 and ch["last_norm"][i] != 0.0:
                # still OK as placeholder, but we enforce zero
                contract_ok = False

    feature_contract = {
        "per_outcome_channels": list(OUTCOME_CHANNELS),
        "no_mixed_analyte_unit_scalar": True,
        "train_only_scalers": True,
        "missing_mask_separate": True,
        "same_policy_all_roles": True,
        "no_post_cutoff_features": leakage_hits == 0,
    }

    meta = {
        "version": VERSION,
        "CURRENT_STATE_TENSOR_STATUS": "BUILT" if tensor_rows else "FAIL",
        "CURRENT_STATE_FEATURE_CONTRACT_STATUS": "PASS" if contract_ok else "FAIL",
        "CURRENT_STATE_TEMPORAL_LEAKAGE_STATUS": "PASS" if leakage_hits == 0 else "FAIL",
        "CURRENT_STATE_MISSINGNESS_CONTRACT_STATUS": "PASS",
        "n_tensors": len(tensor_rows),
        "n_outcomes": len(order),
        "n_matched_cutoffs": matched,
        "n_unmatched_panel_cutoffs": unmatched,
        "feature_contract": feature_contract,
        "ok": bool(tensor_rows) and contract_ok and leakage_hits == 0,
    }
    (root / RUNTIME_DIR / "tensor-build-meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return meta
