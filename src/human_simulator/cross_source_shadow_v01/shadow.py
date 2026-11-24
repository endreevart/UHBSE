"""Technical shadow scoring A→B (not scientific cross-source transfer)."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from human_simulator.scientific.models import FirstLearnedBaseline, PersistenceBaseline
from human_simulator.scientific_v02.policy import (
    DOMAIN_REVIEW_REQUIRED,
    INDEPENDENCE_NOT_ESTABLISHED,
    SCIENTIFIC_CROSS_SOURCE_TRANSFER_NOT_RUN,
    TECHNICAL_SHADOW_TRANSFER_EXECUTED,
    TECHNICAL_SHADOW_TRANSFER_EXECUTED_OUTSIDE_APPLICABILITY,
    TECHNICAL_SHADOW_TRANSFER_FAILED,
    TECHNICAL_SHADOW_TRANSFER_NOT_RUN,
    VERSION,
)


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = min(len(sorted_vals) - 1, max(0, int(math.ceil(p * len(sorted_vals)) - 1)))
    return sorted_vals[idx]


def _metrics(
    preds: list[dict[str, Any]],
    *,
    large_err_thresholds: tuple[float, ...] = (1.0, 2.0, 5.0),
) -> dict[str, Any]:
    if not preds:
        return {"n_pairs": 0, "n_subjects": 0}
    abs_err = [abs(p["y_pred"] - p["y_true"]) for p in preds]
    sq = [(p["y_pred"] - p["y_true"]) ** 2 for p in preds]
    bias = [p["y_pred"] - p["y_true"] for p in preds]
    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[str(p["opaque_subject_key"])].append(abs(p["y_pred"] - p["y_true"]))
    macro = sum(sum(v) / len(v) for v in by.values()) / len(by)
    subject_means = {s: sum(v) / len(v) for s, v in by.items()}
    worst_sid = max(subject_means, key=subject_means.get)
    srt = sorted(abs_err)
    covered = sum(1 for p in preds if p["lower"] <= p["y_true"] <= p["upper"])
    widths = [p["upper"] - p["lower"] for p in preds]
    large_rates = {
        f"large_error_rate_abs_gt_{t}": sum(1 for e in abs_err if e > t) / len(abs_err)
        for t in large_err_thresholds
    }
    return {
        "n_pairs": len(preds),
        "n_subjects": len(by),
        "subject_macro_mae": macro,
        "pair_micro_mae": sum(abs_err) / len(abs_err),
        "mae": sum(abs_err) / len(abs_err),
        "rmse": math.sqrt(sum(sq) / len(sq)),
        "median_absolute_error": srt[len(srt) // 2],
        "p90_absolute_error": _percentile(srt, 0.90),
        "p95_absolute_error": _percentile(srt, 0.95),
        "p99_absolute_error": _percentile(srt, 0.99),
        "maximum_absolute_error": srt[-1],
        "mean_bias": sum(bias) / len(bias),
        "bias": sum(bias) / len(bias),
        "worst_subject_mean_absolute_error": subject_means[worst_sid],
        "uncertainty_coverage": covered / len(preds),
        "mean_interval_width": sum(widths) / len(widths),
        **large_rates,
        "large_error_thresholds_prospective": list(large_err_thresholds),
    }


def _score(model: Any, pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in pairs:
        pred = model.predict_pair(p)
        out.append(
            {
                "y_true": pred.y_true,
                "y_pred": pred.y_pred,
                "lower": pred.lower,
                "upper": pred.upper,
                "opaque_subject_key": pred.opaque_subject_key,
                "horizon_days": pred.horizon_days,
            }
        )
    return out


def _compare(ridge: list[dict[str, Any]], pers: list[dict[str, Any]]) -> dict[str, Any]:
    rm = _metrics(ridge)
    pm = _metrics(pers)
    by_r: dict[str, list[float]] = defaultdict(list)
    by_p: dict[str, list[float]] = defaultdict(list)
    for p in ridge:
        by_r[str(p["opaque_subject_key"])].append(abs(p["y_pred"] - p["y_true"]))
    for p in pers:
        by_p[str(p["opaque_subject_key"])].append(abs(p["y_pred"] - p["y_true"]))
    common = sorted(set(by_r) & set(by_p))
    better = 0
    for s in common:
        if sum(by_r[s]) / len(by_r[s]) < sum(by_p[s]) / len(by_p[s]):
            better += 1
    delta = None
    rel = None
    if rm.get("subject_macro_mae") is not None and pm.get("subject_macro_mae") is not None:
        delta = rm["subject_macro_mae"] - pm["subject_macro_mae"]
        if pm["subject_macro_mae"]:
            rel = delta / pm["subject_macro_mae"]
    return {
        "ridge": rm,
        "persistence": pm,
        "ridge_minus_persistence_macro_mae": delta,
        "relative_delta": rel,
        "fraction_subjects_ridge_better": (better / len(common)) if common else None,
    }


def engineering_shadow_gate(
    *,
    baseline_ok: bool,
    training_ok: bool,
    eval_ok: bool,
    frozen_ok: bool,
    b_dataset_ok: bool,
    feature_contract_ok: bool,
) -> dict[str, Any]:
    checks = {
        "baseline_verified": baseline_ok,
        "source_a_v02_training_pass": training_ok,
        "source_a_held_out_evaluation_completed": eval_ok,
        "frozen_model_verified": frozen_ok,
        "source_b_pair_dataset_built": b_dataset_ok,
        "feature_contract_complete": feature_contract_ok,
        "no_source_b_tuning": True,
        "no_raw_identifiers_in_output": True,
    }
    # T3 domain review intentionally NOT in engineering gate
    failed = [k for k, v in checks.items() if not v]
    return {
        "version": VERSION,
        "engineering_shadow_gate_status": "PASS" if not failed else "FAIL",
        "all_pass": not failed,
        "checks": checks,
        "failed_checks": failed,
        "t3_domain_review_does_not_block_engineering_shadow": True,
    }


def scientific_cross_source_gate(*, t3_status: str, applicability_pass: bool) -> dict[str, Any]:
    checks = {
        "t3_analyte_equivalence_confirmed": False,
        "specimen_material_confirmed": False,
        "assay_method_policy_accepted": False,
        "unit_semantics_accepted": False,
        "applicability_pass": applicability_pass,
        "cross_source_independence_policy_accepted": False,
        "no_source_b_tuning": True,
    }
    if t3_status == DOMAIN_REVIEW_REQUIRED:
        checks["t3_analyte_equivalence_confirmed"] = False
    failed = [k for k, v in checks.items() if not v]
    return {
        "version": VERSION,
        "scientific_cross_source_gate_status": "FAIL",
        "t3_domain_review_status": t3_status,
        "scientific_cross_source_transfer_status": SCIENTIFIC_CROSS_SOURCE_TRANSFER_NOT_RUN,
        "failed_checks": failed,
        "checks": checks,
        "domain_review_not_closed_programmatically": True,
    }


def run_technical_shadow(
    *,
    model: FirstLearnedBaseline,
    b_pairs: list[dict[str, Any]],
    in_support: list[dict[str, Any]],
    out_support: list[dict[str, Any]],
    eng_gate: dict[str, Any],
    applicability_pass: bool,
    applicability_status: str,
) -> dict[str, Any]:
    if not eng_gate.get("all_pass"):
        return {
            "version": VERSION,
            "executed": False,
            "technical_shadow_transfer_status": TECHNICAL_SHADOW_TRANSFER_NOT_RUN,
            "failed_checks": eng_gate.get("failed_checks"),
            "source_b_tuned": False,
        }
    if not b_pairs:
        return {
            "version": VERSION,
            "executed": False,
            "technical_shadow_transfer_status": TECHNICAL_SHADOW_TRANSFER_FAILED,
            "reason": "no_b_pairs",
            "source_b_tuned": False,
        }

    pers = PersistenceBaseline()
    all_r = _score(model, b_pairs)
    all_p = _score(pers, b_pairs)
    in_r = _score(model, in_support) if in_support else []
    in_p = _score(pers, in_support) if in_support else []
    out_r = _score(model, out_support) if out_support else []
    out_p = _score(pers, out_support) if out_support else []

    status = (
        TECHNICAL_SHADOW_TRANSFER_EXECUTED
        if applicability_pass
        else TECHNICAL_SHADOW_TRANSFER_EXECUTED_OUTSIDE_APPLICABILITY
    )
    all_cmp = _compare(all_r, all_p)
    in_cmp = _compare(in_r, in_p) if in_support else {"n_pairs": 0}
    out_cmp = _compare(out_r, out_p) if out_support else {"n_pairs": 0}

    # Tail-risk assessment is separate from applicability (fraction outside support).
    # Thresholds are prospective; do not retro-tune from Source B results.
    out_rmse = (out_cmp.get("ridge") or {}).get("rmse")
    all_mae = (all_cmp.get("ridge") or {}).get("mae")
    out_mae = (out_cmp.get("ridge") or {}).get("mae")
    mae_improved = (
        all_mae is not None
        and (all_cmp.get("persistence") or {}).get("mae") is not None
        and all_mae < (all_cmp["persistence"]["mae"])
    )
    ood_rmse_worsened = False
    if out_rmse is not None and (in_cmp.get("ridge") or {}).get("rmse") is not None:
        ood_rmse_worsened = out_rmse > float(in_cmp["ridge"]["rmse"]) * 1.25

    if not applicability_pass:
        tail_status = "FAIL_APPLICABILITY"
    elif ood_rmse_worsened and mae_improved:
        tail_status = "PARTIAL_MEAN_IMPROVED_OOD_RMSE_WORSENED"
    elif ood_rmse_worsened:
        tail_status = "PARTIAL_OOD_TAIL_ELEVATED"
    else:
        tail_status = "PASS_PROSPECTIVE_THRESHOLDS"

    return {
        "version": VERSION,
        "executed": True,
        "technical_shadow_execution_status": status,
        "technical_shadow_transfer_status": status,
        "technical_applicability_status": applicability_status,
        "scientific_interpretability_status": "NOT_ESTABLISHED",
        "scientific_cross_source_transfer_status": "NOT_RUN_DOMAIN_REVIEW_REQUIRED",
        "scientifically_interpretable": False,
        "interpretation_label": "NOT_SCIENTIFICALLY_INTERPRETABLE",
        "tail_risk_status": tail_status,
        "tail_risk_evidence": {
            "mean_mae_may_improve_while_ood_rmse_worsens": True,
            "mae_improved_vs_persistence_all_pairs": mae_improved,
            "out_of_support_rmse_materially_worse_than_in_support": ood_rmse_worsened,
            "thresholds_prospective": True,
            "note": (
                "Applicability PASS must not be based only on fraction outside support; "
                "tail_risk_status is reported separately."
            ),
        },
        "source_b_tuned": False,
        "refit_on_b": False,
        "applicability_status": applicability_status,
        "all_pairs": all_cmp,
        "in_support_pairs": in_cmp,
        "out_of_support_pairs": out_cmp,
        "horizon_strata": horizon_sensitivity_shadow(all_r, all_p),
        "ood_feature_strata": {
            "in_support": in_cmp.get("ridge"),
            "out_of_support": out_cmp.get("ridge"),
        },
        "individual_predictions_omitted": True,
        "subject_ids_omitted": True,
        "pair_ids_omitted": True,
        "raw_values_omitted": True,
        "claim": (
            "Technical shadow scoring of frozen Source A Ridge v0.2 on provisional "
            "Source B T3 stratum — not scientific cross-source transfer, not clinical validation."
        ),
        "cross_source_independence_status": INDEPENDENCE_NOT_ESTABLISHED,
    }


def horizon_sensitivity_shadow(
    ridge: list[dict[str, Any]], pers: list[dict[str, Any]]
) -> dict[str, Any]:
    buckets = (
        ("lt_1d", 0.0, 1.0),
        ("1_7d", 1.0, 7.0),
        ("7_30d", 7.0, 30.0),
        ("30_90d", 30.0, 90.0),
        ("90_365d", 90.0, 365.0),
        ("gt_365d", 365.0, float("inf")),
    )
    out: dict[str, Any] = {}
    for name, lo, hi in buckets:
        r = [p for p in ridge if lo <= float(p["horizon_days"]) < hi]
        p = [x for x in pers if lo <= float(x["horizon_days"]) < hi]
        out[name] = {
            "n_pairs": len(r),
            "ridge": _metrics(r),
            "persistence": _metrics(p),
        }
    return out
