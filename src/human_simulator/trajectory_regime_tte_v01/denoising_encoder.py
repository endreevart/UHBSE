"""DenoisingSourceAwareStateEncoderV01 — real train-time corruption."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.trajectory_regime_tte_v01.policy import (
    CORRUPTION_FRAC,
    CSR_TENSOR_DIR,
    ENC_EPOCHS,
    ENC_L2,
    ENC_LR,
    ENC_RANK,
    MAX_TRAIN_STATES,
    METHOD_VERSION,
    MODEL_NAME,
    MODELS_DIR,
    OUTCOME_CHANNELS,
    RUNTIME_DIR,
    SEED,
    V0111_STATES_DIR,
    VERSION,
)
from human_simulator.unified_individual_state_v0111.ridge import fit_scaler, transform

CONTEXT_KEYS = (
    "longitudinal_age_days",
    "days_since_last_event",
    "n_events_before",
    "n_obs_before",
    "n_encounters_before",
    "n_medications_before",
    "n_recommendations_before",
    "n_documents_before",
    "n_procedures_before",
    "source_is_a",
    "source_is_b",
    "missingness_lab",
    "overlap_is_unlinked",
    "days_since_last_event_defined",
)


def _init_matrix(rows: int, cols: int, rng: random.Random, scale: float = 0.01) -> list[list[float]]:
    return [[rng.uniform(-scale, scale) for _ in range(cols)] for _ in range(rows)]


def _corrupt_channels(
    channels: dict[str, list[float]],
    hide: list[bool],
) -> dict[str, list[float]]:
    """Zero all leakage channels for hidden outcomes (including mask)."""
    out = {k: list(v) for k, v in channels.items()}
    for i, h in enumerate(hide):
        if not h:
            continue
        out["mask"][i] = 0.0
        out["last_norm"][i] = 0.0
        out["prev_norm"][i] = 0.0
        out["delta_norm"][i] = 0.0
        out["slope_norm"][i] = 0.0
        out["var_norm"][i] = 0.0
        out["time_since"][i] = -1.0
        out["n_prior"][i] = 0.0
    return out


def _pack_lab(channels: dict[str, list[float]], indices: list[int]) -> list[float]:
    out: list[float] = []
    for i in indices:
        m = channels["mask"][i]
        for ch in OUTCOME_CHANNELS:
            v = channels[ch][i]
            if ch == "mask":
                out.append(v)
            elif ch == "time_since":
                out.append(v if m > 0 else -1.0)
            elif ch == "n_prior":
                out.append(v if m > 0 else 0.0)
            else:
                out.append(v * m)
    return out


def _stratified_sample(
    rows: list[dict[str, Any]], n: int, seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministic source / missingness / history stratified subsample."""
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        ctx = json.loads(r["context_json"])
        src = "A" if ctx.get("source_is_a") else "B"
        dens = sum(json.loads(r["channels_json"])["mask"]) / max(r["n_outcomes"], 1)
        dens_b = "hi" if dens >= 0.05 else ("mid" if dens >= 0.01 else "lo")
        hist = "deep" if (ctx.get("n_obs_before") or 0) >= 5 else "shallow"
        buckets[f"{src}|{dens_b}|{hist}"].append(r)
    for k in buckets:
        buckets[k].sort(key=lambda x: x["state_id"])
        rng_b = random.Random(seed ^ hashlib.sha256(k.encode()).digest()[0])
        rng_b.shuffle(buckets[k])
    # proportional allocation
    total = len(rows)
    alloc = {k: max(1, int(round(n * len(v) / total))) for k, v in buckets.items()}
    # fix sum
    while sum(alloc.values()) > n:
        kmax = max(alloc, key=lambda k: alloc[k])
        if alloc[kmax] > 1:
            alloc[kmax] -= 1
        else:
            break
    while sum(alloc.values()) < n:
        kmax = max(buckets, key=lambda k: len(buckets[k]) - alloc.get(k, 0))
        if alloc.get(kmax, 0) < len(buckets[kmax]):
            alloc[kmax] = alloc.get(kmax, 0) + 1
        else:
            break
    chosen = []
    for k, take in alloc.items():
        chosen.extend(buckets[k][: min(take, len(buckets[k]))])
    chosen = sorted(chosen, key=lambda x: x["state_id"])
    funnel = {
        "train_available": total,
        "requested": n,
        "selected": len(chosen),
        "buckets": {k: {"available": len(v), "taken": alloc.get(k, 0)} for k, v in buckets.items()},
        "not_first_rows": True,
        "stratified_by": ["source", "mask_density", "history_depth"],
    }
    return chosen[:n] if len(chosen) > n else chosen, funnel


