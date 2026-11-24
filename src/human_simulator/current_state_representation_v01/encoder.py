"""UnifiedSourceAwareStateEncoderV01 — shared + source-specific blocks."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from human_simulator.current_state_representation_v01.policy import (
    ENC_EPOCHS,
    ENC_L2,
    ENC_LR,
    ENC_RANK,
    MAX_TRAIN_STATES,
    METHOD_VERSION,
    MODEL_NAME,
    MODELS_DIR,
    OUTCOME_CHANNELS,
    SEED,
    TENSOR_DIR,
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


def _pack_lab_block(
    channels: dict[str, list[float]],
    indices: list[int],
) -> list[float]:
    """Pack per-outcome channels; value channels multiplied by mask (no clinical zero claim)."""
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


def encode_row(
    row: dict[str, Any],
    *,
    a_idx: list[int],
    b_idx: list[int],
) -> tuple[list[float], list[float], list[float], list[float]]:
    ctx = json.loads(row["context_json"])
    channels = json.loads(row["channels_json"])
    x_ctx = [float(ctx.get(k) or 0.0) for k in CONTEXT_KEYS]
    x_a = _pack_lab_block(channels, a_idx)
    x_b = _pack_lab_block(channels, b_idx)
    mask = list(channels["mask"])
    return x_ctx, x_a, x_b, mask


def fit_encoder(
    root: Path,
    vocab: dict[str, Any],
    *,
    rank: int = ENC_RANK,
    epochs: int = ENC_EPOCHS,
    lr: float = ENC_LR,
    l2: float = ENC_L2,
    seed: int = SEED,
    max_train: int = MAX_TRAIN_STATES,
) -> dict[str, Any]:
    root = Path(root).resolve()
    order: list[str] = list(vocab["vocabulary_order"])
    a_idx = [i for i, k in enumerate(order) if k.startswith("A::")]
    b_idx = [i for i, k in enumerate(order) if k.startswith("B::")]
    n_out = len(order)

    tensors = pq.read_table(root / TENSOR_DIR / "current_state_tensor.parquet").to_pylist()
    train_rows = [r for r in tensors if r.get("split_role") == "train"]
    rng = random.Random(seed)
    if len(train_rows) > max_train:
        train_rows = sorted(train_rows, key=lambda r: r["state_id"])
        rng.shuffle(train_rows)
        train_rows = train_rows[:max_train]

    # Targets for forecast heads (state_id -> outcome -> value)
    targets = pq.read_table(
        root / V0111_STATES_DIR / "individual_state_target.parquet",
        columns=["state_id", "outcome_key", "target_value", "split_role", "days_after_cutoff"],
    ).to_pylist()
    o_set = set(order)
    y_by_state: dict[str, dict[str, float]] = defaultdict(dict)
    for t in targets:
        if t.get("split_role") != "train":
            continue
        if t["outcome_key"] not in o_set:
            continue
        y_by_state[t["state_id"]][t["outcome_key"]] = float(t["target_value"])

    X_ctx: list[list[float]] = []
    X_a: list[list[float]] = []
    X_b: list[list[float]] = []
    masks: list[list[float]] = []
    last_norms: list[list[float]] = []
    Y_fut: list[list[float | None]] = []
    state_ids: list[str] = []

    for r in train_rows:
        xc, xa, xb, mask = encode_row(r, a_idx=a_idx, b_idx=b_idx)
        ch = json.loads(r["channels_json"])
        X_ctx.append(xc)
        X_a.append(xa)
        X_b.append(xb)
        masks.append(mask)
        last_norms.append(list(ch["last_norm"]))
        fut = y_by_state.get(r["state_id"], {})
        Y_fut.append([fut.get(k) for k in order])
        state_ids.append(r["state_id"])

    n = len(X_ctx)
    if n == 0:
        raise ValueError("no train tensors")

    ctx_mean, ctx_scale = fit_scaler(X_ctx)
    a_mean, a_scale = fit_scaler(X_a) if X_a[0] else ([0.0], [1.0])
    b_mean, b_scale = fit_scaler(X_b) if X_b[0] else ([0.0], [1.0])
    Xs_ctx = transform(X_ctx, ctx_mean, ctx_scale)
    Xs_a = transform(X_a, a_mean, a_scale)
    Xs_b = transform(X_b, b_mean, b_scale)

    # Per-outcome target normalization (train forecast)
    y_means = [0.0] * n_out
    y_scales = [1.0] * n_out
    for o in range(n_out):
        vals = [float(Y_fut[i][o]) for i in range(n) if Y_fut[i][o] is not None]
        if vals:
            mu = sum(vals) / len(vals)
            var = sum((v - mu) ** 2 for v in vals) / len(vals)
            y_means[o] = mu
            y_scales[o] = math.sqrt(var) if var > 1e-12 else 1.0

    d_ctx = len(Xs_ctx[0])
    d_a = len(Xs_a[0])
    d_b = len(Xs_b[0])
    W_ctx = _init_matrix(rank, d_ctx, rng)
    b_ctx = [0.0] * rank
    W_a = _init_matrix(rank, d_a, rng)
    b_a = [0.0] * rank
    W_b = _init_matrix(rank, d_b, rng)
    b_b = [0.0] * rank
    # latent dim = 3 * rank
    lat = 3 * rank
    W_recon = _init_matrix(n_out, lat, rng)
    b_recon = [0.0] * n_out
    W_fore = _init_matrix(n_out, lat, rng)
    b_fore = [0.0] * n_out

    def forward(xc: list[float], xa: list[float], xb: list[float]) -> tuple[list[float], list[float], list[float]]:
        zc = [sum(W_ctx[r][j] * xc[j] for j in range(d_ctx)) + b_ctx[r] for r in range(rank)]
        hc = [math.tanh(v) for v in zc]
        za = [sum(W_a[r][j] * xa[j] for j in range(d_a)) + b_a[r] for r in range(rank)]
        ha = [math.tanh(v) for v in za]
        zb = [sum(W_b[r][j] * xb[j] for j in range(d_b)) + b_b[r] for r in range(rank)]
        hb = [math.tanh(v) for v in zb]
        h = hc + ha + hb
        recon = [sum(W_recon[o][k] * h[k] for k in range(lat)) + b_recon[o] for o in range(n_out)]
        fore = [sum(W_fore[o][k] * h[k] for k in range(lat)) + b_fore[o] for o in range(n_out)]
        return h, recon, fore

    history = []
    for ep in range(epochs):
        print(
            json.dumps({"encoder_epoch": ep, "n_train": n, "n_out": n_out}),
            flush=True,
        )
        total = 0.0
        count = 0
        order_i = list(range(n))
        rng.shuffle(order_i)
        for i in order_i:
            xc, xa, xb = Xs_ctx[i], Xs_a[i], Xs_b[i]
            h, recon, fore = forward(xc, xa, xb)
            g_h = [0.0] * lat
            # reconstruction on observed mask
            for o in range(n_out):
                if masks[i][o] <= 0:
                    continue
                y_true = last_norms[i][o]
                err = recon[o] - y_true
                total += err * err
                count += 1
                for k in range(lat):
                    g_h[k] += err * W_recon[o][k]
                    W_recon[o][k] -= lr * (err * h[k] + l2 * W_recon[o][k])
                b_recon[o] -= lr * err
            # forecast masked
            for o in range(n_out):
                if Y_fut[i][o] is None:
                    continue
                y_true = (float(Y_fut[i][o]) - y_means[o]) / y_scales[o]
                err = fore[o] - y_true
                total += err * err
                count += 1
                for k in range(lat):
                    g_h[k] += err * W_fore[o][k]
                    W_fore[o][k] -= lr * (err * h[k] + l2 * W_fore[o][k])
                b_fore[o] -= lr * err
            # backprop blocks
            for r in range(rank):
                # ctx
                z = sum(W_ctx[r][j] * xc[j] for j in range(d_ctx)) + b_ctx[r]
                dt = (1.0 - math.tanh(z) ** 2) * g_h[r]
                for j in range(d_ctx):
                    W_ctx[r][j] -= lr * (dt * xc[j] + l2 * W_ctx[r][j])
                b_ctx[r] -= lr * dt
                # a
                z = sum(W_a[r][j] * xa[j] for j in range(d_a)) + b_a[r]
                dt = (1.0 - math.tanh(z) ** 2) * g_h[rank + r]
                for j in range(d_a):
                    W_a[r][j] -= lr * (dt * xa[j] + l2 * W_a[r][j])
                b_a[r] -= lr * dt
                # b
                z = sum(W_b[r][j] * xb[j] for j in range(d_b)) + b_b[r]
                dt = (1.0 - math.tanh(z) ** 2) * g_h[2 * rank + r]
                for j in range(d_b):
                    W_b[r][j] -= lr * (dt * xb[j] + l2 * W_b[r][j])
                b_b[r] -= lr * dt
        loss = total / max(count, 1)
        history.append({"epoch": ep, "masked_mse": loss, "n_obs": count})

    model = {
        "model_name": MODEL_NAME,
        "architecture": {
            "type": "UnifiedSourceAwareStateEncoderV01",
            "shared_context_encoder": True,
            "source_specific_lab_blocks": ["A", "B"],
            "source_specific_forecast_heads": True,
            "rank_per_block": rank,
            "latent_dim": lat,
            "epochs": epochs,
            "lr": lr,
            "l2": l2,
            "activation": "tanh",
            "no_mixed_persistence_channel": True,
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
        "mask_schema": "mask[o]==0 => unobserved; recon/forecast loss only on observed",
        "seed": seed,
        "method_version": METHOD_VERSION,
        "vocabulary_hash": vocab["vocabulary_hash"],
        "n_train_states_used": n,
        "max_train_cap": max_train,
        "train_loss_history": history[-5:],
        "final_train_masked_mse": history[-1]["masked_mse"] if history else None,
        "version": VERSION,
    }
    return model


def predict_encoder(
    model: dict[str, Any],
    row: dict[str, Any],
    *,
    hide_mask: list[bool] | None = None,
) -> dict[str, Any]:
    """Forward pass. hide_mask: if True, treat that outcome as missing for input (reconstruction probe)."""
    a_idx = model["a_indices"]
    b_idx = model["b_indices"]
    channels = json.loads(row["channels_json"])
    if hide_mask is not None:
        channels = {k: list(v) for k, v in channels.items()}
        for i, hide in enumerate(hide_mask):
            if hide:
                channels["mask"][i] = 0.0
                channels["last_norm"][i] = 0.0
                channels["prev_norm"][i] = 0.0
                channels["delta_norm"][i] = 0.0
                channels["slope_norm"][i] = 0.0
                channels["var_norm"][i] = 0.0
                channels["time_since"][i] = -1.0
                channels["n_prior"][i] = 0.0
    fake = {**row, "channels_json": json.dumps(channels)}
    xc, xa, xb, mask = encode_row(fake, a_idx=a_idx, b_idx=b_idx)
    xc = [(v - m) / s for v, m, s in zip(xc, model["ctx_scaler_mean"], model["ctx_scaler_scale"], strict=True)]
    xa = [(v - m) / s for v, m, s in zip(xa, model["a_scaler_mean"], model["a_scaler_scale"], strict=True)]
    xb = [(v - m) / s for v, m, s in zip(xb, model["b_scaler_mean"], model["b_scaler_scale"], strict=True)]
    rank = model["architecture"]["rank_per_block"]
    lat = model["architecture"]["latent_dim"]
    d_ctx, d_a, d_b = len(xc), len(xa), len(xb)
    W_ctx, b_ctx = model["W_ctx"], model["b_ctx"]
    W_a, b_a = model["W_a"], model["b_a"]
    W_b, b_b = model["W_b"], model["b_b"]
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
    n_out = model["architecture"] and len(model["outcome_keys"])
    recon = [
        sum(model["W_recon"][o][k] * h[k] for k in range(lat)) + model["b_recon"][o]
        for o in range(n_out)
    ]
    fore_n = [
        sum(model["W_fore"][o][k] * h[k] for k in range(lat)) + model["b_fore"][o]
        for o in range(n_out)
    ]
    fore = [
        fore_n[o] * model["target_scales"][o] + model["target_means"][o]
        for o in range(n_out)
    ]
    return {
        "latent": h,
        "reconstruction_norm": recon,
        "forecast": {k: fore[i] for i, k in enumerate(model["outcome_keys"])},
        "input_mask": mask,
        "applicability_features": {
            "mask_density": sum(mask) / max(len(mask), 1),
            "n_observed": sum(1 for m in mask if m > 0),
            "latent_l2": math.sqrt(sum(x * x for x in h)),
            "source_is_a": json.loads(row["context_json"]).get("source_is_a", 0),
            "source_is_b": json.loads(row["context_json"]).get("source_is_b", 0),
            "longitudinal_age_days": json.loads(row["context_json"]).get(
                "longitudinal_age_days", 0
            ),
        },
    }


def encoder_canonical_identity(model: dict[str, Any], meta: dict[str, Any]) -> str:
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
        "ctx_scaler_mean": model["ctx_scaler_mean"],
        "ctx_scaler_scale": model["ctx_scaler_scale"],
        "a_scaler_mean": model["a_scaler_mean"],
        "a_scaler_scale": model["a_scaler_scale"],
        "b_scaler_mean": model["b_scaler_mean"],
        "b_scaler_scale": model["b_scaler_scale"],
        "target_means": model["target_means"],
        "target_scales": model["target_scales"],
        "mask_schema": model["mask_schema"],
        "seed": model["seed"],
        "vocabulary_hash": model.get("vocabulary_hash"),
        "train_population_hash": meta.get("train_population_hash"),
        "split_hash": meta.get("split_hash"),
        "target_construction_hash": meta.get("target_construction_hash"),
        "method_version": model.get("method_version"),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save_encoder(root: Path, model: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    out = Path(root) / MODELS_DIR
    out.mkdir(parents=True, exist_ok=True)
    ident = encoder_canonical_identity(model, meta)
    model = {**model, "model_identity_sha256": ident, "freeze_meta": meta}
    (out / "frozen-encoder.json").write_text(
        json.dumps(model, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    (out / "encoder-freeze-meta.json").write_text(
        json.dumps({"identity": ident, **meta}, indent=2) + "\n", encoding="utf-8"
    )
    return {"identity": ident, "path": str(out / "frozen-encoder.json")}
