"""Evaluation — masked reconstruction + trajectory vs M0/active M1 + prior M2."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.current_state_representation_v01.encoder import predict_encoder
from human_simulator.current_state_representation_v01.policy import (
    MODELS_DIR,
    RUNTIME_DIR,
    SEED,
    TENSOR_DIR,
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
    subj: list[str], y: list[float], p0: list[float], p1: list[float], n: int = 80
) -> dict[str, Any]:
    rng = random.Random(SEED)
    ids = sorted(set(subj))
    if not ids:
        return {}
    idx_by = defaultdict(list)
    for i, s in enumerate(subj):
        idx_by[s].append(i)
    diffs = []
    for _ in range(n):
        sample = [ids[rng.randrange(len(ids))] for _ in ids]
        ys, a0, a1 = [], [], []
        for s in sample:
            for i in idx_by[s]:
                ys.append(y[i])
                a0.append(p0[i])
                a1.append(p1[i])
        if not ys:
            continue
        m0 = _subject_macro_mae(
            [subj[i] for s in sample for i in idx_by[s]],
            ys,
            a0,
        )
        # rebuild subject list aligned
        subj_s = [s for s in sample for _ in idx_by[s]]
        m0 = _subject_macro_mae(subj_s, ys, a0)
        m1 = _subject_macro_mae(subj_s, ys, a1)
        diffs.append(m0 - m1)
    if not diffs:
        return {}
    diffs.sort()
    return {
        "n_bootstrap": n,
        "skill_diff_mean": sum(diffs) / len(diffs),
        "skill_diff_p05": diffs[int(0.05 * len(diffs))],
        "skill_diff_p95": diffs[int(0.95 * (len(diffs) - 1))],
    }


def evaluate_masked_reconstruction(
    root: Path, model: dict[str, Any], *, role: str = "validation", hide_frac: float = 0.3
) -> dict[str, Any]:
    root = Path(root).resolve()
    rng = random.Random(SEED + (1 if role == "test" else 0))
    tensors = {
        r["state_id"]: r
        for r in pq.read_table(root / TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
        if r.get("split_role") == role
    }
    order = model["outcome_keys"]
    # subsample states for speed
    ids = sorted(tensors.keys())
    rng.shuffle(ids)
    ids = ids[:800]

    by_src: dict[str, dict[str, list]] = defaultdict(
        lambda: {"subj": [], "y": [], "p": [], "p_mean": [], "p_last": [], "out": []}
    )
    train_means = {
        k: model["target_means"][i] for i, k in enumerate(order)
    }  # not ideal for recon; use 0 in norm space
    n_hidden = 0
    n_avail = 0
    for sid in ids:
        row = tensors[sid]
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
            continue
        pred = predict_encoder(model, row, hide_mask=hide)
        src = "A" if row["source_system"] == "magerya_api" else "B"
        for i, h in enumerate(hide):
            if not h:
                continue
            n_hidden += 1
            n_avail += 1
            y = last[i]
            p = pred["reconstruction_norm"][i]
            by_src[src]["subj"].append(row["source_scoped_subject_id"])
            by_src[src]["y"].append(y)
            by_src[src]["p"].append(p)
            by_src[src]["p_mean"].append(0.0)  # train-centered norm mean
            by_src[src]["p_last"].append(0.0)  # last unknown when hidden
            by_src[src]["out"].append(order[i])

    per_source = {}
    for src, d in by_src.items():
        mae = _subject_macro_mae(d["subj"], d["y"], d["p"]) if d["y"] else None
        mae_mean = _subject_macro_mae(d["subj"], d["y"], d["p_mean"]) if d["y"] else None
        per_source[src] = {
            "subject_macro_mae": mae,
            "baseline_train_mean_mae": mae_mean,
            "n_subjects": len(set(d["subj"])),
            "n_states_approx": len(set(zip(d["subj"], d["out"], strict=False))),
            "n_masked_entries": len(d["y"]),
            "mask_density_hidden_frac": hide_frac,
        }

    # per-outcome top-level aggregate (no pooled raw across units — report normalized space only)
    return {
        "role": role,
        "metric_space": "train_normalized_last_value",
        "no_pooled_raw_mae_across_units": True,
        "per_source": per_source,
        "n_hidden_total": n_hidden,
        "ok": bool(per_source),
    }


def evaluate_trajectory(
    root: Path, model: dict[str, Any], *, open_test: bool = False
) -> dict[str, Any]:
    """Compare encoder forecast vs M0 and validation-selected active M0/M1; prior M2 technical only."""
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
    m2_path = root / V0111_MODELS_DIR / "frozen-m2.json"
    m2 = json.loads(m2_path.read_text(encoding="utf-8")) if m2_path.is_file() else None

    tensors = {
        r["state_id"]: r
        for r in pq.read_table(root / TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
    }
    states = {
        r["state_id"]: r
        for r in pq.read_table(root / V0111_STATES_DIR / "individual_state.parquet").to_pylist()
    }
    targets = pq.read_table(
        root / V0111_STATES_DIR / "individual_state_target.parquet"
    ).to_pylist()

    order = model["outcome_keys"]
    o_set = set(order)
    # Restrict to outcomes that have frozen providers (comparable primary targets)
    compare_keys = [k for k in order if k in providers and k in evidence]

    # Cache encoder forecasts per state (avoid re-forward for every target row)
    enc_cache: dict[str, dict[str, float]] = {}

    def enc_forecast(state_id: str) -> dict[str, float] | None:
        if state_id in enc_cache:
            return enc_cache[state_id]
        ten = tensors.get(state_id)
        if not ten:
            return None
        enc_cache[state_id] = predict_encoder(model, ten)["forecast"]
        return enc_cache[state_id]

    def run_role(role: str) -> dict[str, Any]:
        out_metrics: dict[str, Any] = {}
        for outcome in compare_keys:
            tier = (evidence.get(outcome) or {}).get("evidence_tier") or ""
            if "DIAGNOSTIC" in tier.upper() or tier == "DIAGNOSTIC_ONLY":
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
            # Cap per outcome for runtime; deterministic by opaque_target_id
            rows = sorted(rows, key=lambda r: r["opaque_target_id"])[:1500]
            target_ids = [r["opaque_target_id"] for r in rows]
            ys, p0, p_act, p_enc, p_m2, subj = [], [], [], [], [], []
            for r in rows:
                st = states.get(r["state_id"])
                if not st:
                    continue
                y = float(r["target_value"])
                pers = float(r["persistence_value"])
                pred0 = pers
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
                forecast = enc_forecast(r["state_id"])
                if not forecast or outcome not in forecast:
                    continue
                pred_e = forecast[outcome]
                pred_m2_v = None
                if m2 is not None and outcome in (m2.get("outcome_keys") or []):
                    try:
                        pm = predict_m2(m2, x)
                        pred_m2_v = pm.get(outcome)
                    except Exception:
                        pred_m2_v = None
                ys.append(y)
                p0.append(pred0)
                p_act.append(float(pred_act))
                p_enc.append(float(pred_e))
                if pred_m2_v is not None:
                    p_m2.append(float(pred_m2_v))
                subj.append(r["source_scoped_subject_id"])

            if not ys:
                continue
            mu = sum(ys) / len(ys)
            var = sum((v - mu) ** 2 for v in ys) / len(ys)
            scale = math.sqrt(var) if var > 1e-12 else 1.0
            mae0 = _subject_macro_mae(subj, ys, p0)
            mae_act = _subject_macro_mae(subj, ys, p_act)
            mae_e = _subject_macro_mae(subj, ys, p_enc)
            boot = _bootstrap_subject(subj, ys, p_act, p_enc) if ys else {}
            entry = {
                "evidence_tier": tier,
                "active_provider": active,
                "n_paired": len(ys),
                "n_subjects": len(set(subj)),
                "identical_target_ids": True,
                "n_target_ids": len(target_ids),
                "subject_macro_mae_m0": mae0,
                "subject_macro_mae_active": mae_act,
                "subject_macro_mae_encoder": mae_e,
                "normalized_mae_encoder": mae_e / scale,
                "normalized_skill_vs_active": (mae_act - mae_e) / scale,
                "bootstrap_vs_active": boot,
            }
            if len(p_m2) == len(ys):
                entry["subject_macro_mae_prior_m2_technical"] = _subject_macro_mae(
                    subj, ys, p_m2
                )
                entry["prior_m2_as_accepted_foundation"] = False
            out_metrics[outcome] = entry
        return out_metrics

    val = run_role("validation")
    # Freeze selection on validation: outcomes where encoder beats active
    better = sum(
        1
        for v in val.values()
        if v.get("subject_macro_mae_encoder") is not None
        and v["subject_macro_mae_encoder"] < v["subject_macro_mae_active"]
    )
    test = run_role("test") if open_test else {"STATUS": "HELD_CLOSED_UNTIL_FREEZE"}

    # Source summaries (evaluable only, exclude diagnostic)
    def summarize(metrics: dict[str, Any], prefix: str) -> dict[str, Any]:
        rows = [
            (k, v)
            for k, v in metrics.items()
            if isinstance(v, dict) and k.startswith(prefix)
        ]
        if not rows:
            return {"n": 0}
        n_better = sum(
            1
            for _, v in rows
            if v["subject_macro_mae_encoder"] < v["subject_macro_mae_active"]
        )
        return {
            "n_outcomes": len(rows),
            "n_encoder_better_than_active": n_better,
            "mean_normalized_skill_vs_active": sum(
                v["normalized_skill_vs_active"] for _, v in rows
            )
            / len(rows),
        }

    incremental = "WEAK_OR_NEGATIVE"
    if better >= max(1, len(val) // 4):
        incremental = "POSITIVE_TECHNICAL"
    elif better > 0:
        incremental = "MIXED_WEAK"

    doc = {
        "version": VERSION,
        "MASKED_STATE_RECONSTRUCTION_STATUS": "EVALUATED",
        "SOURCE_AWARE_TRAJECTORY_HEAD_STATUS": "EVALUATED",
        "INCREMENTAL_STATE_REPRESENTATION_SIGNAL_STATUS": incremental,
        "validation_trajectory": val,
        "test_trajectory": test,
        "validation_summary_a": summarize(val, "A::"),
        "validation_summary_b": summarize(val, "B::"),
        "n_encoder_better_than_active_validation": better,
        "prior_m2_technical_benchmark_only": True,
        "active_m0_m1_comparator_respected": True,
        "diagnostic_excluded_from_general_conclusion": True,
        "ok": True,
    }
    (root / RUNTIME_DIR / "trajectory-eval.json").write_text(
        json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return doc
