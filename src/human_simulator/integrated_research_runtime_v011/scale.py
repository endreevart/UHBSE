"""Train-only scale. Missing scale is hard FAIL."""

from __future__ import annotations

from typing import Any

from human_simulator.integrated_research_runtime_v011.policy import outcome_unit


class ScaleMissingError(ValueError):
    pass


def scale_value(scales: dict[str, Any], source_system: str, outcome_key: str, value: float) -> float:
    unit = outcome_unit(outcome_key)
    table = scales.get("scales") or scales.get("train_scales") or scales
    rec = table.get(f"{source_system}|{outcome_key}|{unit}") if isinstance(table, dict) else None
    if not rec:
        raise ScaleMissingError(f"missing train scale for {source_system}|{outcome_key}|{unit}")
    return (value - float(rec["median"])) / float(rec["scale"])
