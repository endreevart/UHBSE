"""Held-out multi-outcome inventory and natural-history backtest."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from human_simulator.global_state_v01.policy import VERSION
from human_simulator.global_state_v01.state_assembler import (
    assemble_individual_state,
    _parse_ts,
)
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _next_observation(
    series: list[dict[str, Any]], cutoff: datetime
) -> dict[str, Any] | None:
    future = []
    for obs in series:
        ts = _parse_ts(obs.get("clinical_time") or obs.get("ts"))
        if ts is None or ts <= cutoff:
            continue
        future.append((ts, obs))
    if not future:
        return None
    future.sort(key=lambda x: (x[0].isoformat(), str(x[1].get("component_id") or "")))
    return future[0][1]


def choose_cutoffs_for_subject(
    observations_by_ou: dict[tuple[str, str], list[dict[str, Any]]],
    *,
    max_states: int = 3,
) -> list[datetime]:
    """Select cutoffs by coverage only (not by future model error).

    Strategy: timestamps where ≥3 outcomes have ≥2 observations up to that time,
    pick evenly spaced among candidates.
    """
    all_ts: list[datetime] = []
    for series in observations_by_ou.values():
        for obs in series:
            ts = _parse_ts(obs.get("clinical_time") or obs.get("ts"))
            if ts is not None:
                all_ts.append(ts)
    if not all_ts:
        return []
    uniq = sorted(set(all_ts))
    candidates = []
    for ts in uniq:
        n_ready = 0
        for series in observations_by_ou.values():
            n = sum(
                1
                for obs in series
                if (t := _parse_ts(obs.get("clinical_time") or obs.get("ts"))) is not None
                and t <= ts
            )
            if n >= 2:
                n_ready += 1
        if n_ready >= 3:
            candidates.append(ts)
    if not candidates:
        # fallback: mid timestamp
        return [uniq[len(uniq) // 2]]
    if len(candidates) <= max_states:
        return candidates
    step = max(1, len(candidates) // max_states)
    picked = candidates[::step][:max_states]
    return picked


def build_heldout_inventory(
    *,
    test_subjects: list[str],
    subject_observations: dict[str, dict[tuple[str, str], list[dict[str, Any]]]],
    ensemble: SingleOutcomeTrajectoryEnsemble,
    horizon_days: float = 30.0,
    max_subjects: int | None = None,
    max_states_per_subject: int = 2,
) -> dict[str, Any]:
    subjects = list(test_subjects)
    if max_subjects is not None:
        subjects = subjects[: int(max_subjects)]

    n_states = 0
    n_subjects_with_state = 0
    observed_counts: list[int] = []
    pred_counts: list[int] = []
    status_total: dict[str, int] = defaultdict(int)
    targets = 0
    horizons: list[float] = []
    ge = {3: 0, 5: 0, 10: 0, 20: 0}
    private_states: list[dict[str, Any]] = []
    unexplained = 0

    for sid in subjects:
        obs_map = subject_observations.get(sid) or {}
        if not obs_map:
            continue
        cutoffs = choose_cutoffs_for_subject(
            obs_map, max_states=max_states_per_subject
        )
        if not cutoffs:
            continue
        n_subjects_with_state += 1
        for cut in cutoffs:
            state = assemble_individual_state(
                opaque_subject_key=sid,
                cutoff=cut,
                observations_by_ou=obs_map,
                ensemble=ensemble,
                horizon_days=horizon_days,
            )
            n_states += 1
            n_obs = sum(
                1
                for c in state["components"]
                if c["state_status"] in {"OBSERVED", "PREDICTABLE", "STALE", "OUT_OF_SUPPORT"}
                and c.get("numeric_value") is not None
            )
            n_pred = sum(1 for c in state["components"] if c.get("prediction"))
            observed_counts.append(n_obs)
            pred_counts.append(n_pred)
            for k, v in (state.get("status_counts") or {}).items():
                status_total[k] += int(v)
            for thr in ge:
                if n_obs >= thr:
                    ge[thr] += 1

            # Targets for backtest
            state_targets = []
            for c in state["components"]:
                if not c.get("prediction"):
                    continue
                key = (c["outcome"], c["unit"])
                series = obs_map.get(key) or []
                nxt = _next_observation(series, cut)
                if nxt is None:
                    continue
                ts1 = _parse_ts(nxt.get("clinical_time") or nxt.get("ts"))
                if ts1 is None:
                    unexplained += 1
                    continue
                h = (ts1 - cut).total_seconds() / 86400.0
                if h <= 0:
                    unexplained += 1
                    continue
                targets += 1
                horizons.append(h)
                state_targets.append(
                    {
                        "outcome": c["outcome"],
                        "unit": c["unit"],
                        "y_true": float(nxt["value"]),
                        "y_pred": c["prediction"]["y_pred"],
                        "lower": c["prediction"]["lower"],
                        "upper": c["prediction"]["upper"],
                        "horizon_days": h,
                        "opaque_subject_key": sid,
                        "applicability_status": c.get("applicability_status"),
                    }
                )
            private_states.append(
                {
                    "opaque_subject_key": sid,
                    "cutoff": cut.isoformat(),
                    "state_hash": state["state_hash"],
                    "n_observed": n_obs,
                    "n_predictions": n_pred,
                    "targets": state_targets,
                    "status_counts": state["status_counts"],
                }
            )

    def _med(vals: list[float | int]) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        return float(s[len(s) // 2])

    status = (
        "PASS"
        if n_states > 0 and unexplained == 0
        else ("INSUFFICIENT_DATA" if n_states == 0 else "FAIL")
    )
    return {
        "version": VERSION,
        "REAL_HELDOUT_STATE_INVENTORY_STATUS": status,
        "n_test_subjects_considered": len(subjects),
        "n_test_subjects_with_ge1_valid_state": n_subjects_with_state,
        "n_states": n_states,
        "states_with_ge3_observed_provider_outcomes": ge[3],
        "states_with_ge5_observed_provider_outcomes": ge[5],
        "states_with_ge10_observed_provider_outcomes": ge[10],
        "states_with_ge20_observed_provider_outcomes": ge[20],
        "median_observed_outcomes_per_state": _med(observed_counts),
        "median_predictions_per_state": _med(pred_counts),
        "status_distributions": dict(status_total),
        "n_targets_available_for_backtest": targets,
        "horizon_days": {
            "n": len(horizons),
            "median": _med(horizons),
            "min": min(horizons) if horizons else None,
            "max": max(horizons) if horizons else None,
        },
        "unexplained": unexplained,
        "inventory_hash": _hash(
            {
                "n_states": n_states,
                "targets": targets,
                "ge": ge,
                "status_total": dict(status_total),
            }
        ),
        "_private_states": private_states,
    }


def run_multi_outcome_backtest(inventory: dict[str, Any]) -> dict[str, Any]:
    states = inventory.get("_private_states") or []
    by_ou: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for st in states:
        for t in st.get("targets") or []:
            by_ou[(t["outcome"], t["unit"])].append(t)

    per_outcome = []
    covered = 0
    total_pred = 0
    for (outcome, unit), rows in sorted(by_ou.items()):
        # subject-macro MAE
        by_subj: dict[str, list[float]] = defaultdict(list)
        abs_err = []
        inside = 0
        for r in rows:
            err = abs(float(r["y_pred"]) - float(r["y_true"]))
            abs_err.append(err)
            by_subj[r["opaque_subject_key"]].append(err)
            total_pred += 1
            if float(r["lower"]) <= float(r["y_true"]) <= float(r["upper"]):
                inside += 1
                covered += 1
        subj_mae = [sum(v) / len(v) for v in by_subj.values()]
        per_outcome.append(
            {
                "outcome": outcome,
                "unit": unit,
                "n_targets": len(rows),
                "n_subjects": len(by_subj),
                "subject_macro_mae": sum(subj_mae) / len(subj_mae) if subj_mae else None,
                "pair_micro_mae": sum(abs_err) / len(abs_err) if abs_err else None,
                "interval_coverage": inside / len(rows) if rows else None,
            }
        )

    # Unit-safe across-state aggregates only
    n_states = len(states)
    frac_with_pred = (
        sum(1 for s in states if s.get("n_predictions", 0) > 0) / n_states if n_states else 0
    )
    status = (
        "PASS"
        if per_outcome and total_pred > 0
        else ("INSUFFICIENT_DATA" if total_pred == 0 else "FAIL")
    )
    if per_outcome and total_pred < 30:
        status = "PARTIAL"

    return {
        "version": VERSION,
        "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS": status,
        "claim_level": "SECONDARY_EXPLORATORY_RETROSPECTIVE_BACKTEST",
        "n_outcomes_evaluated": len(per_outcome),
        "n_prediction_targets": total_pred,
        "overall_interval_coverage": covered / total_pred if total_pred else None,
        "fraction_states_with_ge1_prediction": frac_with_pred,
        "per_outcome": per_outcome,
        "no_pooled_raw_mae_across_units": True,
        "not_clinical_accuracy": True,
        "not_joint_multi_outcome_learning": True,
        "backtest_hash": _hash(
            {
                "n_ou": len(per_outcome),
                "n_targets": total_pred,
                "coverage": covered / total_pred if total_pred else None,
            }
        ),
    }
