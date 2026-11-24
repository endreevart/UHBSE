"""Build registry, evaluate G0–G10, consumption, temporal, confounding, readiness."""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_response_readiness_v01.exposure import classify_tier, exposure_contract
from human_simulator.intervention_response_readiness_v01.hashes import public_digest
from human_simulator.intervention_response_readiness_v01.policy import (
    FORBIDDEN_TECHNICAL_TIMESTAMPS,
    GATES,
    IR_ELIGIBLE_TIERS,
    SOURCE_A,
    SOURCE_B,
    VERSION,
)

GATE_FAIL = "FAIL"
GATE_PASS = "PASS"
GATE_NOT_ESTABLISHED = "NOT_ESTABLISHED"


def _gate(status: str, reason: str) -> dict[str, str]:
    return {"status": status, "reason": reason}


def evaluate_cell(cell: dict[str, Any], *, domain_accepted: int, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(cell)
    if overrides:
        data.update(overrides)

    mapping_status = str(data.get("mapping_status") or "unknown")
    mapping_type = str(data.get("mapping_type") or "candidate")
    tier = str(data.get("exposure_semantic_tier") or "UNKNOWN")
    event_field = str(data.get("event_time_field") or "")
    event_sem = str(data.get("event_time_semantics") or "NOT_ESTABLISHED")
    source = str(data.get("source_system") or "")
    vocab_version = str((data.get("vocabulary") or {}).get("version") or "NOT_ESTABLISHED")
    vocab_provider = str((data.get("vocabulary") or {}).get("provider") or "UNKNOWN")
    dose_value = data.get("dose_value_available")
    dose_unit_interp = str(data.get("dose_unit_interpretation_status") or "NOT_ESTABLISHED")
    route = data.get("route_available")
    duration = data.get("duration_available")
    synthetic_filled = bool(data.get("synthetic_defaults_used"))
    future_in_pre = bool(data.get("future_outcome_in_pre_t0_features"))
    exposure_after_outcome = bool(data.get("exposure_after_outcome"))
    patient_overlap = bool(data.get("patient_overlap_across_splits"))
    recorded_as_treatment = bool(data.get("recorded_association_declared_treatment_response"))
    source_transfer = bool(data.get("source_a_mapping_applied_to_source_b"))
    identity_mutated = bool(data.get("source_or_vocabulary_identity_mutated"))
    mapping_promoted = bool(data.get("candidate_promoted_without_evidence"))

    accepted_here = mapping_status == "accepted" and mapping_type == "domain_accepted" and not mapping_promoted
    domain_count = int(domain_accepted)
    if mapping_promoted:
        accepted_here = False

    g0_reason = "SOURCE_IDENTITY_PRESENT"
    g0 = GATE_PASS
    if not source:
        g0, g0_reason = GATE_FAIL, "MISSING_SOURCE_SYSTEM"
    elif source == SOURCE_B and int(data.get("source_medication_row_count") or 0) == 0:
        g0, g0_reason = GATE_FAIL, "SOURCE_B_MEDICATION_CONTEXT_NOT_AVAILABLE_NO_TRANSFER"
    if source_transfer:
        g0, g0_reason = GATE_FAIL, "SOURCE_A_MAPPING_TRANSFERRED_TO_SOURCE_B"
    if identity_mutated:
        g0, g0_reason = GATE_FAIL, "SOURCE_OR_VOCABULARY_IDENTITY_MUTATED"

    g1_reason = "VOCABULARY_AND_MAPPING_IDENTITY_NOT_ESTABLISHED"
    g1 = GATE_FAIL
    if vocab_provider not in {"UNKNOWN", ""} and vocab_version not in {"NOT_ESTABLISHED", ""} and accepted_here:
        g1, g1_reason = GATE_PASS, "EXACT_VOCABULARY_MAPPING_IDENTITY"
    if identity_mutated:
        g1, g1_reason = GATE_FAIL, "VOCABULARY_VERSION_OR_SOURCE_IDENTITY_CHANGED"

    g2_reason = "DOMAIN_ACCEPTED_MAPPING_COUNT=0"
    g2 = GATE_FAIL
    if domain_count > 0 and accepted_here:
        g2, g2_reason = GATE_PASS, "DOMAIN_ACCEPTED_MAPPING_PRESENT"
    if mapping_promoted:
        g2, g2_reason = GATE_FAIL, "CANDIDATE_RENAMED_DOMAIN_ACCEPTED_WITHOUT_EVIDENCE"

    g3_reason = f"TIER_{tier}_NOT_INTERVENTION_RESPONSE_ELIGIBLE"
    g3 = GATE_FAIL
    if tier in IR_ELIGIBLE_TIERS and accepted_here:
        g3, g3_reason = GATE_PASS, f"TIER_{tier}"
    if recorded_as_treatment and tier == "RECORDED_MEDICATION_ASSOCIATION":
        g3, g3_reason = GATE_FAIL, "RECORDED_ASSOCIATION_DECLARED_TREATMENT_RESPONSE"
    if event_sem in {"ADMINISTRATION", "DISPENSED_OR_ADMINISTERED"} and event_field in FORBIDDEN_TECHNICAL_TIMESTAMPS:
        g3, g3_reason = GATE_FAIL, "TECHNICAL_TIMESTAMP_DECLARED_ADMINISTRATION"

    admin_claim = str(data.get("administration_claim") or "NOT_CLAIMED")
    if event_field in FORBIDDEN_TECHNICAL_TIMESTAMPS and admin_claim != "NOT_CLAIMED":
        g4_status, g4_reason = GATE_FAIL, f"{event_field}_IS_NOT_ADMINISTRATION_TIME"
    elif event_field in FORBIDDEN_TECHNICAL_TIMESTAMPS:
        g4_status, g4_reason = GATE_FAIL, "EVENT_TIME_IS_CANDIDATE_TECHNICAL_TIMESTAMP"
    elif data.get("timezone_contract") in {None, "NOT_ESTABLISHED"}:
        g4_status, g4_reason = GATE_FAIL, "TIMEZONE_CONTRACT_NOT_ESTABLISHED"
    elif data.get("timestamp_precision") in {"DATE_ONLY", "DATE_ONLY_OR_UNVERIFIED", "NOT_ESTABLISHED"}:
        g4_status, g4_reason = GATE_FAIL, "DATE_ONLY_OR_AMBIGUOUS_PRECISION"
    else:
        g4_status, g4_reason = GATE_PASS, "TEMPORAL_CONTRACT_ESTABLISHED"
    if exposure_after_outcome:
        g4_status, g4_reason = GATE_FAIL, "EXPOSURE_TIMESTAMP_AFTER_OUTCOME"
    if future_in_pre:
        g4_status, g4_reason = GATE_FAIL, "FUTURE_OUTCOME_IN_PRE_T0_FEATURES"
    if data.get("same_day_ambiguity_unresolved", True):
        if g4_status == GATE_PASS:
            g4_status, g4_reason = GATE_FAIL, "SAME_DAY_AMBIGUITY_UNRESOLVED"

    g5_status, g5_reason = GATE_PASS, "OUTCOME_DIGEST_AND_NATIVE_UNIT_PRESENT"
    if not data.get("outcome_identity_digest") or not data.get("native_outcome_unit"):
        g5_status, g5_reason = GATE_FAIL, "OUTCOME_OR_NATIVE_UNIT_NOT_ESTABLISHED"
    if source == SOURCE_B:
        g5_status, g5_reason = GATE_FAIL, "SOURCE_B_NO_MEDICATION_CONDITIONED_OUTCOME_CELL"

    g6_status, g6_reason = GATE_FAIL, "PRE_POST_NOT_ESTABLISHED_FOR_INTERVENTION_T0"
    if data.get("pre_t0_state_availability") == "ESTABLISHED" and data.get("post_t0_outcome_availability") == "ESTABLISHED":
        g6_status, g6_reason = GATE_PASS, "PRE_POST_ESTABLISHED"
    if future_in_pre:
        g6_status, g6_reason = GATE_FAIL, "FUTURE_INFORMATION_IN_FEATURES"

    g7_status, g7_reason = GATE_FAIL, "INTERVENTION_SPLIT_FEASIBILITY_NOT_ESTABLISHED"
    if data.get("split_feasibility") == "SUBJECT_DISJOINT_LEAKAGE_SAFE":
        g7_status, g7_reason = GATE_PASS, "SUBJECT_DISJOINT_LEAKAGE_SAFE"
    if patient_overlap:
        g7_status, g7_reason = GATE_FAIL, "PATIENT_OVERLAP_ACROSS_SPLITS"

    g8_status, g8_reason = GATE_FAIL, "CONFOUNDING_AND_INDICATION_BIAS_UNRESOLVED"
    if data.get("confounding_resolved") is True:
        g8_status, g8_reason = GATE_PASS, "CONFOUNDING_INVENTORY_RESOLVED"

    g9_status, g9_reason = GATE_FAIL, "MINIMUM_SUPPORT_NOT_MET_FOR_INTERVENTION_CELL"
    if accepted_here and int(data.get("aggregate_support_subjects") or 0) >= 100:
        g9_status, g9_reason = GATE_PASS, "AGGREGATE_SUPPORT_MET"

    g10_status, g10_reason = GATE_FAIL, "FUTURE_MODEL_NOT_ELIGIBLE"
    sequential = [
        ("G0_SOURCE_AND_PROVENANCE_IDENTITY", g0, g0_reason),
        ("G1_EXACT_VOCABULARY_MAPPING_IDENTITY", g1, g1_reason),
        ("G2_DOMAIN_ACCEPTANCE", g2, g2_reason),
        ("G3_EXPOSURE_SEMANTIC_ELIGIBILITY", g3, g3_reason),
        ("G4_TEMPORALLY_VALID_T0_START_END", g4_status, g4_reason),
        ("G5_OUTCOME_AND_NATIVE_UNIT_IDENTITY", g5_status, g5_reason),
        ("G6_PRE_POST_OBSERVATION_AVAILABILITY", g6_status, g6_reason),
        ("G7_SUBJECT_DISJOINT_LEAKAGE_SAFE_SPLIT", g7_status, g7_reason),
        ("G8_CONFOUNDING_AND_INDICATION_BIAS_INVENTORY", g8_status, g8_reason),
        ("G9_MINIMUM_AGGREGATE_SUPPORT", g9_status, g9_reason),
    ]
    prior_fail = next((name for name, status, _ in sequential if status != GATE_PASS), None)
    if prior_fail is None and not synthetic_filled:
        g10_status, g10_reason = GATE_PASS, "PRIOR_GATES_PASSED"
    if synthetic_filled:
        g10_status, g10_reason = GATE_FAIL, "SYNTHETIC_OR_DEFAULT_DOSE_ROUTE_DURATION"
    if dose_value is True and route is True and duration is True and dose_unit_interp == "ACCEPTED" and synthetic_filled:
        g10_status, g10_reason = GATE_FAIL, "MISSING_FIELDS_FILLED_WITH_SYNTHETIC_DEFAULTS"

    gates = {name: _gate(status, reason) for name, status, reason in sequential}
    gates["G10_FUTURE_MODEL_ELIGIBILITY"] = _gate(g10_status, g10_reason)

    all_pass = all(g["status"] == GATE_PASS for g in gates.values())
    if domain_count == 0:
        all_pass = False
    ir_eligible = bool(all_pass and accepted_here and tier in IR_ELIGIBLE_TIERS)
    assoc_eligible = bool(ir_eligible and tier == "PRESCRIBED_OR_ORDERED_EXPOSURE")
    admin_eligible = bool(ir_eligible and tier == "DISPENSED_OR_ADMINISTERED_EXPOSURE")
    temporal_eligible = gates["G4_TEMPORALLY_VALID_T0_START_END"]["status"] == GATE_PASS
    return {
        **{k: v for k, v in data.items() if k != "outcome_key"},
        "gates": gates,
        "gate_order": list(GATES),
        "all_gates_pass": all_pass,
        "intervention_response_eligible": ir_eligible,
        "associational_response_eligible": assoc_eligible,
        "administration_conditioned_eligible": admin_eligible,
        "temporally_eligible_intervention": temporal_eligible and ir_eligible,
        "inventory_only": tier == "RECORDED_MEDICATION_ASSOCIATION",
        "confirmed_administration_mapping": bool(
            accepted_here and tier == "DISPENSED_OR_ADMINISTERED_EXPOSURE"
        ),
    }


def build_registry(phase0: dict[str, Any], *, mutations: dict[str, Any] | None = None) -> dict[str, Any]:
    mutations = mutations or {}
    domain_accepted = int(phase0.get("DOMAIN_ACCEPTED_MAPPING_COUNT") or 0)
    if mutations.get("force_domain_accepted_count") is not None:
        domain_accepted = int(mutations["force_domain_accepted_count"])

    a_rows = int(phase0.get("source_a_medication_rows") or 0)
    record_class = str(phase0.get("source_a_record_class") or "RECORDED_MEDICATION_CONTEXT")
    admin_claim = str(phase0.get("source_a_administration_claim") or "NOT_CLAIMED")
    event_field = str(phase0.get("chosen_technical_timestamp_candidate") or "appointment_date")
    event_sem = "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP"
    if mutations.get("appointment_date_as_administration"):
        event_sem = "ADMINISTRATION"
        admin_claim = "CONFIRMED_ADMINISTRATION"

    mapping_status = "unknown"
    mapping_type = "candidate"
    if mutations.get("promote_candidate_mapping"):
        mapping_status = "accepted"
        mapping_type = "domain_accepted"

    vocab = {
        "provider": "UNKNOWN",
        "version": "NOT_ESTABLISHED",
        "status": "unknown",
    }
    if mutations.get("mutate_vocabulary"):
        vocab = {"provider": "MUTATED", "version": "0.0.0-mutated", "status": "unknown"}

    dose_available = False
    route_available = False
    duration_available = False
    synthetic_defaults = False
    if mutations.get("synthetic_dose_route_duration"):
        dose_available = True
        route_available = True
        duration_available = True
        synthetic_defaults = True

    cells: list[dict[str, Any]] = []
    inventory = phase0.get("inventory") or []
    for item in inventory:
        source = SOURCE_B if mutations.get("apply_source_a_mapping_to_b") else str(item.get("source_system") or SOURCE_A)
        outcome_key = str(item.get("outcome_key") or "")
        horizon = int(item.get("horizon_days") or 0)
        unit = str(item.get("native_outcome_unit") or "NOT_ESTABLISHED")
        outcome_digest = public_digest("outcome", source, outcome_key)
        med_digest = public_digest("unmapped_recorded_context_bag", SOURCE_A)
        mapping_digest = public_digest("mapping_evidence", "NO_DOMAIN_ACCEPTED_MAPPING", source)
        tier = classify_tier(
            record_class=record_class,
            mapping_status=mapping_status,
            administration_claim=admin_claim,
            event_time_semantics=event_sem,
        )
        if mutations.get("declare_recorded_as_treatment"):
            tier = "RECORDED_MEDICATION_ASSOCIATION"
        draft = {
            "cell_id": public_digest("cell", source, outcome_digest, horizon),
            "source_system": source,
            "source_local_medication_identity": {
                "kind": "unmapped_recorded_context_bag",
                "public_digest": med_digest,
                "not_a_domain_accepted_mapping": True,
            },
            "source_medication_row_count": a_rows if source == SOURCE_A else int(phase0.get("source_b_medication_rows") or 0),
            "vocabulary": vocab,
            "mapping_provenance": "PUBLISHED_RESIDUAL_INVENTORY_NOT_DOMAIN_REVIEW",
            "mapping_evidence_digest": mapping_digest,
            "mapping_status": mapping_status,
            "mapping_type": mapping_type,
            "exposure_semantic_tier": tier,
            "event_time_field": event_field,
            "event_time_semantics": event_sem,
            "timestamp_precision": "DATE_ONLY_OR_UNVERIFIED",
            "timezone_contract": "NOT_ESTABLISHED",
            "start_available": "NOT_ESTABLISHED",
            "end_available": "NOT_ESTABLISHED",
            "dose_value_available": dose_available,
            "dose_unit_available": bool(phase0.get("medicine_catalog_columns")) and "unit_of_measurement_id" in (
                phase0.get("medicine_catalog_columns") or []
            ),
            "dose_unit_interpretation_status": "NOT_ESTABLISHED",
            "route_available": route_available,
            "form_available": "FK_PRESENT_EMPTY_FORM_TABLE"
            if int(phase0.get("form_table_n_rows") or 0) == 0
            else "NOT_ESTABLISHED",
            "frequency_available": "FK_PRESENT_NOT_CLINICALLY_INTERPRETED",
            "duration_available": duration_available,
            "outcome_identity_digest": outcome_digest,
            "native_outcome_unit": unit,
            "requested_horizon_days": horizon,
            "pre_t0_state_availability": "NOT_ESTABLISHED_FOR_INTERVENTION_T0",
            "post_t0_outcome_availability": "NOT_ESTABLISHED_FOR_INTERVENTION_T0",
            "leakage_boundary": "RESIDUAL_DECLARED_STRICT_POST_T0_NOT_IR_ELIGIBLE",
            "cohort_split_provenance": "REUSED_UIS_V0111_SPLIT_NOT_REOPENED",
            "administration_claim": admin_claim,
            "record_class": record_class,
            "same_day_ambiguity_unresolved": True,
            "polypharmacy_unresolved": True,
            "residual_engine_eligible": False,
            "synthetic_defaults_used": synthetic_defaults,
            "future_outcome_in_pre_t0_features": bool(mutations.get("future_in_pre_t0")),
            "exposure_after_outcome": bool(mutations.get("exposure_after_outcome")),
            "patient_overlap_across_splits": bool(mutations.get("patient_overlap")),
            "recorded_association_declared_treatment_response": bool(
                mutations.get("declare_recorded_as_treatment")
            ),
            "source_a_mapping_applied_to_source_b": bool(mutations.get("apply_source_a_mapping_to_b")),
            "source_or_vocabulary_identity_mutated": bool(mutations.get("mutate_vocabulary")),
            "candidate_promoted_without_evidence": bool(mutations.get("promote_candidate_mapping")),
        }
        cells.append(evaluate_cell(draft, domain_accepted=domain_accepted))

    b_cell = evaluate_cell(
        {
            "cell_id": public_digest("cell", SOURCE_B, "NO_MEDICATION_CONTEXT"),
            "source_system": SOURCE_B,
            "source_local_medication_identity": {
                "kind": "absent",
                "public_digest": public_digest("absent", SOURCE_B),
                "not_a_domain_accepted_mapping": True,
            },
            "source_medication_row_count": int(phase0.get("source_b_medication_rows") or 0),
            "vocabulary": {"provider": "UNKNOWN", "version": "NOT_ESTABLISHED", "status": "unknown"},
            "mapping_provenance": "NO_TRANSFER_FROM_SOURCE_A",
            "mapping_evidence_digest": public_digest("mapping_evidence", "SOURCE_B_ABSENT"),
            "mapping_status": "unknown",
            "mapping_type": "reference_absence",
            "exposure_semantic_tier": "UNKNOWN",
            "event_time_field": "NOT_ESTABLISHED",
            "event_time_semantics": "NOT_ESTABLISHED",
            "timestamp_precision": "NOT_ESTABLISHED",
            "timezone_contract": "NOT_ESTABLISHED",
            "start_available": "NOT_ESTABLISHED",
            "end_available": "NOT_ESTABLISHED",
            "dose_value_available": False,
            "dose_unit_available": False,
            "dose_unit_interpretation_status": "NOT_ESTABLISHED",
            "route_available": False,
            "form_available": "NOT_ESTABLISHED",
            "frequency_available": "NOT_ESTABLISHED",
            "duration_available": False,
            "outcome_identity_digest": None,
            "native_outcome_unit": None,
            "requested_horizon_days": None,
            "pre_t0_state_availability": "NOT_ESTABLISHED",
            "post_t0_outcome_availability": "NOT_ESTABLISHED",
            "leakage_boundary": "NOT_ESTABLISHED",
            "cohort_split_provenance": "NOT_ESTABLISHED",
            "administration_claim": "NOT_CLAIMED",
            "record_class": None,
            "same_day_ambiguity_unresolved": True,
            "source_a_mapping_applied_to_source_b": bool(mutations.get("apply_source_a_mapping_to_b")),
            "source_or_vocabulary_identity_mutated": bool(mutations.get("mutate_vocabulary")),
        },
        domain_accepted=domain_accepted,
    )
    cells.append(b_cell)

    if domain_accepted == 0:
        for cell in cells:
            cell["intervention_response_eligible"] = False
            cell["associational_response_eligible"] = False
            cell["administration_conditioned_eligible"] = False
            cell["temporally_eligible_intervention"] = False
            cell["confirmed_administration_mapping"] = False

    ir_n = sum(1 for c in cells if c.get("intervention_response_eligible"))
    assoc_n = sum(1 for c in cells if c.get("associational_response_eligible"))
    admin_n = sum(1 for c in cells if c.get("administration_conditioned_eligible"))
    temporal_n = sum(1 for c in cells if c.get("temporally_eligible_intervention"))
    admin_map_n = sum(1 for c in cells if c.get("confirmed_administration_mapping"))
    inventory_n = sum(1 for c in cells if c.get("inventory_only"))
    return {
        "version": VERSION,
        "INTERVENTION_EVIDENCE_REGISTRY_STATUS": "BUILT",
        "mapping_classes": {
            "reference_mapping": "vocabulary_or_absence_record_not_accepted",
            "candidate_mapping": "unreviewed_or_algorithmic_not_accepted",
            "domain_accepted_mapping": "human_or_domain_review_accepted_only",
        },
        "DOMAIN_ACCEPTED_MAPPING_COUNT": domain_accepted,
        "CONFIRMED_ADMINISTRATION_MAPPING_COUNT": admin_map_n,
        "TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT": temporal_n,
        "ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT": assoc_n,
        "ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT": admin_n,
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": ir_n,
        "RECORDED_ASSOCIATION_INVENTORY_CELL_COUNT": inventory_n,
        "n_cells": len(cells),
        "cells": cells,
        "public_fields_only": True,
        "source_medication_names_published": False,
        "patient_identifiers_published": False,
    }


def consumption_decision(phase0: dict[str, Any]) -> dict[str, Any]:
    val_n = int(phase0.get("VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT") or 0)
    held_n = int(phase0.get("HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT") or 0)
    eng_n = int(phase0.get("ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT") or 0)
    listed = int(phase0.get("residual_engine_eligible_listed") or 0)
    incremental = str(phase0.get("INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS") or "")
    foundation = str(phase0.get("MEDICATION_RESIDUAL_FOUNDATION_STATUS") or "")
    runtime_not_consumed = foundation in {
        "NOT_CONSUMED_NOT_ACCEPTED",
        "EVALUATED_NOT_ACCEPTED_NO_INCREMENTAL_SIGNAL",
    } or "NOT_CONSUMED" in foundation
    consume = val_n > 0 and held_n > 0 and eng_n > 0 and listed > 0
    status = "CONSUMED" if consume else "NOT_CONSUMED"
    if not consume and runtime_not_consumed:
        status = "NOT_CONSUMED"
    return {
        "MEDICATION_RESIDUAL_CONSUMPTION_STATUS": status,
        "validation_accepted_cell_count": val_n,
        "heldout_confirmed_cell_count": held_n,
        "engine_eligible_cell_count": eng_n,
        "engine_eligible_listed_from_public_registry": listed,
        "incremental_signal_status": incremental,
        "feature_contract": "NOT_CONSUMED_IN_RUNTIME",
        "applicability_contract": "NO_ENGINE_ELIGIBLE_ACCEPTED_CELL",
        "source_identity": SOURCE_A,
        "exposure_semantic_limitation": "RECORDED_MEDICATION_ASSOCIATION_ONLY",
        "runtime_foundation_status": foundation,
        "heldout_reopened": False,
        "computed_not_handwritten": True,
        "reasons": [
            r
            for r in (
                None if val_n == 0 else None,
                "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT=0" if val_n == 0 else None,
                "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT=0" if held_n == 0 else None,
                "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT=0" if eng_n == 0 else None,
                f"INCREMENTAL_STATUS={incremental}" if incremental else None,
                f"FOUNDATION={foundation}" if foundation else None,
            )
            if r
        ],
    }


def temporal_audit(phase0: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    event_field = str(phase0.get("chosen_technical_timestamp_candidate") or "appointment_date")
    blocks = [
        {
            "issue": "technical_timestamp_as_t0",
            "field": event_field,
            "status": "BLOCK",
            "reason": "appointment_date_created_modified_are_not_administration_without_direct_evidence",
        },
        {"issue": "timezone_aware_timestamps", "status": "BLOCK", "reason": "TIMEZONE_CONTRACT_NOT_ESTABLISHED"},
        {"issue": "date_only_precision", "status": "BLOCK", "reason": "DATE_ONLY_OR_UNVERIFIED"},
        {"issue": "ambiguous_ordering", "status": "BLOCK", "reason": "NOT_ESTABLISHED"},
        {"issue": "same_day_ambiguity", "status": "BLOCK", "reason": "UNRESOLVED"},
        {"issue": "exposure_after_outcome", "status": "NOT_ESTABLISHED", "reason": "NO_VERIFIED_ADMINISTRATION_T0"},
        {"issue": "exposure_overlapping_target_horizon", "status": "NOT_ESTABLISHED", "reason": "NO_VERIFIED_START_END"},
        {"issue": "future_information_in_features", "status": "BLOCK", "reason": "INTERVENTION_T0_NOT_ESTABLISHED"},
        {"issue": "repeated_outcomes_target_reuse", "status": "NOT_ESTABLISHED", "reason": "NO_IR_CELL"},
        {"issue": "patient_overlap_between_splits", "status": "NOT_ESTABLISHED", "reason": "IR_SPLIT_NOT_OPENED"},
        {
            "issue": "polypharmacy_simultaneous_recorded_medicines",
            "status": "BLOCK",
            "reason": "UNRESOLVED",
            "published_aggregate_patient_days_gt1": phase0.get("polypharmacy_patient_days_gt1"),
        },
    ]
    temporally_eligible = int(registry.get("TEMPORALLY_ELIGIBLE_INTERVENTION_CELL_COUNT") or 0)
    return {
        "TEMPORAL_ELIGIBILITY_STATUS": "BLOCKED" if temporally_eligible == 0 else "READY",
        "appointment_date_semantics": "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP",
        "administration_timestamp_verified": False,
        "clinical_event_time_status": phase0.get("clinical_event_time_status"),
        "live_row_recount_status": (phase0.get("materialized") or {}).get("live_row_recount_status"),
        "unresolved_ambiguity_blocks_readiness_lanes": True,
        "temporally_eligible_intervention_cell_count": temporally_eligible,
        "checks": blocks,
    }


def confounding_inventory(phase0: dict[str, Any]) -> dict[str, Any]:
    published = phase0.get("confounding") or {}
    items = {
        "indication_confounding": published.get("indication_confounding") or "UNRESOLVED",
        "care_intensity_confounding": published.get("care_intensity_confounding") or "UNRESOLVED",
        "measurement_scheduling": published.get("measurement_scheduling") or "UNRESOLVED",
        "prevalent_vs_incident_context_ambiguity": published.get("prevalent_vs_incident_context_ambiguity")
        or "UNRESOLVED",
        "adherence_unknown": published.get("adherence_unknown", True),
        "dose_route_duration_missingness": published.get("dose_route_duration_missingness", True),
        "recorded_recommendation_vs_administration_ambiguity": published.get(
            "recorded_recommendation_vs_administration_ambiguity", True
        ),
        "statistical_signal_does_not_remove_these": published.get("statistical_signal_does_not_remove_these", True),
        "not_pharmacological_effect": published.get("not_pharmacological_effect", True),
        "source_b_transfer_confounding": "NOT_APPLICABLE_NO_TRANSFER",
    }
    unresolved = [
        key
        for key, value in items.items()
        if value in {True, "UNRESOLVED"} or (isinstance(value, str) and value.startswith("UNRESOLVED"))
    ]
    return {
        "CONFUNDING_INVENTORY_STATUS": "UNRESOLVED",
        "causal_readiness": "NOT_ESTABLISHED",
        "associational_does_not_raise_causal": True,
        "items": items,
        "unresolved_keys": unresolved,
        "evidence_source": "artifacts/stage-03-first-source-aware-medication-residual-foundation-v0.1/confounding-inventory.json",
    }


def source_readiness(registry: dict[str, Any], source: str, phase0: dict[str, Any]) -> dict[str, Any]:
    cells = [c for c in registry.get("cells") or [] if c.get("source_system") == source]
    ir_n = sum(1 for c in cells if c.get("intervention_response_eligible"))
    if source == SOURCE_B:
        status = "NOT_READY"
        reason = "SOURCE_B_MEDICATION_CONTEXT_NOT_AVAILABLE_NO_TRANSFER"
    else:
        status = "NOT_READY" if ir_n == 0 else "READY"
        reason = "DOMAIN_ACCEPTED_MAPPING_COUNT=0" if int(registry.get("DOMAIN_ACCEPTED_MAPPING_COUNT") or 0) == 0 else (
            "NO_INTERVENTION_RESPONSE_ELIGIBLE_CELL" if ir_n == 0 else "ELIGIBLE_CELL_PRESENT"
        )
    return {
        "source_system": source,
        "readiness_status": status,
        "reason": reason,
        "n_candidate_cells": len(cells),
        "intervention_response_eligible_cell_count": ir_n,
        "medication_row_count_published": (
            phase0.get("source_a_medication_rows") if source == SOURCE_A else phase0.get("source_b_medication_rows")
        ),
        "record_class": phase0.get("source_a_record_class") if source == SOURCE_A else None,
        "mapping_transfer_from_other_source": False,
        "lanes": {
            "descriptive_recorded_association": "INVENTORIED_NOT_INTERVENTION_RESPONSE"
            if source == SOURCE_A
            else "NOT_AVAILABLE",
            "prescribed_ordered_associational": "NOT_READY",
            "administration_conditioned": "NOT_READY",
            "causal": "NOT_ESTABLISHED",
        },
    }


def summarize_gates(registry: dict[str, Any]) -> dict[str, Any]:
    cases = []
    for cell in registry.get("cells") or []:
        cases.append(
            {
                "cell_id": cell.get("cell_id"),
                "source_system": cell.get("source_system"),
                "mapping_status": cell.get("mapping_status"),
                "exposure_semantic_tier": cell.get("exposure_semantic_tier"),
                "intervention_response_eligible": cell.get("intervention_response_eligible"),
                "gates": cell.get("gates"),
            }
        )
    fail_counts: dict[str, int] = {g: 0 for g in GATES}
    for cell in registry.get("cells") or []:
        for name, payload in (cell.get("gates") or {}).items():
            if payload.get("status") != GATE_PASS:
                fail_counts[name] = fail_counts.get(name, 0) + 1
    return {
        "version": VERSION,
        "n_cases": len(cases),
        "gate_fail_counts": fail_counts,
        "cases": cases,
        "note": "Recorded-association cases are technical inventory, not intervention-response eligible.",
    }


def lanes_from_registry(registry: dict[str, Any]) -> dict[str, Any]:
    domain_n = int(registry.get("DOMAIN_ACCEPTED_MAPPING_COUNT") or 0)
    ir_n = int(registry.get("INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT") or 0)
    if domain_n == 0:
        readiness = "NOT_READY"
        ir_n = 0
    elif ir_n == 0:
        readiness = "NOT_READY"
    else:
        readiness = "READY"
    return {
        "descriptive_recorded_association": {
            "status": "INVENTORIED_NOT_INTERVENTION_RESPONSE",
            "counts_as_intervention_response": False,
            "cell_count": int(registry.get("RECORDED_ASSOCIATION_INVENTORY_CELL_COUNT") or 0),
        },
        "prescribed_ordered_associational": {
            "status": "NOT_READY",
            "cell_count": int(registry.get("ASSOCIATIONAL_RESPONSE_ELIGIBLE_CELL_COUNT") or 0),
        },
        "administration_conditioned": {
            "status": "NOT_READY",
            "cell_count": int(registry.get("ADMINISTRATION_CONDITIONED_RESPONSE_ELIGIBLE_CELL_COUNT") or 0),
        },
        "causal": {
            "status": "NOT_ESTABLISHED",
            "cell_count": 0,
            "associational_does_not_raise_causal": True,
        },
        "INTERVENTION_RESPONSE_READINESS_STATUS": readiness,
        "INTERVENTION_RESPONSE_ELIGIBLE_CELL_COUNT": ir_n,
        "exposure_contract": exposure_contract()["promotion"],
    }
