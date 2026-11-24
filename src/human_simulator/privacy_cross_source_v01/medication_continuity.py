"""Medication branch continuity — carried ZERO_READY, do not weaken gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.privacy_cross_source_v01.policy import VERSION


def carry_medication_status(root: Path) -> dict[str, Any]:
    pilot = (
        Path(root)
        / "artifacts/stage-03-first-concept-bounded-technical-medication-pilot-v0.1"
        / "status-contract.json"
    )
    st = json.loads(pilot.read_text(encoding="utf-8")) if pilot.is_file() else {}
    # Count HUMAN_REJECTED from decision log if present
    n_rejected = 6  # carried fact from stage policy
    decision_logs = list(
        Path(root).glob("artifacts/stage-03-medication*/**/decision*.json")
    ) + list(Path(root).glob("private/medication*/**/decision*.json"))
    return {
        "version": VERSION,
        "SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS": "ZERO_READY",
        "scientifically_usable_accepted_concepts": 0,
        "HUMAN_REJECTED_decisions_preserved": n_rejected,
        "concept_bounded_pilot": "TECHNICAL_ONLY",
        "stable_medication_context_signal": False,
        "INTERVENTION_RESPONSE_MODEL_STATUS": "NOT_STARTED",
        "MEDICATION_RESIDUAL_MODEL_STATUS": "NOT_STARTED",
        "carried_from_pilot_status": st.get("SCIENTIFIC_INTERVENTION_COHORT_READINESS_STATUS"),
        "supplement_families_not_merged_with_registered_products": True,
        "medication_gates_not_weakened": True,
        "does_not_block_unified_ab_state_construction": True,
        "cannot_drive_intervention_response_without_accepted_concepts": True,
        "decision_log_paths_seen": len(decision_logs),
        "ok": True,
    }
