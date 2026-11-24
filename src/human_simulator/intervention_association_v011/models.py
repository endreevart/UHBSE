"""M0/M1/M2C baselines with corrected non-ordinal medication representation."""

from __future__ import annotations

import hashlib
import math
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from human_simulator.intervention_association_v011.policy import (
    CAUSAL_INTERPRETATION_PROHIBITED,
    CLINICAL_USE_PROHIBITED,
    L2,
    LEGACY_M2_EXTRA,
    M1_FEATURES,
    M2C_EXTRA_FEATURES,
    M2C_HASH_DIM,
    M2C_HASH_SEED,
    SEED,
)


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
        n = len(rows)
        self.means = [0.0] * p
        self.stds = [1.0] * p
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


def _fit_ridge(
    x: list[list[float]], y: list[float], l2: float = L2
) -> tuple[list[float], float, StandardScaler]:
    scaler = StandardScaler()
    scaler.fit(x)
    xs = [scaler.transform(r) for r in x]
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
    preds = [sum(c * v for c, v in zip(coef, [1.0] + r, strict=True)) for r in xs]
    resid = [yi - pi for yi, pi in zip(y, preds, strict=True)]
    rss = sum(r * r for r in resid) / max(len(resid), 1)
    return coef, math.sqrt(rss) if rss > 0 else 1e-6, scaler


def _predict_ridge(coef: list[float], scaler: StandardScaler, row: list[float]) -> float:
    xs = scaler.transform(row)
    return sum(c * v for c, v in zip(coef, [1.0] + xs, strict=True))


