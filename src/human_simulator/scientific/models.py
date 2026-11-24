"""Scientific baselines with train-only preprocessing (v0.1.1)."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from human_simulator.core.simulation import PredictedValue, crn_unit_noise
from human_simulator.scientific.policy import (
    FORBIDDEN_MODEL_LABELS,
    NOMINAL_COVERAGE,
    SCIENTIFIC_VERSION,
    SEED,
    gaussian_interval_multiplier,
)

FEATURE_ORDER = (
    "y_t0",
    "horizon_days",
    "n_prior_measurements",
    "prior_mean",
    "prior_last_delta",
    "days_since_first",
    "has_prior_history",
    "prior_mean_missing_flag",
    "prior_last_delta_missing_flag",
)


def feature_schema_hash(feature_order: tuple[str, ...] = FEATURE_ORDER) -> str:
    return hashlib.sha256(json.dumps(list(feature_order), sort_keys=True).encode()).hexdigest()


def training_config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()


def check_scope_honesty(model_name: str, claim_text: str) -> dict[str, Any]:
    blob = f"{model_name} {claim_text}".lower()
    hits = [lab for lab in FORBIDDEN_MODEL_LABELS if lab in blob]
    return {"ok": not hits, "forbidden_hits": hits}


@dataclass
class PairPrediction:
    pair_id: str
    y_true: float
    y_pred: float
    lower: float
    upper: float
    opaque_subject_key: str
    horizon_days: float


@dataclass
class StandardScaler:
    """Train-only mean/std scaler — never fit on validation/test."""

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "fitted": self.fitted,
            "fit_n_rows": self.fit_n_rows,
            "means_hash": hashlib.sha256(json.dumps(self.means).encode()).hexdigest()[:16]
            if self.fitted
            else None,
            "stds_hash": hashlib.sha256(json.dumps(self.stds).encode()).hexdigest()[:16]
            if self.fitted
            else None,
        }


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


class PersistenceBaseline:
    MODEL_ID = "persistence_baseline_scientific"
    MODEL_VERSION = SCIENTIFIC_VERSION
    MODEL_KIND = "BASELINE_CONTROL"
    CLAIM_LEVEL = "BASELINE_CONTROL"
    CLINICAL_VALIDATION = "NOT_CLAIMED"

    def predict_pair(self, pair: dict[str, Any]) -> PairPrediction:
        y0 = float(pair["y_t0"])
        return PairPrediction(
            pair_id=pair["pair_id"],
            y_true=float(pair["y_t1"]),
            y_pred=y0,
            lower=y0,
            upper=y0,
            opaque_subject_key=pair["opaque_subject_key"],
            horizon_days=float(pair["horizon_days"]),
        )

    def step(
        self, *, state: dict[str, float], week: int, dose: float, master_seed: int
    ) -> dict[str, PredictedValue]:
        return {k: PredictedValue(k, v, None, v, v) for k, v in state.items()}


class EmpiricalTrendBaseline:
    MODEL_ID = "empirical_trend_baseline"
    MODEL_VERSION = SCIENTIFIC_VERSION
    MODEL_KIND = "EMPIRICAL_BASELINE"
    CLAIM_LEVEL = "EMPIRICAL_BASELINE"
    CLINICAL_VALIDATION = "NOT_CLAIMED"

    def predict_pair(self, pair: dict[str, Any]) -> PairPrediction:
        feats = pair["model_features"]
        y0 = float(feats["y_t0"])
        if feats.get("has_prior_history", 0) < 0.5:
            pred = y0
        else:
            delta = float(feats["prior_last_delta"])
            n_prior = max(float(feats["n_prior_measurements"]), 1.0)
            days_span = max(float(feats["days_since_first"]), 1.0)
            rate = delta / (days_span / n_prior)
            pred = y0 + rate * float(feats["horizon_days"])
        half = abs(pred) * 0.1 + 1e-6
        return PairPrediction(
            pair_id=pair["pair_id"],
            y_true=float(pair["y_t1"]),
            y_pred=pred,
            lower=pred - half,
            upper=pred + half,
            opaque_subject_key=pair["opaque_subject_key"],
            horizon_days=float(pair["horizon_days"]),
        )

    def step(
        self, *, state: dict[str, float], week: int, dose: float, master_seed: int
    ) -> dict[str, PredictedValue]:
        out: dict[str, PredictedValue] = {}
        for k, v in state.items():
            noise = crn_unit_noise(master_seed, week, f"emp|{k}") * 0.01 * abs(v)
            center = v + noise
            half = abs(v) * 0.05 + 1e-6
            out[k] = PredictedValue(k, center, None, center - half, center + half)
        return out


class FirstLearnedBaseline:
    MODEL_ID = "first_learned_baseline"
    MODEL_VERSION = SCIENTIFIC_VERSION
    MODEL_KIND = "RETROSPECTIVE_BASELINE_ONLY"
    CLAIM_LEVEL = "RETROSPECTIVE_BASELINE_ONLY"
    CLINICAL_VALIDATION = "NOT_CLAIMED"
    MODEL_FAMILY = "ridge_regression_with_train_only_standardization"

    def __init__(
        self,
        *,
        seed: int = SEED,
        l2: float = 1.0,
        interval_multiplier: float | None = None,
        nominal_coverage: float = NOMINAL_COVERAGE,
    ) -> None:
        self.seed = seed
        self.l2 = l2
        self.nominal_coverage = nominal_coverage
        self.interval_multiplier = (
            float(interval_multiplier)
            if interval_multiplier is not None
            else gaussian_interval_multiplier(nominal_coverage)
        )
        self.coef: list[float] | None = None
        self.intercept = 0.0
        self.residual_std = 1.0
        self.scaler = StandardScaler()
        self.feature_schema_hash: str | None = feature_schema_hash()
        self.training_configuration_hash: str | None = None
        self.trained = False
        self.preprocessing_fit_split = "train"

    def _raw_vec(self, feats: dict[str, float]) -> list[float]:
        return [float(feats[name]) for name in FEATURE_ORDER]

    def fit(self, train_pairs: list[dict[str, Any]], *, y_override: list[float] | None = None) -> dict[str, Any]:
        if not train_pairs:
            raise ValueError("empty_train")
        xs_raw = [self._raw_vec(p["model_features"]) for p in train_pairs]
        ys = y_override if y_override is not None else [float(p["y_t1"]) for p in train_pairs]
        if len(ys) != len(xs_raw):
            raise ValueError("y_override_length_mismatch")
        self.scaler.fit(xs_raw)
        xs = [self.scaler.transform(x) for x in xs_raw]
        p = len(FEATURE_ORDER)
        y_mean = sum(ys) / len(ys)
        ys_c = [y - y_mean for y in ys]
        xtx = [[0.0] * p for _ in range(p)]
        xty = [0.0] * p
        for x, y in zip(xs, ys_c, strict=True):
            for i in range(p):
                xty[i] += x[i] * y
                for j in range(p):
                    xtx[i][j] += x[i] * x[j]
        self.coef = _solve_ridge(xtx, xty, self.l2)
        self.intercept = y_mean
        preds = [self._predict_scaled(x) for x in xs]
        resid = [yt - yp for yt, yp in zip(ys, preds, strict=True)]
        self.residual_std = math.sqrt(sum(r * r for r in resid) / max(len(resid), 1)) or 1e-6
        cfg = {
            "model_family": self.MODEL_FAMILY,
            "l2": self.l2,
            "seed": self.seed,
            "n_train_pairs": len(train_pairs),
            "feature_order": list(FEATURE_ORDER),
            "preprocessing": "standardize_fit_train_only",
            "intercept": True,
            "version": self.MODEL_VERSION,
            "scaler": self.scaler.to_dict(),
            "nominal_coverage": self.nominal_coverage,
            "interval_multiplier": self.interval_multiplier,
        }
        self.training_configuration_hash = training_config_hash(cfg)
        self.trained = True
        return {
            "n_train_pairs": len(train_pairs),
            "feature_schema_hash": self.feature_schema_hash,
            "training_configuration_hash": self.training_configuration_hash,
            "residual_std": self.residual_std,
            "preprocessing": cfg["preprocessing"],
            "scaler": self.scaler.to_dict(),
            "claim_level": self.CLAIM_LEVEL,
            "l2": self.l2,
        }

    def _predict_scaled(self, x_scaled: list[float]) -> float:
        assert self.coef is not None
        return self.intercept + sum(c * v for c, v in zip(self.coef, x_scaled, strict=True))

    def predict_pair(self, pair: dict[str, Any]) -> PairPrediction:
        if not self.trained or self.coef is None or not self.feature_schema_hash:
            raise RuntimeError("model_not_trained_or_missing_schema_hash")
        x = self.scaler.transform(self._raw_vec(pair["model_features"]))
        pred = self._predict_scaled(x)
        half = self.interval_multiplier * self.residual_std
        return PairPrediction(
            pair_id=pair["pair_id"],
            y_true=float(pair["y_t1"]),
            y_pred=pred,
            lower=pred - half,
            upper=pred + half,
            opaque_subject_key=pair["opaque_subject_key"],
            horizon_days=float(pair["horizon_days"]),
        )

    def step(
        self, *, state: dict[str, float], week: int, dose: float, master_seed: int
    ) -> dict[str, PredictedValue]:
        out: dict[str, PredictedValue] = {}
        half = self.interval_multiplier * (self.residual_std if self.trained else 1.0)
        for k, v in state.items():
            noise = crn_unit_noise(master_seed, week, f"learned|{k}") * 0.01
            center = v + noise
            out[k] = PredictedValue(k, center, None, center - half, center + half)
        return out

    def model_card(self) -> str:
        return f"""# Model card — FirstLearnedBaseline v{self.MODEL_VERSION}

