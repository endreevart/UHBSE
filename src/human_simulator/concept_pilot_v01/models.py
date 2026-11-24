"""M0 / M1 / M2 Ridge baselines for concept-bounded pilot."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from human_simulator.concept_pilot_v01.policy import L2, SEED, VERSION
from human_simulator.intervention_association_v01.models import (
    StandardScaler,
    _fit_ridge,
    _predict_ridge,
    prediction_error_metrics,
)


def _feat_m1(ep: dict[str, Any]) -> list[float]:
    slope = ep.get("prior_slope")
    days = ep.get("days_since_previous")
    return [
        float(ep["pre_value"]),
        float(ep.get("n_prior_measurements") or 0),
        float(slope) if slope is not None else 0.0,
        float(days) if days is not None else 0.0,
        float(ep.get("horizon_days") or 365),
        1.0 if slope is None else 0.0,
        1.0 if days is None else 0.0,
    ]


def _strength_code(stratum: str) -> float:
    import hashlib

    h = int(hashlib.sha256(stratum.encode()).hexdigest()[:8], 16) % 10_000
    return float(h) / 10_000.0


def _feat_m2(
    ep: dict[str, Any],
    *,
    med_vocab: dict[str, int],
    concept_code: float,
    strength_code: float,
    drop_strength: bool = False,
    drop_poly: bool = False,
) -> list[float]:
    base = _feat_m1(ep)
    mid = str(ep.get("source_medicine_id") or "")
    med_idx = float(med_vocab.get(mid, 0))
    poly = 0.0 if drop_poly else float(ep.get("polypharmacy_flag") or 0)
    conc = 1.0 if drop_poly else float(ep.get("concurrent_med_count") or 1)
    strength = 0.0 if drop_strength else strength_code
    return base + [
        concept_code,
        strength,
        float(ep.get("event_to_outcome_days") or ep.get("horizon_days") or 365),
        conc,
        poly,
        med_idx,
    ]


def build_med_vocab(train: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for e in train:
        counts[str(e["source_medicine_id"])] += 1
    ordered = sorted(counts.keys(), key=lambda k: (-counts[k], k))
    return {mid: i + 1 for i, mid in enumerate(ordered)}


def run_fold_baselines(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    *,
    outcome: str,
    unit: str,
    concept_hash: str,
    strength_stratum: str,
    shuffle_med_context: bool = False,
    shuffle_event_time: bool = False,
    drop_strength: bool = False,
    drop_poly: bool = False,
    rng_seed: int = SEED,
) -> dict[str, Any]:
    import random

    def filt(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [e for e in rows if e["outcome"] == outcome and e["unit"] == unit]

    tr, te = filt(train), filt(test)
    if len(tr) < 8 or len(te) < 3:
        return {
            "status": "INSUFFICIENT_FOLD_DATA",
            "n_train": len(tr),
            "n_test": len(te),
            "outcome": outcome,
            "unit": unit,
        }

    tr_work = [dict(e) for e in tr]
    rng = random.Random(rng_seed)
    if shuffle_med_context:
        polys = [e.get("polypharmacy_flag") for e in tr_work]
        concs = [e.get("concurrent_med_count") for e in tr_work]
        mids = [e.get("source_medicine_id") for e in tr_work]
        rng.shuffle(polys)
        rng.shuffle(concs)
        rng.shuffle(mids)
        for e, p, c, m in zip(tr_work, polys, concs, mids, strict=True):
            e["polypharmacy_flag"] = p
            e["concurrent_med_count"] = c
            e["source_medicine_id"] = m
    if shuffle_event_time:
        times = [e.get("event_to_outcome_days") for e in tr_work]
        rng.shuffle(times)
        for e, t in zip(tr_work, times, strict=True):
            e["event_to_outcome_days"] = t

    vocab = build_med_vocab(tr_work)
    concept_code = _strength_code(concept_hash)
    strength_code = _strength_code(strength_stratum)

    # M0 persistence
    m0_preds = [
        {
            "opaque_subject_key": e["opaque_subject_key"],
            "y_true": float(e["post_value"]),
            "y_pred": float(e["pre_value"]),
            "model": "M0",
        }
        for e in te
    ]

    x1 = [_feat_m1(e) for e in tr_work]
    y = [float(e["post_value"]) for e in tr_work]
    coef1, resid1, sc1 = _fit_ridge(x1, y, L2)
    m1_preds = [
        {
            "opaque_subject_key": e["opaque_subject_key"],
            "y_true": float(e["post_value"]),
            "y_pred": _predict_ridge(coef1, sc1, _feat_m1(e)),
            "model": "M1",
        }
        for e in te
    ]

    x2 = [
        _feat_m2(
            e,
            med_vocab=vocab,
            concept_code=concept_code,
            strength_code=strength_code,
            drop_strength=drop_strength,
            drop_poly=drop_poly,
        )
        for e in tr_work
    ]
    coef2, resid2, sc2 = _fit_ridge(x2, y, L2)
    m2_preds = [
        {
            "opaque_subject_key": e["opaque_subject_key"],
            "y_true": float(e["post_value"]),
            "y_pred": _predict_ridge(
                coef2,
                sc2,
                _feat_m2(
                    e,
                    med_vocab=vocab,
                    concept_code=concept_code,
                    strength_code=strength_code,
                    drop_strength=drop_strength,
                    drop_poly=drop_poly,
                ),
            ),
            "model": "M2",
        }
        for e in te
    ]

    m0m = prediction_error_metrics(m0_preds)
    m1m = prediction_error_metrics(m1_preds)
    m2m = prediction_error_metrics(m2_preds)
    delta = float(m1m["subject_macro_mae"]) - float(m2m["subject_macro_mae"])

    frozen = {
        "version": VERSION,
        "outcome": outcome,
        "unit": unit,
        "l2": L2,
        "seed": SEED,
        "m1": {
            "coef": coef1,
            "scaler": {"means": sc1.means, "stds": sc1.stds},
            "residual_std": resid1,
        },
        "m2": {
            "coef": coef2,
            "scaler": {"means": sc2.means, "stds": sc2.stds},
            "residual_std": resid2,
            "med_vocab": vocab,
            "concept_code": concept_code,
            "strength_code": strength_code,
        },
    }

    return {
        "status": "EVALUATED",
        "outcome": outcome,
        "unit": unit,
        "n_train": len(tr_work),
        "n_test": len(te),
        "m0": m0m,
        "m1": m1m,
        "m2": m2m,
        "m1_minus_m2_subject_macro_mae": delta,
        "frozen": frozen,
        "m1_preds": m1_preds,
        "m2_preds": m2_preds,
        "train_residual_std_m2": resid2,
    }
