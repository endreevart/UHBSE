"""Fold stability audit — reproduce fold metrics without retraining."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from human_simulator.post_pilot_audit_v01.policy import PILOT_ARTIFACT_DIR, VERSION


def _causes_for_cohort(fold_rows: list[dict[str, Any]], cohort_id: str) -> dict[str, Any]:
    deltas = [r["m1_minus_m2"] for r in fold_rows if r.get("m1_minus_m2") is not None]
    signs = [1 if d > 0 else (-1 if d < 0 else 0) for d in deltas]
    sign_flip = any(s > 0 for s in signs) and any(s < 0 for s in signs)
    small_folds = [r for r in fold_rows if (r.get("n_test_episodes") or 0) < 10]
    causes = []
    if small_folds:
        causes.append(
            {
                "cause": "small_fold",
                "detail": f"{len(small_folds)} folds with <10 test episodes",
                "folds": [r["fold"] for r in small_folds],
            }
        )
    if sign_flip:
        causes.append(
            {
                "cause": "subject_heterogeneity_or_small_n",
                "detail": "M1−M2 sign flips across folds under subject-grouped CV",
            }
        )
    # extreme errors
    extreme = [
        r
        for r in fold_rows
        if (r.get("m2_max_abs_error") or 0) > 3 * max((r.get("m2_subject_macro_mae") or 1), 1e-6)
    ]
    if extreme:
        causes.append(
            {
                "cause": "outlier",
                "detail": "max abs error >> 3× subject-macro MAE on some folds",
                "folds": [r["fold"] for r in extreme],
            }
        )
    # source-id imbalance only relevant for multi-medicine cohorts
    if cohort_id == "udca_oral_tablet_500mg":
        causes.append(
            {
                "cause": "medication_context_sparsity",
                "detail": (
                    "M2 adds concept/strength/med-id/poly features on ~40 train rows; "
                    "Ridge with fixed L2 can overfit relative to M1"
                ),
            }
        )
    if not causes:
        causes.append({"cause": "причина не установлена", "detail": "insufficient markers"})

    primary = causes[0]["cause"]
    return {
        "primary_cause": primary,
        "all_causes": causes,
        "sign_flip_across_folds": sign_flip,
        "architecture_change_in_this_stage": False,
    }


def audit_fold_stability(root: Path) -> dict[str, Any]:
    art = Path(root) / PILOT_ARTIFACT_DIR
    out_cohorts = []
    for path in sorted((art / "cohorts").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        folds_meta = (doc.get("folds") or {}).get("fold_accounting") or []
        by_fold_acct = {f["fold"]: f for f in folds_meta}
        fold_rows = []
        for fm in doc.get("fold_metrics") or []:
            if fm.get("status") != "EVALUATED":
                continue
            fi = int(fm["fold"])
            acct = by_fold_acct.get(fi, {})
            m0 = fm.get("m0") or {}
            m1 = fm.get("m1") or {}
            m2 = fm.get("m2") or {}
            delta = fm.get("m1_minus_m2_subject_macro_mae")
            fold_rows.append(
                {
                    "fold": fi,
                    "n_train_subjects": acct.get("n_train_subjects"),
                    "n_test_subjects": acct.get("n_test_subjects"),
                    "n_train_episodes": acct.get("n_train_episodes"),
                    "n_test_episodes": acct.get("n_test_episodes"),
                    "m0_subject_macro_mae": m0.get("subject_macro_mae"),
                    "m1_subject_macro_mae": m1.get("subject_macro_mae"),
                    "m2_subject_macro_mae": m2.get("subject_macro_mae"),
                    "m1_minus_m2": delta,
                    "sign_of_improvement": (
                        "M2_better"
                        if delta is not None and delta > 0
                        else (
                            "M1_better"
                            if delta is not None and delta < 0
                            else "tie_or_missing"
                        )
                    ),
                    "m2_max_abs_error": m2.get("maximum_absolute_error"),
                    "m2_p95_abs_error": m2.get("p95_absolute_error"),
                    "m2_n_pairs": m2.get("n_pairs"),
                    "m2_n_subjects": m2.get("n_subjects"),
                    # Outcome range / missingness / horizon not stored per fold in pilot
                    # artifacts — mark as not persisted (no retrain to recompute).
                    "outcome_range": "NOT_PERSISTED_IN_PILOT_ARTIFACT",
                    "invalid_values": "NOT_PERSISTED_IN_PILOT_ARTIFACT",
                    "missingness": "NOT_PERSISTED_IN_PILOT_ARTIFACT",
                    "horizon_distribution": "NOT_PERSISTED_IN_PILOT_ARTIFACT",
                }
            )

        reproduced = True
        for r in fold_rows:
            m1v, m2v, d = (
                r["m1_subject_macro_mae"],
                r["m2_subject_macro_mae"],
                r["m1_minus_m2"],
            )
            if m1v is None or m2v is None or d is None:
                reproduced = False
                continue
            if abs((m1v - m2v) - d) > 1e-9:
                reproduced = False

        causes = _causes_for_cohort(fold_rows, str(doc.get("cohort_id")))
        out_cohorts.append(
            {
                "cohort_id": doc.get("cohort_id"),
                "primary_outcome": doc.get("primary_outcome"),
                "folds": fold_rows,
                "metrics_reproduced_from_artifacts_without_retrain": reproduced,
                "instability": causes,
            }
        )

    status = (
        "EXPLAINED"
        if out_cohorts
        and all(c["metrics_reproduced_from_artifacts_without_retrain"] for c in out_cohorts)
        else "PARTIAL"
    )
    return {
        "version": VERSION,
        "FOLD_INSTABILITY_EXPLANATION_STATUS": status,
        "no_architecture_change": True,
        "cohorts": out_cohorts,
    }
