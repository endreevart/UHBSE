"""Subject-grouped repeated cross-validation (technical only)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from human_simulator.concept_pilot_v01.policy import N_FOLDS, SEED, VERSION


def _subject_fold(opaque_subject_key: str, *, n_folds: int = N_FOLDS, seed: int = SEED) -> int:
    h = hashlib.sha256(f"{seed}|cvfold|{opaque_subject_key}".encode()).hexdigest()
    return int(h[:12], 16) % n_folds


def make_folds(
    episodes: list[dict[str, Any]],
    *,
    n_folds: int = N_FOLDS,
    seed: int = SEED,
) -> dict[str, Any]:
    subject_fold: dict[str, int] = {}
    folds: list[dict[str, Any]] = []
    for f in range(n_folds):
        folds.append({"fold": f, "train": [], "test": []})

    for e in episodes:
        s = e["opaque_subject_key"]
        if s not in subject_fold:
            subject_fold[s] = _subject_fold(s, n_folds=n_folds, seed=seed)
        fi = subject_fold[s]
        for f in range(n_folds):
            if f == fi:
                folds[f]["test"].append(e)
            else:
                folds[f]["train"].append(e)

    # leakage checks across each fold
    checks = []
    all_ok = True
    for fold in folds:
        tr_s = {e["opaque_subject_key"] for e in fold["train"]}
        te_s = {e["opaque_subject_key"] for e in fold["test"]}
        tr_e = {e["episode_id"] for e in fold["train"]}
        te_e = {e["episode_id"] for e in fold["test"]}
        tr_l = {
            e.get("medication_event_locator_hash")
            for e in fold["train"]
            if e.get("medication_event_locator_hash")
        }
        te_l = {
            e.get("medication_event_locator_hash")
            for e in fold["test"]
            if e.get("medication_event_locator_hash")
        }
        so = tr_s & te_s
        eo = tr_e & te_e
        lo = tr_l & te_l
        ok = not so and not eo and not lo
        all_ok = all_ok and ok
        checks.append(
            {
                "fold": fold["fold"],
                "n_train_subjects": len(tr_s),
                "n_test_subjects": len(te_s),
                "n_train_episodes": len(fold["train"]),
                "n_test_episodes": len(fold["test"]),
                "zero_subject_overlap": len(so) == 0,
                "zero_episode_overlap": len(eo) == 0,
                "zero_locator_overlap": len(lo) == 0,
            }
        )

    return {
        "version": VERSION,
        "scheme": "SUBJECT_GROUPED_REPEATED_CROSS_VALIDATION",
        "TECHNICAL_CV_ONLY_NOT_EXTERNAL_VALIDATION": True,
        "n_folds": n_folds,
        "seed": seed,
        "leakage_ok": all_ok,
        "fold_accounting": checks,
        "folds": folds,
        "n_subjects": len(subject_fold),
    }
