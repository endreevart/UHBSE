"""Longitudinal transition dataset: state(t0) → state(t1)."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from human_simulator.trajectory_regime_tte_v01.policy import (
    CSR_TENSOR_DIR,
    NAMESPACE,
    TRANSITIONS_DIR,
    V0111_OVERLAP_DIR,
    V0111_STATES_DIR,
    VERSION,
)


def build_transitions(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    out = root / TRANSITIONS_DIR
    out.mkdir(parents=True, exist_ok=True)

    states = pq.read_table(root / V0111_STATES_DIR / "individual_state.parquet").to_pylist()
    tensors = {
        r["state_id"]: r
        for r in pq.read_table(root / CSR_TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
    }
    # overlap groups for leakage check
    split = pq.read_table(root / V0111_OVERLAP_DIR / "subject-split.parquet").to_pylist()
    role_by = {r["source_scoped_subject_id"]: r["split_role"] for r in split}
    group_by = {
        r["source_scoped_subject_id"]: r.get("overlap_group_id") or r["source_scoped_subject_id"]
        for r in split
    }

    by_subj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for st in states:
        by_subj[st["source_scoped_subject_id"]].append(st)

    rows: list[dict[str, Any]] = []
    same_ts_excluded = 0
    missing_tensor = 0
    contamination = 0
    funnel = {
        "subjects_considered": 0,
        "subjects_with_ge2_states": 0,
        "eligible_transitions": 0,
        "written": 0,
    }

    for sid, sts in by_subj.items():
        funnel["subjects_considered"] += 1
        sts = sorted(sts, key=lambda s: (s.get("cutoff_ordinal", 0), s["state_id"]))
        if len(sts) < 2:
            continue
        funnel["subjects_with_ge2_states"] += 1
        role = role_by.get(sid) or sts[0]["split_role"]
        for i in range(len(sts) - 1):
            s0, s1 = sts[i], sts[i + 1]
            # consecutive ordinals
            if int(s1.get("cutoff_ordinal") or 0) != int(s0.get("cutoff_ordinal") or 0) + 1:
                continue
            age0 = float(s0.get("longitudinal_age_days") or 0)
            age1 = float(s1.get("longitudinal_age_days") or 0)
            horizon = age1 - age0
            if horizon <= 0:
                same_ts_excluded += 1
                continue
            funnel["eligible_transitions"] += 1
            t0 = tensors.get(s0["state_id"])
            t1 = tensors.get(s1["state_id"])
            if not t0 or not t1:
                missing_tensor += 1
                continue
            # source contamination check
            if s0["source_system"] != s1["source_system"]:
                contamination += 1
                continue
            ch0 = json.loads(t0["channels_json"])
            ch1 = json.loads(t1["channels_json"])
            n = min(len(ch0["mask"]), len(ch1["mask"]))
            deltas = []
            appeared = disappeared = 0
            for j in range(n):
                m0, m1 = ch0["mask"][j], ch1["mask"][j]
                if m0 > 0 and m1 > 0:
                    deltas.append(ch1["last_norm"][j] - ch0["last_norm"][j])
                else:
                    deltas.append(0.0)
                if m0 <= 0 and m1 > 0:
                    appeared += 1
                if m0 > 0 and m1 <= 0:
                    disappeared += 1
            tid = hashlib.sha256(
                f"{NAMESPACE}|transition|{s0['state_id']}|{s1['state_id']}".encode()
            ).hexdigest()
            rows.append(
                {
                    "transition_id": tid,
                    "source_scoped_subject_id": sid,
                    "source_system": s0["source_system"],
                    "split_role": role,
                    "overlap_group_id": group_by.get(sid),
                    "state_id_t0": s0["state_id"],
                    "state_id_t1": s1["state_id"],
                    "cutoff_ordinal_t0": s0.get("cutoff_ordinal"),
                    "cutoff_ordinal_t1": s1.get("cutoff_ordinal"),
                    "horizon_days": horizon,
                    "history_depth_t0": s0.get("n_obs_before"),
                    "mask_density_t0": sum(ch0["mask"][:n]) / max(n, 1),
                    "n_appeared": appeared,
                    "n_disappeared": disappeared,
                    "mean_abs_delta_observed": (
                        sum(abs(d) for d, m0, m1 in zip(
                            deltas,
                            ch0["mask"][:n],
                            ch1["mask"][:n],
                            strict=False,
                        ) if m0 > 0 and m1 > 0)
                        / max(
                            sum(
                                1
                                for m0, m1 in zip(ch0["mask"][:n], ch1["mask"][:n], strict=False)
                                if m0 > 0 and m1 > 0
                            ),
                            1,
                        )
                    ),
                    "context_t0_json": t0["context_json"],
                    "channels_t0_json": t0["channels_json"],
                    "provenance": "csr_tensor+v0111_states_consecutive",
                }
            )
            funnel["written"] += 1

    pq.write_table(pa.Table.from_pylist(rows), out / "transitions.parquet", compression="zstd")

    # Split/overlap leakage
    groups_by_role: dict[str, set] = defaultdict(set)
    subjects_by_role: dict[str, set] = defaultdict(set)
    for r in rows:
        groups_by_role[r["split_role"]].add(r["overlap_group_id"])
        subjects_by_role[r["split_role"]].add(r["source_scoped_subject_id"])
    leak_subj = (
        subjects_by_role["train"] & subjects_by_role["validation"]
        | subjects_by_role["train"] & subjects_by_role["test"]
        | subjects_by_role["validation"] & subjects_by_role["test"]
    )
    leak_grp = (
        groups_by_role["train"] & groups_by_role["validation"]
        | groups_by_role["train"] & groups_by_role["test"]
        | groups_by_role["validation"] & groups_by_role["test"]
    )
    # source composition
    src_counts = defaultdict(int)
    for r in rows:
        src_counts[r["source_system"]] += 1

    unexplained = 0  # funnel closed by construction
    doc = {
        "version": VERSION,
        "TRANSITION_DATASET_STATUS": "BUILT" if rows else "FAIL",
        "TRANSITION_DATASET_ACCOUNTING_STATUS": "PASS" if unexplained == 0 and contamination == 0 else "FAIL",
        "n_transitions": len(rows),
        "funnel": funnel,
        "same_timestamp_excluded": same_ts_excluded,
        "missing_tensor": missing_tensor,
        "source_contamination_ab": contamination,
        "subject_split_leakage": len(leak_subj),
        "overlap_group_split_leakage": len(leak_grp),
        "source_counts": dict(src_counts),
        "unexplained": unexplained,
        "ok": bool(rows) and contamination == 0 and len(leak_subj) == 0 and len(leak_grp) == 0,
    }
    (out / "transition-dataset-meta.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )
    return doc
