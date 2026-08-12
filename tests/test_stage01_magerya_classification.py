"""Regression tests for Source A (magerya) entity classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from human_simulator.classify.entities import classify_clinical_entities
from human_simulator.classify.table_roles import assign_table_role
from human_simulator.stage01.settings import MAGERYA_APPLICATION_SCHEMAS


def _magerya_relation(name: str, *, columns: list[str] | None = None) -> dict:
    return {
        "schema": "magerya_api",
        "name": name,
        "kind": "table",
    }


def _profile(*relations: dict, columns: list[dict] | None = None) -> dict:
    return {
        "database": "magerya_api",
        "relations": list(relations),
        "columns": columns or [],
        "foreign_keys": [],
    }


def _candidate(result: dict, relation: str, entity_type: str) -> dict | None:
    for item in result["entity_types"].get(entity_type, []):
        if item["relation"] == relation:
            return item
    return None


def test_account_patient_is_patients_candidate(tmp_path: Path) -> None:
    profile = _profile(_magerya_relation("account_patient"))
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    patients = result["entity_types"]["patients"]
    assert any(item["relation"] == "account_patient" for item in patients)
    assert all(item["status"] == "CANDIDATE" for item in patients)
    assert patients[0]["data_level"] == "ATTRIBUTE_CONTAINER"


def test_account_doctor_is_doctors_candidate(tmp_path: Path) -> None:
    profile = _profile(_magerya_relation("account_doctor"))
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    doctors = result["entity_types"]["doctors"]
    assert any(item["relation"] == "account_doctor" for item in doctors)


def test_appointment_appointment_is_visit_and_appointment_candidate(tmp_path: Path) -> None:
    profile = _profile(
        _magerya_relation("appointment_appointment"),
        columns=[
            {
                "schema": "magerya_api",
                "relation": "appointment_appointment",
                "name": "patient_id",
                "data_type": "integer",
            }
        ],
    )
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    visit = _candidate(result, "appointment_appointment", "visits")
    appointment = _candidate(result, "appointment_appointment", "appointments")
    assert visit is not None
    assert appointment is not None
    assert visit["data_level"] == "PATIENT_EVENT"


@pytest.mark.parametrize(
    "relation_name",
    ["appointment_appointmentrequest", "appointment_callbackrequest"],
)
def test_request_tables_are_not_visit_candidates(relation_name: str, tmp_path: Path) -> None:
    profile = _profile(
        _magerya_relation(relation_name),
        columns=[
            {
                "schema": "magerya_api",
                "relation": relation_name,
                "name": "visit_type",
                "data_type": "text",
            },
            {
                "schema": "magerya_api",
                "relation": relation_name,
                "name": "appointment_id",
                "data_type": "integer",
            },
        ],
    )
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    visit_relations = {item["relation"] for item in result["entity_types"]["visits"]}
    appointment_relations = {item["relation"] for item in result["entity_types"]["appointments"]}
    assert relation_name not in visit_relations
    assert relation_name not in appointment_relations


def test_link_table_with_appointment_id_not_appointment_candidate(tmp_path: Path) -> None:
    profile = _profile(
        _magerya_relation("document_medicalreport"),
        columns=[
            {
                "schema": "magerya_api",
                "relation": "document_medicalreport",
                "name": "appointment_id",
                "data_type": "integer",
            }
        ],
    )
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    appointment_relations = {item["relation"] for item in result["entity_types"]["appointments"]}
    assert "document_medicalreport" not in appointment_relations
    medical_docs = {item["relation"] for item in result["entity_types"]["medical_documents"]}
    assert "document_medicalreport" in medical_docs


def test_diagnosis_catalogs_are_reference_not_patient_diagnoses(tmp_path: Path) -> None:
    profile = _profile(
        _magerya_relation("diagnosis_diagnosis"),
        _magerya_relation("diagnosis_medicines"),
        _magerya_relation("document_analysisresult"),
    )
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    assert _candidate(result, "diagnosis_diagnosis", "diagnoses") is None
    assert _candidate(result, "diagnosis_medicines", "medications") is None
    assert _candidate(result, "diagnosis_medicines", "diagnoses") is None
    assert _candidate(result, "document_analysisresult", "laboratory_results") is not None


def test_never_emits_confirmed_status(tmp_path: Path) -> None:
    profile = _profile(
        _magerya_relation("account_patient"),
        _magerya_relation("appointment_appointment"),
    )
    result = classify_clinical_entities(
        profile, tmp_path, application_schemas=MAGERYA_APPLICATION_SCHEMAS
    )
    for items in result["entity_types"].values():
        for item in items:
            assert item["status"] == "CANDIDATE"


def test_appointment_request_role_is_workflow() -> None:
    role = assign_table_role(
        "magerya_api",
        "appointment_appointmentrequest",
        ["appointment_id", "patient_id"],
        is_technical_name=False,
    )
    assert role == "WORKFLOW"
