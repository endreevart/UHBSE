"""Unified source-aware longitudinal state schema (no identity merge)."""

from __future__ import annotations

from typing import Any

from human_simulator.privacy_cross_source_v01.policy import VERSION


UNIFIED_STATE_SCHEMA = {
    "entity": "UnifiedLongitudinalState",
    "version": VERSION,
    "required_fields": [
        "research_subject_id",
        "source_system",
        "cutoff_relative",
        "relative_timeline",
        "observed_outcomes",
        "missingness_mask",
        "prediction_horizon_days",
        "applicability_fields",
        "provenance_evidence_locators",
        "identity_merge",
    ],
    "identity_merge_must_be": False,
    "notes": [
        "Union of compatible schema/semantics across sources.",
        "Does not assert that Source A and Source B records belong to the same people.",
        "Populations must not be mixed for learning before domain-shift and independence gates.",
    ],
}


def build_unified_state_layer(
    *,
    accepted_comparable_count: int,
    source_a_providers: int,
    source_b_catalog_grains: int,
) -> dict[str, Any]:
    built = True  # schema-level layer always built
    populated = accepted_comparable_count > 0
    return {
        "version": VERSION,
        "UNIFIED_SOURCE_AWARE_STATE_STATUS": "BUILT" if built else "FAIL",
        "schema": UNIFIED_STATE_SCHEMA,
        "n_accepted_comparable_outcomes": accepted_comparable_count,
        "n_source_a_providers": source_a_providers,
        "n_source_b_catalog_grains": source_b_catalog_grains,
        "instance_population": (
            "POPULATED_FOR_ACCEPTED_MAPPINGS" if populated else "SCHEMA_ONLY_NO_ACCEPTED_MAPPINGS"
        ),
        "CROSS_SOURCE_IDENTITY_MERGE_STATUS": "NOT_RUN",
        "identity_merge": False,
        "source_populations_mixed_for_learning": False,
        "ok": built,
    }
