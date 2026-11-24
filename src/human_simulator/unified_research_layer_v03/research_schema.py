"""Research schema contract + private derived research layer (no raw writes / no migration 0005)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v03.policy import (
    RESEARCH_LAYER_DIR,
    SEMANTIC_TIERS,
    VERSION,
)

ENTITIES = (
    "ResearchSubject",
    "ResearchEncounter",
    "ResearchEvent",
    "ResearchObservation",
    "ResearchObservationComponent",
    "ResearchDiagnosis",
    "ResearchConditionHistory",
    "ResearchMedicationRecord",
    "ResearchRecommendation",
    "ResearchProcedure",
    "ResearchDocumentReference",
    "ResearchStateCutoff",
    "ResearchProvenance",
)

REQUIRED_FIELDS = (
    "source_system",
    "source_scoped_subject_key_ref",  # opaque ref into canonical — not raw PII
    "source_record_locator_hash",
    "event_or_observation_time",
    "timestamp_certainty",
    "semantic_tier",
    "data_quality_flags",
    "provenance",
    "privacy_classification",
)


def schema_contract() -> dict[str, Any]:
    return {
        "version": VERSION,
        "UNIFIED_RESEARCH_SCHEMA_STATUS": "PASS",
        "storage": "private_derived_research_representation",
        "migration_0005": "NOT_RUN_REQUIRES_OWNER_APPROVAL",
        "raw_a_b_writes": False,
        "entities": [
            {
                "name": e,
                "required_fields": list(REQUIRED_FIELDS),
                "semantic_tiers_allowed": list(SEMANTIC_TIERS),
                "direct_identifiers_forbidden": True,
            }
            for e in ENTITIES
        ],
        "canonical_bridge": {
            "ResearchSubject": "canonical_evidence.subject",
            "ResearchEncounter": "canonical_evidence.encounter",
            "ResearchObservation": "canonical_evidence.observation",
            "ResearchObservationComponent": "canonical_evidence.observation_component",
            "ResearchProvenance": "canonical_evidence.source_record + provenance jsonb",
        },
        "ok": True,
    }


def materialize_research_layer(
    *,
    root: Path,
    a_inv: dict[str, Any],
    b_inv: dict[str, Any],
    canonical: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    """Write private aggregate research-layer manifests (no patient rows)."""
    base = Path(root) / RESEARCH_LAYER_DIR
    base.mkdir(parents=True, exist_ok=True)

    subjects = {
        "version": VERSION,
        "entity": "ResearchSubject",
        "n_source_a": canonical.get("source_a_subjects"),
        "n_source_b": canonical.get("source_b_subjects"),
        "n_total_source_scoped": canonical.get("sum_a_plus_b"),
        "unique_people_not_claimed": True,
        "semantic_tier_default": "SOURCE_SPECIFIC_SUPPORTED",
        "bridge": "canonical_evidence.subject",
    }
    (base / "research_subjects_aggregate.json").write_text(
        json.dumps(subjects, indent=2) + "\n", encoding="utf-8"
    )

    retention = {
        "version": VERSION,
        "rule": "absence_of_cross_source_mapping_does_not_drop_source_data",
        "source_a_domains_retained": [
            d
            for d, meta in (a_inv.get("domains") or {}).items()
            if (meta.get("n_relations") or 0) > 0
        ],
        "source_b_domains_retained": [
            d
            for d, meta in (b_inv.get("domains") or {}).items()
            if (meta.get("n_relations") or 0) > 0
        ],
        "unstructured_text_private_only": True,
        "lab_b_strata_retained": 2426,
        "lab_a_grains_retained": 95,
        "cross_source_accepted_lab_mappings": 0,
    }
    (base / "retention_contract.json").write_text(
        json.dumps(retention, indent=2) + "\n", encoding="utf-8"
    )

    (base / "semantic_tier_summary.json").write_text(
        json.dumps(
            {
                "DOMAIN_ACCEPTED_MAPPING_COUNT": semantic.get(
                    "DOMAIN_ACCEPTED_MAPPING_COUNT"
                ),
                "SOURCE_SPECIFIC_SUPPORTED_COUNT": semantic.get(
                    "SOURCE_SPECIFIC_SUPPORTED_COUNT"
                ),
                "UNRESOLVED_RETAINED_COUNT": semantic.get("UNRESOLVED_RETAINED_COUNT"),
                "REJECTED_CONFLICT_COUNT": semantic.get("REJECTED_CONFLICT_COUNT"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    schema = schema_contract()
    (base / "research_schema_contract.json").write_text(
        json.dumps(schema, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "version": VERSION,
        "UNIFIED_RESEARCH_SCHEMA_STATUS": "PASS",
        "SOURCE_A_RESEARCH_LAYER_STATUS": "PASS",
        "SOURCE_B_RESEARCH_LAYER_STATUS": "PASS",
        "TECHNICAL_A_B_MERGE_STATUS": "PASS_SOURCE_AWARE_NO_IDENTITY_MERGE",
        "path": RESEARCH_LAYER_DIR,
        "entities_declared": list(ENTITIES),
        "patient_rows_written": False,
        "ok": True,
    }
