"""Real jointly fitted masked multi-output model (shared encoder + outcome heads)."""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

from human_simulator.unified_individual_state_v0111.policy import (
    M2_EPOCHS,
    M2_L2,
    M2_LR,
    M2_RANK,
    METHOD_VERSION,
    MODELS_DIR,
    SEED,
    VERSION,
)
from human_simulator.unified_individual_state_v0111.ridge import fit_scaler, transform


def _init_matrix(rows: int, cols: int, rng: random.Random, scale: float = 0.01) -> list[list[float]]:
    return [[rng.uniform(-scale, scale) for _ in range(cols)] for _ in range(rows)]


def _matvec(W: list[list[float]], x: list[float]) -> list[float]:
    return [sum(W[i][j] * x[j] for j in range(len(x))) for i in range(len(W))]


def fit_joint_masked_m2(
    *,
    X: list[list[float]],
    Y: list[list[float | None]],
    outcome_keys: list[str],
    source_of_outcome: list[str],
    rank: int = M2_RANK,
    epochs: int = M2_EPOCHS,
    lr: float = M2_LR,
    l2: float = M2_L2,
    seed: int = SEED,
) -> dict[str, Any]:
    """
    Shared encoder h = tanh(X_scaled @ W_enc + b_enc);
    yhat_o = h · w_o + b_o; masked MSE + L2.
    """
    rng = random.Random(seed)
    n = len(X)
    d = len(X[0]) if X else 0
    n_out = len(outcome_keys)
    if n == 0 or d == 0 or n_out == 0:
        raise ValueError("empty M2 design")

    means, scales = fit_scaler(X)
    Xs = transform(X, means, scales)

    # Per-outcome target normalization (train-only callers pass train Y)
    y_means = [0.0] * n_out
    y_scales = [1.0] * n_out
    for o in range(n_out):
        vals = [float(Y[i][o]) for i in range(n) if Y[i][o] is not None]
        if vals:
            mu = sum(vals) / len(vals)
            var = sum((v - mu) ** 2 for v in vals) / len(vals)
            y_means[o] = mu
            y_scales[o] = math.sqrt(var) if var > 1e-12 else 1.0

    W_enc = _init_matrix(rank, d, rng)
    b_enc = [0.0] * rank
    W_out = _init_matrix(n_out, rank, rng)
    b_out = [0.0] * n_out

    def forward(x: list[float]) -> tuple[list[float], list[float]]:
        z = [sum(W_enc[r][j] * x[j] for j in range(d)) + b_enc[r] for r in range(rank)]
        h = [math.tanh(v) for v in z]
        yhat = [
            sum(W_out[o][r] * h[r] for r in range(rank)) + b_out[o] for o in range(n_out)
        ]
        return h, yhat

    history = []
    for ep in range(epochs):
        total = 0.0
        count = 0
        order = list(range(n))
        rng.shuffle(order)
        for i in order:
            x = Xs[i]
            h, yhat = forward(x)
            # grads
            g_h = [0.0] * rank
            for o in range(n_out):
                if Y[i][o] is None:
                    continue
                y_true = (float(Y[i][o]) - y_means[o]) / y_scales[o]
                err = yhat[o] - y_true
                total += err * err
                count += 1
                for r in range(rank):
                    g_h[r] += err * W_out[o][r]
                    W_out[o][r] -= lr * (err * h[r] + l2 * W_out[o][r])
                b_out[o] -= lr * err
            # backprop encoder through tanh
            for r in range(rank):
                z = sum(W_enc[r][j] * x[j] for j in range(d)) + b_enc[r]
                dt = (1.0 - math.tanh(z) ** 2) * g_h[r]
                for j in range(d):
                    W_enc[r][j] -= lr * (dt * x[j] + l2 * W_enc[r][j])
                b_enc[r] -= lr * dt
        loss = total / max(count, 1)
        history.append({"epoch": ep, "masked_mse": loss, "n_obs": count})

    model = {
        "architecture": {
            "type": "shared_tanh_encoder_outcome_heads",
            "rank": rank,
            "epochs": epochs,
            "lr": lr,
            "l2": l2,
            "activation": "tanh",
        },
        "feature_dim": d,
        "n_outcomes": n_out,
        "outcome_keys": list(outcome_keys),
        "source_of_outcome": list(source_of_outcome),
        "feature_scaler_mean": means,
        "feature_scaler_scale": scales,
        "target_means": y_means,
        "target_scales": y_scales,
        "W_enc": W_enc,
        "b_enc": b_enc,
        "W_out": W_out,
        "b_out": b_out,
        "mask_schema": "Y[i][o] is None => unobserved; loss only on observed",
        "seed": seed,
        "method_version": METHOD_VERSION,
        "train_loss_history": history[-5:],
        "final_train_masked_mse": history[-1]["masked_mse"] if history else None,
    }
    return model


def predict_m2(
    model: dict[str, Any],
    x: list[float],
    *,
    mask: list[bool] | None = None,
) -> dict[str, float | None]:
    means = model["feature_scaler_mean"]
    scales = model["feature_scaler_scale"]
    xs = [(v - m) / s for v, m, s in zip(x, means, scales, strict=True)]
    d = len(xs)
    rank = model["architecture"]["rank"]
    W_enc = model["W_enc"]
    b_enc = model["b_enc"]
    W_out = model["W_out"]
    b_out = model["b_out"]
    n_out = model["n_outcomes"]
    z = [sum(W_enc[r][j] * xs[j] for j in range(d)) + b_enc[r] for r in range(rank)]
    h = [math.tanh(v) for v in z]
    out: dict[str, float | None] = {}
    for o, key in enumerate(model["outcome_keys"]):
        if mask is not None and not mask[o]:
            out[key] = None
            continue
        yhat_n = sum(W_out[o][r] * h[r] for r in range(rank)) + b_out[o]
        yhat = yhat_n * model["target_scales"][o] + model["target_means"][o]
        out[key] = float(yhat)
    return out


def m2_canonical_identity(model: dict[str, Any], meta: dict[str, Any]) -> str:
    material = {
        "architecture": model["architecture"],
        "W_enc": model["W_enc"],
        "b_enc": model["b_enc"],
        "W_out": model["W_out"],
        "b_out": model["b_out"],
        "outcome_keys": model["outcome_keys"],
        "source_of_outcome": model["source_of_outcome"],
        "feature_scaler_mean": model["feature_scaler_mean"],
        "feature_scaler_scale": model["feature_scaler_scale"],
        "target_means": model["target_means"],
        "target_scales": model["target_scales"],
        "mask_schema": model["mask_schema"],
        "seed": model["seed"],
        "train_population_hash": meta.get("train_population_hash"),
        "split_hash": meta.get("split_hash"),
        "target_construction_hash": meta.get("target_construction_hash"),
        "method_version": model.get("method_version"),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save_m2(root: Path, model: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    out = Path(root) / MODELS_DIR
    out.mkdir(parents=True, exist_ok=True)
    ident = m2_canonical_identity(model, meta)
    payload = {
        "version": VERSION,
        "model": model,
        "meta": meta,
        "model_identity_sha256": ident,
    }
    path = out / "frozen-m2.json"
    raw = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(raw, encoding="utf-8")
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path),
        "model_file_sha256": file_sha,
        "model_identity_sha256": ident,
    }
