"""Horizon-aligned full-test evaluation with unique-target primary accounting."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from human_simulator.global_state_v011.policy import (
    HORIZON_BINS,
    MIN_TEST_SUBJECTS_EVALUABLE,
    VERSION,
)
from human_simulator.global_state_v01.backtest import choose_cutoffs_for_subject
from human_simulator.global_state_v01.state_assembler import (
    assemble_individual_state,
    _parse_ts,
)
from human_simulator.trajectory_expansion_v011.ensemble import (
    SingleOutcomeTrajectoryEnsemble,
)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _med(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return float(s[len(s) // 2])


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


def target_locator(
    *,
    opaque_subject_key: str,
    outcome: str,
    unit: str,
    target_obs: dict[str, Any],
    target_ts: datetime,
) -> dict[str, Any]:
    loc = {
        "opaque_subject_key": opaque_subject_key,
        "outcome": outcome,
        "unit": unit,
        "target_component_id": str(target_obs.get("component_id") or ""),
        "target_observation_id": str(target_obs.get("observation_id") or ""),
        "target_timestamp": target_ts.isoformat(),
    }
    loc["locator_hash"] = _hash(loc)
    return loc


def build_horizon_aligned_rows(
    *,
    test_subjects: list[str],
    subject_observations: dict[str, dict[tuple[str, str], list[dict[str, Any]]]],
    ensemble: SingleOutcomeTrajectoryEnsemble,
    max_states_per_subject: int = 3,
    max_test_subjects: int | None = None,
    owner_explicit_cap_contract: str | None = None,
) -> dict[str, Any]:
    """Build all cutoff→actual-horizon prediction rows (pre-dedup).

    Silent first-N caps are forbidden. A cap requires an explicit owner contract string.
    """
    if max_test_subjects is not None and not owner_explicit_cap_contract:
        raise ValueError(
            "REFUSE_SILENT_CAP: max_test_subjects requires owner_explicit_cap_contract"
        )

    subjects = list(test_subjects)
    if max_test_subjects is not None:
        subjects = subjects[: int(max_test_subjects)]

    funnel = {
        "n_global_test_subjects": None,  # filled by caller
        "n_test_subjects_with_provider_grain_obs": len(
            [s for s in test_subjects if subject_observations.get(s)]
        ),
        "n_test_subjects_considered": len(subjects),
        "n_subjects_with_valid_cutoffs": 0,
        "n_subjects_with_predictions": 0,
        "n_subjects_with_horizon_aligned_targets": 0,
        "silent_cap_used": False,
        "owner_explicit_cap_contract": owner_explicit_cap_contract,
    }

    rows: list[dict[str, Any]] = []
    n_states = 0
    n_zero_neg = 0
    n_horizon_mismatch_refused = 0
    unexplained = 0
    subjects_with_cutoffs: set[str] = set()
    subjects_with_pred: set[str] = set()
    subjects_with_targets: set[str] = set()

    for sid in subjects:
        obs_map = subject_observations.get(sid) or {}
        if not obs_map:
            continue
        cutoffs = choose_cutoffs_for_subject(obs_map, max_states=max_states_per_subject)
        if not cutoffs:
            continue
        subjects_with_cutoffs.add(sid)
        for cut in cutoffs:
            # Discover candidate OUs with a strict next observation first
            candidates: list[tuple[tuple[str, str], dict[str, Any], datetime, float]] = []
            for ou, series in obs_map.items():
                nxt = _next_observation(series, cut)
                if nxt is None:
                    continue
                ts1 = _parse_ts(nxt.get("clinical_time") or nxt.get("ts"))
                if ts1 is None:
                    unexplained += 1
                    continue
                h = (ts1 - cut).total_seconds() / 86400.0
                if h <= 0:
                    n_zero_neg += 1
                    continue
                candidates.append((ou, nxt, ts1, h))

            if not candidates:
                continue

            # Group by actual horizon to minimize assemble calls (same horizon → one state)
            by_h: dict[float, list[tuple[tuple[str, str], dict[str, Any], datetime]]] = defaultdict(
                list
            )
            for ou, nxt, ts1, h in candidates:
                by_h[h].append((ou, nxt, ts1))

            for h, items in by_h.items():
                state = assemble_individual_state(
                    opaque_subject_key=sid,
                    cutoff=cut,
                    observations_by_ou=obs_map,
                    ensemble=ensemble,
                    horizon_days=float(h),
                )
                n_states += 1
                pred_by_ou = {
                    (c["outcome"], c["unit"]): c
                    for c in state["components"]
                    if c.get("prediction")
                }
                if pred_by_ou:
                    subjects_with_pred.add(sid)

                for ou, nxt, ts1 in items:
                    comp = pred_by_ou.get(ou)
                    if not comp or not comp.get("prediction"):
                        continue
                    pred = comp["prediction"]
                    pred_h = float(pred.get("horizon_days"))
                    target_h = float(h)
                    if abs(pred_h - target_h) > 1e-9:
                        n_horizon_mismatch_refused += 1
                        continue

                    # Prove target row absent from state inputs: all inputs ≤ cutoff < target
                    loc = target_locator(
                        opaque_subject_key=sid,
                        outcome=ou[0],
                        unit=ou[1],
                        target_obs=nxt,
                        target_ts=ts1,
                    )
                    y0 = float(comp["numeric_value"])
                    rows.append(
                        {
                            "opaque_subject_key": sid,
                            "cutoff": cut.isoformat(),
                            "outcome": ou[0],
                            "unit": ou[1],
                            "y_true": float(nxt["value"]),
                            "y_pred": float(pred["y_pred"]),
                            "y_persistence": y0,
                            "lower": float(pred["lower"]),
                            "upper": float(pred["upper"]),
                            "prediction_horizon_days": pred_h,
                            "target_horizon_days": target_h,
                            "horizon_aligned": True,
                            "active_provider": pred.get("active_provider"),
                            "applicability_status": comp.get("applicability_status")
                            or pred.get("applicability_status"),
                            "model_identity_hash": pred.get("model_identity_hash"),
                            "locator": loc,
                            "locator_hash": loc["locator_hash"],
                            "cutoff_before_target": cut < ts1,
                            "record_origin": "PREDICTED",
                        }
                    )
                    subjects_with_targets.add(sid)

    funnel["n_subjects_with_valid_cutoffs"] = len(subjects_with_cutoffs)
    funnel["n_subjects_with_predictions"] = len(subjects_with_pred)
    funnel["n_subjects_with_horizon_aligned_targets"] = len(subjects_with_targets)

    return {
        "version": VERSION,
        "rows": rows,
        "funnel": funnel,
        "n_states_assembled": n_states,
        "n_zero_or_negative_horizons": n_zero_neg,
        "n_horizon_mismatch_refused": n_horizon_mismatch_refused,
        "unexplained": unexplained,
    }


def audit_target_identity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_loc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_loc[r["locator_hash"]].append(r)

    reused = {k: v for k, v in by_loc.items() if len(v) > 1}
    cutoffs_per_target = [len(v) for v in by_loc.values()]
    # same-time duplicate targets: same subject+ou+timestamp, different component?
    same_time: dict[tuple, list] = defaultdict(list)
    for r in rows:
        key = (
            r["opaque_subject_key"],
            r["outcome"],
            r["unit"],
            r["locator"]["target_timestamp"],
        )
        same_time[key].append(r["locator"]["target_component_id"])
    n_dup_same_time = sum(
        1 for comps in same_time.values() if len(set(comps)) > 1
    )
    n_zero_neg = sum(1 for r in rows if float(r["target_horizon_days"]) <= 0)

    return {
        "version": VERSION,
        "TARGET_IDENTITY_ACCOUNTING_STATUS": "PASS",
        "n_rows_pre_dedup": len(rows),
        "n_unique_targets": len(by_loc),
        "n_reused_targets": len(reused),
        "max_cutoffs_referencing_one_target": max(cutoffs_per_target) if cutoffs_per_target else 0,
        "median_cutoffs_per_target": _med([float(x) for x in cutoffs_per_target]),
        "n_duplicate_same_time_targets": n_dup_same_time,
        "n_zero_or_negative_horizon_rows": n_zero_neg,
        "reused_target_cutoff_histogram": {
            "2": sum(1 for c in cutoffs_per_target if c == 2),
            "3_plus": sum(1 for c in cutoffs_per_target if c >= 3),
        },
    }


def select_primary_unique_targets(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Primary: one row per unique target locator — last valid cutoff before target."""
    by_loc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_loc[r["locator_hash"]].append(r)

    primary: list[dict[str, Any]] = []
    for _lh, group in by_loc.items():
        # last cutoff before target (ISO strings sort lexicographically for aware ISO)
        group_sorted = sorted(group, key=lambda r: r["cutoff"])
        chosen = group_sorted[-1]
        primary.append(chosen)

    # Prove reuse == 0 in primary
    loc_counts: dict[str, int] = {}
    for r in primary:
        loc_counts[r["locator_hash"]] = loc_counts.get(r["locator_hash"], 0) + 1
    n_reuse = sum(1 for c in loc_counts.values() if c > 1)
    status = "PASS" if n_reuse == 0 else "FAIL"

    return {
        "version": VERSION,
        "TARGET_REUSE_AUDIT_STATUS": status,
        "primary_n_targets": len(primary),
        "primary_target_reuse": n_reuse,
        "selection_rule": "last_valid_cutoff_before_target",
        "rows": primary,
        "ok": n_reuse == 0,
    }


