"""Transfer gate for v0.1.2.1.1 — transfer must not execute this release."""

from __future__ import annotations

from typing import Any

from human_simulator.unified_v01211.policy import (
    CROSS_SOURCE_TRANSFER_NAME,
    DOMAIN_REVIEW_REQUIRED,
    NOT_RUN_DUE_TO_FAILED_GATE,
    VERSION,
)


def build_transfer_gate(
    *,
    baseline_ok: bool,
    t3_status: str,
    frozen_status: str,
    applicability_pass: bool,
    applicability_status: str,
    provenance_ok: bool,
    lineage_ok: bool,
) -> dict[str, Any]:
    checks = {
        "baseline_verification": baseline_ok,
        "t3_harmonization_allows_transfer": t3_status != DOMAIN_REVIEW_REQUIRED,
        "frozen_model_ready": frozen_status in ("FROZEN", "UNCHANGED_COPIED"),
        "applicability_allows_transfer": applicability_pass,
        "applicability_not_partial": applicability_status == "APPLICABILITY_CHECK_PASS",
        "source_a_provenance_isolation": provenance_ok,
        "source_a_population_lineage": lineage_ok,
        "transfer_execution_forbidden_this_release": False,  # informational invert below
    }
    # This release never executes transfer regardless — mark intentional non-run
    failed = [k for k, v in checks.items() if k != "transfer_execution_forbidden_this_release" and not v]
    # Always include t3 if domain review
    if t3_status == DOMAIN_REVIEW_REQUIRED and "t3_harmonization_allows_transfer" not in failed:
        failed.append("t3_harmonization_allows_transfer")
        checks["t3_harmonization_allows_transfer"] = False
    if applicability_status == "APPLICABILITY_CHECK_PARTIAL":
        if "applicability_allows_transfer" not in failed:
            failed.append("applicability_allows_transfer")
        checks["applicability_allows_transfer"] = False
        checks["applicability_not_partial"] = False
        if "applicability_not_partial" not in failed:
            failed.append("applicability_not_partial")

    return {
        "version": VERSION,
        "name": CROSS_SOURCE_TRANSFER_NAME,
        "transfer_gate_status": "FAIL",
        "all_gates_pass": False,
        "checks": checks,
        "failed_checks": sorted(set(failed)),
        "b_cannot_tune_a": True,
        "clinical_validation": "NOT_STARTED",
        "transfer_must_not_run_this_release": True,
    }


def non_execution_result(gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "name": CROSS_SOURCE_TRANSFER_NAME,
        "executed": False,
        "cross_source_transfer_status": NOT_RUN_DUE_TO_FAILED_GATE,
        "failed_checks": gate.get("failed_checks") or [],
        "claim": (
            "Transfer intentionally not executed in v0.1.2.1.1 integrity correction."
        ),
        "b_cannot_tune_a": True,
        "external_clinical_validation": False,
    }
