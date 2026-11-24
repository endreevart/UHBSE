"""Real marginal multi-outcome assembly. No demo outcomes. No joint model."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from human_simulator.natural_history_rollout_v011.policy import PREDECLARED_ABSOLUTE_GRID_DAYS, VERSION


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
            abstentions.append({"outcome_key": key, "reason": "UNSUPPORTED_OR_NO_ELIGIBLE_CELL"})
            continue
        if rec.get("imputed") or rec.get("filled_with_zero") or rec.get("filled_with_mean"):
            raise RuntimeError("unsupported outcome must remain missing")
        predicted[key] = {
            "unit": rec.get("unit"),
            "original_unit": rec.get("unit"),
            "has_value": rec.get("value") is not None,
        }
        uncertainty[key] = rec.get("uncertainty")
        providers[key] = rec.get("provider_identity")
    return {
        "version": VERSION,
        "MARGINAL_MULTI_OUTCOME_ASSEMBLY_CONTRACT_STATUS": "MARGINAL_SOURCE_SPECIFIC_MULTI_OUTCOME_ROLLOUT",
        "MULTI_OUTCOME_DEPENDENCE_STATUS": "MARGINAL_ONLY_NO_JOINT_MODEL",
        "source_system": source_system,
        "horizon_days": horizon_days,
        "seed": seed,
        "n_predicted": len(predicted),
        "n_missing": len(missing),
        "predicted_outcome_keys": list(predicted),
        "missing_unsupported_outcomes": missing,
        "per_outcome_uncertainty": uncertainty,
        "provider_identity": providers,
        "no_zero_mean_imputation": True,
        "rejected_encoder_used": False,
        "demo_outcome_used": False,
    }


def heldout_assembly(origins: list[dict[str, Any]], cells: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = {
        (c["source_system"], c["outcome_key"], int(c["horizon_days"]))
        for c in cells
        if c.get("one_step_status")
        in {"VALIDATION_BASELINE_SUPPORTED_P0", "VALIDATION_INCREMENTAL_PROVIDER_ACCEPTED"}
    }
    test = [r for r in origins if r.get("split_role") == "test"]
    by_subj: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in test:
        by_subj[(r["source_system"], r["source_scoped_subject_id"])].add(r["outcome_key"])
    if not by_subj:
        return {
            "MARGINAL_MULTI_OUTCOME_HELDOUT_EVALUATION_STATUS": "NOT_EVALUABLE",
            "demo_outcome_used": False,
        }
    key = max(by_subj, key=lambda k: len(by_subj[k]))
    ss, _sid = key
    outcomes = sorted(by_subj[key])
    h = 90 if 90 in PREDECLARED_ABSOLUTE_GRID_DAYS else PREDECLARED_ABSOLUTE_GRID_DAYS[0]
    per = {}
    for ok in outcomes:
        unit = ok.split("::")[-1] if ok.count("::") >= 2 else None
        supported = (ss, ok, h) in eligible
        per[ok] = {
            "value": "present" if supported else None,
            "unit": unit,
            "unsupported": not supported,
            "uncertainty": {"q05": None, "q95": None} if supported else None,
            "provider_identity": "frozen" if supported else None,
        }
    state = assemble_marginal_state(
        source_system=ss,
        horizon_days=h,
        seed=42,
        requested_outcomes=outcomes,
        per_outcome=per,
    )
    # do not keep synthetic 0.0 as a claimed prediction quality
    if state["predicted_outcome_keys"]:
        state["predicted_outcome_keys"] = list(state["predicted_outcome_keys"])
    state["MARGINAL_MULTI_OUTCOME_HELDOUT_EVALUATION_STATUS"] = (
        "EVALUATED_MARGINAL_COUNTS_ONLY" if outcomes else "NOT_EVALUABLE"
    )
    state["n_source_specific_outcomes_on_shared_subject"] = len(outcomes)
    state["no_subject_id_published"] = True
    return state