def prediction_error_metrics(preds: list[dict[str, Any]]) -> dict[str, Any]:
    if not preds:
        return {"n_pairs": 0, "n_subjects": 0}
    abs_err = [abs(float(p["y_pred"]) - float(p["y_true"])) for p in preds]
    sq = [(float(p["y_pred"]) - float(p["y_true"])) ** 2 for p in preds]
    by: dict[str, list[float]] = defaultdict(list)
    for p, e in zip(preds, abs_err, strict=True):
        by[str(p["opaque_subject_key"])].append(e)
    macro = sum(sum(v) / len(v) for v in by.values()) / len(by)
    srt = sorted(abs_err)
    return {
        "n_pairs": len(preds),
        "n_subjects": len(by),
        "subject_macro_mae": macro,
        "pair_micro_mae": sum(abs_err) / len(abs_err),
        "mae": sum(abs_err) / len(abs_err),
        "rmse": math.sqrt(sum(sq) / len(sq)),
        "median_absolute_error": srt[len(srt) // 2],
        "p90_absolute_error": srt[min(len(srt) - 1, int(math.ceil(0.90 * len(srt)) - 1))],
        "p95_absolute_error": srt[min(len(srt) - 1, int(math.ceil(0.95 * len(srt)) - 1))],
        "p99_absolute_error": srt[min(len(srt) - 1, int(math.ceil(0.99 * len(srt)) - 1))],
        "maximum_absolute_error": srt[-1],
    }


def feat_m1(ep: dict[str, Any]) -> list[float]:
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


def signed_medicine_hash_features(
    medicine_id: str,
    *,
    dim: int = M2C_HASH_DIM,
    seed: int = M2C_HASH_SEED,
) -> list[float]:
    """Deterministic signed feature hashing — non-ordinal categorical encoding."""
    out = [0.0] * dim
    digest = hashlib.sha256(f"{seed}|med|{medicine_id}".encode()).digest()
    # two 32-bit ints from digest → index and sign
    idx = struct.unpack(">I", digest[0:4])[0] % dim
    sign = 1.0 if (struct.unpack(">I", digest[4:8])[0] % 2 == 0) else -1.0
    out[idx] = sign
    return out


def feat_m2c(ep: dict[str, Any]) -> list[float]:
    return (
        feat_m1(ep)
        + signed_medicine_hash_features(str(ep.get("medicine_id") or ""))
        + [
            float(ep.get("polypharmacy_flag") or 0),
            float(ep.get("concurrent_med_count") or 1),
        ]
    )


def build_legacy_ordinal_vocab(train_eps: list[dict[str, Any]]) -> dict[str, int]:
    """LEGACY_ORDINAL_MEDICATION_ENCODING — diagnostic only; not authoritative."""
    counts: dict[str, int] = defaultdict(int)
    for e in train_eps:
        counts[str(e["medicine_id"])] += 1
    ordered = sorted(counts.keys(), key=lambda k: (-counts[k], k))
    return {mid: i + 1 for i, mid in enumerate(ordered)}


def feat_legacy_m2(ep: dict[str, Any], vocab: dict[str, int]) -> list[float]:
    mid = str(ep.get("medicine_id") or "")
    return feat_m1(ep) + [
        float(vocab.get(mid, 0)),
        float(ep.get("polypharmacy_flag") or 0),
        float(ep.get("concurrent_med_count") or 1),
    ]


def hash_collision_report(train_eps: list[dict[str, Any]]) -> dict[str, Any]:
    """Train-only occupancy / collision diagnostics for signed hashing."""
    buckets: dict[int, set[str]] = defaultdict(set)
    for e in train_eps:
        mid = str(e["medicine_id"])
        digest = hashlib.sha256(f"{M2C_HASH_SEED}|med|{mid}".encode()).digest()
        idx = struct.unpack(">I", digest[0:4])[0] % M2C_HASH_DIM
        buckets[idx].add(mid)
    collisions = {str(i): sorted(v) for i, v in buckets.items() if len(v) > 1}
    n_ids = len({str(e["medicine_id"]) for e in train_eps})
    return {
        "hash_dim": M2C_HASH_DIM,
        "hash_seed": M2C_HASH_SEED,
        "n_train_medicine_ids": n_ids,
        "occupied_buckets": len(buckets),
        "n_collision_buckets": len(collisions),
        "collision_bucket_examples": {k: v[:5] for k, v in list(collisions.items())[:10]},
        "representation": "deterministic_signed_feature_hashing",
        "ordinal_encoding_used": False,
    }


def _preds_for(
    eps: list[dict[str, Any]],
    *,
    predict_fn,
) -> list[dict[str, Any]]:
    out = []
    for e in eps:
        out.append(
            {
                "opaque_subject_key": e["opaque_subject_key"],
                "y_true": float(e["post_value"]),
                "y_pred": float(predict_fn(e)),
                "episode_id": e["episode_id"],
            }
        )
    return out


def run_corrected_baselines(
    *,
    cohort: dict[str, Any],
    train: list[dict[str, Any]],
    val: list[dict[str, Any]],
    test: list[dict[str, Any]],
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
            "n_validation": len(va),
            "n_test": len(te),
        }

    y_tr = [float(e["post_value"]) for e in tr]
    legacy_vocab = build_legacy_ordinal_vocab(tr)
    hash_report = hash_collision_report(tr)

    # M0
    m0_te = [
        {
            "opaque_subject_key": e["opaque_subject_key"],
            "y_true": float(e["post_value"]),
            "y_pred": float(e["pre_value"]),
            "episode_id": e["episode_id"],
        }
        for e in te
    ]
    m0_va = [
        {
            "opaque_subject_key": e["opaque_subject_key"],
            "y_true": float(e["post_value"]),
            "y_pred": float(e["pre_value"]),
            "episode_id": e["episode_id"],
        }
        for e in va
    ]

    # M1
    coef1, _, sc1 = _fit_ridge([feat_m1(e) for e in tr], y_tr)
    m1_te = _preds_for(te, predict_fn=lambda e: _predict_ridge(coef1, sc1, feat_m1(e)))
    m1_va = _preds_for(va, predict_fn=lambda e: _predict_ridge(coef1, sc1, feat_m1(e)))

    # M2C corrected
    coef_c, _, sc_c = _fit_ridge([feat_m2c(e) for e in tr], y_tr)
    m2c_te = _preds_for(te, predict_fn=lambda e: _predict_ridge(coef_c, sc_c, feat_m2c(e)))
    m2c_va = _preds_for(va, predict_fn=lambda e: _predict_ridge(coef_c, sc_c, feat_m2c(e)))

    # Legacy ordinal M2 — diagnostic only
    coef_l, _, sc_l = _fit_ridge([feat_legacy_m2(e, legacy_vocab) for e in tr], y_tr)
    m2_legacy_te = _preds_for(
        te, predict_fn=lambda e: _predict_ridge(coef_l, sc_l, feat_legacy_m2(e, legacy_vocab))
    )

    def _imp(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, float]:
        ma = prediction_error_metrics(a)
        mb = prediction_error_metrics(b)
        return {
            "abs_mae_diff_micro": (ma.get("pair_micro_mae") or 0) - (mb.get("pair_micro_mae") or 0),
            "rel_mae_diff_micro": (
                ((ma.get("pair_micro_mae") or 0) - (mb.get("pair_micro_mae") or 0))
                / (ma.get("pair_micro_mae") or 1e-12)
            ),
        }

    assert len(m1_va) == len(va)
    assert len(m2c_va) == len(va)

    return {
        "outcome": outcome,
        "unit": unit,
        "status": "EVALUATED",
        "clinical_use": CLINICAL_USE_PROHIBITED,
        "causal_interpretation": CAUSAL_INTERPRETATION_PROHIBITED,
        "authoritative_comparison": "M1_vs_M2C",
        "legacy_m2_role": "LEGACY_ORDINAL_MEDICATION_ENCODING",
        "legacy_m2_authoritative": False,
        "n_train": len(tr),
        "n_validation": len(va),
        "n_test": len(te),
        "n_validation_predictions_m1": len(m1_va),
        "n_validation_predictions_m2c": len(m2c_va),
        "validation_predictions_match_episodes": len(m1_va) == len(va) and len(m2c_va) == len(va),
        "m1_feature_order": list(M1_FEATURES),
        "m2c_feature_order": list(M1_FEATURES) + list(M2C_EXTRA_FEATURES),
        "legacy_m2_feature_order": list(M1_FEATURES) + list(LEGACY_M2_EXTRA),
        "m2c_hash_report": hash_report,
        "m0": prediction_error_metrics(m0_te),
        "m1": prediction_error_metrics(m1_te),
        "m2c": prediction_error_metrics(m2c_te),
        "m2_legacy_ordinal": prediction_error_metrics(m2_legacy_te),
        "m2c_vs_m1": _imp(m1_te, m2c_te),
        "legacy_m2_vs_m1_diagnostic_only": _imp(m1_te, m2_legacy_te),
        "serialized": {
            "m1": {
                "coef": coef1,
                "scaler": {"means": sc1.means, "stds": sc1.stds, "fit_n_rows": sc1.fit_n_rows},
            },
            "m2c": {
                "coef": coef_c,
                "scaler": {"means": sc_c.means, "stds": sc_c.stds, "fit_n_rows": sc_c.fit_n_rows},
                "hash_dim": M2C_HASH_DIM,
                "hash_seed": M2C_HASH_SEED,
            },
            "m2_legacy_ordinal": {
                "coef": coef_l,
                "scaler": {"means": sc_l.means, "stds": sc_l.stds, "fit_n_rows": sc_l.fit_n_rows},
                "vocab": legacy_vocab,
                "encoding": "LEGACY_ORDINAL_MEDICATION_ENCODING",
            },
        },
        "m0_val_preds": m0_va,
        "m1_val_preds": m1_va,
        "m2c_val_preds": m2c_va,
        "m1_preds": m1_te,
        "m2c_preds": m2c_te,
        "m2_legacy_preds": m2_legacy_te,
    }