- Family: {self.MODEL_FAMILY}
- Claim level: {self.CLAIM_LEVEL}
- Clinical validation: {self.CLINICAL_VALIDATION}
- Feature schema hash: `{self.feature_schema_hash}`
- Training configuration hash: `{self.training_configuration_hash}`
- Preprocessing: standardize fit on train only; applied to val/test
- Intercept: yes
- L2: {self.l2}
- Seed: {self.seed}

Not an intervention-response model. DOMAIN_REVIEW_PENDING for measurement semantics.
"""


def is_constant_model(preds: list[PairPrediction]) -> bool:
    if len(preds) < 2:
        return False
    return len({round(p.y_pred, 12) for p in preds}) <= 1


def select_ridge_l2(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    *,
    seed: int,
    candidates: tuple[float, ...] = (0.1, 1.0, 10.0),
) -> tuple[FirstLearnedBaseline, dict[str, Any]]:
    """Choose L2 on validation MAE only — test never seen."""
    results = []
    best: FirstLearnedBaseline | None = None
    best_mae = float("inf")
    for l2 in candidates:
        model = FirstLearnedBaseline(seed=seed, l2=l2)
        model.fit(train)
        if not validation:
            results.append({"l2": l2, "val_mae": None})
            if best is None:
                best = model
            continue
        preds = [model.predict_pair(p) for p in validation]
        mae = sum(abs(p.y_pred - p.y_true) for p in preds) / len(preds)
        results.append({"l2": l2, "val_mae": mae})
        if mae < best_mae:
            best_mae = mae
            best = model
    assert best is not None
    return best, {
        "candidates": list(candidates),
        "results": results,
        "selected_l2": best.l2,
        "selection_split": "validation",
        "test_used_in_tuning": False,
    }
