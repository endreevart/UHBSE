"""Recompute Source A uncertainty with exclusive quantiles on real test preds."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_v011.robustness_a import run_robustness, sanitize_robustness_for_artifact
from human_simulator.unified_v011.uncertainty_a import evaluate_uncertainty
from human_simulator.unified_v012.quantile_fix import (
    detect_q4_bug_from_counts,
    quantile_assignment_report,
)
from human_simulator.unified_v0121.policy import VERSION


def _starting_values(
    test_preds_ridge: list[dict[str, Any]],
    test_preds_persistence: list[dict[str, Any]] | None,
) -> list[float]:
    """Prefer persistence y_pred (== y_t0); else ridge y_pred as proxy."""
    if test_preds_persistence and len(test_preds_persistence) == len(test_preds_ridge):
        return [float(p["y_pred"]) for p in test_preds_persistence]
    return [float(p["y_pred"]) for p in test_preds_ridge]


def exclusive_quantile_coverage(
    *,
    test_preds_ridge: list[dict[str, Any]],
    starting_values: list[float],
) -> dict[str, Any]:
    covered = [
        bool(p["lower"] <= p["y_true"] <= p["upper"]) for p in test_preds_ridge
    ]
    widths = [float(p["upper"]) - float(p["lower"]) for p in test_preds_ridge]
    report = quantile_assignment_report(starting_values, covered=covered)
    # Enrich with mean width per exclusive bucket
    bins = {}
    from human_simulator.unified_v012.quantile_fix import assign_exclusive_quantiles

    exclusive = assign_exclusive_quantiles(starting_values)
    for q, idxs in exclusive.items():
        if not idxs:
            bins[q] = {"n_pairs": 0, "coverage": None, "mean_width": None}
            continue
        cov = sum(1 for i in idxs if covered[i]) / len(idxs)
        mean_w = sum(widths[i] for i in idxs) / len(idxs)
        bins[q] = {
            "n_pairs": len(idxs),
            "coverage": cov,
            "mean_width": mean_w,
        }
    sum_n = sum(int(v["n_pairs"]) for v in bins.values())
    n = len(test_preds_ridge)
    buggy_counts = report.get("buggy_v011_style_counts") or {}
    bug = detect_q4_bug_from_counts(
        {k: int(v) for k, v in buggy_counts.items()}, n=n
    )
    return {
        "n": n,
        "exclusive_bins": bins,
        "exclusive_sum": sum_n,
        "exclusive_sum_equals_n": sum_n == n,
        "old_q4_all_rejected": bool(bug.get("regression_rejected")),
        "quantile_assignment_report": {
            "exclusive_counts": report["exclusive_counts"],
            "exclusive_sum_equals_n": report["exclusive_sum_equals_n"],
            "pairwise_intersection_empty": report["pairwise_intersection_empty"],
            "union_equals_full": report["union_equals_full"],
            "q4_bug_detected_in_legacy_method": report["q4_bug_detected_in_legacy_method"],
        },
    }


def sanitize_uncertainty_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    """Aggregates only — never write prediction vectors or subject keys."""
    out = dict(doc)
    out.pop("test_preds_ridge", None)
    out.pop("test_preds_persistence", None)
    out.pop("_learned_model", None)
    out.pop("val_preds_ridge", None)
    unc = dict(out.get("uncertainty") or {})
    # Mark nested legacy quantile slice as non-authoritative (v0.1.1 q4 bug still in helper)
    if "coverage_by_starting_value_quantile" in unc:
        unc["coverage_by_starting_value_quantile_LEGACY_BUGGY"] = unc.pop(
            "coverage_by_starting_value_quantile"
        )
        unc["legacy_quantile_note"] = (
            "Nested coverage_by_starting_value_quantile from evaluate_uncertainty "
            "uses overlapping bins (q4 may equal n). Authoritative exclusive bins are "
            "in exclusive_quantile_coverage.exclusive_bins."
        )
    out["uncertainty"] = unc
    eq = out.get("exclusive_quantile_coverage") or {}
    out["authoritative_exclusive_quantile_ok"] = bool(eq.get("exclusive_sum_equals_n"))
    return out


def recompute_uncertainty(conn: Any, *, seed: int = 42) -> dict[str, Any]:
    """Call run_robustness → evaluate_uncertainty + exclusive quantiles."""
    rob = run_robustness(conn, seed=seed)
    if rob.get("status") == "INSUFFICIENT_DATA":
        return {
            "version": VERSION,
            "status": "INSUFFICIENT_DATA",
            "source_a_uncertainty_recomputation_status": "INSUFFICIENT_DATA",
            "robustness_sanitized": sanitize_robustness_for_artifact(rob),
        }

    ridge = list(rob.get("test_preds_ridge") or [])
    pers = list(rob.get("test_preds_persistence") or [])
    meta = rob.get("learned_for_uncertainty") or {}
    unc = evaluate_uncertainty(
        test_preds_ridge=ridge,
        test_preds_persistence=pers,
        val_n=int(meta.get("val_n") or 0),
        interval_construction_ok=int(meta.get("val_n") or 0)
        >= int(meta.get("min_val_for_construction") or 1),
    )
    starts = _starting_values(ridge, pers)
    exclusive = exclusive_quantile_coverage(
        test_preds_ridge=ridge, starting_values=starts
    )
    status = (
        "PASS"
        if exclusive["exclusive_sum_equals_n"] and exclusive["old_q4_all_rejected"]
        else "FAIL"
    )
    doc = {
        "version": VERSION,
        "status": status,
        "source_a_uncertainty_recomputation_status": status,
        "uncertainty": unc,
        "exclusive_quantile_coverage": exclusive,
        "n_test_pairs": len(ridge),
        "prediction_vectors_omitted": True,
        "subject_keys_omitted": True,
        "robustness_sanitized": sanitize_robustness_for_artifact(rob),
        "_runtime": {
            "test_preds_ridge": ridge,
            "test_preds_persistence": pers,
            "_learned_model": rob.get("_learned_model"),
        },
    }
    return doc
