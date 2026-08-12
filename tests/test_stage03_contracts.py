"""Executable contract tests for snapshot fingerprint and canonical payload hash."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from human_simulator.stage03.contract_algorithms import (
    ContractSerializationError,
    MissingRowFieldError,
    UnsupportedScalarTypeError,
    build_stable_payload,
    canonical_json_dumps,
    canonical_payload_hash,
    classify_promotion,
    length_prefix_utf8,
    normalize_canonical_json,
    relation_aggregate_hmac,
    row_content_hmac,
    serialize_scalar,
    snapshot_aggregate_hmac,
)
from human_simulator.stage03.pilot_read_set import compute_pilot_read_set, validate_fingerprint_coverage

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPL_DIR = REPO_ROOT / "artifacts" / "stage-03-implementation"
STAGE03_DIR = REPO_ROOT / "artifacts" / "stage-03"
TEST_SECRET = b"contract-test-secret-v1"
SOURCE_SYSTEM = "magerya_api"

RELATION_COLUMNS = {
    "account_patient": ["id", "created", "modified", "birthdate", "sex"],
    "appointment_appointment": [
        "id",
        "patient_id",
        "doctor_id",
        "created",
        "modified",
        "completed_at",
        "next_appointment_date",
        "chat_end_time",
    ],
    "document_analysisresult": [
        "id",
        "patient_id",
        "created",
        "modified",
        "status",
        "sampling_date",
        "appointment_date",
    ],
    "document_analysisresultitem": [
        "id",
        "analysis_result_id",
        "name",
        "unit",
        "value",
        "flag",
        "ref_value_from",
        "ref_value_to",
        "note",
    ],
}


def _relation_fingerprint(relation: str, rows: list[dict]) -> str:
    columns = RELATION_COLUMNS[relation]
    ordered = sorted(rows, key=lambda row: row["id"])
    row_hmacs = [
        row_content_hmac(
            source_system=SOURCE_SYSTEM,
            source_relation=relation,
            row=row,
            field_order=columns,
            secret=TEST_SECRET,
            contract_version="2",
        )
        for row in ordered
    ]
    return relation_aggregate_hmac(ordered_row_hmacs=row_hmacs, secret=TEST_SECRET)


def test_length_prefix_null_differs_from_empty_string() -> None:
    assert length_prefix_utf8(None) != length_prefix_utf8("")
    assert length_prefix_utf8(None) == b"\xff\xff\xff\xff"
    assert length_prefix_utf8("") == b"\x00\x00\x00\x00"


def test_serialize_scalar_python_types() -> None:
    assert serialize_scalar(True) == "bool:true"
    assert serialize_scalar(7) == "int:7"
    assert serialize_scalar(1.25) == "float:1.25"
    assert serialize_scalar(Decimal("10.500")) == "decimal:10.5"
    assert serialize_scalar(date(2020, 1, 2)) == "date:2020-01-02"
    aware = datetime(2020, 1, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
    assert serialize_scalar(aware) == "datetime:2020-01-02T03:04:05.000006Z"
    assert serialize_scalar(UUID("00000000-0000-0000-0000-000000000001")) == "uuid:00000000-0000-0000-0000-000000000001"


def test_serialize_scalar_rejects_naive_datetime() -> None:
    with pytest.raises(ContractSerializationError):
        serialize_scalar(datetime(2020, 1, 2, 3, 4, 5))


def test_serialize_scalar_rejects_non_finite_float() -> None:
    with pytest.raises(ContractSerializationError):
        serialize_scalar(float("inf"))


def test_missing_row_field_fails_closed() -> None:
    with pytest.raises(MissingRowFieldError):
        row_content_hmac(
            source_system=SOURCE_SYSTEM,
            source_relation="account_patient",
            row={"id": 1},
            field_order=["id", "created"],
            secret=TEST_SECRET,
        )


def test_unsupported_scalar_type_raises() -> None:
    with pytest.raises(UnsupportedScalarTypeError):
        serialize_scalar({"bad": "object"})


def test_row_value_change_changes_fingerprint() -> None:
    base = {
        "id": 1,
        "created": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "modified": datetime(2020, 1, 2, tzinfo=timezone.utc),
        "birthdate": date(1990, 1, 1),
        "sex": "F",
    }
    changed = {**base, "sex": "M"}
    columns = RELATION_COLUMNS["account_patient"]
    first = row_content_hmac(
        source_system=SOURCE_SYSTEM,
        source_relation="account_patient",
        row=base,
        field_order=columns,
        secret=TEST_SECRET,
    )
    second = row_content_hmac(
        source_system=SOURCE_SYSTEM,
        source_relation="account_patient",
        row=changed,
        field_order=columns,
        secret=TEST_SECRET,
    )
    assert first != second


def test_row_order_after_pk_sort_is_stable() -> None:
    rows_a = [
        {
            "id": 2,
            "created": datetime(2020, 1, 1, tzinfo=timezone.utc),
            "modified": datetime(2020, 1, 2, tzinfo=timezone.utc),
            "birthdate": None,
            "sex": "F",
        },
        {
            "id": 1,
            "created": datetime(2020, 1, 3, tzinfo=timezone.utc),
            "modified": datetime(2020, 1, 4, tzinfo=timezone.utc),
            "birthdate": date(1990, 1, 1),
            "sex": "M",
        },
    ]
    rows_b = list(reversed(rows_a))
    assert _relation_fingerprint("account_patient", rows_a) == _relation_fingerprint("account_patient", rows_b)


def test_appointment_read_set_includes_completed_at_and_doctor_id() -> None:
    construction = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    mapping = yaml.safe_load((STAGE03_DIR / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))
    pilot_slice = yaml.safe_load((IMPL_DIR / "pilot-slice.yaml").read_text(encoding="utf-8"))
    read_sets = compute_pilot_read_set(
        construction_contract=construction,
        source_a_mapping_draft=mapping,
        pilot_slice=pilot_slice,
    )
    appointment = read_sets["appointment_appointment"]
    assert "completed_at" in appointment
    assert "doctor_id" in appointment
    assert "next_appointment_date" in appointment
    assert "chat_end_time" in appointment
    assert "patient_id" in appointment


def test_pilot_read_set_fingerprint_coverage_passes_for_pipeline_plan() -> None:
    construction = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    mapping = yaml.safe_load((STAGE03_DIR / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))
    pilot_slice = yaml.safe_load((IMPL_DIR / "pilot-slice.yaml").read_text(encoding="utf-8"))
    pipeline = yaml.safe_load((IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    validations = validate_fingerprint_coverage(
        construction_contract=construction,
        source_a_mapping_draft=mapping,
        pilot_slice=pilot_slice,
        fingerprint_contract=pipeline["source_snapshot_fingerprint_contract"],
    )
    assert all(not item.uncovered for item in validations)
    assert all(not item.undocumented_without_justification for item in validations)


def _load_pilot_validation_inputs() -> tuple[dict, dict, dict, dict]:
    construction = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    mapping = yaml.safe_load((STAGE03_DIR / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))
    pilot_slice = yaml.safe_load((IMPL_DIR / "pilot-slice.yaml").read_text(encoding="utf-8"))
    pipeline = yaml.safe_load((IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    return construction, mapping, pilot_slice, pipeline


def _required_pilot_fingerprint_columns() -> list[tuple[str, str]]:
    construction, mapping, pilot_slice, pipeline = _load_pilot_validation_inputs()
    validations = validate_fingerprint_coverage(
        construction_contract=construction,
        source_a_mapping_draft=mapping,
        pilot_slice=pilot_slice,
        fingerprint_contract=pipeline["source_snapshot_fingerprint_contract"],
    )
    required: list[tuple[str, str]] = []
    for item in validations:
        for column in sorted(item.read_set - item.excluded_columns):
            required.append((item.relation, column))
    return required


@pytest.mark.parametrize("relation,column", _required_pilot_fingerprint_columns())
def test_removing_required_fingerprint_column_fails_gate(relation: str, column: str) -> None:
    construction, mapping, pilot_slice, pipeline = _load_pilot_validation_inputs()
    fingerprint = pipeline["source_snapshot_fingerprint_contract"]
    relation_spec = fingerprint["relations"][relation]
    original = list(relation_spec["fingerprint_columns"])
    relation_spec["fingerprint_columns"] = [item for item in original if item != column]
    validations = validate_fingerprint_coverage(
        construction_contract=construction,
        source_a_mapping_draft=mapping,
        pilot_slice=pilot_slice,
        fingerprint_contract=fingerprint,
    )
    match = next(item for item in validations if item.relation == relation)
    assert column in match.uncovered


def test_undocumented_extra_fingerprint_column_requires_justification() -> None:
    construction, mapping, pilot_slice, pipeline = _load_pilot_validation_inputs()
    fingerprint = pipeline["source_snapshot_fingerprint_contract"]
    relation_spec = fingerprint["relations"]["appointment_appointment"]
    relation_spec["fingerprint_columns"] = list(relation_spec["fingerprint_columns"]) + ["__synthetic_extra__"]
    validations = validate_fingerprint_coverage(
        construction_contract=construction,
        source_a_mapping_draft=mapping,
        pilot_slice=pilot_slice,
        fingerprint_contract=fingerprint,
    )
    appointment = next(item for item in validations if item.relation == "appointment_appointment")
    assert "__synthetic_extra__" in appointment.undocumented_without_justification


def test_canonical_payload_hash_supports_nested_scalars() -> None:
    payload = build_stable_payload(
        canonical_entity="Observation",
        canonical_id="obs-1",
        stable_clinical_fields={
            "observed_at": datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            "value": Decimal("12.500"),
            "specimen_date": date(2020, 1, 1),
            "identifier": UUID("00000000-0000-0000-0000-000000000099"),
        },
        provenance={"source_system_id": "magerya_api"},
        source_record_locator="loc",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version="0.3.5",
    )
    digest = canonical_payload_hash(payload)
    assert len(digest) == 64
    assert canonical_payload_hash(payload) == digest


def test_canonical_payload_hash_uses_documented_shape() -> None:
    pipeline = yaml.safe_load((IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    payload_shape = pipeline["canonical_payload_hash_contract"]["payload_shape"]
    payload = build_stable_payload(
        canonical_entity="Subject",
        canonical_id="subj-001",
        stable_clinical_fields={"birthdate": "1990-01-01"},
        provenance={"source_system_id": "magerya_api", "pipeline_run_id": "run-a", "unknown": "ignored"},
        source_record_locator="magerya_api.account_patient/1",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version="0.3.5",
    )
    assert list(payload.keys()) == payload_shape


def test_canonical_payload_hash_excludes_volatile_and_unknown_provenance() -> None:
    stable = build_stable_payload(
        canonical_entity="Subject",
        canonical_id="subj-001",
        stable_clinical_fields={"birthdate": "1990-01-01"},
        provenance={"source_system_id": "magerya_api", "pipeline_run_id": "run-a"},
        source_record_locator="loc",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version="0.3.5",
    )
    mutated = build_stable_payload(
        canonical_entity="Subject",
        canonical_id="subj-001",
        stable_clinical_fields={"birthdate": "1990-01-01"},
        provenance={"source_system_id": "magerya_api", "pipeline_run_id": "run-b", "emitted_at": "2026-01-01T00:00:00Z"},
        source_record_locator="loc",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version="0.3.5",
    )
    assert canonical_payload_hash(stable) == canonical_payload_hash(mutated)


def test_canonical_payload_hash_changes_when_clinical_field_changes() -> None:
    first = build_stable_payload(
        canonical_entity="Subject",
        canonical_id="subj-001",
        stable_clinical_fields={"birthdate": "1990-01-01"},
        provenance={"source_system_id": "magerya_api"},
        source_record_locator="loc",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version="0.3.5",
    )
    second = build_stable_payload(
        canonical_entity="Subject",
        canonical_id="subj-001",
        stable_clinical_fields={"birthdate": "1991-01-01"},
        provenance={"source_system_id": "magerya_api"},
        source_record_locator="loc",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version="0.3.5",
    )
    assert canonical_payload_hash(first) != canonical_payload_hash(second)


def test_promotion_classifier_matrix() -> None:
    assert classify_promotion(canonical_id_present=False, payload_hash_match=False, input_version_tuple_match=False, mapping_or_transform_changed=False) == "INSERT"
    assert classify_promotion(canonical_id_present=True, payload_hash_match=True, input_version_tuple_match=False, mapping_or_transform_changed=False) == "NOOP_ALREADY_PUBLISHED"
    assert classify_promotion(canonical_id_present=True, payload_hash_match=False, input_version_tuple_match=True, mapping_or_transform_changed=False) == "SOURCE_PAYLOAD_CHANGED"
    assert classify_promotion(canonical_id_present=True, payload_hash_match=False, input_version_tuple_match=False, mapping_or_transform_changed=True) == "VERSIONED_REBUILD_REQUIRED"
    assert classify_promotion(canonical_id_present=True, payload_hash_match=False, input_version_tuple_match=False, mapping_or_transform_changed=False) == "CANONICAL_PAYLOAD_CONFLICT"


def test_canonical_json_v4_rejects_non_string_object_keys() -> None:
    with pytest.raises(ContractSerializationError):
        normalize_canonical_json({1: "x"})


def test_canonical_json_v4_rejects_tuple() -> None:
    with pytest.raises(ContractSerializationError):
        normalize_canonical_json((1, 2))


def test_canonical_json_v4_decimal_not_equal_to_user_object() -> None:
    decimal_node = normalize_canonical_json(Decimal("1.0"))
    user_object = normalize_canonical_json({"__canonical_scalar__": "decimal", "value": "1.0"})
    assert decimal_node != user_object
    assert canonical_json_dumps({"value": Decimal("1.0")}) != canonical_json_dumps(
        {"value": {"__canonical_scalar__": "decimal", "value": "1.0"}}
    )


def test_canonical_json_v4_string_not_equal_to_integer() -> None:
    assert canonical_payload_hash({"value": "int:7"}) != canonical_payload_hash({"value": 7})


def test_canonical_json_v4_type_change_changes_hash() -> None:
    as_string = canonical_payload_hash({"value": "7"})
    as_int = canonical_payload_hash({"value": 7})
    assert as_string != as_int


def test_canonical_json_v4_nested_hash_is_stable() -> None:
    payload = build_stable_payload(
        canonical_entity="Observation",
        canonical_id="obs-1",
        stable_clinical_fields={
            "observed_at": datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            "value": Decimal("12.500"),
            "specimen_date": date(2020, 1, 1),
            "identifier": UUID("00000000-0000-0000-0000-000000000099"),
        },
        provenance={"source_system_id": "magerya_api"},
        source_record_locator="loc",
        mapping_status="MAPPED",
        mapping_version="0.7.4",
        transformation_version="0.3.5",
    )
    first = canonical_payload_hash(payload)
    second = canonical_payload_hash(payload)
    assert first == second


def test_mapping_draft_source_columns_in_read_set() -> None:
    construction = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    mapping = yaml.safe_load((STAGE03_DIR / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))
    mapping["mappings"] = list(mapping["mappings"]) + [
        {
            "source_relation": "magerya_api.appointment_appointment",
            "source_columns": ["patient_id", "doctor_id"],
            "canonical_entity": "Encounter",
            "canonical_field": "placeholder",
        }
    ]
    read_sets = compute_pilot_read_set(
        construction_contract=construction,
        source_a_mapping_draft=mapping,
        pilot_slice=yaml.safe_load((IMPL_DIR / "pilot-slice.yaml").read_text(encoding="utf-8")),
    )
    assert {"patient_id", "doctor_id"}.issubset(read_sets["appointment_appointment"])


def test_fingerprint_contract_version_is_v2() -> None:
    pipeline = yaml.safe_load((IMPL_DIR / "pipeline-plan.yaml").read_text(encoding="utf-8"))
    contract = pipeline["source_snapshot_fingerprint_contract"]
    assert contract["contract_version"] == "2"
    assert json.loads(json.dumps({"z": 1, "a": 2}, sort_keys=True)) == {"a": 2, "z": 1}
