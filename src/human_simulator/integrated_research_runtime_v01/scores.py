"""Normalized Energy/Variogram. Raw pooled mixed-unit scoring is forbidden."""

from __future__ import annotations

import math
from typing import Any


class RawUnitPoolingError(ValueError):
    pass


def _euclid(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def energy_score(paths: list[list[float]], y: list[float], *, normalized: bool) -> float:
    if not normalized:
        raise RawUnitPoolingError("Energy Score requires normalized space")
    if not paths or not y:
        return float("nan")
    n = len(paths)
    term1 = sum(_euclid(p, y) for p in paths) / n
    term2 = 0.0
    cnt = 0
    for i, a in enumerate(paths):
        for b in paths[i + 1 :]:
            term2 += _euclid(a, b)
            cnt += 1
    if cnt:
        term2 = term2 / cnt
    return term1 - 0.5 * term2


def variogram_score(paths: list[list[float]], y: list[float], *, normalized: bool) -> float:
    if not normalized:
        raise RawUnitPoolingError("Variogram Score requires normalized space")
    d = len(y)
    if d < 2 or not paths:
        return float("nan")
    acc = 0.0
    n_pairs = 0
    for i in range(d):
        for j in range(i + 1, d):
            obs = 0.5 * (y[i] - y[j]) ** 2
            pred = sum(0.5 * (p[i] - p[j]) ** 2 for p in paths) / len(paths)
            acc += (obs - pred) ** 2
            n_pairs += 1
    return acc / n_pairs if n_pairs else float("nan")


def pairwise_corr_error(est: list[list[float]], emp: list[list[float]]) -> float:
    n = len(est)
    if n != len(emp) or n == 0:
        return float("nan")
    acc = 0.0
    n_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            acc += abs(est[i][j] - emp[i][j])
            n_pairs += 1
    return acc / n_pairs if n_pairs else float("nan")


def crps_paths(paths: list[float], y: float) -> float:
    if not paths:
        return float("nan")
    n = len(paths)
    term1 = sum(abs(p - y) for p in paths) / n
    term2 = 0.0
    for i, a in enumerate(paths):
        for b in paths[i + 1 :]:
            term2 += abs(a - b)
    term2 = term2 / (n * n)
    return term1 - term2
