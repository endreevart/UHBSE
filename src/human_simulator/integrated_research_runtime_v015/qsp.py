"""QSP/PKPD adapter boundary. Synthetic only. Real intervention unavailable."""

from __future__ import annotations

from typing import Any

from human_simulator.integrated_research_runtime_v01.qsp import run_pkpd, run_qsp, sandbox_audit as v01_sandbox
from human_simulator.integrated_research_runtime_v015.policy import VERSION


def _public(run: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in run.items() if k not in {"concentration", "effect", "biomarker", "solver"}}


def execute_qsp(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("link_to_patient") or request.get("patient_id") or request.get("patient_linked"):
        return {
            "status": "FAIL",
            "reason": "PATIENT_SPECIFIC_QSP_PROHIBITED",
            "synthetic_only": True,
            "patient_linked": False,
            "version": VERSION,
        }
    iv = request.get("intervention") or {}
    real = False
    for obj in (request, iv):
        for k in ("medication", "dose", "supplement", "nutrition"):
            v = obj.get(k)
            if v not in (None, "", 0, 0.0, False, [], {}):
                real = True
    if real and not request.get("allow_synthetic_compound_x"):
        return {
            "status": "FAIL",
            "reason": "INTERVENTION_EFFECT_UNAVAILABLE",
            "ignored": False,
            "synthetic_only": True,
            "patient_linked": False,
            "version": VERSION,
        }
    mid = request.get("model_id") or "SYNTHETIC_REFERENCE_COMPOUND_X_PKPD"
    run = run_qsp() if mid == "SYNTHETIC_HOMEOSTATIC_BIOMARKER_QSP" else run_pkpd()
    return {
        **_public(run),
        "status": "OK",
        "synthetic_only": True,
        "patient_linked": False,
        "CLINICAL_USE_PROHIBITED": True,
        "version": VERSION,
    }


def sandbox_audit() -> dict[str, Any]:
    base = v01_sandbox()
    blocked = execute_qsp({"medication": "real-drug-x", "dose": 10})
    return {
        **base,
        "version": VERSION,
        "nonzero_real_intervention": blocked,
        "INTERVENTION_EFFECT_UNAVAILABLE": blocked.get("reason") == "INTERVENTION_EFFECT_UNAVAILABLE",
        "does_not_ignore_and_continue": blocked.get("ignored") is False,
        "ok": bool(base.get("ok")) and blocked.get("reason") == "INTERVENTION_EFFECT_UNAVAILABLE",
    }
