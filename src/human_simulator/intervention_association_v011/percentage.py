"""Percentage-value mathematical bound sensitivity (no canonical mutation)."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_association_v011.models import (
    prediction_error_metrics,
    run_corrected_baselines,
)
from human_simulator.intervention_association_v011.policy import VERSION


def is_percentage_cohort(outcome: str, unit: str) -> bool:
    u = (unit or "").strip().lower()
    if u in ("%", "percent", "pct", "в%"):
        return True
    # Cyrillic percent outcomes commonly use unit '%'
    return False


def audit_percentage_bounds(
    episodes: list[dict[str, Any]], outcome: str, unit: str
) -> dict[str, Any]:
    if not is_percentage_cohort(outcome, unit):
        return {
            "is_percentage_cohort": False,
            "invalid_value_count": 0,
            "status": "NOT_APPLICABLE",
        }
    invalid = []
    for e in episodes:
        if e["outcome"] != outcome or e["unit"] != unit:
            continue
        for field in ("pre_value", "post_value"):
            v = float(e[field])
            if v < 0.0 or v > 100.0:
                invalid.append(
                    {
                        "episode_id": e["episode_id"],
                        "opaque_subject_key": e["opaque_subject_key"],
                        "split": e.get("split"),
                        "field": field,
                        "value": v,
                    }
                )
    subjects = sorted({x["opaque_subject_key"] for x in invalid})
    by_split: dict[str, int] = {}
    for x in invalid:
        sp = str(x.get("split") or "unknown")
        by_split[sp] = by_split.get(sp, 0) + 1
    return {
        "is_percentage_cohort": True,
        "invalid_value_count": len(invalid),
        "affected_subjects": len(subjects),
        "affected_splits": by_split,
        "bound": "[0, 100]",
        "mutation_of_canonical": False,
        "status": "AUDITED",
        # do not publish raw episode ids in aggregate beyond counts
        "example_invalid_magnitudes": sorted(
            {abs(float(x["value"])) for x in invalid}, reverse=True
        )[:5],
    }


def sensitivity_excluding_invalid(
    *,
    cohort: dict[str, Any],
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
    primary_result: dict[str, Any],
) -> dict[str, Any]:
    outcome, unit = cohort["outcome"], cohort["unit"]
    audit = audit_percentage_bounds(train + val + test, outcome, unit)
    if not audit["is_percentage_cohort"] or audit["invalid_value_count"] == 0:
        return {
            "version": VERSION,
            "audit": audit,
            "sensitivity_ran": False,
            "primary_metrics_unchanged": True,
        }

    def _ok(e: dict[str, Any]) -> bool:
        if e["outcome"] != outcome or e["unit"] != unit:
            return True
        return 0.0 <= float(e["pre_value"]) <= 100.0 and 0.0 <= float(e["post_value"]) <= 100.0

    tr = [e for e in train if _ok(e)]
    va = [e for e in val if _ok(e)]
    te = [e for e in test if _ok(e)]
    sens = run_corrected_baselines(cohort=cohort, train=tr, val=va, test=te)
    # strip preds for publication size
    for k in list(sens.keys()):
        if k.endswith("_preds") or k.endswith("_val_preds") or k == "serialized":
            sens.pop(k, None)
    return {
        "version": VERSION,
        "audit": audit,
        "sensitivity_ran": True,
        "primary_m0_mae": (primary_result.get("m0") or {}).get("pair_micro_mae"),
        "primary_m1_mae": (primary_result.get("m1") or {}).get("pair_micro_mae"),
        "primary_m2c_mae": (primary_result.get("m2c") or {}).get("pair_micro_mae"),
        "primary_max_ae_m1": (primary_result.get("m1") or {}).get("maximum_absolute_error"),
        "sensitivity_metrics": {
            "m0": sens.get("m0"),
            "m1": sens.get("m1"),
            "m2c": sens.get("m2c"),
            "n_train": sens.get("n_train"),
            "n_validation": sens.get("n_validation"),
            "n_test": sens.get("n_test"),
            "status": sens.get("status"),
        },
        "note": (
            "Invalid percentage values excluded only in sensitivity rerun; "
            "primary frozen cohort metrics unchanged; no clinical reference ranges applied."
        ),
    }
