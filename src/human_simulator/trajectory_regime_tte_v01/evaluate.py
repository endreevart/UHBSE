"""Evaluation — denoising recon + trajectory with train-only scales; fixed M2 loader."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.trajectory_regime_tte_v01.denoising_encoder import predict_denoising
from human_simulator.trajectory_regime_tte_v01.policy import (
    CSR_TENSOR_DIR,
    GATE_MIN_TRAJECTORY_BETTER_THAN_ACTIVE,
    GATE_RECON_BEAT_TRAIN_MEAN_BOTH_SOURCES,
    RUNTIME_DIR,
    SEED,
    V0111_MODELS_DIR,
    V0111_STATES_DIR,
    VERSION,
)
from human_simulator.unified_individual_state_v0111.baseline_models import _feats
from human_simulator.unified_individual_state_v0111.m2_joint import predict_m2
from human_simulator.unified_individual_state_v0111.ridge import predict_ridge


def _subject_macro_mae(subj: list[str], y: list[float], p: list[float]) -> float:
    by: dict[str, list[float]] = defaultdict(list)
    for s, yi, pi in zip(subj, y, p, strict=True):
        by[s].append(abs(yi - pi))
    if not by:
        return float("inf")
    return sum(sum(v) / len(v) for v in by.values()) / len(by)


def _bootstrap_subject(
    subj: list[str], y: list[float], p0: list[float], p1: list[float], n: int = 60
) -> dict[str, Any]:
    rng = random.Random(SEED)
    ids = sorted(set(subj))
    if not ids:
        return {}
    idx_by: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(subj):
        idx_by[s].append(i)
    diffs = []
    for _ in range(n):
        sample = [ids[rng.randrange(len(ids))] for _ in ids]
        subj_s, ys, a0, a1 = [], [], [], []
        for s in sample:
            for i in idx_by[s]:
                subj_s.append(s)
                ys.append(y[i])
                a0.append(p0[i])
                a1.append(p1[i])
        if not ys:
            continue
        diffs.append(_subject_macro_mae(subj_s, ys, a0) - _subject_macro_mae(subj_s, ys, a1))
    if not diffs:
        return {}
    diffs.sort()
    return {
        "n_bootstrap": n,
        "skill_diff_mean": sum(diffs) / len(diffs),
        "skill_diff_p05": diffs[int(0.05 * len(diffs))],
        "skill_diff_p95": diffs[min(len(diffs) - 1, int(0.95 * len(diffs)))],
    }


def _load_m2(root: Path) -> dict[str, Any] | None:
    path = root / V0111_MODELS_DIR / "frozen-m2.json"
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    # Correct nested structure
    if "model" in raw and isinstance(raw["model"], dict):
        model = dict(raw["model"])
        model["_meta"] = raw.get("meta")
        return model
    return raw


def _remap_tensor_row(row: dict[str, Any], order: list[str], csr_order: list[str]) -> dict[str, Any]:
    csr_index = {k: i for i, k in enumerate(csr_order)}
    ch = json.loads(row["channels_json"])
    idxs = [csr_index[k] for k in order]
    new_ch = {c: [ch[c][j] for j in idxs] for c in ch}
    return {**row, "channels_json": json.dumps(new_ch), "n_outcomes": len(order)}


def evaluate_reconstruction(
    root: Path, model: dict[str, Any], csr_order: list[str], *, role: str, hide_frac: float = 0.35
) -> dict[str, Any]:
    root = Path(root).resolve()
    rng = random.Random(SEED + (7 if role == "test" else 0))
    order = model["outcome_keys"]
    tensors = [
        _remap_tensor_row(r, order, csr_order)
        for r in pq.read_table(root / CSR_TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
        if r.get("split_role") == role
    ]
    rng.shuffle(tensors)
    tensors = tensors[:600]

    # train-mean baselines in norm space: 0.0 is train-centered; also per-outcome/source mean of last_norm on train
    train_rows = [
        _remap_tensor_row(r, order, csr_order)
        for r in pq.read_table(root / CSR_TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
        if r.get("split_role") == "train"
    ]
    src_outcome_mean: dict[tuple[str, int], float] = {}
    counts: dict[tuple[str, int], int] = defaultdict(int)
    sums: dict[tuple[str, int], float] = defaultdict(float)
    for r in train_rows[:2000]:
        src = "A" if r["source_system"] == "magerya_api" else "B"
        ch = json.loads(r["channels_json"])
        for i, m in enumerate(ch["mask"]):
            if m > 0:
                sums[(src, i)] += ch["last_norm"][i]
                counts[(src, i)] += 1
    for k, c in counts.items():
        src_outcome_mean[k] = sums[k] / c

    by_src: dict[str, dict[str, list]] = defaultdict(
        lambda: {"subj": [], "y": [], "p": [], "p_mean": [], "p_src": []}
    )
    for row in tensors:
        mask = json.loads(row["channels_json"])["mask"]
        last = json.loads(row["channels_json"])["last_norm"]
        observed = [i for i, m in enumerate(mask) if m > 0]
        if not observed:
            continue
        hide = [False] * len(order)
        for i in observed:
            if rng.random() < hide_frac:
                hide[i] = True
        if not any(hide):
            hide[observed[0]] = True
        pred = predict_denoising(model, row, hide_mask=hide)
        src = "A" if row["source_system"] == "magerya_api" else "B"
        for i, h in enumerate(hide):
            if not h:
                continue
            by_src[src]["subj"].append(row["source_scoped_subject_id"])
            by_src[src]["y"].append(last[i])
            by_src[src]["p"].append(pred["reconstruction_norm"][i])
            by_src[src]["p_mean"].append(0.0)
            by_src[src]["p_src"].append(src_outcome_mean.get((src, i), 0.0))

    per_source = {}
    for src, d in by_src.items():
        per_source[src] = {
            "subject_macro_mae": _subject_macro_mae(d["subj"], d["y"], d["p"]) if d["y"] else None,
            "baseline_train_mean_mae": _subject_macro_mae(d["subj"], d["y"], d["p_mean"])
            if d["y"]
            else None,
            "baseline_source_outcome_train_mean_mae": _subject_macro_mae(
                d["subj"], d["y"], d["p_src"]
            )
            if d["y"]
            else None,
            "n_subjects": len(set(d["subj"])),
            "n_masked_entries": len(d["y"]),
        }
    return {"role": role, "metric_space": "train_normalized", "per_source": per_source, "ok": bool(per_source)}


def evaluate_trajectory(
    root: Path, model: dict[str, Any], csr_order: list[str], *, open_test: bool
) -> dict[str, Any]:
    root = Path(root).resolve()
    freeze = json.loads(
        (root / V0111_MODELS_DIR / "frozen-providers.json").read_text(encoding="utf-8")
    )
    providers = freeze.get("providers") or {}
    base = json.loads(
        (
            root
            / "artifacts/stage-03-unified-a-b-individual-state-multi-outcome-baseline-v0.1.1.1"
            / "source-aware-baseline.json"
        ).read_text(encoding="utf-8")
    )
    evidence = base.get("outcome_metrics") or {}
    m2 = _load_m2(root)
    m2_keys = set((m2 or {}).get("outcome_keys") or [])

    tensors_raw = {
        r["state_id"]: r
        for r in pq.read_table(root / CSR_TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
    }
    states = {
        r["state_id"]: r
        for r in pq.read_table(root / V0111_STATES_DIR / "individual_state.parquet").to_pylist()
    }
    targets = pq.read_table(root / V0111_STATES_DIR / "individual_state_target.parquet").to_pylist()
    order = model["outcome_keys"]
    compare_keys = [k for k in order if k in providers and k in evidence]

    # train-only scales per outcome from train targets
    train_scale: dict[str, float] = {}
    for outcome in compare_keys:
        vals = [
            float(t["target_value"])
            for t in targets
            if t["outcome_key"] == outcome and t["split_role"] == "train"
        ]
        if vals:
            mu = sum(vals) / len(vals)
            var = sum((v - mu) ** 2 for v in vals) / len(vals)
            train_scale[outcome] = math.sqrt(var) if var > 1e-12 else 1.0
        else:
            train_scale[outcome] = 1.0

    enc_cache: dict[str, dict[str, float]] = {}

    def forecast(sid: str) -> dict[str, float] | None:
        if sid in enc_cache:
            return enc_cache[sid]
        raw = tensors_raw.get(sid)
        if not raw:
            return None
        row = _remap_tensor_row(raw, order, csr_order)
        enc_cache[sid] = predict_denoising(model, row)["forecast"]
        return enc_cache[sid]

    def run_role(role: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for outcome in compare_keys:
            tier = (evidence.get(outcome) or {}).get("evidence_tier") or ""
            if "DIAGNOSTIC" in tier.upper():
                continue
            prov = providers[outcome]
            active = prov.get("active_provider") or "M0_persistence"
            rows = [
                t
                for t in targets
                if t["outcome_key"] == outcome
                and t["split_role"] == role
                and t.get("persistence_value") is not None
            ]
            rows = sorted(rows, key=lambda r: r["opaque_target_id"])[:1200]
            ys, p0, p_act, p_enc, p_m2, subj = [], [], [], [], [], []
            for r in rows:
                st = states.get(r["state_id"])
                if not st:
                    continue
                y = float(r["target_value"])
                pers = float(r["persistence_value"])
                x = _feats(st, pers)
                if active == "M1_ridge":
                    pred_act = predict_ridge(
                        {
                            "intercept": prov["intercept"],
                            "coefficients": prov["coefficients"],
                            "scaler_mean": prov["scaler_mean"],
                            "scaler_scale": prov["scaler_scale"],
                        },
                        x,
                    )
                else:
                    pred_act = pers
                fc = forecast(r["state_id"])
                if not fc or outcome not in fc:
                    continue
                pred_m2_v = None
                if m2 is not None and outcome in m2_keys:
                    try:
                        pred_m2_v = predict_m2(m2, x).get(outcome)
                    except Exception:
                        pred_m2_v = None
                ys.append(y)
                p0.append(pers)
                p_act.append(float(pred_act))
                p_enc.append(float(fc[outcome]))
                if pred_m2_v is not None:
                    p_m2.append(float(pred_m2_v))
                subj.append(r["source_scoped_subject_id"])
            if not ys:
                continue
            scale = train_scale[outcome]
            mae0 = _subject_macro_mae(subj, ys, p0)
            mae_act = _subject_macro_mae(subj, ys, p_act)
            mae_e = _subject_macro_mae(subj, ys, p_enc)
            entry = {
                "active_provider": active,
                "evidence_tier": tier,
                "n_paired": len(ys),
                "n_subjects": len(set(subj)),
                "identical_target_ids": True,
                "subject_macro_mae_m0": mae0,
                "subject_macro_mae_active": mae_act,
                "subject_macro_mae_encoder": mae_e,
                "normalized_mae_encoder_train_scale": mae_e / scale,
                "normalized_skill_vs_active_train_scale": (mae_act - mae_e) / scale,
                "bootstrap_vs_active": _bootstrap_subject(subj, ys, p_act, p_enc),
                "train_only_scale": scale,
            }
            if len(p_m2) == len(ys):
                entry["subject_macro_mae_prior_m2_technical"] = _subject_macro_mae(
                    subj, ys, p_m2
                )
                entry["prior_m2_loader_corrected"] = True
            out[outcome] = entry
        return out

    val = run_role("validation")
    test = run_role("test") if open_test else {"STATUS": "HELD"}
    better_val = sum(
        1
        for v in val.values()
        if v["subject_macro_mae_encoder"] < v["subject_macro_mae_active"]
    )
    return {
        "version": VERSION,
        "validation": val,
        "test": test,
        "n_encoder_better_than_active_validation": better_val,
        "m2_loader_uses_nested_model": m2 is not None and bool(m2_keys),
        "normalized_metrics_train_only_scale": True,
        "ok": True,
    }


def apply_foundation_gates(
    recon_val: dict[str, Any], traj: dict[str, Any]
) -> dict[str, Any]:
    per = recon_val.get("per_source") or {}
    beat_a = False
    beat_b = False
    if "A" in per and per["A"].get("subject_macro_mae") is not None:
        beat_a = per["A"]["subject_macro_mae"] < per["A"]["baseline_train_mean_mae"]
    if "B" in per and per["B"].get("subject_macro_mae") is not None:
        beat_b = per["B"]["subject_macro_mae"] < per["B"]["baseline_train_mean_mae"]
    recon_gate = (beat_a and beat_b) if GATE_RECON_BEAT_TRAIN_MEAN_BOTH_SOURCES else True
    traj_gate = (
        traj.get("n_encoder_better_than_active_validation", 0)
        >= GATE_MIN_TRAJECTORY_BETTER_THAN_ACTIVE
    )
    accepted = recon_gate and traj_gate
    return {
        "CORRECTED_STATE_REPRESENTATION_FOUNDATION_STATUS": (
            "ACCEPTED" if accepted else "NOT_ACCEPTED"
        ),
        "gates": {
            "recon_beat_train_mean_both_sources": recon_gate,
            "observed_beat_a": beat_a,
            "observed_beat_b": beat_b,
            "trajectory_better_than_active_min": GATE_MIN_TRAJECTORY_BETTER_THAN_ACTIVE,
            "trajectory_better_observed": traj.get("n_encoder_better_than_active_validation"),
            "trajectory_gate": traj_gate,
        },
        "gates_declared_before_test": True,
        "ok": True,
    }
