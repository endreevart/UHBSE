"""Stable Ridge with train-only scaler and intercept (no numpy)."""

from __future__ import annotations

import math
from typing import Any


def fit_scaler(X: list[list[float]]) -> tuple[list[float], list[float]]:
    if not X:
        return [], []
    d = len(X[0])
    n = len(X)
    means = [0.0] * d
    for row in X:
        for j, v in enumerate(row):
            means[j] += v
    means = [m / n for m in means]
    scales = [0.0] * d
    for row in X:
        for j, v in enumerate(row):
            scales[j] += (v - means[j]) ** 2
    scales = [math.sqrt(s / n) if s > 0 else 1.0 for s in scales]
    scales = [s if s > 1e-12 else 1.0 for s in scales]
    return means, scales


def transform(X: list[list[float]], means: list[float], scales: list[float]) -> list[list[float]]:
    return [
        [(v - m) / s for v, m, s in zip(row, means, scales, strict=True)] for row in X
    ]


def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [a[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-14:
            m[col][col] = 1e-14
        else:
            m[col], m[piv] = m[piv], m[col]
        piv_val = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= piv_val
        for r in range(n):
            if r == col:
                continue
            f = m[r][col]
            for j in range(col, n + 1):
                m[r][j] -= f * m[col][j]
    return [m[i][n] for i in range(n)]


def fit_ridge(
    X: list[list[float]],
    y: list[float],
    *,
    l2: float,
) -> dict[str, Any]:
    """Fit Ridge with intercept. Returns weights (incl. intercept at index 0), scaler."""
    means, scales = fit_scaler(X)
    Xs = transform(X, means, scales)
    n = len(Xs)
    d = len(Xs[0]) if Xs else 0
    if n == 0 or d == 0:
        return {
            "intercept": 0.0,
            "coefficients": [],
            "scaler_mean": means,
            "scaler_scale": scales,
            "l2": l2,
            "n_train": n,
            "feature_dim": d,
        }
    # Design matrix with intercept column
    xtx = [[0.0] * (d + 1) for _ in range(d + 1)]
    xty = [0.0] * (d + 1)
    for i in range(n):
        row = [1.0] + Xs[i]
        for a in range(d + 1):
            xty[a] += row[a] * y[i]
            for b in range(d + 1):
                xtx[a][b] += row[a] * row[b]
    for a in range(1, d + 1):  # do not regularize intercept
        xtx[a][a] += l2
    w = _solve_linear(xtx, xty)
    if not all(math.isfinite(v) for v in w):
        raise ValueError("non-finite ridge coefficients")
    if len(w) != d + 1:
        raise ValueError("coefficient dimension mismatch")
    return {
        "intercept": w[0],
        "coefficients": w[1:],
        "scaler_mean": means,
        "scaler_scale": scales,
        "l2": l2,
        "n_train": n,
        "feature_dim": d,
    }


def predict_ridge(model: dict[str, Any], x: list[float]) -> float:
    means = model["scaler_mean"]
    scales = model["scaler_scale"]
    xs = [(v - m) / s for v, m, s in zip(x, means, scales, strict=True)]
    yhat = float(model["intercept"])
    for c, v in zip(model["coefficients"], xs, strict=True):
        yhat += c * v
    return yhat
