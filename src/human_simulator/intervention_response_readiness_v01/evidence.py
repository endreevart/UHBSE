"""Load Phase 0 unreadiness from published artifacts and registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.intervention_response_readiness_v01.policy import (
    EVIDENCE_PATHS,
    MATERIALIZED_DIR,
    SOURCE_A,
    SOURCE_B,
)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"_missing": True, "path": path.as_posix()}
    return json.loads(path.read_text(encoding="utf-8"))


def _unit_from_outcome_key(outcome_key: str) -> str:
    parts = str(outcome_key).split("::")
    return parts[-1] if parts else "NOT_ESTABLISHED"


def materialized_probe(root: Path) -> dict[str, Any]:
    folder = root / MATERIALIZED_DIR
    parquets = sorted(p.name for p in folder.glob("*.parquet")) if folder.is_dir() else []
    manifest = folder / "materialization-manifest.json"
    if not parquets:
        status = "NOT_RUN_SOURCE_UNAVAILABLE"
    else:
        status = "AVAILABLE_NOT_QUERIED_PUBLISHED_AGGREGATES_AUTHORITATIVE"
    return {
        "live_row_recount_status": status,
        "materialized_dir_exists": folder.is_dir(),
        "materialized_parquet_count": len(parquets),
        "materialization_manifest_present": manifest.is_file(),
        "synthetic_substitute": False,
        "note": (
            "Private parquet was not substituted with synthetic rows. "
            "Phase 0 uses published aggregate artifacts."
        ),
    }


def load_published_evidence(root: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = {}
    missing: list[str] = []
    for key, rel in EVIDENCE_PATHS.items():
        path = root / rel
        doc = _load_json(path)
        loaded[key] = doc
        if doc.get("_missing"):
            missing.append(rel)

    irr = loaded["irr_v016_status"]
    protocol = loaded["irr_v016_protocol"]
    medres = loaded["medres_status"]
    cells_doc = loaded["medres_cells"]
    accounting = loaded["medres_accounting"]
    schema = loaded["pop_schema"]
    time_sem = loaded["pop_time"]
    status_sem = loaded["pop_status_sem"]
    hierarchy = loaded["pop_hierarchy"]
    confounding = loaded["medres_confounding"]

    cells = cells_doc.get("cells") or []
    engine_eligible = [c for c in cells if c.get("engine_eligible") is True]
    unique_inventory: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for cell in cells:
        source = str(cell.get("source_system") or "")
        outcome = str(cell.get("outcome_key") or "")
        horizon = int(cell.get("horizon_days") or 0)
        key = (source, outcome, horizon)
        if key in seen:
            continue
        seen.add(key)
        unique_inventory.append(
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

    appt_cols = ((schema.get("tables_present") or {}).get("diagnosis_medicineappointments") or {}).get(
        "columns"
    ) or []
    med_cols = ((schema.get("tables_present") or {}).get("diagnosis_medicines") or {}).get("columns") or []
    form_n = int(
        (((schema.get("tables_present") or {}).get("diagnosis_medicinesform") or {}).get("n_rows") or 0)
    )
    dose_like = [c for c in appt_cols + med_cols if "dose" in str(c).lower() or "route" in str(c).lower()]

    by_source = accounting.get("by_source") or accounting.get("sources") or {}
    source_a_acc = by_source.get("A") or by_source.get("source_a") or {}
    source_b_acc = by_source.get("B") or by_source.get("source_b") or {}
    if not source_a_acc and "medication_rows" in accounting:
        source_a_acc = accounting

    # Accounting file may be nested; keep bounded aggregates only.
    def _count(block: dict[str, Any], *keys: str, default: int = 0) -> int:
        for key in keys:
            if key in block and isinstance(block[key], int):
                return int(block[key])
        return default

    phase0 = {
        "DOMAIN_ACCEPTED_MAPPING_COUNT": int(
            irr.get("DOMAIN_ACCEPTED_MAPPING_COUNT", medres.get("DOMAIN_ACCEPTED_MAPPING_COUNT", 0)) or 0
        ),
        "STATE_ENCODER_STATUS": irr.get("STATE_ENCODER_STATUS") or medres.get("STATE_ENCODER_STATUS") or "NOT_ACCEPTED",
        "MEDICATION_RESIDUAL_FOUNDATION_STATUS": irr.get("MEDICATION_RESIDUAL_FOUNDATION_STATUS")
        or medres.get("MEDICATION_RESIDUAL_FOUNDATION_STATUS"),
        "MEDICATION_TIMESTAMP_SEMANTICS_STATUS": medres.get("MEDICATION_TIMESTAMP_SEMANTICS_STATUS")
        or time_sem.get("clinical_event_time_status"),
        "SOURCE_A_MEDICATION_CONTEXT_STATUS": medres.get("SOURCE_A_MEDICATION_CONTEXT_STATUS"),
        "SOURCE_B_MEDICATION_CONTEXT_STATUS": medres.get("SOURCE_B_MEDICATION_CONTEXT_STATUS"),
        "SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT": int(
            medres.get("SCIENTIFICALLY_USABLE_ACCEPTED_DRUG_CONCEPT_COUNT") or 0
        ),
        "HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT": int(medres.get("HUMAN_ACCEPTED_DRUG_CONCEPT_COUNT") or 0),
        "VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT": int(
            medres.get("VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT")
            or cells_doc.get("VALIDATION_ACCEPTED_RESIDUAL_CELL_COUNT")
            or 0
        ),
        "HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT": int(
            medres.get("HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT")
            or cells_doc.get("HELDOUT_TEST_CONFIRMED_RESIDUAL_CELL_COUNT")
            or 0
        ),
        "ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT": int(
            medres.get("ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT")
            or cells_doc.get("ENGINE_ELIGIBLE_RESIDUAL_CELL_COUNT")
            or len(engine_eligible)
        ),
        "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS": medres.get(
            "INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS"
        )
        or cells_doc.get("INCREMENTAL_MEDICATION_RESIDUAL_SIGNAL_STATUS"),
        "appointment_date_not_administration": bool(medres.get("appointment_date_not_administration", True)),
        "mapping_accepted": bool(protocol.get("mapping_accepted")),
        "IROS_PROVIDER_COMMITMENT_STATUS": protocol.get("IROS_PROVIDER_COMMITMENT_STATUS"),
        "AUTOMATED_EXTERNAL_CONTACT_STATUS": protocol.get("AUTOMATED_EXTERNAL_CONTACT_STATUS"),
        "email_sent": bool(protocol.get("email_sent")),
        "calendar_event_created": bool(protocol.get("calendar_event_created")),
        "chosen_technical_timestamp_candidate": time_sem.get("chosen_technical_timestamp_candidate")
        or "appointment_date",
        "clinical_event_time_status": time_sem.get("clinical_event_time_status") or "CANDIDATE_ONLY",
        "appointment_columns": list(appt_cols),
        "medicine_catalog_columns": list(med_cols),
        "dose_or_route_columns": dose_like,
        "form_table_n_rows": form_n,
        "status_default_transition_label": status_sem.get("default_transition_label"),
        "level5_intervention_associated_modeling_episodes": int(
            ((hierarchy.get("levels") or {}).get("level_5_intervention_associated_modeling_episodes") or 0)
        ),
        "polypharmacy_patient_days_gt1": ((hierarchy.get("overlap_polypharmacy") or {}).get(
            "patient_days_with_gt1_distinct_medicine_id"
        )),
        "confounding": confounding if not confounding.get("_missing") else {},
        "residual_public_cell_count": int(cells_doc.get("n_cells") or len(cells)),
        "residual_engine_eligible_listed": len(engine_eligible),
        "inventory_source_outcome_horizon_count": len(unique_inventory),
        "source_a": SOURCE_A,
        "source_b": SOURCE_B,
        "source_a_medication_rows": _count(source_a_acc, "medication_rows", default=0)
        or int(schema.get("source_rows") or 0),
        "source_a_record_class": source_a_acc.get("record_class")
        or "RECORDED_MEDICATION_CONTEXT",
        "source_a_administration_claim": source_a_acc.get("administration_claim") or "NOT_CLAIMED",
        "source_b_medication_rows": _count(source_b_acc, "medication_rows", default=0),
        "evidence_files_missing": missing,
        "materialized": materialized_probe(root),
        "inventory": unique_inventory,
        "paths": {k: v for k, v in EVIDENCE_PATHS.items()},
    }
    return {"phase0": phase0, "raw_missing": missing, "ok": not missing}
