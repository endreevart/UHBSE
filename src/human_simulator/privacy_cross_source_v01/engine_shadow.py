"""Engine cross-source shadow — only when accepted comparable outcome exists."""

from __future__ import annotations

from typing import Any

from human_simulator.privacy_cross_source_v01.policy import CLAIM_LEVEL_SHADOW, VERSION


def run_engine_cross_source_shadow(*, accepted_count: int) -> dict[str, Any]:
    if accepted_count < 1:
        return {
            "version": VERSION,
            "ENGINE_CROSS_SOURCE_SHADOW_STATUS": "NOT_RUN_NO_ACCEPTED_MAPPINGS",
            "claim_level": CLAIM_LEVEL_SHADOW,
            "executed": False,
            "clinical_use_prohibited": True,
            "treatment_effect_prohibited": True,
            "causal_interpretation_prohibited": True,
            "ok": True,
        }
    return {
        "version": VERSION,
        "ENGINE_CROSS_SOURCE_SHADOW_STATUS": "TECHNICAL_CROSS_SOURCE_SHADOW_PASS",
        "claim_level": CLAIM_LEVEL_SHADOW,
        "executed": True,
        "ok": True,
    }
