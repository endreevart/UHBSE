"""Cross-source comparability gates and backtest (honest NOT_RUN when gates fail)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified.policy import (
    CROSS_SOURCE_NOT_RUN_GATE,
    INDEPENDENCE_NOT_ESTABLISHED,
    OUTCOME_NOT_COMPARABLE,
    STATUS_NOT_ESTABLISHED,
)


def load_stage02_linkage(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "artifacts" / "stage-02" / "identity-linkage-assessment.json"
    if not path.is_file():
        return {"missing": True, "identity_verdict": {"verdict": "NOT_EVALUATED"}}
    return json.loads(path.read_text(encoding="utf-8"))


def linkage_readiness_assessment(repo_root: Path) -> dict[str, Any]:
    """Sanitised aggregate linkage readiness — no identifiers."""
    doc = load_stage02_linkage(repo_root)
    verdict_obj = doc.get("identity_verdict") or {}
    if isinstance(verdict_obj, dict):
        verdict = verdict_obj.get("verdict")
        reason = verdict_obj.get("reason")
    else:
        verdict = verdict_obj
        reason = None
    overlap = doc.get("overlap_aggregates") or {}
    return {
        "linkage_inputs_available": not doc.get("missing", False),
        "linkage_contract_present": True,
        "candidate_overlap_count": int(overlap.get("matched_unique_email_identifiers") or 0)
        + int(overlap.get("matched_unique_phone_identifiers") or 0),
        "confirmed_overlap_count": int(overlap.get("consistent_subject_pairs_by_phone_and_email") or 0),
        "ambiguous_overlap_count": int(overlap.get("ambiguous_subject_pairs") or 0),
        "conflicting_overlap_count": int(overlap.get("cross_field_conflicts") or 0),
        "linkage_false_positive_control_available": False,
        "linkage_status": (
            "CANDIDATE_ONLY"
            if verdict == "POTENTIAL_OVERLAP"
            else ("INSUFFICIENT_EVIDENCE" if doc.get("missing") else "NOT_EVALUATED")
        ),
        "stage02_identity_verdict": verdict,
        "stage02_reason_sanitised": reason,
        "identity_merge_performed": False,
        "notes": [
            "POTENTIAL_OVERLAP is not proof of subject equality.",
            "Source-local identities preserved; no global_patient_id.",
        ],
    }


def assess_comparability(
    *,
    has_exact_outcome_map: bool,
    intersection_status: str,
    linkage: dict[str, Any],
) -> dict[str, Any]:
    gates = {
        "exact_outcome_map": has_exact_outcome_map,
        "intersection_comparable": intersection_status not in (OUTCOME_NOT_COMPARABLE, "NOT_COMPARABLE"),
        "independence_established": False,  # POTENTIAL_OVERLAP ⇒ not established
    }
    failed = [k for k, v in gates.items() if not v]

    if not has_exact_outcome_map or intersection_status == OUTCOME_NOT_COMPARABLE:
        comparability = OUTCOME_NOT_COMPARABLE
    elif failed:
        comparability = "FAIL"
    else:
        comparability = "PASS"

    independence = INDEPENDENCE_NOT_ESTABLISHED
    if linkage.get("stage02_identity_verdict") == "POTENTIAL_OVERLAP":
        independence = INDEPENDENCE_NOT_ESTABLISHED
    elif linkage.get("linkage_status") == "CONFIRMED_LINKAGE_AVAILABLE":
        # Even then, independence for transfer is not established without holdout design.
        independence = INDEPENDENCE_NOT_ESTABLISHED

    return {
        "status": comparability,
        "gates": gates,
        "failed_gates": failed,
        "cross_source_independence_status": independence,
        "claim_forbidden": "CROSS_SOURCE_EXTERNAL_VALIDATION",
        "allowed_label_if_run": "CROSS_SOURCE_TRANSFER_EXPLORATION",
    }


def run_cross_source_backtest(
    *,
    comparability: dict[str, Any],
) -> dict[str, Any]:
    """Execute A→B only when all gates pass; otherwise honest NOT_RUN."""
    failed = list(comparability.get("failed_gates") or [])
    if failed or comparability.get("status") in (OUTCOME_NOT_COMPARABLE, "FAIL"):
        reason_status = CROSS_SOURCE_NOT_RUN_GATE
        if comparability.get("status") == OUTCOME_NOT_COMPARABLE:
            reason_status = OUTCOME_NOT_COMPARABLE
        elif comparability.get("cross_source_independence_status") == INDEPENDENCE_NOT_ESTABLISHED:
            # Prefer independence when that is the binding scientific constraint and outcome also fails.
            if "exact_outcome_map" in failed:
                reason_status = OUTCOME_NOT_COMPARABLE
            else:
                reason_status = INDEPENDENCE_NOT_ESTABLISHED
        return {
            "status": reason_status,
            "executed": False,
            "failed_gates": failed,
            "detail": (
                "Cross-source backtest not executed: Stage 02 POTENTIAL_OVERLAP and/or "
                "no EXACT outcome map between Source A and Source B."
            ),
            "external_validation_claimed": False,
        }

    return {
        "status": STATUS_NOT_ESTABLISHED,
        "executed": False,
        "detail": "Gates unexpectedly passed without B outcome data; still not run.",
        "external_validation_claimed": False,
    }
