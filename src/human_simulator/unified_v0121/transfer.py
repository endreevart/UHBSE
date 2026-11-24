"""Gated frozen-model transfer to Source B — never tune on B."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from human_simulator.scientific.models import PersistenceBaseline
from human_simulator.unified_v0121.frozen_model_a import load_frozen_model
from human_simulator.unified_v0121.policy import (
    ALLOWED_TRANSFER_RESULT_STATUSES,
    CROSS_SOURCE_TRANSFER_NAME,
    DOMAIN_REVIEW_REQUIRED,
    EXECUTED_EXPLORATORY_TRANSFER,
    INSUFFICIENT_METADATA,
    NOT_RUN_DUE_TO_FAILED_GATE,
    OUTCOME_NOT_COMPARABLE,
    SEED,
    VERSION,
)


def _subject_macro_mae(preds: list[dict[str, Any]]) -> float:
    by: dict[str, list[float]] = defaultdict(list)
    for p in preds:
        by[str(p["opaque_subject_key"])].append(abs(p["y_pred"] - p["y_true"]))
    if not by:
        return float("nan")
    return sum(sum(v) / len(v) for v in by.values()) / len(by)


def _pair_micro_mae(preds: list[dict[str, Any]]) -> float:
    if not preds:
        return float("nan")
    return sum(abs(p["y_pred"] - p["y_true"]) for p in preds) / len(preds)


def _bootstrap_mae_diff(
    ridge: list[dict[str, Any]],
    pers: list[dict[str, Any]],
    *,
    n_iter: int = 200,
    seed: int = SEED,
) -> dict[str, Any]:
    by_r: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_p: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in ridge:
        by_r[str(p["opaque_subject_key"])].append(p)
    for p in pers:
        by_p[str(p["opaque_subject_key"])].append(p)
    subjects = sorted(set(by_r) & set(by_p))
    if len(subjects) < 2:
        return {"status": "INSUFFICIENT", "n_iterations": 0}
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(n_iter):
        sample = [subjects[rng.randrange(len(subjects))] for _ in subjects]
        r_rows = [r for s in sample for r in by_r[s]]
        p_rows = [r for s in sample for r in by_p[s]]
        diffs.append(_subject_macro_mae(r_rows) - _subject_macro_mae(p_rows))
    diffs_sorted = sorted(diffs)
    return {
        "status": "COMPUTED",
        "n_iterations": n_iter,
        "mean_diff_ridge_minus_persistence": sum(diffs) / n_iter,
        "ci_95_lower": diffs_sorted[int(0.025 * n_iter)],
        "ci_95_upper": diffs_sorted[min(n_iter - 1, int(0.975 * n_iter))],
    }


def score_pairs(model: Any, pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in pairs:
        pred = model.predict_pair(p)
        out.append(
            {
                "y_true": pred.y_true,
                "y_pred": pred.y_pred,
                "opaque_subject_key": pred.opaque_subject_key,
                "horizon_days": pred.horizon_days,
            }
        )
    return out


def build_transfer_gate(
    *,
    baseline_ok: bool,
    t3_status: str,
    pairs_status: str,
    pairs_gate_pass: bool,
    frozen_status: str,
    applicability_pass: bool,
    validation_rollback_pass: bool,
    uncertainty_pass: bool,
) -> dict[str, Any]:
    checks = {
        "baseline_verification": baseline_ok,
        "validation_rollback": validation_rollback_pass,
        "uncertainty_recompute": uncertainty_pass,
        "t3_harmonization_allows_transfer": t3_status
        not in (
            DOMAIN_REVIEW_REQUIRED,
            INSUFFICIENT_METADATA,
            OUTCOME_NOT_COMPARABLE,
        ),
        "source_b_pairs_built": pairs_status == "BUILT",
        "source_b_min_sample": pairs_gate_pass,
        "frozen_model_ready": frozen_status == "FROZEN",
        "applicability": applicability_pass,
    }
    failed = [k for k, v in checks.items() if not v]
    all_pass = not failed
    return {
        "version": VERSION,
        "name": CROSS_SOURCE_TRANSFER_NAME,
        "transfer_gate_status": "PASS" if all_pass else "FAIL",
        "all_gates_pass": all_pass,
        "checks": checks,
        "failed_checks": failed,
        "b_cannot_tune_a": True,
        "clinical_validation": "NOT_STARTED",
    }


def run_transfer_or_skip(
    *,
    gate: dict[str, Any],
    frozen_doc: dict[str, Any] | None,
    b_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Real execution only when ALL gates PASS; else NOT_RUN_DUE_TO_FAILED_GATE."""
    base = {
        "version": VERSION,
        "name": CROSS_SOURCE_TRANSFER_NAME,
        "b_cannot_tune_a": True,
        "external_clinical_validation": False,
        "claim": (
            "Exploratory frozen-model external-source transfer only — "
            "not clinical validation."
        ),
        "allowed_result_statuses": list(ALLOWED_TRANSFER_RESULT_STATUSES),
    }
    if not gate.get("all_gates_pass"):
        status = NOT_RUN_DUE_TO_FAILED_GATE
        assert status in ALLOWED_TRANSFER_RESULT_STATUSES
        return {
            **base,
            "executed": False,
            "cross_source_transfer_status": status,
            "failed_checks": gate.get("failed_checks") or [],
        }

    if not frozen_doc or not b_pairs:
        status = "FROZEN_MODEL_UNAVAILABLE" if not frozen_doc else "INSUFFICIENT_SOURCE_B_PAIRS"
        return {
            **base,
            "executed": False,
            "cross_source_transfer_status": status,
        }

    ridge_model = load_frozen_model(frozen_doc)
    pers_model = PersistenceBaseline()
    ridge_preds = score_pairs(ridge_model, b_pairs)
    pers_preds = score_pairs(pers_model, b_pairs)

    # Horizon slices
    buckets = (
        ("lt_1d", 0.0, 1.0),
        ("1_7d", 1.0, 7.0),
        ("7_30d", 7.0, 30.0),
        ("30_90d", 30.0, 90.0),
        ("90_365d", 90.0, 365.0),
        ("gt_365d", 365.0, float("inf")),
    )
    horizon_slices: dict[str, Any] = {}
    for name, lo, hi in buckets:
        rows_r = [p for p in ridge_preds if lo <= float(p["horizon_days"]) < hi]
        rows_p = [p for p in pers_preds if lo <= float(p["horizon_days"]) < hi]
        horizon_slices[name] = {
            "n_pairs": len(rows_r),
            "ridge_pair_micro_mae": _pair_micro_mae(rows_r) if rows_r else None,
            "persistence_pair_micro_mae": _pair_micro_mae(rows_p) if rows_p else None,
        }

    boot = _bootstrap_mae_diff(ridge_preds, pers_preds)
    status = EXECUTED_EXPLORATORY_TRANSFER
    assert status in ALLOWED_TRANSFER_RESULT_STATUSES
    return {
        **base,
        "executed": True,
        "cross_source_transfer_status": status,
        "n_pairs": len(b_pairs),
        "n_subjects": len({p["opaque_subject_key"] for p in b_pairs}),
        "ridge": {
            "subject_macro_mae": _subject_macro_mae(ridge_preds),
            "pair_micro_mae": _pair_micro_mae(ridge_preds),
        },
        "persistence": {
            "subject_macro_mae": _subject_macro_mae(pers_preds),
            "pair_micro_mae": _pair_micro_mae(pers_preds),
        },
        "bootstrap": boot,
        "horizon_slices": horizon_slices,
        "tuned_on_b": False,
        "nan_safe": not any(
            math.isnan(float(x))
            for x in (
                _subject_macro_mae(ridge_preds),
                _pair_micro_mae(ridge_preds),
            )
        ),
        "prediction_vectors_omitted": True,
    }