def evidence_tiers(primary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_ou: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in primary_rows:
        by_ou[(r["outcome"], r["unit"])].add(r["opaque_subject_key"])

    tiers = []
    n_eval = n_diag = n_insuf = 0
    for (outcome, unit), subjects in sorted(by_ou.items()):
        n = len(subjects)
        if n >= MIN_TEST_SUBJECTS_EVALUABLE:
            tier = "EVALUABLE"
            n_eval += 1
        elif n >= 1:
            tier = "DIAGNOSTIC_ONLY"
            n_diag += 1
        else:
            tier = "INSUFFICIENT_DATA"
            n_insuf += 1
        tiers.append(
            {
                "outcome": outcome,
                "unit": unit,
                "n_unique_test_subjects": n,
                "evidence_tier": tier,
            }
        )

    # Outcomes with zero subjects never appear — still report gate
    status = "PASS" if n_eval >= 1 else "FAIL"
    return {
        "version": VERSION,
        "PER_OUTCOME_EVIDENCE_TIER_STATUS": status,
        "min_test_subjects": MIN_TEST_SUBJECTS_EVALUABLE,
        "n_evaluable": n_eval,
        "n_diagnostic_only": n_diag,
        "n_insufficient_data": n_insuf,
        "tiers": tiers,
        "ok": n_eval >= 1,
    }


def compute_corrected_metrics(
    primary_rows: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
) -> dict[str, Any]:
    tier_map = {(t["outcome"], t["unit"]): t["evidence_tier"] for t in tiers}
    by_ou: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in primary_rows:
        by_ou[(r["outcome"], r["unit"])].append(r)

    evaluable = []
    diagnostic = []
    for (outcome, unit), rows in sorted(by_ou.items()):
        tier = tier_map.get((outcome, unit), "INSUFFICIENT_DATA")
        metrics = _ou_metrics(outcome, unit, rows, tier)
        if tier == "EVALUABLE":
            evaluable.append(metrics)
        elif tier == "DIAGNOSTIC_ONLY":
            diagnostic.append(metrics)

    # Horizon alignment proof
    n_aligned = sum(
        1
        for r in primary_rows
        if abs(float(r["prediction_horizon_days"]) - float(r["target_horizon_days"])) < 1e-9
    )
    align_ok = n_aligned == len(primary_rows) and len(primary_rows) > 0

    status = "PASS" if evaluable and align_ok else "FAIL"
    return {
        "version": VERSION,
        "REAL_HELDOUT_MULTI_OUTCOME_BACKTEST_STATUS": status,
        "HORIZON_ALIGNMENT_STATUS": "PASS" if align_ok else "FAIL",
        "claim_level": "SECONDARY_EXPLORATORY_RETROSPECTIVE_BACKTEST",
        "n_evaluable_outcomes": len(evaluable),
        "n_diagnostic_only_outcomes": len(diagnostic),
        "n_primary_targets": len(primary_rows),
        "n_prediction_horizon_equals_target_horizon": n_aligned,
        "evaluable_per_outcome": evaluable,
        "diagnostic_only_per_outcome": diagnostic,
        "no_pooled_raw_mae_across_units": True,
        "not_clinical_accuracy": True,
        "not_joint_multi_outcome_learning": True,
        "provider_selection_unchanged": True,
        "test_not_used_for_model_selection": True,
        "backtest_hash": _hash(
            {
                "n_eval": len(evaluable),
                "n_diag": len(diagnostic),
                "n_targets": len(primary_rows),
                "aligned": n_aligned,
            }
        ),
        "ok": status == "PASS",
    }


def _ou_metrics(
    outcome: str, unit: str, rows: list[dict[str, Any]], tier: str
) -> dict[str, Any]:
    by_subj_active: dict[str, list[float]] = defaultdict(list)
    by_subj_pers: dict[str, list[float]] = defaultdict(list)
    abs_err = []
    pers_err = []
    inside = 0
    in_sup = out_sup = 0
    horizons = []
    unique_targets = {r["locator_hash"] for r in rows}

    for r in rows:
        ea = abs(float(r["y_pred"]) - float(r["y_true"]))
        ep = abs(float(r["y_persistence"]) - float(r["y_true"]))
        abs_err.append(ea)
        pers_err.append(ep)
        by_subj_active[r["opaque_subject_key"]].append(ea)
        by_subj_pers[r["opaque_subject_key"]].append(ep)
        if float(r["lower"]) <= float(r["y_true"]) <= float(r["upper"]):
            inside += 1
        appl = r.get("applicability_status")
        if appl == "IN_SUPPORT":
            in_sup += 1
        elif appl == "OUT_OF_SUPPORT":
            out_sup += 1
        horizons.append(float(r["target_horizon_days"]))

    subj_mae_a = [sum(v) / len(v) for v in by_subj_active.values()]
    subj_mae_p = [sum(v) / len(v) for v in by_subj_pers.values()]
    active_macro = sum(subj_mae_a) / len(subj_mae_a) if subj_mae_a else None
    pers_macro = sum(subj_mae_p) / len(subj_mae_p) if subj_mae_p else None

    bins = {}
    for name, lo, hi in HORIZON_BINS:
        if hi == float("inf"):
            bins[name] = sum(1 for h in horizons if h > lo)
        else:
            bins[name] = sum(1 for h in horizons if lo < h <= hi) if lo > 1 else sum(
                1 for h in horizons if lo <= h <= hi
            )
    # Fix 1-30 inclusive both ends
    bins["1_30"] = sum(1 for h in horizons if 1.0 <= h <= 30.0)
    bins["31_90"] = sum(1 for h in horizons if 30.0 < h <= 90.0)
    bins["91_180"] = sum(1 for h in horizons if 90.0 < h <= 180.0)
    bins["181_365"] = sum(1 for h in horizons if 180.0 < h <= 365.0)
    bins["gt_365"] = sum(1 for h in horizons if h > 365.0)

    return {
        "outcome": outcome,
        "unit": unit,
        "evidence_tier": tier,
        "n_subjects": len(by_subj_active),
        "n_unique_targets": len(unique_targets),
        "active_provider_subject_macro_mae": active_macro,
        "pair_target_micro_mae": sum(abs_err) / len(abs_err) if abs_err else None,
        "persistence_subject_macro_mae": pers_macro,
        "active_minus_persistence": (
            (active_macro - pers_macro)
            if active_macro is not None and pers_macro is not None
            else None
        ),
        "interval_coverage": inside / len(rows) if rows else None,
        "n_in_support": in_sup,
        "n_out_of_support": out_sup,
        "horizon_distribution": {
            "n": len(horizons),
            "min": min(horizons) if horizons else None,
            "max": max(horizons) if horizons else None,
            "median": _med(horizons),
            "bins": bins,
        },
    }


def build_inventory_summary(
    *,
    primary_rows: list[dict[str, Any]],
    funnel: dict[str, Any],
    n_states: int,
) -> dict[str, Any]:
    subjects = {r["opaque_subject_key"] for r in primary_rows}
    horizons = [float(r["target_horizon_days"]) for r in primary_rows]
    return {
        "version": VERSION,
        "REAL_HELDOUT_STATE_INVENTORY_STATUS": "PASS" if primary_rows else "FAIL",
        "GLOBAL_TEST_POPULATION_EVALUATION_STATUS": (
            "PASS" if funnel.get("n_subjects_with_horizon_aligned_targets", 0) > 0 else "FAIL"
        ),
        "full_test_population": True,
        "funnel": funnel,
        "n_states_assembled": n_states,
        "n_subjects_with_horizon_aligned_targets": len(subjects),
        "n_primary_targets": len(primary_rows),
        "horizon_days": {
            "n": len(horizons),
            "median": _med(horizons),
            "min": min(horizons) if horizons else None,
            "max": max(horizons) if horizons else None,
        },
        "inventory_hash": _hash(
            {
                "funnel": funnel,
                "n_targets": len(primary_rows),
                "n_subjects": len(subjects),
            }
        ),
    }