def fit_denoising_encoder(
    root: Path,
    vocab: dict[str, Any],
    *,
    rank: int = ENC_RANK,
    epochs: int = ENC_EPOCHS,
    lr: float = ENC_LR,
    l2: float = ENC_L2,
    seed: int = SEED,
    max_train: int = MAX_TRAIN_STATES,
    corruption_frac: float = CORRUPTION_FRAC,
) -> dict[str, Any]:
    root = Path(root).resolve()
    order: list[str] = list(vocab["vocabulary_order"])
    # Map CSR tensor channel indices (CSR used same 308 keys typically)
    csr_vocab_path = (
        root
        / "artifacts/stage-03-first-unified-current-state-representation-applicability-ood-v0.1"
        / "outcome-vocabulary.json"
    )
    csr_order = json.loads(csr_vocab_path.read_text(encoding="utf-8"))["vocabulary_order"]
    csr_index = {k: i for i, k in enumerate(csr_order)}
    # Align: only outcomes present in CSR tensor
    order = [k for k in order if k in csr_index]
    local_from_csr = [csr_index[k] for k in order]
    a_idx = [i for i, k in enumerate(order) if k.startswith("A::")]
    b_idx = [i for i, k in enumerate(order) if k.startswith("B::")]
    n_out = len(order)

    tensors = pq.read_table(root / CSR_TENSOR_DIR / "current_state_tensor.parquet").to_pylist()

    def remap_row(r: dict[str, Any]) -> dict[str, Any]:
        ch = json.loads(r["channels_json"])
        new_ch = {c: [ch[c][j] for j in local_from_csr] for c in OUTCOME_CHANNELS}
        return {
            **r,
            "channels_json": json.dumps(new_ch, separators=(",", ":")),
            "n_outcomes": n_out,
        }

    train_all = [remap_row(r) for r in tensors if r.get("split_role") == "train"]
    val_all = [remap_row(r) for r in tensors if r.get("split_role") == "validation"]

    if len(train_all) > max_train:
        train_rows, sample_funnel = _stratified_sample(train_all, max_train, seed)
    else:
        train_rows, sample_funnel = train_all, {
            "train_available": len(train_all),
            "requested": len(train_all),
            "selected": len(train_all),
            "full_train_used": True,
        }
    (root / RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / RUNTIME_DIR / "encoder-sampling-funnel.json").write_text(
        json.dumps(sample_funnel, indent=2) + "\n", encoding="utf-8"
    )

    # Targets for forecast
    targets = pq.read_table(
        root / V0111_STATES_DIR / "individual_state_target.parquet",
        columns=["state_id", "outcome_key", "target_value", "split_role"],
    ).to_pylist()
    o_set = set(order)
    y_by_state: dict[str, dict[str, float]] = defaultdict(dict)
    for t in targets:
        if t.get("split_role") != "train" or t["outcome_key"] not in o_set:
            continue
        y_by_state[t["state_id"]][t["outcome_key"]] = float(t["target_value"])

    # Train-only target means/scales
    y_means = [0.0] * n_out
    y_scales = [1.0] * n_out
    for o, key in enumerate(order):
        vals = [
            y_by_state[sid][key]
            for sid in y_by_state
            if key in y_by_state[sid]
        ]
        # only from train states in subsample? Use all train targets for that outcome
        if vals:
            mu = sum(vals) / len(vals)
            var = sum((v - mu) ** 2 for v in vals) / len(vals)
            y_means[o] = mu
            y_scales[o] = math.sqrt(var) if var > 1e-12 else 1.0

    # Build design matrices from uncorrupted rows for scalers (train-only)
    X_ctx, X_a, X_b = [], [], []
    for r in train_rows:
        ctx = json.loads(r["context_json"])
        ch = json.loads(r["channels_json"])
        X_ctx.append([float(ctx.get(k) or 0.0) for k in CONTEXT_KEYS])
        X_a.append(_pack_lab(ch, a_idx))
        X_b.append(_pack_lab(ch, b_idx))
    ctx_mean, ctx_scale = fit_scaler(X_ctx)
    a_mean, a_scale = fit_scaler(X_a) if X_a and X_a[0] else ([0.0], [1.0])
    b_mean, b_scale = fit_scaler(X_b) if X_b and X_b[0] else ([0.0], [1.0])

    rng = random.Random(seed)
    d_ctx = len(CONTEXT_KEYS)
    d_a = len(a_idx) * len(OUTCOME_CHANNELS)
    d_b = len(b_idx) * len(OUTCOME_CHANNELS)
    W_ctx = _init_matrix(rank, d_ctx, rng)
    b_ctx = [0.0] * rank
    W_a = _init_matrix(rank, d_a, rng)
    b_a = [0.0] * rank
    W_b = _init_matrix(rank, d_b, rng)
    b_b = [0.0] * rank
    lat = 3 * rank
    W_recon = _init_matrix(n_out, lat, rng)
    b_recon = [0.0] * n_out
    W_fore = _init_matrix(n_out, lat, rng)
    b_fore = [0.0] * n_out

    def forward(xc, xa, xb):
        hc = [
            math.tanh(sum(W_ctx[r][j] * xc[j] for j in range(d_ctx)) + b_ctx[r])
            for r in range(rank)
        ]
        ha = [
            math.tanh(sum(W_a[r][j] * xa[j] for j in range(d_a)) + b_a[r])
            for r in range(rank)
        ]
        hb = [
            math.tanh(sum(W_b[r][j] * xb[j] for j in range(d_b)) + b_b[r])
            for r in range(rank)
        ]
        h = hc + ha + hb
        recon = [sum(W_recon[o][k] * h[k] for k in range(lat)) + b_recon[o] for o in range(n_out)]
        fore = [sum(W_fore[o][k] * h[k] for k in range(lat)) + b_fore[o] for o in range(n_out)]
        return h, recon, fore

    def pack_scaled(r, hide):
        ctx = json.loads(r["context_json"])
        ch = _corrupt_channels(json.loads(r["channels_json"]), hide)
        xc = [(float(ctx.get(k) or 0.0) - m) / s for k, m, s in zip(CONTEXT_KEYS, ctx_mean, ctx_scale, strict=True)]
        xa = [(v - m) / s for v, m, s in zip(_pack_lab(ch, a_idx), a_mean, a_scale, strict=True)]
        xb = [(v - m) / s for v, m, s in zip(_pack_lab(ch, b_idx), b_mean, b_scale, strict=True)]
        return xc, xa, xb

    def eval_fixed(rows_eval: list[dict[str, Any]], tag: str) -> dict[str, float]:
        """Epoch-end fixed-set loss (not online pre-update)."""
        total_r = total_f = 0.0
        n_r = n_f = 0
        n_a = n_b = 0
        loss_a = loss_b = 0.0
        for r in rows_eval:
            ch = json.loads(r["channels_json"])
            mask = ch["mask"]
            observed = [i for i, m in enumerate(mask) if m > 0]
            hide = [False] * n_out
            for i in observed:
                if rng.random() < corruption_frac:
                    hide[i] = True
            if not any(hide):
                if observed:
                    hide[observed[0]] = True
                else:
                    continue
            xc, xa, xb = pack_scaled(r, hide)
            _, recon, fore = forward(xc, xa, xb)
            src_a = json.loads(r["context_json"]).get("source_is_a", 0) > 0
            for o in range(n_out):
                if not hide[o] or mask[o] <= 0:
                    continue
                err = recon[o] - ch["last_norm"][o]
                total_r += err * err
                n_r += 1
                if src_a:
                    loss_a += err * err
                    n_a += 1
                else:
                    loss_b += err * err
                    n_b += 1
            fut = y_by_state.get(r["state_id"], {})
            for o, key in enumerate(order):
                if key not in fut:
                    continue
                y_true = (fut[key] - y_means[o]) / y_scales[o]
                err = fore[o] - y_true
                total_f += err * err
                n_f += 1
        return {
            f"{tag}_recon_mse": total_r / max(n_r, 1),
            f"{tag}_fore_mse": total_f / max(n_f, 1),
            f"{tag}_recon_a": loss_a / max(n_a, 1),
            f"{tag}_recon_b": loss_b / max(n_b, 1),
            f"{tag}_n_recon": float(n_r),
            f"{tag}_n_fore": float(n_f),
        }

    val_probe = sorted(val_all, key=lambda r: r["state_id"])[:400]
    history = []
    best_val = float("inf")
    best_snapshot = None

    for ep in range(epochs):
        print(json.dumps({"denoising_epoch": ep, "n_train": len(train_rows)}), flush=True)
        order_i = list(range(len(train_rows)))
        rng.shuffle(order_i)
        for i in order_i:
            r = train_rows[i]
            ch = json.loads(r["channels_json"])
            mask = ch["mask"]
            observed = [j for j, m in enumerate(mask) if m > 0]
            hide = [False] * n_out
            for j in observed:
                if rng.random() < corruption_frac:
                    hide[j] = True
            if observed and not any(hide):
                hide[observed[rng.randrange(len(observed))]] = True
            xc, xa, xb = pack_scaled(r, hide)
            h, recon, fore = forward(xc, xa, xb)
            g_h = [0.0] * lat
            # balanced recon: weight by 1/n_hidden and source
            hidden_idx = [o for o in range(n_out) if hide[o] and mask[o] > 0]
            src_a = json.loads(r["context_json"]).get("source_is_a", 0) > 0
            src_w = 0.5  # equal A/B emphasis in gradient scale
            for o in hidden_idx:
                err = recon[o] - ch["last_norm"][o]
                w = src_w / max(len(hidden_idx), 1)
                for k in range(lat):
                    g_h[k] += w * err * W_recon[o][k]
                    W_recon[o][k] -= lr * (w * err * h[k] + l2 * W_recon[o][k])
                b_recon[o] -= lr * w * err
            fut = y_by_state.get(r["state_id"], {})
            fut_idx = [o for o, key in enumerate(order) if key in fut]
            for o in fut_idx:
                y_true = (fut[order[o]] - y_means[o]) / y_scales[o]
                err = fore[o] - y_true
                w = 0.5 / max(len(fut_idx), 1)  # balance vs recon
                for k in range(lat):
                    g_h[k] += w * err * W_fore[o][k]
                    W_fore[o][k] -= lr * (w * err * h[k] + l2 * W_fore[o][k])
                b_fore[o] -= lr * w * err
            for rnk in range(rank):
                z = sum(W_ctx[rnk][j] * xc[j] for j in range(d_ctx)) + b_ctx[rnk]
                dt = (1.0 - math.tanh(z) ** 2) * g_h[rnk]
                for j in range(d_ctx):
                    W_ctx[rnk][j] -= lr * (dt * xc[j] + l2 * W_ctx[rnk][j])
                b_ctx[rnk] -= lr * dt
                z = sum(W_a[rnk][j] * xa[j] for j in range(d_a)) + b_a[rnk]
                dt = (1.0 - math.tanh(z) ** 2) * g_h[rank + rnk]
                for j in range(d_a):
                    W_a[rnk][j] -= lr * (dt * xa[j] + l2 * W_a[rnk][j])
                b_a[rnk] -= lr * dt
                z = sum(W_b[rnk][j] * xb[j] for j in range(d_b)) + b_b[rnk]
                dt = (1.0 - math.tanh(z) ** 2) * g_h[2 * rank + rnk]
                for j in range(d_b):
                    W_b[rnk][j] -= lr * (dt * xb[j] + l2 * W_b[rnk][j])
                b_b[rnk] -= lr * dt

        # fixed-set epoch metrics (fresh rng stream offset)
        metrics = eval_fixed(train_rows[:300], "train")
        metrics.update(eval_fixed(val_probe, "val"))
        metrics["epoch"] = ep
        history.append(metrics)
        val_score = metrics["val_recon_mse"] + metrics["val_fore_mse"]
        if val_score < best_val:
            best_val = val_score
            best_snapshot = {
                "W_ctx": [row[:] for row in W_ctx],
                "b_ctx": b_ctx[:],
                "W_a": [row[:] for row in W_a],
                "b_a": b_a[:],
                "W_b": [row[:] for row in W_b],
                "b_b": b_b[:],
                "W_recon": [row[:] for row in W_recon],
                "b_recon": b_recon[:],
                "W_fore": [row[:] for row in W_fore],
                "b_fore": b_fore[:],
                "epoch": ep,
            }

    if best_snapshot:
        W_ctx, b_ctx = best_snapshot["W_ctx"], best_snapshot["b_ctx"]
        W_a, b_a = best_snapshot["W_a"], best_snapshot["b_a"]
        W_b, b_b = best_snapshot["W_b"], best_snapshot["b_b"]
        W_recon, b_recon = best_snapshot["W_recon"], best_snapshot["b_recon"]
        W_fore, b_fore = best_snapshot["W_fore"], best_snapshot["b_fore"]

    model = {
        "model_name": MODEL_NAME,
        "architecture": {
            "type": MODEL_NAME,
            "denoising_masked_training": True,
            "corruption_frac": corruption_frac,
            "rank_per_block": rank,
            "latent_dim": lat,
            "epochs": epochs,
            "early_stopped_epoch": best_snapshot["epoch"] if best_snapshot else epochs - 1,
            "lr": lr,
            "l2": l2,
            "no_v01_weight_init": True,
            "balanced_source_outcome_recon_fore": True,
        },
        "outcome_keys": list(order),
        "a_indices": a_idx,
        "b_indices": b_idx,
        "context_keys": list(CONTEXT_KEYS),
        "outcome_channels": list(OUTCOME_CHANNELS),
        "ctx_scaler_mean": ctx_mean,
        "ctx_scaler_scale": ctx_scale,
        "a_scaler_mean": a_mean,
        "a_scaler_scale": a_scale,
        "b_scaler_mean": b_mean,
        "b_scaler_scale": b_scale,
        "target_means": y_means,
        "target_scales": y_scales,
        "W_ctx": W_ctx,
        "b_ctx": b_ctx,
        "W_a": W_a,
        "b_a": b_a,
        "W_b": W_b,
        "b_b": b_b,
        "W_recon": W_recon,
        "b_recon": b_recon,
        "W_fore": W_fore,
        "b_fore": b_fore,
        "mask_schema": "corruption hides all channels; recon loss only on hidden originally-observed",
        "seed": seed,
        "method_version": METHOD_VERSION,
        "vocabulary_hash": vocab["vocabulary_hash"],
        "n_train_states_used": len(train_rows),
        "sampling_funnel": sample_funnel,
        "epoch_end_history": history,
        "version": VERSION,
    }
    return model


