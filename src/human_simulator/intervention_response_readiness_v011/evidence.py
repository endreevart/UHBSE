"""Fail-closed Phase 0 loader.

Positive clinical claims are emitted only when a verified snapshot contains the field.
Missing evidence stays NOT_ESTABLISHED. It is not replaced by a boolean default.
"""

from __future__ import annotations

from typing import Any

from human_simulator.intervention_response_readiness_v011.policy import SOURCE_A, SOURCE_B, VERSION
from human_simulator.intervention_response_readiness_v011.snapshots import load_snapshot_documents, verify_snapshots

NOT_ESTABLISHED = "NOT_ESTABLISHED"


def handwritten_literals(provenance: list[dict[str, Any]]) -> bool:
    return any(item.get("origin") == "code_literal" for item in provenance)


def _note(provenance: list[dict[str, Any]], field: str, origin: str, source: str | None, key: str) -> None:
    provenance.append({"field": field, "origin": origin, "source": source, "key": key})


def _doc_ok(doc: Any) -> bool:
    return isinstance(doc, dict) and not doc.get("_missing") and not doc.get("_sha_mismatch") and doc.get("_verified") is True


def take(doc: Any, key: str, provenance: list[dict[str, Any]], field: str) -> tuple[Any, bool]:
    if not _doc_ok(doc) or key not in doc:
        source = doc.get("_source_key") if isinstance(doc, dict) else None
        _note(provenance, field, "missing_evidence", source, key)
        return NOT_ESTABLISHED, False
    _note(provenance, field, "evidence", doc.get("_source_key"), key)
    return doc[key], True


def take_path(doc: Any, path: list[str], provenance: list[dict[str, Any]], field: str) -> tuple[Any, bool]:
    if not _doc_ok(doc):
        _note(provenance, field, "missing_evidence", None, ".".join(path))
        return NOT_ESTABLISHED, False
    current: Any = doc
    for part in path:
        if not isinstance(current, dict) or part not in current:
            _note(provenance, field, "missing_evidence", doc.get("_source_key"), ".".join(path))
            return NOT_ESTABLISHED, False
        current = current[part]
    _note(provenance, field, "evidence", doc.get("_source_key"), ".".join(path))
    return current, True


def _fallback(primary: tuple[Any, bool], secondary: tuple[Any, bool]) -> tuple[Any, bool]:
    if primary[1]:
        return primary
    if secondary[1]:
        return secondary
    return NOT_ESTABLISHED, False


def _derive(ok: bool, value: Any, provenance: list[dict[str, Any]], field: str, key: str) -> Any:
    if not ok:
        _note(provenance, field, "missing_evidence", None, key)
        return NOT_ESTABLISHED
    _note(provenance, field, "derived_from_evidence", None, key)
    return value


def _unit_from_outcome_key(outcome_key: str) -> str:
    parts = str(outcome_key).split("::")
    return parts[-1] if parts else NOT_ESTABLISHED


