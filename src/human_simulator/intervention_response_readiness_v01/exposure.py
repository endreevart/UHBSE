"""Exposure semantic ladder. No automatic promotion between levels."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_response_readiness_v01.policy import EXPOSURE_TIERS, IR_ELIGIBLE_TIERS

LEVELS: list[dict[str, Any]] = [
    {
        "id": "UNKNOWN",
        "required_fields": ["source_system"],
        "evidence_source": "absence_or_unclassified_record",
        "missing_evidence": "NOT_ESTABLISHED",
        "intervention_response_eligible": False,
        "descriptive_lane": False,
        "associational_lane": False,
        "administration_lane": False,
        "causal_lane": False,
    },
    {
        "id": "RECOMMENDED",
        "required_fields": ["recommendation_identity", "recommendation_time"],
        "evidence_source": "explicit_recommendation_record_with_time_semantics",
        "missing_evidence": "NOT_ESTABLISHED",
        "intervention_response_eligible": False,
        "descriptive_lane": False,
        "associational_lane": False,
        "administration_lane": False,
        "causal_lane": False,
        "note": "A recommendation is not prescription, dispense, administration, or ingestion.",
    },
    {
        "id": "RECORDED_MEDICATION_ASSOCIATION",
        "required_fields": [
            "source_system",
            "source_local_medication_identity_or_public_digest",
            "record_class=RECORDED_MEDICATION_CONTEXT",
        ],
        "evidence_source": "source_medication_row_with_recorded_context_semantics",
        "missing_evidence": "NOT_ESTABLISHED",
        "intervention_response_eligible": False,
        "inventory_only": True,
        "descriptive_lane": True,
        "associational_lane": False,
        "administration_lane": False,
        "causal_lane": False,
        "note": "Recorded association is technical inventory only, not intervention-response eligible.",
    },
    {
        "id": "PRESCRIBED_OR_ORDERED_EXPOSURE",
        "required_fields": [
            "domain_accepted_mapping",
            "order_or_prescription_identity",
            "order_time",
            "order_time_semantics=PRESCRIBED_OR_ORDERED",
        ],
        "evidence_source": "domain-accepted prescription or order record, not LLM/algorithmic candidate",
        "missing_evidence": "NOT_READY",
        "intervention_response_eligible": True,
        "descriptive_lane": False,
        "associational_lane": True,
        "administration_lane": False,
        "causal_lane": False,
    },
    {
        "id": "INGESTION_UNVERIFIED",
        "required_fields": ["dispense_or_administration_candidate", "ingestion_confirmation=NOT_ESTABLISHED"],
        "evidence_source": "dispense/administration candidate without verified ingest",
        "missing_evidence": "NOT_ESTABLISHED",
        "intervention_response_eligible": False,
        "descriptive_lane": False,
        "associational_lane": False,
        "administration_lane": False,
        "causal_lane": False,
    },
    {
        "id": "DISPENSED_OR_ADMINISTERED_EXPOSURE",
        "required_fields": [
            "domain_accepted_mapping",
            "administration_or_dispense_identity",
            "administration_or_dispense_time",
            "time_semantics=DISPENSED_OR_ADMINISTERED",
            "confirmed_administration_mapping",
        ],
        "evidence_source": "domain-accepted dispense or administration record",
        "missing_evidence": "NOT_READY",
        "intervention_response_eligible": True,
        "descriptive_lane": False,
        "associational_lane": False,
        "administration_lane": True,
        "causal_lane": False,
    },
    {
        "id": "CAUSAL_INTERVENTION_EVIDENCE",
        "required_fields": [
            "domain_accepted_mapping",
            "causal_identification_strategy",
            "resolved_confounding_and_indication_bias",
            "temporally_valid_t0",
        ],
        "evidence_source": "explicit causal identification, never inferred from associational readiness",
        "missing_evidence": "NOT_ESTABLISHED",
        "intervention_response_eligible": False,
        "descriptive_lane": False,
        "associational_lane": False,
        "administration_lane": False,
        "causal_lane": True,
        "never_auto_promoted_from_associational": True,
    },
]


def classify_tier(
    *,
    record_class: str | None,
    mapping_status: str | None,
    administration_claim: str | None,
    event_time_semantics: str | None,
    recommendation: bool = False,
) -> str:
    if recommendation:
        return "RECOMMENDED"
    if administration_claim in {"CONFIRMED_ADMINISTRATION", "DISPENSED"} and mapping_status == "accepted":
        return "DISPENSED_OR_ADMINISTERED_EXPOSURE"
    if event_time_semantics in {"PRESCRIBED_OR_ORDERED", "PRESCRIPTION_TIME"} and mapping_status == "accepted":
        return "PRESCRIBED_OR_ORDERED_EXPOSURE"
    if record_class in {"RECORDED_MEDICATION_CONTEXT", "RECORDED_MEDICATION_ASSOCIATION"}:
        return "RECORDED_MEDICATION_ASSOCIATION"
    if not record_class:
        return "UNKNOWN"
    return "UNKNOWN"


def no_auto_promote(from_tier: str, to_tier: str) -> bool:
    order = {name: idx for idx, name in enumerate(EXPOSURE_TIERS)}
    return order.get(to_tier, 0) > order.get(from_tier, 0)


def exposure_contract() -> dict[str, Any]:
    return {
        "version": "0.1",
        "promotion": "FORBIDDEN_AUTOMATIC",
        "associational_does_not_raise_causal": True,
        "appointment_date_is_not_administration": True,
        "created_modified_are_not_administration": True,
        "recorded_association_is_not_treatment_response": True,
        "tiers": list(EXPOSURE_TIERS),
        "intervention_response_eligible_tiers": sorted(IR_ELIGIBLE_TIERS),
        "levels": LEVELS,
        "lanes": {
            "descriptive_recorded_association": {
                "eligible_tiers": ["RECORDED_MEDICATION_ASSOCIATION"],
                "counts_as_intervention_response": False,
            },
            "prescribed_ordered_associational": {
                "eligible_tiers": ["PRESCRIBED_OR_ORDERED_EXPOSURE"],
                "counts_as_intervention_response": True,
                "requires_domain_accepted_mapping": True,
            },
            "administration_conditioned": {
                "eligible_tiers": ["DISPENSED_OR_ADMINISTERED_EXPOSURE"],
                "counts_as_intervention_response": True,
                "requires_domain_accepted_mapping": True,
            },
            "causal": {
                "eligible_tiers": ["CAUSAL_INTERVENTION_EVIDENCE"],
                "counts_as_intervention_response": False,
                "always_evaluated_separately": True,
            },
        },
    }
