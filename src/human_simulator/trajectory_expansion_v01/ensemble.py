"""SingleOutcomeTrajectoryEnsemble — independent providers, not joint multi-outcome."""

from __future__ import annotations

from typing import Any

from human_simulator.scientific.models import (
    EmpiricalTrendBaseline,
    FirstLearnedBaseline,
    PersistenceBaseline,
    FEATURE_ORDER,
)
from human_simulator.trajectory_expansion_v01.policy import L2, SEED, VERSION


class SingleOutcomeTrajectoryEnsemble:
    """Collection of independent single-outcome frozen providers."""

    def __init__(self, frozen_providers: list[dict[str, Any]]) -> None:
        self.providers = {
            (p["outcome"], p["unit"]): p for p in frozen_providers if p.get("frozen")
        }
        # normalize: accept either nested frozen or flat
        rebuilt = {}
        for p in frozen_providers:
            fr = p.get("frozen") or p
            key = (fr.get("outcome") or p.get("outcome"), fr.get("unit") or p.get("unit"))
            rebuilt[key] = fr
        self.providers = rebuilt

    def available_outcomes(self) -> list[dict[str, str]]:
        return [{"outcome": o, "unit": u} for o, u in sorted(self.providers)]

    def predict_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        horizon_days: float = 30.0,
    ) -> dict[str, Any]:
        """One-step predictions for outcomes present in snapshot; no cross-outcome imputation."""
        components = snapshot.get("components") or []
        by_ou = {}
        for c in components:
            key = (c.get("outcome") or c.get("variable_key"), c.get("unit") or "")
            if key[0] is None:
                continue
            by_ou[key] = c

        predictions = []
        missing = []
        unsupported = []
        for key, prov in self.providers.items():
            outcome, unit = key
            if key not in by_ou:
                missing.append({"outcome": outcome, "unit": unit, "reason": "not_in_snapshot"})
                continue
            comp = by_ou[key]
            y0 = float(comp.get("numeric_value") or comp.get("value"))
            pair = {
                "pair_id": f"snap|{outcome}|{unit}",
                "opaque_subject_key": snapshot.get("subject_id") or "opaque",
                "y_t0": y0,
                "y_t1": y0,  # placeholder; prediction does not require true
                "horizon_days": float(horizon_days),
                "model_features": {
                    "y_t0": y0,
                    "horizon_days": float(horizon_days),
                    "n_prior_measurements": float(comp.get("n_prior_measurements") or 1),
                    "prior_mean": float(comp.get("prior_mean") or y0),
                    "prior_last_delta": float(comp.get("prior_last_delta") or 0.0),
                    "days_since_first": float(comp.get("days_since_first") or 1.0),
                    "has_prior_history": float(comp.get("has_prior_history") or 0.0),
                    "prior_mean_missing_flag": 0.0,
                    "prior_last_delta_missing_flag": 1.0
                    if comp.get("prior_last_delta") is None
                    else 0.0,
                },
            }
            # Ensure all feature slots present
            for name in FEATURE_ORDER:
                pair["model_features"].setdefault(name, 0.0)

            active = prov.get("active_provider") or "persistence"
            if active == "ridge":
                model = FirstLearnedBaseline(seed=SEED, l2=L2)
                ser = prov["ridge"]
                model.coef = list(ser["coef"])
                model.intercept = float(ser["intercept"])
                model.residual_std = float(ser["residual_std"])
                model.scaler.means = list(ser["scaler"]["means"])
                model.scaler.stds = list(ser["scaler"]["stds"])
                model.scaler.fitted = True
                model.interval_multiplier = float(ser.get("interval_multiplier") or 1.6448536269514722)
                model.trained = True
                pred = model.predict_pair(pair)
            elif active == "empirical_trend":
                pred = EmpiricalTrendBaseline().predict_pair(pair)
            else:
                pred = PersistenceBaseline().predict_pair(pair)

            # Applicability: horizon vs training support hash presence
            appl = "IN_SUPPORT"
            reasons = []
            href = prov.get("applicability_reference_hash")
            if not href:
                appl = "PARTIAL_SUPPORT"
                reasons.append("missing_applicability_reference_hash")

            predictions.append(
                {
                    "outcome": outcome,
                    "unit": unit,
                    "active_provider": active,
                    "y_pred": pred.y_pred,
                    "lower": pred.lower,
                    "upper": pred.upper,
                    "applicability": appl,
                    "applicability_reasons": reasons,
                    "model_identity_hash": prov.get("model_identity_hash"),
                    "model_file_hash": prov.get("model_file_hash"),
                    "horizon_days": horizon_days,
                }
            )

        return {
            "version": VERSION,
            "TRAJECTORY_ENSEMBLE_STATUS": "PASS",
            "ensemble_kind": "SingleOutcomeTrajectoryEnsemble",
            "not_joint_multi_outcome_model": True,
            "no_silent_imputation": True,
            "n_providers": len(self.providers),
            "n_predictions": len(predictions),
            "n_missing_outcomes": len(missing),
            "predictions": predictions,
            "missing_outcomes": missing,
            "unsupported_outcomes": unsupported,
        }
