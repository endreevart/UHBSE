"""Deterministic subject-disjoint split and M0/M1/M2 Ridge baselines."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from human_simulator.intervention_association_v01.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    L2,
    M1_FEATURES,
    M2_EXTRA_FEATURES,
    MIN_TEST_EPISODES,
    MIN_TEST_SUBJECTS,
    SEED,
    SPLIT_FRACTIONS,
    VERSION,
)


def prediction_error_metrics(
    preds: list[dict[str, Any]],
    *,
    thresholds: tuple[float, ...] = (1.0, 2.0, 5.0),
) -> dict[str, Any]:
    if not preds:
        return {"n_pairs": 0, "n_subjects": 0}
    abs_err = [abs(float(p["y_pred"]) - float(p["y_true"])) for p in preds]
    sq = [(float(p["y_pred"]) - float(p["y_true"])) ** 2 for p in preds]
    by: dict[str, list[float]] = defaultdict(list)
    for p, e in zip(preds, abs_err, strict=True):
        by[str(p["opaque_subject_key"])].append(e)
    macro = sum(sum(v) / len(v) for v in by.values()) / len(by)
    srt = sorted(abs_err)
    out: dict[str, Any] = {
        "n_pairs": len(preds),
        "n_subjects": len(by),
        "subject_macro_mae": macro,
        "pair_micro_mae": sum(abs_err) / len(abs_err),
        "mae": sum(abs_err) / len(abs_err),
        "rmse": math.sqrt(sum(sq) / len(sq)),
        "median_absolute_error": srt[len(srt) // 2],
        "p90_absolute_error": srt[min(len(srt) - 1, max(0, int(math.ceil(0.90 * len(srt)) - 1)))],
        "p95_absolute_error": srt[min(len(srt) - 1, max(0, int(math.ceil(0.95 * len(srt)) - 1)))],
        "p99_absolute_error": srt[min(len(srt) - 1, max(0, int(math.ceil(0.99 * len(srt)) - 1)))],
        "maximum_absolute_error": srt[-1],
    }
    for t in thresholds:
        out[f"large_error_rate_abs_gt_{t}"] = sum(1 for e in abs_err if e > t) / len(abs_err)
    return out


@dataclass
class StandardScaler:
    means: list[float] = field(default_factory=list)
    stds: list[float] = field(default_factory=list)
    fitted: bool = False
    fit_n_rows: int = 0

    def fit(self, rows: list[list[float]]) -> None:
        if not rows:
            raise ValueError("empty_scaler_fit")
        p = len(rows[0])
        self.means = [0.0] * p
        self.stds = [1.0] * p
        n = len(rows)
        for j in range(p):
            col = [r[j] for r in rows]
            mu = sum(col) / n
            var = sum((x - mu) ** 2 for x in col) / max(n, 1)
            self.means[j] = mu
            self.stds[j] = math.sqrt(var) if var > 1e-12 else 1.0
        self.fitted = True
        self.fit_n_rows = n

    def transform(self, row: list[float]) -> list[float]:
        if not self.fitted:
            raise RuntimeError("scaler_not_fitted")
        return [(x - m) / s for x, m, s in zip(row, self.means, self.stds, strict=True)]


def _solve_ridge(xtx: list[list[float]], xty: list[float], l2: float) -> list[float]:
    n = len(xty)
    a = [row[:] for row in xtx]
    b = xty[:]
    for i in range(n):
        a[i][i] += l2
    for i in range(n):
        pivot = a[i][i] if abs(a[i][i]) > 1e-12 else 1e-12
        a[i][i] = pivot
        for j in range(i + 1, n):
            f = a[j][i] / pivot
            for k in range(i, n):
                a[j][k] -= f * a[i][k]
            b[j] -= f * b[i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = b[i] - sum(a[i][k] * x[k] for k in range(i + 1, n))
        x[i] = s / a[i][i]
    return x


def _bucket(opaque_subject_key: str, seed: int = SEED) -> float:
    h = hashlib.sha256(f"{seed}|{opaque_subject_key}".encode()).hexdigest()
    return int(h[:12], 16) / float(16**12)


def assign_split(opaque_subject_key: str, seed: int = SEED) -> str:
    u = _bucket(opaque_subject_key, seed)
    t, v, _ = SPLIT_FRACTIONS
    if u < t:
        return "train"
    if u < t + v:
        return "validation"
    return "test"


def load_episodes(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def split_episodes(episodes: list[dict[str, Any]], seed: int = SEED) -> dict[str, Any]:
    by_split: dict[str, list[dict[str, Any]]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    subject_split: dict[str, str] = {}
    for ep in episodes:
        okey = ep["opaque_subject_key"]
        if okey not in subject_split:
            subject_split[okey] = assign_split(okey, seed)
        sp = subject_split[okey]
        ep = {**ep, "split": sp}
        by_split[sp].append(ep)

    # Overlap checks
    sets = {k: {e["opaque_subject_key"] for e in v} for k, v in by_split.items()}
    eid_sets = {k: {e["episode_id"] for e in v} for k, v in by_split.items()}
    loc_sets = {
        k: {
            e.get("medication_event_locator_hash")
            for e in v
            if e.get("medication_event_locator_hash")
        }
        for k, v in by_split.items()
    }
    subject_overlap = (
        sets["train"] & sets["validation"]
        | sets["train"] & sets["test"]
        | sets["validation"] & sets["test"]
    )
    episode_overlap = (
        eid_sets["train"] & eid_sets["validation"]
        | eid_sets["train"] & eid_sets["test"]
        | eid_sets["validation"] & eid_sets["test"]
    )
    locator_overlap = (
        loc_sets["train"] & loc_sets["validation"]
        | loc_sets["train"] & loc_sets["test"]
        | loc_sets["validation"] & loc_sets["test"]
    )

    def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
        meds = {e["medicine_id"] for e in rows}
        ous = {(e["outcome"], e["unit"]) for e in rows}
        return {
            "n_episodes": len(rows),
            "n_subjects": len({e["opaque_subject_key"] for e in rows}),
            "n_medicine_ids": len(meds),
            "n_outcome_units": len(ous),
        }

    test_ok = (
        _counts(by_split["test"])["n_subjects"] >= MIN_TEST_SUBJECTS
        and _counts(by_split["test"])["n_episodes"] >= MIN_TEST_EPISODES
    )
    return {
        "version": VERSION,
        "seed": seed,
        "fractions": list(SPLIT_FRACTIONS),
        "splits": {k: _counts(v) for k, v in by_split.items()},
        "subject_overlap_count": len(subject_overlap),
        "episode_overlap_count": len(episode_overlap),
        "locator_overlap_count": len(locator_overlap),
        "zero_subject_overlap": len(subject_overlap) == 0,
        "zero_episode_overlap": len(episode_overlap) == 0,
        "zero_locator_overlap": len(locator_overlap) == 0,
        "test_size_gate_passed": test_ok,
        "episodes_by_split": by_split,
    }


def train_outcome_unit_cohorts(
    train_eps: list[dict[str, Any]],
    *,
    min_episodes: int,
    min_subjects: int,
) -> list[dict[str, Any]]:
    """Select cohorts using train only."""
    by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in train_eps:
        by[(e["outcome"], e["unit"])].append(e)
    out = []
    for (outcome, unit), rows in sorted(by.items(), key=lambda x: -len(x[1])):
        n_subj = len({r["opaque_subject_key"] for r in rows})
        if len(rows) >= min_episodes and n_subj >= min_subjects:
            out.append(
                {
                    "outcome": outcome,
                    "unit": unit,
                    "n_train_episodes": len(rows),
                    "n_train_subjects": n_subj,
                }
            )
    return out


# --- M0 / M1 / M2 Ridge-style baselines ---


def _feat_m1(ep: dict[str, Any]) -> list[float]:
    slope = ep.get("prior_slope")
    days = ep.get("days_since_previous")
    return [
        float(ep["pre_value"]),
        float(ep.get("n_prior_measurements") or 0),
        float(slope) if slope is not None else 0.0,
        float(days) if days is not None else 0.0,
        float(ep["horizon_days"]),
        1.0 if slope is None else 0.0,
        1.0 if days is None else 0.0,
    ]


def _feat_m2(ep: dict[str, Any], med_vocab: dict[str, int]) -> list[float]:
    base = _feat_m1(ep)
    mid = str(ep.get("medicine_id") or "")
    # train-only vocab index; OOV → 0
    med_idx = float(med_vocab.get(mid, 0))
    return base + [
        med_idx,
        float(ep.get("polypharmacy_flag") or 0),
        float(ep.get("concurrent_med_count") or 1),
    ]


def _fit_ridge(x: list[list[float]], y: list[float], l2: float = L2) -> tuple[list[float], float, StandardScaler]:
    scaler = StandardScaler()
    scaler.fit(x)
    xs = [scaler.transform(r) for r in x]
    # design matrix with intercept
    p = len(xs[0]) + 1
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for row, yi in zip(xs, y, strict=True):
        xr = [1.0] + row
        for i in range(p):
            xty[i] += xr[i] * yi
            for j in range(p):
                xtx[i][j] += xr[i] * xr[j]
    coef = _solve_ridge(xtx, xty, l2)
    # residual std on train
    preds = []
    for row in xs:
        xr = [1.0] + row
        preds.append(sum(c * v for c, v in zip(coef, xr, strict=True)))
    resid = [yi - pi for yi, pi in zip(y, preds, strict=True)]
    rss = sum(r * r for r in resid) / max(len(resid), 1)
    return coef, math.sqrt(rss) if rss > 0 else 1e-6, scaler


def _predict_ridge(coef: list[float], scaler: StandardScaler, row: list[float]) -> float:
    xs = scaler.transform(row)
    xr = [1.0] + xs
    return sum(c * v for c, v in zip(coef, xr, strict=True))


def build_med_vocab(train_eps: list[dict[str, Any]]) -> dict[str, int]:
    """Train-only medicine_id vocabulary (1-indexed; 0 = OOV)."""
    counts: dict[str, int] = defaultdict(int)
    for e in train_eps:
        counts[str(e["medicine_id"])] += 1
    # stable order by count desc then id
    ordered = sorted(counts.keys(), key=lambda k: (-counts[k], k))
    return {mid: i + 1 for i, mid in enumerate(ordered)}


def run_baselines_for_cohort(
    *,
    cohort: dict[str, Any],
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
    shuffle_medication: bool = False,
) -> dict[str, Any]:
    outcome, unit = cohort["outcome"], cohort["unit"]

    def _filt(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [e for e in rows if e["outcome"] == outcome and e["unit"] == unit]

    tr, va, te = _filt(train), _filt(val), _filt(test)
    if len(tr) < 10 or len(te) < 5:
        return {
            "outcome": outcome,
            "unit": unit,
            "status": "INSUFFICIENT_DATA",
            "n_train": len(tr),
            "n_test": len(te),
        }

    med_vocab = build_med_vocab(tr)
    tr_use = tr
    if shuffle_medication:
        rng = random.Random(SEED)
        ids = [e["medicine_id"] for e in tr]
        rng.shuffle(ids)
        tr_use = [{**e, "medicine_id": mid} for e, mid in zip(tr, ids, strict=True)]

    # M0 persistence
    m0_preds = [
        {
            "opaque_subject_key": e["opaque_subject_key"],
            "y_true": float(e["post_value"]),
            "y_pred": float(e["pre_value"]),
            "episode_id": e["episode_id"],
        }
        for e in te
    ]

    # M1
    x1 = [_feat_m1(e) for e in tr]
    y = [float(e["post_value"]) for e in tr]
    coef1, resid1, sc1 = _fit_ridge(x1, y)
    m1_preds = []
    for e in te:
        pred = _predict_ridge(coef1, sc1, _feat_m1(e))
        m1_preds.append(
            {
                "opaque_subject_key": e["opaque_subject_key"],
                "y_true": float(e["post_value"]),
                "y_pred": pred,
                "episode_id": e["episode_id"],
            }
        )

    # M2
    x2 = [_feat_m2(e, med_vocab) for e in tr_use]
    coef2, resid2, sc2 = _fit_ridge(x2, y)
    m2_preds = []
    for e in te:
        pred = _predict_ridge(coef2, sc2, _feat_m2(e, med_vocab))
        m2_preds.append(
            {
                "opaque_subject_key": e["opaque_subject_key"],
                "y_true": float(e["post_value"]),
                "y_pred": pred,
                "episode_id": e["episode_id"],
            }
        )

    m0_m = prediction_error_metrics(m0_preds)
    m1_m = prediction_error_metrics(m1_preds)
    m2_m = prediction_error_metrics(m2_preds)

    # subject-level improvement M2 vs M1
    by_subj: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for a, b in zip(m1_preds, m2_preds, strict=True):
        err1 = abs(a["y_pred"] - a["y_true"])
        err2 = abs(b["y_pred"] - b["y_true"])
        by_subj[a["opaque_subject_key"]].append((err1, err2))
    improvements = []
    for errs in by_subj.values():
        m1e = sum(e[0] for e in errs) / len(errs)
        m2e = sum(e[1] for e in errs) / len(errs)
        improvements.append(m1e - m2e)
    frac_improved = (
        sum(1 for d in improvements if d > 0) / len(improvements) if improvements else 0.0
    )
    median_imp = sorted(improvements)[len(improvements) // 2] if improvements else 0.0

    return {
        "outcome": outcome,
        "unit": unit,
        "status": "EVALUATED",
        "clinical_use": CLINICAL_USE_PROHIBITED,
        "causal_interpretation": CAUSAL_INTERPRETATION_PROHIBITED,
        "not_treatment_response": True,
        "n_train": len(tr),
        "n_validation": len(va),
        "n_test": len(te),
        "n_medicine_ids_train": len(med_vocab),
        "m1_feature_order": list(M1_FEATURES),
        "m2_feature_order": list(M1_FEATURES) + list(M2_EXTRA_FEATURES),
        "m0": m0_m,
        "m1": m1_m,
        "m2": m2_m,
        "m2_vs_m1": {
            "abs_mae_diff_micro": (m1_m.get("pair_micro_mae") or 0) - (m2_m.get("pair_micro_mae") or 0),
            "rel_mae_diff_micro": (
                ((m1_m.get("pair_micro_mae") or 0) - (m2_m.get("pair_micro_mae") or 0))
                / (m1_m.get("pair_micro_mae") or 1e-12)
            ),
            "median_subject_improvement": median_imp,
            "fraction_subjects_improved": frac_improved,
        },
        "serialized": {
            "m1": {
                "coef": coef1,
                "residual_std": resid1,
                "scaler": {"means": sc1.means, "stds": sc1.stds, "fit_n_rows": sc1.fit_n_rows},
            },
            "m2": {
                "coef": coef2,
                "residual_std": resid2,
                "scaler": {"means": sc2.means, "stds": sc2.stds, "fit_n_rows": sc2.fit_n_rows},
                "med_vocab": med_vocab,
            },
        },
        "shuffle_medication": shuffle_medication,
        "m1_preds": m1_preds,
        "m2_preds": m2_preds,
    }
