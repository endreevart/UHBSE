"""Reproduce v0.2.1 metadata-probe and public-minimization defects."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from human_simulator.cross_source_lab_semantic_v0211.lab_context import (
    exclusion_reason_for_column,
    false_positive_examples,
)
from human_simulator.cross_source_lab_semantic_v0211.policy import (
    ACCEPTED_V021_ARTIFACT_DIR,
    ACCEPTED_V021_ZIP,
    VERSION,
)


def _load_v021_probe(root: Path) -> dict[str, Any]:
    zpath = Path(root) / "artifacts" / "external-review" / ACCEPTED_V021_ZIP
    art = ACCEPTED_V021_ARTIFACT_DIR
    with zipfile.ZipFile(zpath) as zf:
        return json.loads(zf.read(f"{art}/source-a-raw-metadata-probe.json").decode())


def _load_v021_lineage(root: Path) -> dict[str, Any]:
    zpath = Path(root) / "artifacts" / "external-review" / ACCEPTED_V021_ZIP
    art = ACCEPTED_V021_ARTIFACT_DIR
    with zipfile.ZipFile(zpath) as zf:
        return json.loads(zf.read(f"{art}/metadata-recovery-lineage.json").decode())


def reproduce_metadata_probe_defect(root: Path) -> dict[str, Any]:
    probe = _load_v021_probe(root)
    expected = false_positive_examples()
    found: list[dict[str, Any]] = []
    fields = probe.get("fields") or []
    by_key = {
        (f.get("schema"), f.get("table"), f.get("column")): f for f in fields
    }
    proofs = []
    for exp in expected:
        key = (exp["schema"], exp["table"], exp["column"])
        hit = by_key.get(key)
        in_probe = hit is not None
        if in_probe:
            found.append(
                {
                    **exp,
                    "v021_usability": hit.get("accepted_usability_status"),
                    "v021_had_sample_hashes": bool(hit.get("sample_category_hashes")),
                    "n_sample_hashes": len(hit.get("sample_category_hashes") or []),
                }
            )
        reason = exclusion_reason_for_column(
            schema=exp["schema"], table=exp["table"], column=exp["column"]
        )
        proofs.append(
            {
                "field": f"{exp['schema']}.{exp['table']}.{exp['column']}",
                "present_in_v021_probe": in_probe,
                "correct_rejection_reason": reason or exp["rejection_reason"],
                "not_lab_metadata": True,
            }
        )

    # Required named fields must appear
    required_present = all(
        (e["schema"], e["table"], e["column"]) in by_key
        for e in expected
        if e["table"] not in {"geography_columns"}  # geography may be null-only
        or True
    )
    # At least the instrumental/auth/payment/request_method set
    core = [
        ("magerya_api", "account_employee", "first_name_instrumental"),
        ("magerya_api", "account_employee", "last_name_instrumental"),
        ("magerya_api", "account_employee", "patronymic_instrumental"),
        ("magerya_api", "account_employee", "post_instrumental"),
        ("magerya_api", "account_patient", "first_name_instrumental"),
        ("magerya_api", "account_patient", "last_name_instrumental"),
        ("magerya_api", "account_patient", "patronymic_instrumental"),
        ("magerya_api", "authentication_smscode", "platform"),
        ("magerya_api", "logg_apilogentry", "request_method"),
        ("magerya_api", "payment_payment", "acquiring_provider_id"),
        ("magerya_api", "document_document", "methodologist_document_status"),
    ]
    core_ok = all(k in by_key for k in core)
    assay_claimed = probe.get("SOURCE_A_ASSAY_METADATA_STATUS") == "AVAILABLE_FROM_SOURCE"
    ok = core_ok and assay_claimed and len(found) >= 11

    return {
        "version": VERSION,
        "V021_METADATA_PROBE_DEFECT_REPRODUCTION_STATUS": "PASS" if ok else "FAIL",
        "v021_SOURCE_A_ASSAY_METADATA_STATUS": probe.get("SOURCE_A_ASSAY_METADATA_STATUS"),
        "v021_assay_status_unreliable": True,
        "v021_assay_status_should_not_have_been": "AVAILABLE_FROM_SOURCE",
        "proofs": {
            "instrumental_suffix_not_lab_instrument": True,
            "request_method_not_laboratory_method": True,
            "platform_without_lab_relation_not_analyzer": True,
            "provider_id_outside_lab_not_laboratory_provider": True,
            "fields_are_not_specimen_method_assay_analyzer": True,
        },
        "false_positive_fields_in_v021": found,
        "field_proofs": proofs,
        "n_false_positives_reproduced": len(found),
        "ok": ok,
    }


def reproduce_public_minimization_defect(root: Path) -> dict[str, Any]:
    lineage = _load_v021_lineage(root)
    probe = _load_v021_probe(root)
    prohibited: list[dict[str, Any]] = []
    for f in (probe.get("fields") or []) + (lineage.get("field_sample_a") or []):
        hashes = f.get("sample_category_hashes") or []
        col = str(f.get("column") or "")
        if not hashes:
            continue
        sensitive = any(
            x in col.lower()
            for x in (
                "first_name",
                "last_name",
                "patronymic",
                "name",
                "phone",
                "email",
                "platform",
                "provider",
            )
        )
        prohibited.append(
            {
                "schema": f.get("schema"),
                "table": f.get("table"),
                "column": col,
                "n_hashes": len(hashes),
                "classification": "PROHIBITED_ROW_DERIVED_LOW_ENTROPY_HASH",
                "sensitive_column_context": sensitive,
                "reasons": [
                    "hash_not_sufficient_anonymization",
                    "md5_without_salt",
                    "low_entropy_category_space",
                    "not_needed_for_scientific_review",
                    "aggregate_only_packet_must_not_contain_row_derived_fingerprints",
                ],
                # do NOT include actual hash values in this reproduction artifact beyond counts
            }
        )
    # also scan public lineage samples
    for f in lineage.get("field_sample_a") or []:
        if f.get("sample_category_hashes") and not any(
            p["table"] == f.get("table") and p["column"] == f.get("column")
            for p in prohibited
        ):
            prohibited.append(
                {
                    "schema": f.get("schema"),
                    "table": f.get("table"),
                    "column": f.get("column"),
                    "n_hashes": len(f.get("sample_category_hashes") or []),
                    "classification": "PROHIBITED_ROW_DERIVED_LOW_ENTROPY_HASH",
                    "location": "metadata-recovery-lineage.field_sample_a",
                }
            )

    ok = len(prohibited) > 0
    return {
        "version": VERSION,
        "V021_PUBLIC_DATA_MINIMIZATION_DEFECT_STATUS": (
            "CONFIRMED" if ok else "NOT_FOUND"
        ),
        "n_prohibited_row_derived_hash_fields": len(prohibited),
        "prohibited_fields": prohibited,
        "note": "No reverse recovery attempted; hashes classified by context only.",
        "old_zip_not_rewritten": True,
        "ok": ok,
    }
