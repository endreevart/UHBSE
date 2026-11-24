"""Train-only robust scale per source-specific outcome×unit. Frozen for val/test."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from human_simulator.integrated_research_runtime_v01.hashes import sha_obj
from human_simulator.integrated_research_runtime_v01.policy import VERSION, outcome_unit


def _mad(xs: list[float]) -> float:
    if not xs:
        return 1.0
    ys = sorted(xs)
    med = ys[len(ys) // 2]
    dev = sorted(abs(x - med) for x in ys)
    mad = dev[len(dev) // 2]
    return max(mad * 1.4826, 1e-6)


def fit_train_scales(train_panels: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for p in train_panels:
        for ok, row in p["rows"].items():
            resid = row.get("oof_residual")
            if resid is None or not math.isfinite(float(resid)):
                continue
            unit = outcome_unit(ok)
            by[(p["source_system"], ok, unit)].append(float(resid))
    scales = {}
    for (ss, ok, unit), xs in by.items():
        scales[f"{ss}|{ok}|{unit}"] = {
            "source_system": ss,
            "outcome_key": ok,
            "unit": unit,
            "n": len(xs),
            "median": sorted(xs)[len(xs) // 2],
            "scale": _mad(xs),
        }
    return {
        "version": VERSION,
        "TRAIN_ONLY_JOINT_NORMALIZATION_STATUS": "PASS" if scales else "EMPTY",
        "scales": scales,
        "identity_sha256": sha_obj(scales),
        "ok": bool(scales),
    }


def scale_value(scales: dict[str, Any], source_system: str, outcome_key: str, value: float) -> float:
    unit = outcome_unit(outcome_key)
    table = scales.get("scales") or scales.get("train_scales") or scales
    rec = table.get(f"{source_system}|{outcome_key}|{unit}") if isinstance(table, dict) else None
    if not rec:
        return value
    return (value - float(rec["median"])) / float(rec["scale"])


def transform_vector(
    scales: dict[str, Any],
    source_system: str,
    outcomes: list[str],
    values: list[float],
) -> list[float]:
    return [scale_value(scales, source_system, ok, v) for ok, v in zip(outcomes, values, strict=True)]
