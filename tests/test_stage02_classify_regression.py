"""Regression tests for Source B semantic classification fixes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from human_simulator.classify.entities import classify_clinical_entities
from human_simulator.stage02.classify_second_source import (
    MANIFEST_NAME,
    reclassify_second_source,
    run_classification_regression_checks,
    verify_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
KGZ_PROFILE = REPO_ROOT / "artifacts" / "stage-02" / "schema-profile-kgz.json"
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "stage-02"


def _assignments(result: dict) -> dict[tuple[str, str], set[str]]:
    grouped: dict[tuple[str, str], set[str]] = {}
    for entity_type, items in result.get("entity_types", {}).items():
        for item in items:
            key = (item["schema"], item["relation"])
            grouped.setdefault(key, set()).add(entity_type)
    return grouped


def _candidate(result: dict, schema: str, relation: str, entity_type: str) -> dict | None:
    for item in result["entity_types"].get(entity_type, []):
        if item["schema"] == schema and item["relation"] == relation:
            return item
    return None


def _role(result: dict, schema: str, relation: str) -> str:
    for item in result["table_roles"]:
        if item["schema"] == schema and item["relation"] == relation:
            return item["role"]
    raise KeyError(f"{schema}.{relation}")


@pytest.fixture
def kgz_profile() -> dict:
    if not KGZ_PROFILE.exists():
        pytest.skip("schema-profile-kgz.json not present")
    return json.loads(KGZ_PROFILE.read_text(encoding="utf-8"))


def test_consultations_is_event_not_patient_or_doctor(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assignments = _assignments(result)

    assert "patients" not in assignments.get(("public", "consultations"), set())
    assert "doctors" not in assignments.get(("public", "consultations"), set())
    assert assignments.get(("public", "consultations"), set()) & {"visits", "appointments"}
    assert _role(result, "public", "consultations") == "EVENT"


def test_consultation_linked_tables_not_visits(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assignments = _assignments(result)

    for relation in ("feedback", "questionnaire", "users_rating", "consultation_service_changes"):
        assert "visits" not in assignments.get(("public", relation), set()), relation

    assert _role(result, "public", "feedback") == "ATTRIBUTE_CONTAINER"
    assert _role(result, "public", "questionnaire") == "ATTRIBUTE_CONTAINER"
    assert _role(result, "public", "users_rating") == "REFERENCE"
    assert _role(result, "public", "consultation_service_changes") == "WORKFLOW"


def test_outside_doctor_medicine_does_not_classify_doctors(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assignments = _assignments(result)

    assert "doctors" not in assignments.get(("public", "feedback"), set())
    assert "doctors" not in assignments.get(("public", "questionnaire"), set())


def test_payment_transactions_not_operations(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assert "operations" not in _assignments(result).get(("public", "payment_transactions"), set())


def test_identity_document_columns_not_medical_documents(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assert "medical_documents" not in _assignments(result).get(("public", "persons"), set())


def test_lab_reference_tables_not_laboratory_results(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assignments = _assignments(result)
    false_positives = (
        "analyses_codes",
        "catalog_labs",
        "lab_addresses",
        "lab_referral",
        "lab_referral_codes",
        "lab_referral_regions",
    )
    for relation in false_positives:
        assert "laboratory_results" not in assignments.get(("quest_digital", relation), set()), relation


def test_analyses_constructor_is_laboratory_results_candidate(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    candidate = _candidate(result, "quest_digital", "analyses_constructor", "laboratory_results")
    assert candidate is not None
    assert candidate["status"] == "CANDIDATE"
    assert candidate["role"] == "OBSERVATION"
    assert any(ev["type"] == "row_estimate" for ev in candidate["evidence"])


def test_profilaxys_profile_is_measurements_candidate(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    candidate = _candidate(result, "public", "profilaxys_profile", "measurements")
    assert candidate is not None
    assert candidate["status"] == "CANDIDATE"
    assert candidate["role"] == "ATTRIBUTE_CONTAINER"


def test_profilaxys_analyses_is_measurements_not_laboratory_results(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assert _role(result, "public", "profilaxys_analyses") == "OBSERVATION"
    assignments = _assignments(result).get(("public", "profilaxys_analyses"), set())
    assert "measurements" in assignments
    assert "laboratory_results" not in assignments
    candidate = _candidate(result, "public", "profilaxys_analyses", "measurements")
    assert candidate is not None
    assert candidate["data_level"] == "OBSERVATION_VALUE"


def test_analyses_pool_is_workflow_not_laboratory_results(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assert _role(result, "quest_digital", "analyses_pool") == "WORKFLOW"
    assert "laboratory_results" not in _assignments(result).get(("quest_digital", "analyses_pool"), set())


def test_analyses_constructor_has_observation_value_data_level(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    candidate = _candidate(result, "quest_digital", "analyses_constructor", "laboratory_results")
    assert candidate is not None
    assert candidate["data_level"] == "OBSERVATION_VALUE"


def test_lab_result_payload_candidate_with_empty_note(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    candidate = _candidate(result, "quest_digital", "lab_result", "laboratory_results")
    assert candidate is not None
    assert candidate["data_level"] == "PAYLOAD"
    assert any(ev.get("type") == "snapshot_note" for ev in candidate["evidence"])


def test_profilaxys_analyses_is_observation_candidate(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assert _role(result, "public", "profilaxys_analyses") == "OBSERVATION"
    assignments = _assignments(result).get(("public", "profilaxys_analyses"), set())
    assert "measurements" in assignments


def test_spatial_ref_sys_in_infrastructure(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    infra = {(item["schema"], item["relation"]) for item in result["infrastructure_inventory"]}
    assert ("public", "spatial_ref_sys") in infra

    unknown = {(item["schema"], item["relation"]) for item in result["unknown_relations"]}
    assert ("public", "spatial_ref_sys") not in unknown


def test_unknown_relations_use_unclassified_not_reference(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    assert all(item["role"] == "UNCLASSIFIED" for item in result["unknown_relations"])
    assert any(item["role"] == "REFERENCE" for item in result["role_classified_relations"])


def test_infrastructure_schemas_separated(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    infra_schemas = {item["schema"] for item in result["infrastructure_inventory"]}
    assert "tiger" in infra_schemas
    assert "topology" in infra_schemas

    unknown_schemas = {item["schema"] for item in result["unknown_relations"]}
    assert "tiger" not in unknown_schemas
    assert "topology" not in unknown_schemas


def test_heuristics_never_emit_confirmed(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    for items in result["entity_types"].values():
        for item in items:
            assert item["status"] == "CANDIDATE"


def test_regression_checks_all_pass(kgz_profile: dict, tmp_path: Path) -> None:
    result = classify_clinical_entities(kgz_profile, tmp_path)
    checks = run_classification_regression_checks(result)
    failed = [check for check in checks if check["status"] == "FAIL"]
    assert not failed, failed


@pytest.mark.skipif(not KGZ_PROFILE.exists(), reason="schema-profile-kgz.json not present")
def test_reclassify_second_source_updates_artifacts() -> None:
    result = reclassify_second_source(REPO_ROOT)
    assert result["status"] == "PASS"

    audit_path = ARTIFACTS_DIR / "source-b-audit.json"
    manifest_path = ARTIFACTS_DIR / MANIFEST_NAME
    assert audit_path.exists()
    assert manifest_path.exists()

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["status"] == "PASS"
    assert "source-b-audit.json" not in audit["artifact_hashes"]
    assert audit["manifest"] == MANIFEST_NAME
    assert len(audit["artifact_hashes"]) == 4

    manifest_ok, _ = verify_manifest(ARTIFACTS_DIR)
    assert manifest_ok

    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        path = ARTIFACTS_DIR / name.strip()
        assert path.exists()
        if name.strip() == "source-b-audit.json":
            assert digest != audit["artifact_hashes"].get("source-b-audit.json")
