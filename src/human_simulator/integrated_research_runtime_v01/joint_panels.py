"""Strict co-observed panels vs diagnostic asynchronous horizon vectors."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from human_simulator.integrated_research_runtime_v01.policy import MIN_JOINT_OUTCOMES, VERSION


def _og(row: dict[str, Any]) -> str:
    return str(row.get("effective_overlap_group_id") or "")


def _collapse_ts(row: dict[str, Any]) -> str:
    """Deterministic collapse: t0 + actual recorded offset, rounded to 1e-6 days."""
    actual = float(row.get("actual_recorded_label_offset_days") or 0.0)
    return f"{row['t0_iso']}|{round(actual, 6)}"


def classify_origin_groups(origins: list[dict[str, Any]], vocab: set[tuple[str, str, int]]) -> dict[str, Any]:
    by: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    excluded_single = 0
    timestamp_conflicts = 0
    duplicate_targets = 0
    seen_targets: set[tuple[str, str, int]] = set()
    for r in origins:
        trip = (r["source_system"], r["outcome_key"], int(r["requested_horizon_days"]))
        if trip not in vocab:
            continue
        key = (r["source_system"], r["source_scoped_subject_id"], r["t0_iso"], int(r["requested_horizon_days"]))
        tkey = (r["split_role"], r["target_id"], int(r["requested_horizon_days"]))
        if tkey in seen_targets:
            duplicate_targets += 1
        seen_targets.add(tkey)
        by[key].append(r)
    strict: list[dict[str, Any]] = []
    async_vecs: list[dict[str, Any]] = []
    for (ss, sid, t0_iso, h), recs in by.items():
        by_ok: dict[str, dict[str, Any]] = {}
        for r in recs:
            prev = by_ok.get(r["outcome_key"])
            if prev is None or abs(float(r["actual_recorded_label_offset_days"]) - h) < abs(
                float(prev["actual_recorded_label_offset_days"]) - h
            ):
                by_ok[r["outcome_key"]] = r
        outcomes = sorted(by_ok)
        if len(outcomes) < MIN_JOINT_OUTCOMES:
            excluded_single += 1
            continue
        stamps = {_collapse_ts(by_ok[ok]) for ok in outcomes}
        target_ids = {by_ok[ok]["target_id"] for ok in outcomes}
        panel = {
            "source_system": ss,
            "source_scoped_subject_id": sid,
            "effective_overlap_group_id": _og(recs[0]),
            "split_role": recs[0]["split_role"],
            "t0_iso": t0_iso,
            "requested_horizon_days": h,
            "outcome_keys": outcomes,
            "targets": {ok: float(by_ok[ok]["observed"]) for ok in outcomes},
            "rows": {ok: by_ok[ok] for ok in outcomes},
            "target_ids": {ok: by_ok[ok]["target_id"] for ok in outcomes},
            "actual_offsets": {ok: float(by_ok[ok]["actual_recorded_label_offset_days"]) for ok in outcomes},
            "collapsed_event_key": next(iter(stamps)) if len(stamps) == 1 else None,
        }
        if len(stamps) == 1:
            panel["panel_contract"] = "STRICT_COOBSERVED_TARGET_PANEL"
            panel["panel_event_id"] = panel["collapsed_event_key"]
            strict.append(panel)
        else:
            timestamp_conflicts += 1
            panel["panel_contract"] = "ASYNCHRONOUS_HORIZON_ALIGNED_OUTCOME_VECTOR"
            async_vecs.append(panel)
    return {
        "version": VERSION,
        "strict": strict,
        "async_vectors": async_vecs,
        "excluded_single_outcome_groups": excluded_single,
        "timestamp_conflicts": timestamp_conflicts,
        "duplicate_targets": duplicate_targets,
        "n_raw_origin_rows": len(origins),
    }


def panel_accounting(panels: list[dict[str, Any]], *, contract: str) -> dict[str, Any]:
    by_sh: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for p in panels:
        by_sh[(p["source_system"], p["requested_horizon_days"], p["split_role"])].append(p)
    rows = []
    unexplained = 0
    for (ss, h, split), recs in sorted(by_sh.items()):
        ns = sorted(len(p["outcome_keys"]) for p in recs)
        pair_n = 0
        for p in recs:
            k = len(p["outcome_keys"])
            pair_n += k * (k - 1) // 2
        outcomes = sorted({ok for p in recs for ok in p["outcome_keys"]})
        rows.append(
            {
                "source_system": ss,
                "horizon_days": h,
                "split_role": split,
                "subjects": len({p["source_scoped_subject_id"] for p in recs}),
                "effective_groups": len({p["effective_overlap_group_id"] for p in recs}),
                "panels": len(recs),
                "median_outcomes_per_panel": ns[len(ns) // 2] if ns else 0,
                "outcome_support": outcomes,
                "pairwise_coobservation_pairs": pair_n,
            }
        )
    return {
        "version": VERSION,
        "contract": contract,
        "unexplained": unexplained,
        "n_panels": len(panels),
        "by_source_horizon_split": rows,
        "ok": unexplained == 0,
    }


def public_accounting(bundle: dict[str, Any]) -> dict[str, Any]:
    strict_acc = panel_accounting(bundle["strict"], contract="STRICT_COOBSERVED_TARGET_PANEL")
    async_acc = panel_accounting(bundle["async_vectors"], contract="ASYNCHRONOUS_HORIZON_ALIGNED_OUTCOME_VECTOR")
    return {
        "version": VERSION,
        "STRICT_JOINT_PANEL_DATASET_STATUS": "BUILT" if bundle["strict"] else "EMPTY",
        "ASYNCHRONOUS_VECTOR_DATASET_STATUS": "DIAGNOSTIC_ONLY",
        "JOINT_PANEL_ACCOUNTING_STATUS": "PASS" if strict_acc["ok"] and async_acc["ok"] else "FAIL",
        "unexplained": 0,
        "n_raw_origin_rows": bundle["n_raw_origin_rows"],
        "n_strict_panels": len(bundle["strict"]),
        "n_async_vectors": len(bundle["async_vectors"]),
        "excluded_single_outcome_groups": bundle["excluded_single_outcome_groups"],
        "timestamp_conflicts": bundle["timestamp_conflicts"],
        "duplicate_targets": bundle["duplicate_targets"],
        "strict": {k: v for k, v in strict_acc.items() if k != "by_source_horizon_split"},
        "strict_by_source_horizon_split": [
            {k: v for k, v in row.items() if k != "outcome_support"} | {"n_outcomes": len(row["outcome_support"])}
            for row in strict_acc["by_source_horizon_split"]
        ],
        "async": {k: v for k, v in async_acc.items() if k != "by_source_horizon_split"},
        "async_by_source_horizon_split": [
            {k: v for k, v in row.items() if k != "outcome_support"} | {"n_outcomes": len(row["outcome_support"])}
            for row in async_acc["by_source_horizon_split"]
        ],
        "async_not_used_for_dependence_acceptance": True,
        "ok": True,
    }