def predict_denoising(
    model: dict[str, Any],
    row: dict[str, Any],
    *,
    hide_mask: list[bool] | None = None,
) -> dict[str, Any]:
    a_idx, b_idx = model["a_indices"], model["b_indices"]
    channels = json.loads(row["channels_json"])
    if hide_mask is not None:
        channels = _corrupt_channels(channels, hide_mask)
    ctx = json.loads(row["context_json"])
    xc = [
        (float(ctx.get(k) or 0.0) - m) / s
        for k, m, s in zip(
            model["context_keys"], model["ctx_scaler_mean"], model["ctx_scaler_scale"], strict=True
        )
    ]
    xa = [
        (v - m) / s
        for v, m, s in zip(_pack_lab(channels, a_idx), model["a_scaler_mean"], model["a_scaler_scale"], strict=True)
    ]
    xb = [
        (v - m) / s
        for v, m, s in zip(_pack_lab(channels, b_idx), model["b_scaler_mean"], model["b_scaler_scale"], strict=True)
    ]
    rank = model["architecture"]["rank_per_block"]
    lat = model["architecture"]["latent_dim"]
    d_ctx, d_a, d_b = len(xc), len(xa), len(xb)
    hc = [
        math.tanh(sum(model["W_ctx"][r][j] * xc[j] for j in range(d_ctx)) + model["b_ctx"][r])
        for r in range(rank)
    ]
    ha = [
        math.tanh(sum(model["W_a"][r][j] * xa[j] for j in range(d_a)) + model["b_a"][r])
        for r in range(rank)
    ]
    hb = [
        math.tanh(sum(model["W_b"][r][j] * xb[j] for j in range(d_b)) + model["b_b"][r])
        for r in range(rank)
    ]
    h = hc + ha + hb
    n_out = len(model["outcome_keys"])
    recon = [
        sum(model["W_recon"][o][k] * h[k] for k in range(lat)) + model["b_recon"][o]
        for o in range(n_out)
    ]
    fore = [
        (
            sum(model["W_fore"][o][k] * h[k] for k in range(lat)) + model["b_fore"][o]
        )
        * model["target_scales"][o]
        + model["target_means"][o]
        for o in range(n_out)
    ]
    mask = channels["mask"]
    return {
        "latent": h,
        "reconstruction_norm": recon,
        "forecast": {k: fore[i] for i, k in enumerate(model["outcome_keys"])},
        "input_mask": mask,
        "applicability_features": {
            "mask_density": sum(mask) / max(len(mask), 1),
            "n_observed": sum(1 for m in mask if m > 0),
            "latent_l2": math.sqrt(sum(x * x for x in h)),
            "source_is_a": ctx.get("source_is_a", 0),
            "source_is_b": ctx.get("source_is_b", 0),
            "longitudinal_age_days": ctx.get("longitudinal_age_days", 0),
            "n_obs_before": ctx.get("n_obs_before", 0),
        },
    }


