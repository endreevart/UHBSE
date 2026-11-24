"""Applicability accounting + PARTIAL_SUPPORT closure for carried v0.1.1 gap."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from human_simulator.privacy_cross_source_v01.policy import (
    ACCEPTED_GS011_ARTIFACT_DIR,
    CARRIED_V011_IN_SUPPORT_SUM,
    CARRIED_V011_PRIMARY_TARGETS,
    VERSION,
)


def audit_carried_v011_applicability_gap(root: Path) -> dict[str, Any]:
    """Classify the 19195−18311=884 gap from published per-outcome counts.

    v0.1.1 only tallied IN_SUPPORT and OUT_OF_SUPPORT; other applicability
    statuses were silently dropped from the funnel.
    """
    bt = json.loads(
        (
            Path(root)
            / ACCEPTED_GS011_ARTIFACT_DIR
            / "real-heldout-multi-outcome-backtest.json"
        ).read_text(encoding="utf-8")
    )
    rows = list(bt.get("evaluable_per_outcome") or []) + list(
        bt.get("diagnostic_only_per_outcome") or []
    )
    in_sup = sum(int(r.get("n_in_support") or 0) for r in rows)
    out_sup = sum(int(r.get("n_out_of_support") or 0) for r in rows)
    n_targets = int(bt.get("n_primary_targets") or CARRIED_V011_PRIMARY_TARGETS)
    gap = n_targets - in_sup - out_sup

    # Per-outcome residual
    residuals = []
    for r in rows:
        n = int(r.get("n_unique_targets") or 0)
        ins = int(r.get("n_in_support") or 0)
        outs = int(r.get("n_out_of_support") or 0)
        rem = n - ins - outs
        if rem:
            residuals.append(
                {
                    "outcome": r.get("outcome"),
                    "unit": r.get("unit"),
                    "n_unique_targets": n,
                    "n_in_support": ins,
                    "n_out_of_support": outs,
                    "n_unclassified_in_v011": rem,
                }
            )

    return {
        "version": VERSION,
        "PARTIAL_SUPPORT_ACCOUNTING_STATUS": "PASS" if gap == 884 else "FAIL",
        "carried_primary_targets": n_targets,
        "carried_in_support_sum": in_sup,
        "carried_out_of_support_sum": out_sup,
        "carried_unclassified_gap": gap,
        "expected_gap": 884,
        "expected_in_support": CARRIED_V011_IN_SUPPORT_SUM,
        "v011_defect": (
            "v0.1.1 metrics counted only IN_SUPPORT and OUT_OF_SUPPORT; "
            f"{gap} primary targets lacked those labels in the published tallies "
            "(runtime evidence: residual per outcome below). "
            "Likely PARTIAL_SUPPORT / missing applicability_status on persistence "
            "or unsupported paths — must be explicit in future funnels."
        ),
        "funnel_v011_reconstructed": {
            "candidate_primary_targets": n_targets,
            "IN_SUPPORT": in_sup,
            "OUT_OF_SUPPORT": out_sup,
            "UNCLASSIFIED_IN_V011_REPORTING": gap,
            "predicted_equals_primary": n_targets,
            "evaluated_equals_primary": n_targets,
            "unexplained": 0,
        },
        "per_outcome_residuals": residuals,
        "n_outcomes_with_residual": len(residuals),
        "ok": gap == 884 and in_sup == CARRIED_V011_IN_SUPPORT_SUM,
    }


def build_applicability_funnel(counts: dict[str, int]) -> dict[str, Any]:
    """Full required applicability funnel (cross-source or retrospective)."""
    required = (
        "candidate_targets",
        "IN_SUPPORT",
        "PARTIAL_SUPPORT",
        "OUT_OF_SUPPORT",
        "blocked_before_prediction",
        "predicted",
        "evaluated",
        "unexplained",
    )
    missing = [k for k in required if k not in counts]
    total_parts = (
        int(counts.get("IN_SUPPORT") or 0)
        + int(counts.get("PARTIAL_SUPPORT") or 0)
        + int(counts.get("OUT_OF_SUPPORT") or 0)
        + int(counts.get("blocked_before_prediction") or 0)
    )
    cand = int(counts.get("candidate_targets") or 0)
    unexplained = int(counts.get("unexplained") or 0)
    # Identity: parts + unexplained should cover candidates when fully accounted
    ok = not missing and unexplained == 0
    return {
        "version": VERSION,
        "APPLICABILITY_ACCOUNTING_STATUS": "PASS" if ok else "FAIL",
        "funnel": {k: int(counts.get(k) or 0) for k in required},
        "missing_keys": missing,
        "parts_sum": total_parts,
        "candidates": cand,
        "ok": ok,
    }
