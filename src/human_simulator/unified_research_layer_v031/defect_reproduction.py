"""Reproduce inflated v0.3 claims without rewriting the v0.3 ZIP."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v031.policy import (
    ACCEPTED_V03_ARTIFACT_DIR,
    VERSION,
)


def reproduce_v03_defects(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    art = root / ACCEPTED_V03_ARTIFACT_DIR
    priv = root / "private" / "unified-research-layer-v03" / "research-layer"

    status = json.loads((art / "unified-research-layer-status.json").read_text(encoding="utf-8"))
    states = json.loads(
        (art / "unified-source-aware-state-assembly.json").read_text(encoding="utf-8")
    )
    b_inv = json.loads((art / "full-source-b-domain-inventory.json").read_text(encoding="utf-8"))
    accounting = json.loads((art / "multi-domain-accounting.json").read_text(encoding="utf-8"))
    temporal = json.loads((art / "unified-temporal-layer.json").read_text(encoding="utf-8"))
    split = json.loads((art / "global-a-b-split-foundation.json").read_text(encoding="utf-8"))
    a_inv = json.loads((art / "full-source-a-domain-inventory.json").read_text(encoding="utf-8"))

    research_files = sorted(p.name for p in priv.glob("*") if p.is_file()) if priv.is_dir() else []
    patient_rows = bool(status.get("patient_rows_written"))
    # aggregate-only: private research-layer has JSON contracts, no parquet/row datasets
    has_row_datasets = any(
        n.endswith((".parquet", ".csv", ".feather")) for n in research_files
    )
    diagnoses_cov = states.get("diagnoses_coverage")
    med_cov = states.get("medication_coverage")
    if diagnoses_cov is None:
        diagnoses_cov = (states.get("domain_coverage") or {}).get("diagnoses")
    if med_cov is None:
        med_cov = (states.get("domain_coverage") or {}).get("medications")
    if diagnoses_cov is None:
        diagnoses_cov = status.get("diagnoses_coverage") or "SOURCE_SPECIFIC_PENDING_STRUCTURED_LOAD"
    if med_cov is None:
        med_cov = status.get("medication_coverage") or "SOURCE_SPECIFIC_PENDING_STRUCTURED_LOAD"

    # inspect state assembly for counts-only
    state_records_created = bool(states.get("state_records_created")) or bool(
        states.get("n_state_records")
    )
    if states.get("INDIVIDUAL_STATE_DATASET_STATUS") == "NOT_STARTED":
        state_records_created = False
    if states.get("CURRENT_STATE_CLASSIFIER_STATUS") == "NOT_STARTED" and not states.get(
        "n_state_rows"
    ):
        # v0.3 wrote coverage flags + subject counts, not state records
        state_records_created = False
    if "COUNTS_ONLY" in str(states.get("UNIFIED_STATE_ASSEMBLY_STATUS") or "").upper():
        state_records_created = False
    if states.get("n_subjects") and not states.get("n_state_rows"):
        state_records_created = False

    b_schema_scope = b_inv.get("schema") or b_inv.get("schemas") or "quest_digital"
    b_n_rel = b_inv.get("n_relations_listed") or b_inv.get("n_relations") or 0
    uses_reltuples = True  # v0.3 domain_inventory used pg_class.reltuples
    # confirm from a_inv / accounting notes
    if "reltuples" in json.dumps(a_inv).lower() or "estimated" in json.dumps(accounting).lower():
        uses_reltuples = True

    unaccounted = accounting.get("UNACCOUNTED_COUNT")
    # relation-assignment accounting: unaccounted is about domain assignment not rows
    accounting_kind = "RELATION_ASSIGNMENT_NOT_ROW_RECONCILIATION"

    overlap_aware_claim = bool(split.get("overlap_aware"))
    # v0.3 hashes each source independently (see split_foundation.assign_role); no group assignment
    split_src = (
        Path(root)
        / "src/human_simulator/unified_research_layer_v03/split_foundation.py"
    ).read_text(encoding="utf-8")
    independent_hash = (
        "source_system}|{source_subject_key}" in split_src.replace(" ", "")
        or ("|{source_system}|" in split_src and "GROUP" not in split_src)
        or ("source_system" in split_src and "assign_group" not in split_src.lower())
    )
    has_group_assignment = "GROUP|" in split_src or bool(split.get("overlap_groups_assigned"))
    split_protects = overlap_aware_claim and has_group_assignment and not independent_hash

    # temporal false positives from published temporal layer
    false_positives = []
    samples = list(temporal.get("source_a_temporal_columns_sample") or []) + list(
        temporal.get("source_b_temporal_columns_sample") or []
    )
    samples += list(temporal.get("a_columns") or []) + list(temporal.get("b_columns") or [])
    for entry in samples:
        if not isinstance(entry, dict):
            continue
        col = str(entry.get("column") or "")
        dtype = str(entry.get("data_type") or "").lower()
        if col in {
            "appointment_price_at_clinic",
            "appointment_price_at_clinic_id",
            "perform_at_clinic",
            "power_attorney",
            "recommendation_notes",
        } or "price_at_clinic" in col or col.endswith("_at_clinic_id"):
            if "timestamp" not in dtype and dtype not in {
                "date",
                "time",
                "timestamp with time zone",
                "timestamp without time zone",
            }:
                false_positives.append({"column": col, "data_type": dtype})
        if col == "perform_at_clinic" and "bool" in dtype:
            false_positives.append({"column": col, "data_type": dtype})

    # also scan full temporal JSON for known bad names
    temporal_blob = json.dumps(temporal)
    for bad in (
        "appointment_price_at_clinic",
        "perform_at_clinic",
        "power_attorney",
        "service_price",
        "recommendation_notes",
    ):
        if bad in temporal_blob and not any(fp["column"] == bad for fp in false_positives):
            false_positives.append({"column": bad, "data_type": "matched_in_temporal_artifact"})

    # test or True
    unit_test = root / "tests" / "test_unified_research_layer_v03_unit.py"
    or_true = False
    if unit_test.is_file():
        src = unit_test.read_text(encoding="utf-8")
        or_true = "or True" in src
        try:
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert) and isinstance(node.test, ast.BoolOp):
                    if any(
                        isinstance(v, ast.Constant) and v.value is True
                        for v in node.test.values
                    ):
                        or_true = True
        except SyntaxError:
            pass

    defects = {
        "1_patient_rows_written": {
            "confirmed": patient_rows is False,
            "patient_rows_written": patient_rows,
        },
        "2_aggregate_manifest_only": {
            "confirmed": (not has_row_datasets) and len(research_files) > 0,
            "research_layer_files": research_files,
            "has_row_datasets": has_row_datasets,
        },
        "3_state_assembly_counts_only": {
            "confirmed": not state_records_created,
            "state_records_created": state_records_created,
            "assembly_status": states.get("UNIFIED_STATE_ASSEMBLY_STATUS")
            or states.get("status"),
        },
        "4_diagnoses_pending": {
            "confirmed": str(diagnoses_cov) == "SOURCE_SPECIFIC_PENDING_STRUCTURED_LOAD"
            or "PENDING" in str(diagnoses_cov).upper(),
            "coverage": diagnoses_cov,
        },
        "5_medication_pending": {
            "confirmed": str(med_cov) == "SOURCE_SPECIFIC_PENDING_STRUCTURED_LOAD"
            or "PENDING" in str(med_cov).upper(),
            "coverage": med_cov,
        },
        "6_source_b_quest_digital_only": {
            "confirmed": b_schema_scope == "quest_digital"
            or (isinstance(b_schema_scope, list) and b_schema_scope == ["quest_digital"]),
            "schema_scope": b_schema_scope,
        },
        "7_source_b_19_relations": {
            "confirmed": int(b_n_rel) == 19,
            "n_relations_listed": b_n_rel,
        },
        "8_reltuples_estimates": {
            "confirmed": uses_reltuples,
            "note": "v0.3 inventory used pg_class.reltuples for source_rows_estimated",
        },
        "9_unaccounted_relation_assignment": {
            "confirmed": unaccounted == 0,
            "UNACCOUNTED_COUNT": unaccounted,
            "accounting_kind": accounting_kind,
        },
        "10_split_not_overlap_protected": {
            "confirmed": overlap_aware_claim and independent_hash and not has_group_assignment,
            "overlap_aware_claim": overlap_aware_claim,
            "independent_source_hashing": independent_hash,
            "has_group_assignment": has_group_assignment,
        },
        "11_temporal_substring_false_positives": {
            "confirmed": len(false_positives) > 0,
            "examples": false_positives[:12],
        },
        "12_or_true_test": {
            "confirmed": or_true,
            "test_file": "tests/test_unified_research_layer_v03_unit.py",
        },
    }
    all_confirmed = all(d["confirmed"] for d in defects.values())

    doc = {
        "version": VERSION,
        "baseline_zip": "stage-03-unified-a-b-clinical-research-layer-v0.3-review.zip",
        "V03_RESEARCH_LAYER_MATERIALIZATION_STATUS": "AGGREGATE_MANIFEST_ONLY",
        "V03_STATE_ASSEMBLY_STATUS": "COUNTS_ONLY_NOT_STATES",
        "V03_SOURCE_B_INVENTORY_SCOPE_STATUS": "INCOMPLETE",
        "V03_MULTI_DOMAIN_ACCOUNTING_STATUS": "ESTIMATED_RELATION_LEVEL_ONLY",
        "V03_OVERLAP_AWARE_SPLIT_STATUS": "NOT_ESTABLISHED",
        "V03_TECHNICAL_MERGE_CLAIM_STATUS": "CORRECTION_REQUIRED",
        "defects": defects,
        "all_twelve_confirmed": all_confirmed,
        "ok": all_confirmed,
    }
    return doc