def encoder_identity(model: dict[str, Any], meta: dict[str, Any]) -> str:
    material = {
        "architecture": model["architecture"],
        "W_ctx": model["W_ctx"],
        "b_ctx": model["b_ctx"],
        "W_a": model["W_a"],
        "b_a": model["b_a"],
        "W_b": model["W_b"],
        "b_b": model["b_b"],
        "W_recon": model["W_recon"],
        "b_recon": model["b_recon"],
        "W_fore": model["W_fore"],
        "b_fore": model["b_fore"],
        "outcome_keys": model["outcome_keys"],
        "target_means": model["target_means"],
        "target_scales": model["target_scales"],
        "mask_schema": model["mask_schema"],
        "seed": model["seed"],
        "vocabulary_hash": model.get("vocabulary_hash"),
        **{k: meta.get(k) for k in ("train_population_hash", "split_hash", "target_construction_hash")},
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save_encoder(root: Path, model: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    out = Path(root) / MODELS_DIR
    out.mkdir(parents=True, exist_ok=True)
    ident = encoder_identity(model, meta)
    model = {**model, "model_identity_sha256": ident, "freeze_meta": meta}
    (out / "frozen-denoising-encoder.json").write_text(
        json.dumps(model, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return {"identity": ident, "path": str(out / "frozen-denoising-encoder.json")}
