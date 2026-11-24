"""Freeze selected outcome registry from conservative profile (pre-training)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from human_simulator.trajectory_expansion_v011.policy import (
    EXPECTED_REGISTRY_COUNT_V01,
    INVENTORY_PATH,
    PRIMARY_THRESHOLD_PROFILE,
    VERSION,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def build_selected_registry(root: Path, criteria: dict[str, Any]) -> dict[str, Any]:
    inv = json.loads((Path(root) / INVENTORY_PATH).read_text(encoding="utf-8"))
    grains = inv.get("grains") or []
    selected = []
    for g in grains:
        ok = (
            int(g.get("n_subjects_with_ge2") or 0) >= int(criteria["min_subjects_with_ge2"])
            and int(g.get("n_strict_consecutive_pairs") or 0)
            >= int(criteria["min_strict_consecutive_pairs"])
        )
        if not ok:
            continue
        selected.append(
            {
                "grain_id": _hash(
                    {"outcome": g["outcome"], "unit": g["unit"], "profile": PRIMARY_THRESHOLD_PROFILE}
                )[:24],
                "source_code": g["outcome"],
                "normalized_label": g["outcome"],
                "unit": g["unit"],
                "n_subjects": g.get("n_subjects"),
                "n_subjects_with_repeats": g.get("n_subjects_with_ge2"),
                "n_observations": g.get("n_numeric_observations"),
                "n_strict_consecutive_pairs": g.get("n_strict_consecutive_pairs"),
                "temporal_coverage": g.get("temporal_coverage"),
                "unit_dominance": g.get("unit_dominance_approx"),
                "numeric_validity": {
                    "n_numeric": g.get("n_numeric_observations"),
                    "n_non_numeric": g.get("n_non_numeric"),
                    "n_missing_timestamps": g.get("n_missing_timestamps"),
                },
                "provenance_coverage": g.get("provenance"),
                "record_origin": g.get("record_origin"),
                "profile_criteria": dict(criteria),
                "threshold_checks": {
                    "subjects_ge2_ok": True,
                    "pairs_ok": True,
                },
                "selected": True,
                "selection_reason": (
                    f"Passed {PRIMARY_THRESHOLD_PROFILE} profile "
                    f"(subjects_ge2>={criteria['min_subjects_with_ge2']}, "
                    f"pairs>={criteria['min_strict_consecutive_pairs']}); "
                    "not selected by model performance."
                ),
            }
        )
    # Stable order by pairs desc then label
    selected.sort(
        key=lambda r: (
            -int(r["n_strict_consecutive_pairs"] or 0),
            str(r["normalized_label"]),
            str(r["unit"]),
        )
    )
    registry_hash = _hash(
        [{"outcome": r["normalized_label"], "unit": r["unit"]} for r in selected]
    )
    status = (
        "PASS"
        if len(selected) == EXPECTED_REGISTRY_COUNT_V01
        else "FAIL_COUNT_MISMATCH"
    )
    return {
        "version": VERSION,
        "SELECTED_OUTCOME_REGISTRY_STATUS": status,
        "profile": PRIMARY_THRESHOLD_PROFILE,
        "n_selected": len(selected),
        "expected": EXPECTED_REGISTRY_COUNT_V01,
        "registry_hash": registry_hash,
        "selection_basis": "conservative_profile_only",
        "model_performance_used": False,
        "grains": selected,
    }