def build_phase0(docs: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    provenance: list[dict[str, Any]] = []
    irr = docs.get("irr_v016_status") or {"_missing": True}
    protocol = docs.get("irr_v016_protocol") or {"_missing": True}
    medres = docs.get("medres_status") or {"_missing": True}
    cells_doc = docs.get("medres_cells") or {"_missing": True}
    accounting = docs.get("medres_accounting") or {"_missing": True}
    schema = docs.get("pop_schema") or {"_missing": True}
    time_sem = docs.get("pop_time") or {"_missing": True}
    status_sem = docs.get("pop_status_sem") or {"_missing": True}
    hierarchy = docs.get("pop_hierarchy") or {"_missing": True}
    confounding = docs.get("medres_confounding") or {"_missing": True}

    domain, domain_ok = _fallback(
        take(irr, "DOMAIN_ACCEPTED_MAPPING_COUNT", provenance, "DOMAIN_ACCEPTED_MAPPING_COUNT"),
        take(medres, "DOMAIN_ACCEPTED_MAPPING_COUNT", provenance, "DOMAIN_ACCEPTED_MAPPING_COUNT_MEDRES"),
    )
    encoder, encoder_ok = _fallback(
        take(irr, "STATE_ENCODER_STATUS", provenance, "STATE_ENCODER_STATUS"),
        take(medres, "STATE_ENCODER_STATUS", provenance, "STATE_ENCODER_STATUS_MEDRES"),
    )
    foundation, foundation_ok = _fallback(
        take(irr, "MEDICATION_RESIDUAL_FOUNDATION_STATUS", provenance, "MEDICATION_RESIDUAL_FOUNDATION_STATUS"),
        take(medres, "MEDICATION_RESIDUAL_FOUNDATION_STATUS", provenance, "MEDICATION_RESIDUAL_FOUNDATION_STATUS_MEDRES"),
    )
    timestamp_sem, timestamp_ok = take(
        medres, "MEDICATION_TIMESTAMP_SEMANTICS_STATUS", provenance, "MEDICATION_TIMESTAMP_SEMANTICS_STATUS"
    )
    source_a_context, _ = take(medres, "SOURCE_A_MEDICATION_CONTEXT_STATUS", provenance, "SOURCE_A_MEDICATION_CONTEXT_STATUS")
    source_b_context, source_b_ok = take(
        medres, "SOURCE_B_MEDICATION_CONTEXT_STATUS", provenance, "SOURCE_B_MEDICATION_CONTEXT_STATUS"
    )
    appointment_flag, appointment_ok = take(
        medres, "appointment_date_not_administration", provenance, "appointment_date_not_administration"
    )
    mapping_accepted, mapping_ok = take(protocol, "mapping_accepted", provenance, "mapping_accepted")
    iros, _ = take(protocol, "IROS_PROVIDER_COMMITMENT_STATUS", provenance, "IROS_PROVIDER_COMMITMENT_STATUS")
    contact, contact_ok = take(protocol, "AUTOMATED_EXTERNAL_CONTACT_STATUS", provenance, "AUTOMATED_EXTERNAL_CONTACT_STATUS")
    val_n, val_ok = take(medres, "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT", provenance, "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT")
    held_n, held_ok = take(
        medres, "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT", provenance, "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT"
    )
    eng_n, eng_ok = take(medres, "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT", provenance, "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT")
    incremental, inc_ok = take(
        medres, "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS", provenance, "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS"
    )
    usable, _ = take(
        medres,
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT",
        provenance,
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT",
    )
    human_n, _ = take(medres, "HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT", provenance, "HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT")
    chosen, chosen_ok = take(time_sem, "chosen_technical_timestamp_candidate", provenance, "chosen_technical_timestamp_candidate")
    clinical, clinical_ok = take(time_sem, "clinical_event_time_status", provenance, "clinical_event_time_status")
    record_class, record_ok = take_path(
        accounting, ["by_source", "A", "record_class"], provenance, "source_a_record_class"
    )
    admin_claim, admin_ok = take_path(
        accounting, ["by_source", "A", "administration_claim"], provenance, "source_a_administration_claim"
    )
    rows_a, rows_a_ok = take_path(accounting, ["by_source", "A", "medication_rows"], provenance, "source_a_medication_rows")
    rows_b, rows_b_ok = take_path(accounting, ["by_source", "B", "medication_rows"], provenance, "source_b_medication_rows")
    appt_cols, appt_ok = take_path(
        schema,
        ["tables_present", "diagnosis_medicineappointments", "columns"],
        provenance,
        "appointment_columns",
    )
    med_cols, med_cols_ok = take_path(
        schema, ["tables_present", "diagnosis_medicines", "columns"], provenance, "medicine_catalog_columns"
    )
    form_n, form_ok = take_path(
        schema, ["tables_present", "diagnosis_medicinesform", "n_rows"], provenance, "form_table_n_rows"
    )
    transition, _ = take(status_sem, "default_transition_label", provenance, "status_default_transition_label")
    level5, _ = take_path(
        hierarchy,
        ["levels", "level_5_intervention_associated_modeling_episodes"],
        provenance,
        "level5_intervention_associated_modeling_episodes",
    )
    poly, _ = take_path(
        hierarchy,
        ["overlap_polypharmacy", "patient_days_with_gt1_distinct_medicine_id"],
        provenance,
        "polypharmacy_patient_days_gt1",
    )
    cells, cells_ok = take(cells_doc, "cells", provenance, "residual_cells")

    inventory: list[dict[str, Any]] = []
    engine_listed = NOT_ESTABLISHED
    if cells_ok and isinstance(cells, list):
        seen: set[tuple[str, str, int]] = set()
        engine_listed = 0
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            if cell.get("engine_eligible") is True:
                engine_listed += 1
            source = str(cell.get("source_system") or "")
            outcome = str(cell.get("outcome_key") or "")
            try:
                horizon = int(cell.get("horizon_days") or 0)
            except (TypeError, ValueError):
                continue
            identity = (source, outcome, horizon)
            if identity in seen:
                continue
            seen.add(identity)
            inventory.append(
                {
                    "source_system": source,
                    "outcome_key": outcome,
                    "native_outcome_unit": _unit_from_outcome_key(outcome),
                    "horizon_days": horizon,
                    "residual_engine_eligible": bool(cell.get("engine_eligible")),
                    "residual_validation_status": cell.get("validation_status"),
                    "residual_heldout_status": cell.get("heldout_status"),
                    "residual_reason": cell.get("reason"),
                    "residual_cell_id_sha256": cell.get("cell_id_sha256"),
                }
            )
        _note(provenance, "inventory", "derived_from_evidence", "medres_cells", "cells")
    else:
        _note(provenance, "inventory", "missing_evidence", "medres_cells", "cells")

    dose_columns: Any = NOT_ESTABLISHED
    if appt_ok and med_cols_ok and isinstance(appt_cols, list) and isinstance(med_cols, list):
        dose_columns = [col for col in list(appt_cols) + list(med_cols) if "dose" in str(col).lower() or "route" in str(col).lower()]
        _note(provenance, "dose_or_route_columns", "derived_from_evidence", "pop_schema", "columns")
    else:
        _note(provenance, "dose_or_route_columns", "missing_evidence", "pop_schema", "columns")

    semantics_inputs_ok = chosen_ok and clinical_ok and appointment_ok and timestamp_ok
    if (
        semantics_inputs_ok
        and chosen == "appointment_date"
        and clinical == "CANDIDATE_ONLY"
        and appointment_flag is True
        and timestamp_sem == "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP"
    ):
        appointment_semantics = _derive(True, "CANDIDATE_TECHNICAL_EVENT_TIMESTAMP", provenance, "appointment_date_semantics", "derived")
    else:
        appointment_semantics = _derive(False, None, provenance, "appointment_date_semantics", "derived")

    verified_admin_time = _derive(
        semantics_inputs_ok,
        False if semantics_inputs_ok and clinical == "CANDIDATE_ONLY" else NOT_ESTABLISHED,
        provenance,
        "verified_administration_or_dispense_or_ingest_timestamp",
        "clinical_event_time_status",
    )
    if not semantics_inputs_ok:
        verified_admin_time = NOT_ESTABLISHED

    dose_confirmed = _derive(
        isinstance(dose_columns, list),
        False if isinstance(dose_columns, list) and len(dose_columns) == 0 else NOT_ESTABLISHED,
        provenance,
        "dose_value_confirmed",
        "dose_or_route_columns",
    )
    route_confirmed = _derive(
        isinstance(dose_columns, list),
        False if isinstance(dose_columns, list) and len(dose_columns) == 0 else NOT_ESTABLISHED,
        provenance,
        "route_confirmed",
        "dose_or_route_columns",
    )
    fk_interpreted = _derive(
        form_ok and med_cols_ok,
        False if form_ok and med_cols_ok else NOT_ESTABLISHED,
        provenance,
        "unit_form_frequency_fk_clinically_interpreted",
        "form_id",
    )
    not_prescription = _derive(
        record_ok,
        True if record_class == "RECORDED_MEDICATION_CONTEXT" else False,
        provenance,
        "not_prescription",
        "record_class",
    )
    not_administration = _derive(
        admin_ok,
        True if admin_claim == "NOT_CLAIMED" else False,
        provenance,
        "not_administration",
        "administration_claim",
    )
    transfer = _derive(
        source_b_ok,
        False if source_b_context == "NOT_AVAILABLE_NO_TRANSFER" else NOT_ESTABLISHED,
        provenance,
        "source_b_created_by_source_a_transfer",
        "SOURCE_B_MEDICATION_CONTEXT_STATUS",
    )

    _note(provenance, "live_row_recount_status", "policy_exclusion", None, "parquet_not_an_evidence_source")
    required_ok = all(
        (
            domain_ok,
            encoder_ok,
            foundation_ok,
            timestamp_ok,
            record_ok,
            admin_ok,
            rows_a_ok,
            rows_b_ok,
            chosen_ok,
            clinical_ok,
            appointment_ok,
            mapping_ok,
            val_ok,
            held_ok,
            eng_ok,
            inc_ok,
            cells_ok,
            appt_ok,
            contact_ok,
        )
    )
    files_missing = list(verification.get("evidence_files_missing") or [])
    verified = bool(verification.get("ok")) and required_ok and not files_missing
    handwritten = handwritten_literals(provenance)
    computed = bool(verified and not handwritten)
    if not verified:
        computed = False

    phase0 = {
        "DOMAIN_ACCEPTED_MAPPING_COUNT": domain if domain_ok else NOT_ESTABLISHED,
        "STATE_ENCODER_STATUS": encoder if encoder_ok else NOT_ESTABLISHED,
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": foundation if foundation_ok else NOT_ESTABLISHED,
        "MEDICATION_TIMESTAMP_SEMANTICS_STATUS": timestamp_sem,
        "SOURCE_A_MEDICATION_CONTEXT_STATUS": source_a_context,
        "SOURCE_B_MEDICATION_CONTEXT_STATUS": source_b_context,
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT": usable,
        "HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT": human_n,
        "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT": val_n if val_ok else NOT_ESTABLISHED,
        "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT": held_n if held_ok else NOT_ESTABLISHED,
        "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT": eng_n if eng_ok else NOT_ESTABLISHED,
        "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS": incremental,
        "appointment_date_not_administration": appointment_flag if appointment_ok else NOT_ESTABLISHED,
        "mapping_accepted": mapping_accepted if mapping_ok else NOT_ESTABLISHED,
        "IROS_PROVIDER_COMMITMENT_STATUS": iros,
        "AUTOMATED_EXTERNAL_CONTACT_STATUS": contact if contact_ok else NOT_ESTABLISHED,
        "chosen_technical_timestamp_candidate": chosen if chosen_ok else NOT_ESTABLISHED,
        "clinical_event_time_status": clinical if clinical_ok else NOT_ESTABLISHED,
        "appointment_date_semantics": appointment_semantics,
        "appointment_columns": appt_cols if appt_ok else NOT_ESTABLISHED,
        "medicine_catalog_columns": med_cols if med_cols_ok else NOT_ESTABLISHED,
        "dose_or_route_columns": dose_columns,
        "form_table_n_rows": form_n if form_ok else NOT_ESTABLISHED,
        "status_default_transition_label": transition,
        "level5_intervention_associated_modeling_episodes": level5,
        "polypharmacy_patient_days_gt1": poly,
        "confounding": (
            {key: value for key, value in confounding.items() if not str(key).startswith("_")}
            if _doc_ok(confounding)
            else {}
        ),
        "confounding_verified": _doc_ok(confounding),
        "residual_engine_eligible_listed": engine_listed,
        "inventory": inventory,
        "source_a": SOURCE_A,
        "source_b": SOURCE_B,
        "source_a_medication_rows": rows_a if rows_a_ok else NOT_ESTABLISHED,
        "source_a_record_class": record_class if record_ok else NOT_ESTABLISHED,
        "source_a_administration_claim": admin_claim if admin_ok else NOT_ESTABLISHED,
        "source_b_medication_rows": rows_b if rows_b_ok else NOT_ESTABLISHED,
        "evidence_files_missing": files_missing,
        "evidence_sha_verified": bool(verification.get("ok")),
        "computed_from_published_artifacts": computed,
        "handwritten_literals": handwritten,
        "required_fields_established": required_ok,
        "not_prescription": not_prescription,
        "not_administration": not_administration,
        "dose_value_confirmed": dose_confirmed,
        "route_confirmed": route_confirmed,
        "unit_form_frequency_fk_clinically_interpreted": fk_interpreted,
        "verified_administration_or_dispense_or_ingest_timestamp": verified_admin_time,
        "source_b_created_by_source_a_transfer": transfer,
        "materialized": {
            "live_row_recount_status": "NOT_RUN_SOURCE_UNAVAILABLE",
            "private_parquet_consulted": False,
            "reason": "PARQUET_NOT_PACKED_AND_NOT_USED_AS_EVIDENCE",
        },
        "provenance": provenance,
        "provenance_origin_counts": _origin_counts(provenance),
    }
    return phase0


def _origin_counts(provenance: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in provenance:
        origin = str(item.get("origin") or "unknown")
        counts[origin] = counts.get(origin, 0) + 1
    return counts


def gaps_from_phase0(phase0: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": VERSION,
        "DOMAIN_ACCEPTED_MAPPING_COUNT": phase0.get("DOMAIN_ACCEPTED_MAPPING_COUNT"),
        "medication_record_class": phase0.get("source_a_record_class"),
        "not_prescription": phase0.get("not_prescription"),
        "not_administration": phase0.get("not_administration"),
        "appointment_date_semantics": phase0.get("appointment_date_semantics"),
        "appointment_date_not_administration": phase0.get("appointment_date_not_administration"),
        "verified_administration_or_dispense_or_ingest_timestamp": phase0.get(
            "verified_administration_or_dispense_or_ingest_timestamp"
        ),
        "dose_value_confirmed": phase0.get("dose_value_confirmed"),
        "route_confirmed": phase0.get("route_confirmed"),
        "dose_or_route_columns": phase0.get("dose_or_route_columns"),
        "unit_form_frequency_fk_clinically_interpreted": phase0.get(
            "unit_form_frequency_fk_clinically_interpreted"
        ),
        "form_table_n_rows": phase0.get("form_table_n_rows"),
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": phase0.get("MEDICATION_RESIDUAL_FOUNDATION_STATUS"),
        "engine_eligible_accepted_medication_residual_cells": phase0.get("ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT"),
        "engine_eligible_listed": phase0.get("residual_engine_eligible_listed"),
        "STATE_ENCODER_STATUS": phase0.get("STATE_ENCODER_STATUS"),
        "SOURCE_B_MEDICATION_CONTEXT_STATUS": phase0.get("SOURCE_B_MEDICATION_CONTEXT_STATUS"),
        "source_b_created_by_source_a_transfer": phase0.get("source_b_created_by_source_a_transfer"),
        "mapping_accepted": phase0.get("mapping_accepted"),
        "IROS_PROVIDER_COMMITMENT_STATUS": phase0.get("IROS_PROVIDER_COMMITMENT_STATUS"),
        "live_row_recount_status": (phase0.get("materialized") or {}).get("live_row_recount_status"),
        "evidence_files_missing": phase0.get("evidence_files_missing") or [],
        "evidence_sha_verified": phase0.get("evidence_sha_verified"),
        "computed_from_published_artifacts": phase0.get("computed_from_published_artifacts"),
        "handwritten_literals": phase0.get("handwritten_literals"),
        "provenance_origin_counts": phase0.get("provenance_origin_counts"),
        "required_fields_established": phase0.get("required_fields_established"),
    }


def load_published_evidence(root: Any) -> dict[str, Any]:
    from pathlib import Path

    root = Path(root)
    verification = verify_snapshots(root)
    docs = load_snapshot_documents(root, verification)
    phase0 = build_phase0(docs, verification)
    return {
        "ok": bool(phase0.get("computed_from_published_artifacts")),
        "verification": verification,
        "phase0": phase0,
        "raw_missing": list(phase0.get("evidence_files_missing") or []),
    }
