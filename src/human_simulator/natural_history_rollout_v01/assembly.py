"""Marginal multi-outcome assembly. No joint dependence claim. No fill of missing."""

from __future__ import annotations

from typing import Any

from human_simulator.natural_history_rollout_v01.policy import VERSION


def assemble_marginal_state(
    *,
    source_system: str,
    horizon_days: int,
    seed: int,
    requested_outcomes: list[str],
    per_outcome: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    predicted: dict[str, Any] = {}
    missing: list[str] = []
    uncertainty: dict[str, Any] = {}
    providers: dict[str, Any] = {}
    abstentions: list[dict[str, str]] = []
    for key in requested_outcomes:
        rec = per_outcome.get(key)
        if rec is None or rec.get("unsupported"):
            missing.append(key)
            abstentions.append({"outcome_key": key, "reason": "UNSUPPORTED_OR_NO_ACCEPTED_CELL"})
            continue
        if rec.get("imputed") or rec.get("filled_with_zero") or rec.get("filled_with_mean"):
            raise RuntimeError("unsupported outcome must remain missing")
        predicted[key] = {
            "value": rec.get("value"),
            "unit": rec.get("unit"),
            "original_unit": rec.get("unit"),
        }
        uncertainty[key] = rec.get("uncertainty")
        providers[key] = rec.get("provider_identity")
    return {
        "version": VERSION,
        "MULTI_OUTCOME_ROLLOUT_ASSEMBLY_STATUS": "MARGINAL_SOURCE_SPECIFIC_MULTI_OUTCOME_ROLLOUT",
        "MULTI_OUTCOME_DEPENDENCE_STATUS": "MARGINAL_ONLY_NO_JOINT_MODEL",
        "source_system": source_system,
        "horizon_days": horizon_days,
        "seed": seed,
        "predicted_outcomes": predicted,
        "missing_unsupported_outcomes": missing,
        "per_outcome_uncertainty": uncertainty,
        "provider_identity": providers,
        "applicability": "NATURAL_HISTORY_ONLY",
        "abstention_reasons": abstentions,
        "no_zero_mean_imputation": True,
        "rejected_encoder_used": False,
    }
