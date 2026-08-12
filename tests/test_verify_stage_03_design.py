"""Tests for Stage 03 design verification."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from human_simulator.audit.report import REPORT_STATUS_DRAFT
from human_simulator.stage03.constants import DATA_LEVELS, REQUIRED_ENTITIES, STAGE03_CONTENT_ARTIFACTS
from human_simulator.stage03.canonical_id import (
    compute_hmac_hex,
    get_id_namespace_version,
    length_prefix_utf8,
    null_and_empty_distinct,
    validate_canonical_id_contract_document,
    validate_key_rotation_policy,
)
from human_simulator.stage03.construction_validator import (
    validate_construction_contract,
    validate_construction_group_completeness,
    validate_identity_algorithm,
)
from human_simulator.stage03.mapping_validator import (
    extract_entity_fields,
    validate_clinical_normalization_rules,
    validate_mapping_collisions,
    validate_mapping_draft,
    validate_mapping_record,
)
from human_simulator.stage03.model_validator import REQUIRED_CONSTRAINT_KEYS, validate_canonical_model
from human_simulator.stage03.preconditions import check_stage_03_preconditions, sha256_file
from human_simulator.stage03.review_bundle import BUNDLE_ZIP_NAME
from human_simulator.stage03.schema_index import load_schema_index
from human_simulator.stage03.verify_stage_03_design import (
    DESIGN_CONTENT_MANIFEST_NAME,
    DESIGN_REPORT_NAME,
    DESIGN_VERIFICATION_NAME,
    FORBIDDEN_IN_CONTENT_MANIFEST,
    LEGACY_MANIFEST_NAME,
    STAGE03_DESIGN_ARTIFACTS,
    _check_audit_chronology_from_disk,
    _check_canonical_id_contract,
    _publish_report,
    gate_pytest_filter_expr,
    verify_stage_03_design,
    _check_state_snapshot_contract,
    _verify_content_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE03_DIR = REPO_ROOT / "artifacts" / "stage-03"

INVALID_DRAFT_COLUMNS = [
    ("magerya_api.appointment_appointment", "start_datetime"),
    ("magerya_api.appointment_appointment", "end_datetime"),
    ("magerya_api.account_patient", "created_at"),
    ("quest_digital.analyses_constructor", "result"),
    ("public.consultations", "user_id"),
]


def test_stage_03_preconditions() -> None:
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 artifacts unavailable")
    ok, results = check_stage_03_preconditions(REPO_ROOT)
    assert ok, [(item.name, item.detail) for item in results if item.status == "FAIL"]


def test_all_design_artifacts_exist() -> None:
    if not STAGE03_DIR.exists():
        pytest.skip("stage-03 artifacts missing")
    for name in STAGE03_DESIGN_ARTIFACTS:
        assert (STAGE03_DIR / name).exists(), name
    assert (STAGE03_DIR / DESIGN_CONTENT_MANIFEST_NAME).exists()
    assert not (STAGE03_DIR / LEGACY_MANIFEST_NAME).exists()


def test_content_manifest_matches_stage03_content_artifacts() -> None:
    manifest_path = STAGE03_DIR / DESIGN_CONTENT_MANIFEST_NAME
    if not manifest_path.exists():
        pytest.skip("content manifest missing")
    entries = [line.split(maxsplit=1)[1].strip() for line in manifest_path.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == len(STAGE03_CONTENT_ARTIFACTS)
    assert set(entries) == set(STAGE03_CONTENT_ARTIFACTS)
    assert DESIGN_REPORT_NAME not in entries
    assert DESIGN_CONTENT_MANIFEST_NAME not in entries
    assert DESIGN_VERIFICATION_NAME not in entries
    ok, detail = _verify_content_manifest(manifest_path, STAGE03_DIR)
    assert ok, detail


def test_report_references_content_manifest_not_self() -> None:
    report = (STAGE03_DIR / DESIGN_REPORT_NAME).read_text(encoding="utf-8")
    manifest_hash = sha256_file(STAGE03_DIR / DESIGN_CONTENT_MANIFEST_NAME)
    assert manifest_hash in report
    assert not re.search(r"stage-03-design-report\.md[^\n`]*[`']?[0-9a-f]{64}", report, re.IGNORECASE)
    assert "Design artifact SHA-256" not in report


def test_verification_json_schema_and_no_self_hash() -> None:
    path = STAGE03_DIR / DESIGN_VERIFICATION_NAME
    if not path.exists():
        pytest.skip("verification json missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "overall_status",
        "checks_total",
        "checks_passed",
        "checks_failed",
        "checks",
        "failures",
        "pytest_command",
        "pytest_exit_code",
        "pytest_collected",
        "pytest_selected",
        "pytest_deselected",
        "pytest_passed",
        "pytest_failed",
        "pytest_skipped",
        "pytest_duration_seconds",
        "pytest_summary",
        "python_version",
        "content_manifest_sha256",
        "report_sha256",
        "verified_at",
    ):
        assert key in payload
    assert "verification_sha256" not in payload
    assert "/Volumes/" not in payload["pytest_command"]
    assert payload["report_sha256"] == sha256_file(STAGE03_DIR / DESIGN_REPORT_NAME)
    assert payload["content_manifest_sha256"] == sha256_file(STAGE03_DIR / DESIGN_CONTENT_MANIFEST_NAME)
    for forbidden in FORBIDDEN_IN_CONTENT_MANIFEST:
        assert forbidden not in (STAGE03_DIR / DESIGN_CONTENT_MANIFEST_NAME).read_text(encoding="utf-8")


def test_canonical_model_entities_and_layers() -> None:
    model = _load_model()
    assert set(model["layers"]) == {"evidence", "simulation_scenario", "prediction"}
    for entity in REQUIRED_ENTITIES:
        assert entity in model["entities"]
    assert set(model["data_level_enum"]) == set(DATA_LEVELS)


def test_predicted_state_has_generated_and_target_at() -> None:
    model = _load_model()
    fields = model["entities"]["PredictedState"]["fields"]
    assert "generated_at" in fields
    assert "target_at" in fields
    assert "predicted_at" not in fields
    assert "predicted_value" not in fields
    assert "point_estimate" not in fields
    assert "input_snapshot_id" not in fields
    assert "prediction_status" in fields
    typed = {"numeric_value", "text_value", "categorical_value", "boolean_value"}
    assert typed <= set(fields)


def test_v04_scenario_intervention_and_checkpoint_state() -> None:
    model = _load_model()
    entities = model["entities"]
    assert "ScenarioIntervention" in entities
    assert "ScenarioCheckpointState" in entities
    si = entities["ScenarioIntervention"]
    assert si["layer"] == "simulation_scenario"
    assert si["record_origin"] == "SYNTHETIC"
    assert "provenance" in si["fields"]
    event = entities["ScenarioEvent"]["fields"]
    assert "scenario_intervention_id" in event
    assert "intervention_id" not in event
    assert "effective_at" in event and event["effective_at"]["nullable"] is False
    run = entities["SimulationRun"]["fields"]
    assert "input_evidence_snapshot_id" in run
    assert "input_checkpoint_id" in run
    assert "input_state_reference" not in run
    assert "predicted_state_ids" not in entities["ScenarioCheckpoint"]["fields"]


def test_v04_variable_identity_fields() -> None:
    model = _load_model()
    comp = model["entities"]["StateSnapshotComponent"]["fields"]
    pred = model["entities"]["PredictedState"]["fields"]
    assert {"raw_code", "variable_key"} <= set(comp)
    assert {"raw_code", "variable_key", "missingness_reason"} <= set(comp)
    assert {"raw_code", "variable_key", "failure_reason"} <= set(pred)


def test_v04_documented_constraints_present() -> None:
    model = _load_model()
    for key in REQUIRED_CONSTRAINT_KEYS:
        assert key in model["constraints"], key


@pytest.mark.parametrize("constraint_key", sorted(REQUIRED_CONSTRAINT_KEYS))
def test_model_validator_fails_when_constraint_removed(constraint_key: str) -> None:
    model = copy.deepcopy(_load_model())
    del model["constraints"][constraint_key]
    errors = validate_canonical_model(model)
    assert any(error.name == f"constraint_{constraint_key}_missing" for error in errors), constraint_key


def test_model_validator_rejects_evidence_intervention_on_scenario_event() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["ScenarioEvent"]["fields"]["intervention_id"] = {}
    errors = validate_canonical_model(model)
    assert any(error.name == "scenario_event_no_evidence_intervention" for error in errors)


def test_model_validator_rejects_input_state_reference() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["SimulationRun"]["fields"]["input_state_reference"] = {}
    errors = validate_canonical_model(model)
    assert any(error.name == "simulation_run_no_input_state_reference" for error in errors)


def test_v03_snapshot_split_and_branch_fields() -> None:
    model = _load_model()
    entities = model["entities"]
    assert "StateSnapshot" not in entities
    assert "EvidenceStateSnapshot" in entities
    assert "ScenarioCheckpoint" in entities
    assert "StateSnapshotComponent" in entities

    ess = entities["EvidenceStateSnapshot"]
    assert ess["layer"] == "evidence"
    assert ess["record_origin"] in {"DERIVED", "IMPUTED"}
    assert "state_variables" not in ess["fields"]

    checkpoint = entities["ScenarioCheckpoint"]
    assert checkpoint["layer"] == "simulation_scenario"
    assert checkpoint["record_origin"] == "SYNTHETIC"

    branch_fields = entities["ScenarioBranch"]["fields"]
    assert "forked_from_branch_id" not in branch_fields
    for field in (
        "parent_branch_id",
        "created_at",
        "forked_at_timeline",
        "baseline_snapshot_id",
        "checkpoint_id",
        "forked_from_event_id",
    ):
        assert field in branch_fields


def test_state_snapshot_component_structured_fields() -> None:
    model = _load_model()
    fields = model["entities"]["StateSnapshotComponent"]["fields"]
    required = {
        "component_id",
        "snapshot_id",
        "concept_id",
        "raw_value",
        "numeric_value",
        "text_value",
        "categorical_value",
        "boolean_value",
        "raw_unit",
        "normalized_unit",
        "source_observation_ids",
        "missingness_status",
        "confidence",
        "uncertainty",
        "provenance",
    }
    assert required <= set(fields)


def test_simulation_run_reproducibility_fields() -> None:
    model = _load_model()
    fields = model["entities"]["SimulationRun"]["fields"]
    required = {
        "model_id",
        "model_version",
        "model_artifact_hash",
        "configuration_hash",
        "input_evidence_snapshot_id",
        "input_checkpoint_id",
        "random_seed",
        "started_at",
        "completed_at",
        "run_status",
        "deterministic_model",
        "provenance",
    }
    assert required <= set(fields)
    assert "input_state_reference" not in fields


def test_scenario_event_typed_fields() -> None:
    model = _load_model()
    fields = model["entities"]["ScenarioEvent"]["fields"]
    assert "payload" not in fields
    assert "intervention_id" not in fields
    assert "scenario_intervention_id" in fields
    for field in (
        "event_action",
        "scenario_intervention_id",
        "dose",
        "dose_unit",
        "frequency",
        "adherence_pattern",
        "effective_at",
        "effective_until",
        "extension_payload",
        "extension_namespace",
        "extension_schema_version",
    ):
        assert field in fields


def test_model_validator_passes_on_canonical_model() -> None:
    errors = validate_canonical_model(_load_model())
    assert not errors, [error.detail for error in errors]


def test_model_validator_rejects_legacy_state_snapshot() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["StateSnapshot"] = {
        "layer": "simulation_scenario",
        "record_origin": "DERIVED",
        "fields": {"snapshot_id": {}},
    }
    errors = validate_canonical_model(model)
    assert any(error.name == "legacy_state_snapshot" for error in errors)


def test_model_validator_rejects_derived_in_simulation_checkpoint() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["ScenarioCheckpoint"]["record_origin"] = "DERIVED"
    errors = validate_canonical_model(model)
    assert any(error.name in {"record_origin_layer_match", "scenario_checkpoint_synthetic_only"} for error in errors)


def test_model_validator_rejects_duplicate_fork_field() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["ScenarioBranch"]["fields"]["forked_from_branch_id"] = {}
    errors = validate_canonical_model(model)
    assert any(error.name == "branch_no_duplicate_fork_field" for error in errors)


def test_model_validator_rejects_predicted_value_string() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["PredictedState"]["fields"]["predicted_value"] = {}
    errors = validate_canonical_model(model)
    assert any(error.name == "predicted_state_shape" for error in errors)


def test_model_validator_rejects_generic_event_payload() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["ScenarioEvent"]["fields"]["payload"] = {}
    errors = validate_canonical_model(model)
    assert any(error.name == "scenario_event_typed_fields" for error in errors)


def test_model_validator_rejects_record_origin_layer_mismatch() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["ScenarioCheckpoint"]["record_origin"] = "DERIVED"
    errors = validate_canonical_model(model)
    assert any(error.name == "record_origin_layer_match" for error in errors)


def test_model_validator_rejects_inheritance_cycle() -> None:
    model = copy.deepcopy(_load_model())
    model["entities"]["Intervention"]["extends"] = "MedicationExposure"
    errors = validate_canonical_model(model)
    assert any(error.name == "inheritance_cycle" for error in errors)


def test_provenance_discriminated_profiles() -> None:
    provenance = yaml.safe_load(
        (STAGE03_DIR / "provenance-contract.yaml").read_text(encoding="utf-8")
    )
    profiles = provenance["profiles"]
    assert "source_record_locator" in profiles["SOURCE_BACKED"]["required_fields"]
    assert "source_record_locator" in profiles["SCENARIO"]["forbidden_fields"]
    assert "source_record_locator" in profiles["MODEL_OUTPUT"]["forbidden_fields"]
    normalized = provenance["origin_specific_rules"]["NORMALIZED"]
    assert "correction_history_ref" in normalized["must_not_require"]


def test_invalid_phantom_columns_fail_validation() -> None:
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    model = _load_model()
    entity_fields = extract_entity_fields(model)
    index_a = load_schema_index(REPO_ROOT / "artifacts" / "stage-01" / "schema-profile.json")
    index_b = load_schema_index(REPO_ROOT / "artifacts" / "stage-02" / "schema-profile-kgz.json")

    for relation, column in INVALID_DRAFT_COLUMNS:
        schema_index = index_b if relation.startswith(("public.", "quest_digital.")) else index_a
        errors = validate_mapping_record(
            draft_name="test",
            index=0,
            mapping={
                "source_relation": relation,
                "source_column": column,
                "canonical_entity": "Encounter",
                "canonical_field": "encounter_id",
                "mapping_status": "HYPOTHESIS",
                "data_level": "PATIENT_EVENT",
                "transformation": "test",
                "evidence": "test",
                "lossiness": "test",
            },
            schema_index=schema_index,
            entity_fields=entity_fields,
        )
        assert errors, f"expected failure for {relation}.{column}"


def test_wildcard_mapping_forbidden() -> None:
    model = _load_model()
    entity_fields = extract_entity_fields(model)
    index_a = load_schema_index(REPO_ROOT / "artifacts" / "stage-01" / "schema-profile.json")
    errors = validate_mapping_record(
        draft_name="test",
        index=0,
        mapping={
            "source_relation": "magerya_api.diagnosis_diagnosis",
            "source_column": "*",
            "canonical_entity": "Concept",
            "canonical_field": "source_concept_key",
            "mapping_status": "CONFIRMED_SCHEMA",
            "data_level": "REFERENCE_CATALOG",
            "transformation": "test",
            "evidence": "test",
            "lossiness": "test",
        },
        schema_index=index_a,
        entity_fields=entity_fields,
    )
    assert any("wildcard" in error.message for error in errors)


def test_source_mapping_integrity_live_drafts() -> None:
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    model = _load_model()
    entity_fields = extract_entity_fields(model)
    draft_a = yaml.safe_load((STAGE03_DIR / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))
    draft_b = yaml.safe_load((STAGE03_DIR / "source-b-mapping-draft.yaml").read_text(encoding="utf-8"))
    contract = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    index_a = load_schema_index(REPO_ROOT / "artifacts" / "stage-01" / "schema-profile.json")
    index_b = load_schema_index(REPO_ROOT / "artifacts" / "stage-02" / "schema-profile-kgz.json")
    errors_a = validate_mapping_draft("source-a", draft_a, index_a, entity_fields, contract)
    errors_b = validate_mapping_draft("source-b", draft_b, index_b, entity_fields, contract)
    assert not errors_a, [error.as_text() for error in errors_a[:5]]
    assert not errors_b, [error.as_text() for error in errors_b[:5]]


def test_public_persons_not_subject_root_candidate() -> None:
    draft_b = yaml.safe_load((STAGE03_DIR / "source-b-mapping-draft.yaml").read_text(encoding="utf-8"))
    persons = next(m for m in draft_b["mappings"] if m["source_relation"] == "public.persons")
    assert persons["mapping_status"] == "NOT_MAPPED"
    assert "NO_SUBJECT_ROOT" in persons["evidence"]


def test_unresolved_mappings_preserved() -> None:
    crosswalk = yaml.safe_load(
        (REPO_ROOT / "artifacts/stage-02/entity-crosswalk.yaml").read_text(encoding="utf-8")
    )
    decisions = (STAGE03_DIR / "unresolved-design-decisions.md").read_text(encoding="utf-8")
    for item in crosswalk["unresolved_mappings"]:
        assert item in decisions


def test_report_remains_draft() -> None:
    report = (STAGE03_DIR / DESIGN_REPORT_NAME).read_text(encoding="utf-8")
    assert f"**Report status:** {REPORT_STATUS_DRAFT}" in report


def test_verify_stage_03_design_passes() -> None:
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    result = verify_stage_03_design(REPO_ROOT, run_pytest=False, publish_artifacts=False)
    assert result["status"] == "PASS", result.get("failures")
    assert result["checks_failed"] == 0


def test_v05_subject_characteristic_entity() -> None:
    model = _load_model()
    assert "SubjectCharacteristic" in model["entities"]
    assert "SubjectCharacteristic" in REQUIRED_ENTITIES
    assert len(REQUIRED_ENTITIES) == 29
    fields = model["entities"]["SubjectCharacteristic"]["fields"]
    for field in (
        "characteristic_id",
        "subject_id",
        "characteristic_code",
        "concept_id",
        "raw_value",
        "date_value",
        "categorical_value",
        "status",
        "provenance",
    ):
        assert field in fields


def test_v05_state_snapshot_contract_artifact_exists() -> None:
    path = STAGE03_DIR / "state-snapshot-contract.yaml"
    assert path.exists()
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert contract.get("source_event_cutoff", {}).get("required") is True
    assert contract.get("no_future_leakage")
    assert contract.get("age_at_snapshot", {}).get("rule")
    versioning = contract.get("deterministic_construction", {}).get("versioning", {})
    assert "snapshot_builder_version" in versioning
    assert "input_artifact_hashes" in versioning


def test_model_validator_fails_when_subject_characteristic_removed() -> None:
    model = copy.deepcopy(_load_model())
    del model["entities"]["SubjectCharacteristic"]
    errors = validate_canonical_model(model)
    assert any(error.name == "subjectcharacteristic_present" for error in errors)


def test_model_validator_fails_when_scenario_event_precedence_removed() -> None:
    model = copy.deepcopy(_load_model())
    del model["constraints"]["scenario_event_precedence_contract"]
    errors = validate_canonical_model(model)
    assert any(error.name == "constraint_scenario_event_precedence_contract_missing" for error in errors)


def test_mapping_validator_rejects_biological_sex_without_evidence() -> None:
    errors = validate_clinical_normalization_rules(
        draft_name="test",
        index=0,
        mapping={
            "source_relation": "magerya_api.account_patient",
            "source_column": "sex",
            "canonical_entity": "SubjectCharacteristic",
            "canonical_field": "categorical_value",
            "characteristic_code": "biological_sex",
            "mapping_status": "CANDIDATE",
            "data_level": "ATTRIBUTE_CONTAINER",
            "transformation": "normalize_to_biological_sex",
            "evidence": "test",
            "lossiness": "test",
        },
    )
    assert errors


def test_stage_03_doc_sync_no_legacy_manifest_reference() -> None:
    paths = [
        REPO_ROOT / "docs/stage-03.md",
        REPO_ROOT / "docs/stage-03-acceptance.md",
        REPO_ROOT / "docs/current-stage.md",
        REPO_ROOT / ".cursor/rules/07-canonical-model.mdc",
        REPO_ROOT / ".cursor/skills/design-canonical-model/SKILL.md",
        REPO_ROOT / ".cursor/skills/verify-stage-03-design/SKILL.md",
        REPO_ROOT / ".cursor/commands/stage-03-check.md",
        REPO_ROOT / ".cursor/commands/stage-03-start.md",
    ]
    legacy = "design-manifest.sha256"
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if legacy in line and "no stale" in line.lower():
                continue
            if legacy in line and "legacy" in line.lower():
                continue
            assert legacy not in line, f"{path.name}: {line.strip()}"
        assert "22 required" not in text.lower(), path.name


def test_state_snapshot_contract_checks_fail_when_cutoff_removed() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "state-snapshot-contract.yaml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(contract)
    mutated["source_event_cutoff"] = {"required": False}
    checks: list = []

    def add(check: object) -> None:
        checks.append(check)

    _check_state_snapshot_contract(add, mutated)
    assert any(c.name == "state_snapshot_cutoff_required" and c.status == "FAIL" for c in checks)


def test_state_snapshot_contract_checks_fail_when_age_rule_removed() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "state-snapshot-contract.yaml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(contract)
    del mutated["age_at_snapshot"]
    checks: list = []

    def add(check: object) -> None:
        checks.append(check)

    _check_state_snapshot_contract(add, mutated)
    assert any(c.name == "state_snapshot_age_at_snapshot_rule" and c.status == "FAIL" for c in checks)


def test_stage03_content_artifacts_includes_canonical_id_contract() -> None:
    assert "canonical-id-contract.yaml" in STAGE03_CONTENT_ARTIFACTS
    assert "record-construction-contract.yaml" in STAGE03_CONTENT_ARTIFACTS
    assert len(STAGE03_CONTENT_ARTIFACTS) == 12


def test_documented_entity_count_matches_canonical_model() -> None:
    model = _load_model()
    assert len(REQUIRED_ENTITIES) == 29
    assert all(entity in model["entities"] for entity in REQUIRED_ENTITIES)
    acceptance = (REPO_ROOT / "docs/stage-03-acceptance.md").read_text(encoding="utf-8")
    assert "29 required canonical entities" in acceptance
    stage03 = (REPO_ROOT / "docs/stage-03.md").read_text(encoding="utf-8")
    assert "29 required entities" in stage03


def test_v06_record_construction_contract_exists() -> None:
    path = STAGE03_DIR / "record-construction-contract.yaml"
    assert path.exists()
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    group_ids = {g["group_id"] for g in contract["construction_groups"]}
    assert "source_a_account_patient_characteristics" in group_ids
    assert "source_b_profilaxys_profile_observation_components" in group_ids


def test_construction_validator_passes_on_contract() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    errors = validate_construction_contract(
        contract,
        model,
        schema_index_a=index_a,
        schema_index_b=index_b,
        canonical_id_contract=canonical_id,
    )
    assert not errors, [error.detail for error in errors]


def _source_record_group(contract: dict[str, Any]) -> dict[str, Any]:
    return next(g for g in contract["construction_groups"] if g["group_id"] == "source_a_source_record_account_patient")


@pytest.mark.parametrize(
    ("mutator_name", "mutator"),
    [
        (
            "source_system_id",
            lambda g: g["relationship_fields"].pop("source_system_id"),
        ),
        (
            "source_relation",
            lambda g: g["constant_fields"].pop("source_relation"),
        ),
        (
            "locator_key_version",
            lambda g: g["constant_fields"].pop("locator_key_version"),
        ),
        (
            "source_record_locator",
            lambda g: g["generated_fields"].pop("source_record_locator"),
        ),
        (
            "provenance",
            lambda g: g.pop("provenance_profile"),
        ),
    ],
)
def test_source_record_field_mutation_fails_coverage(mutator_name: str, mutator: Any) -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = _source_record_group(mutated)
    mutator(group)
    errors = validate_construction_contract(
        mutated,
        model,
        schema_index_a=index_a,
        schema_index_b=index_b,
        canonical_id_contract=canonical_id,
    )
    assert errors, mutator_name
    assert any(
        mutator_name in error.detail or "missing required fields" in error.detail or "provenance" in error.detail
        for error in errors
    )


def test_source_record_groups_have_explicit_system_and_relation() -> None:
    _, contract, _, _, _ = _load_construction_bundle()
    groups = [g for g in contract["construction_groups"] if g.get("target_entity") == "SourceRecord"]
    assert len(groups) == 4
    for group in groups:
        assert group["relationship_fields"].get("source_system_id", {}).get("pilot_value") == "magerya_api"
        relation = group["constant_fields"]["source_relation"]
        assert "." not in relation
        assert relation in {
            "account_patient",
            "appointment_appointment",
            "document_analysisresult",
            "document_analysisresultitem",
        }


def test_construction_validator_fails_without_characteristic_id_generation() -> None:
    model = _load_model()
    contract = yaml.safe_load(
        (STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8")
    )
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_a_account_patient_characteristics")
    del group["identity_rule"]["characteristic_id"]
    del group["generated_fields"]["characteristic_id"]
    errors = validate_construction_contract(mutated, model)
    assert errors


def test_construction_validator_fails_without_subject_resolution() -> None:
    model = _load_model()
    contract = yaml.safe_load(
        (STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8")
    )
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_a_account_patient_characteristics")
    del group["subject_resolution"]
    errors = validate_construction_contract(mutated, model)
    assert errors


def test_construction_validator_fails_without_raw_value_serialization() -> None:
    model = _load_model()
    contract = yaml.safe_load(
        (STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8")
    )
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_a_account_patient_characteristics")
    del group["raw_value_serialization"]
    errors = validate_construction_contract(mutated, model)
    assert errors


def test_construction_validator_fails_without_provenance_profile() -> None:
    model = _load_model()
    contract = yaml.safe_load(
        (STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8")
    )
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_a_account_patient_characteristics")
    del group["provenance_profile"]
    errors = validate_construction_contract(mutated, model)
    assert errors


def test_construction_validator_fails_without_component_raw_code() -> None:
    model = _load_model()
    contract = yaml.safe_load(
        (STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8")
    )
    mutated = copy.deepcopy(contract)
    group = next(
        g for g in mutated["construction_groups"]
        if g["group_id"] == "source_b_profilaxys_profile_observation_components"
    )
    group["mapped_fields"][0]["raw_code"] = None
    entity_fields = extract_entity_fields(model)
    errors = validate_construction_group_completeness(group, entity_fields)
    assert any("raw_code" in error.detail for error in errors)


def test_construction_validator_fails_without_parent_observation_id() -> None:
    model = _load_model()
    contract = yaml.safe_load(
        (STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8")
    )
    mutated = copy.deepcopy(contract)
    group = next(
        g for g in mutated["construction_groups"]
        if g["group_id"] == "source_b_profilaxys_profile_observation_components"
    )
    group["relationship_fields"] = {}
    entity_fields = extract_entity_fields(model)
    errors = validate_construction_group_completeness(group, entity_fields)
    assert any("observation_id" in error.detail for error in errors)


def test_mapping_collisions_fail_without_precedence_rule() -> None:
    draft = {
        "mappings": [
            {
                "source_relation": "public.profilaxys_profile",
                "source_column": "created_at",
                "canonical_entity": "Observation",
                "canonical_field": "recorded_at",
                "mapping_status": "HYPOTHESIS",
                "data_level": "OBSERVATION_HEADER",
                "transformation": "a",
                "evidence": "a",
                "lossiness": "a",
            },
            {
                "source_relation": "public.profilaxys_profile",
                "source_column": "updated_at",
                "canonical_entity": "Observation",
                "canonical_field": "recorded_at",
                "mapping_status": "HYPOTHESIS",
                "data_level": "OBSERVATION_HEADER",
                "transformation": "b",
                "evidence": "b",
                "lossiness": "b",
            },
        ]
    }
    errors = validate_mapping_collisions("test", draft, None)
    assert errors


def test_subject_characteristic_identity_allows_code_and_concept() -> None:
    model = _load_model()
    identity = model["constraints"]["subject_characteristic_identity"]
    assert identity.get("both_allowed") is True
    assert "XOR" in identity.get("forbidden", "")


def test_snapshot_contract_age_lineage_requires_birthdate_reference() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "state-snapshot-contract.yaml").read_text(encoding="utf-8"))
    lineage = contract["age_at_snapshot"]["lineage"]
    assert lineage["required_reference"]["characteristic_code"] == "source_birthdate"
    checks: list = []

    def add(check: object) -> None:
        checks.append(check)

    _check_state_snapshot_contract(add, contract)
    assert any(c.name == "state_snapshot_age_birthdate_lineage" and c.status == "PASS" for c in checks)


def test_snapshot_contract_fails_age_lineage_without_birthdate_reference() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "state-snapshot-contract.yaml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(contract)
    del mutated["age_at_snapshot"]["lineage"]
    checks: list = []

    def add(check: object) -> None:
        checks.append(check)

    _check_state_snapshot_contract(add, mutated)
    assert any(c.name == "state_snapshot_age_birthdate_lineage" and c.status == "FAIL" for c in checks)


def test_construction_null_policy_forbids_empty_substitution() -> None:
    contract = yaml.safe_load(
        (STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8")
    )
    forbidden = contract["global_rules"]["null_emission_policy"]["forbidden"]
    assert "empty_string_substitution" in forbidden


def _load_construction_bundle() -> tuple[dict, dict, dict, Any, Any]:
    model = _load_model()
    contract = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    canonical_id = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    index_a = load_schema_index(REPO_ROOT / "artifacts" / "stage-01" / "schema-profile.json")
    index_b = load_schema_index(REPO_ROOT / "artifacts" / "stage-02" / "schema-profile-kgz.json")
    return model, contract, canonical_id, index_a, index_b


def test_v07_construction_groups_present() -> None:
    _, contract, _, _, _ = _load_construction_bundle()
    group_ids = {g["group_id"] for g in contract["construction_groups"]}
    for required in (
        "source_a_appointment_encounter",
        "source_a_observation_component",
        "source_b_consultations_encounter",
        "source_b_lab_observation_header",
        "source_b_analyses_constructor_component",
    ):
        assert required in group_ids, required


def test_source_b_users_subject_forbids_row_filter_always() -> None:
    _, contract, _, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_b_users_subject")
    group["row_filter"] = "always"
    model = _load_model()
    errors = validate_construction_contract(mutated, model, schema_index_a=index_a, schema_index_b=index_b)
    assert any("users_unconditional" in error.name or "unconditional" in error.detail for error in errors)


def test_construction_validator_fails_nonexistent_source_relation() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = mutated["construction_groups"][0]
    group["source_relation"] = "magerya_api.nonexistent_table"
    errors = validate_construction_contract(
        mutated, model, schema_index_a=index_a, schema_index_b=index_b, canonical_id_contract=canonical_id
    )
    assert errors


def test_construction_validator_fails_nonexistent_source_primary_key() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = mutated["construction_groups"][0]
    group["source_primary_key"] = "nonexistent_pk"
    errors = validate_construction_contract(
        mutated, model, schema_index_a=index_a, schema_index_b=index_b, canonical_id_contract=canonical_id
    )
    assert errors


def test_construction_validator_fails_nonexistent_mapped_column() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_a_account_patient_characteristics")
    group["mapped_fields"][0]["source_column"] = "nonexistent_column"
    errors = validate_construction_contract(
        mutated, model, schema_index_a=index_a, schema_index_b=index_b, canonical_id_contract=canonical_id
    )
    assert errors


def test_construction_validator_fails_nonexistent_parent_group() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_a_observation_component")
    group["parent_group"] = "nonexistent_parent"
    errors = validate_construction_contract(
        mutated, model, schema_index_a=index_a, schema_index_b=index_b, canonical_id_contract=canonical_id
    )
    assert errors


def test_construction_validator_fails_nonexistent_subject_group() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_b_users_profile_characteristics")
    group["subject_resolution"]["subject_group"] = "missing_subject_group"
    errors = validate_construction_contract(
        mutated, model, schema_index_a=index_a, schema_index_b=index_b, canonical_id_contract=canonical_id
    )
    assert errors


def test_construction_validator_fails_undefined_mapping_record_group() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    draft_a = yaml.safe_load((STAGE03_DIR / "source-a-mapping-draft.yaml").read_text(encoding="utf-8"))
    mutated_draft = copy.deepcopy(draft_a)
    mutated_draft["mappings"][0]["record_group"] = "nonexistent_record_group"
    errors = validate_construction_contract(
        contract,
        model,
        schema_index_a=index_a,
        schema_index_b=index_b,
        canonical_id_contract=canonical_id,
        mapping_drafts={"source-a-mapping-draft.yaml": mutated_draft},
    )
    assert errors


def test_mapping_collisions_fail_record_group_only() -> None:
    draft = {
        "mappings": [
            {
                "source_relation": "public.profilaxys_profile",
                "source_column": "created_at",
                "canonical_entity": "Observation",
                "canonical_field": "recorded_at",
                "mapping_status": "HYPOTHESIS",
                "data_level": "OBSERVATION_HEADER",
                "transformation": "a",
                "evidence": "a",
                "lossiness": "a",
                "record_group": "source_b_profilaxys_profile_observation",
            },
            {
                "source_relation": "public.profilaxys_profile",
                "source_column": "updated_at",
                "canonical_entity": "Observation",
                "canonical_field": "recorded_at",
                "mapping_status": "HYPOTHESIS",
                "data_level": "OBSERVATION_HEADER",
                "transformation": "b",
                "evidence": "b",
                "lossiness": "b",
                "record_group": "source_b_profilaxys_profile_observation",
            },
        ]
    }
    contract = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(contract)
    mutated["target_collision_rules"] = [
        rule for rule in mutated["target_collision_rules"] if rule.get("name") != "source_b_profilaxys_recorded_at"
    ]
    errors = validate_mapping_collisions("test", draft, mutated)
    assert errors
    assert any("record_group alone" in error.message for error in errors)


def test_mapping_collisions_fail_incomplete_source_columns() -> None:
    draft = {
        "mappings": [
            {
                "source_relation": "magerya_api.appointment_appointment",
                "source_column": "next_appointment_date",
                "canonical_entity": "Encounter",
                "canonical_field": "missingness_reason",
                "mapping_status": "UNRESOLVED",
                "data_level": "PATIENT_EVENT",
                "transformation": "defer",
                "grouping_rule": "encounter_missingness_evidence",
                "record_group": "source_a_appointment_encounter",
                "evidence": "a",
                "lossiness": "a",
            },
            {
                "source_relation": "magerya_api.appointment_appointment",
                "source_column": "chat_end_time",
                "canonical_entity": "Encounter",
                "canonical_field": "missingness_reason",
                "mapping_status": "UNRESOLVED",
                "data_level": "PATIENT_EVENT",
                "transformation": "defer",
                "grouping_rule": "encounter_missingness_evidence",
                "record_group": "source_a_appointment_encounter",
                "evidence": "b",
                "lossiness": "b",
            },
        ]
    }
    contract = yaml.safe_load((STAGE03_DIR / "record-construction-contract.yaml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(contract)
    for rule in mutated["target_collision_rules"]:
        if rule.get("name") == "source_a_appointment_missingness_evidence":
            rule["source_columns"] = ["next_appointment_date"]
    errors = validate_mapping_collisions("test", draft, mutated)
    assert errors
    assert any("incomplete" in error.message or "source_columns" in error.message for error in errors)


def test_construction_validator_fails_random_uuid_algorithm() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_a_account_patient_subject")
    group["identity_rule"]["subject_id"]["algorithm"] = "random_uuid"
    errors = validate_construction_contract(
        mutated, model, schema_index_a=index_a, schema_index_b=index_b, canonical_id_contract=canonical_id
    )
    assert any("forbidden" in error.detail or "unknown" in error.detail for error in errors)


def test_construction_validator_fails_missing_provenance_population() -> None:
    model, contract, canonical_id, index_a, index_b = _load_construction_bundle()
    mutated = copy.deepcopy(contract)
    group = next(g for g in mutated["construction_groups"] if g["group_id"] == "source_a_source_record_account_patient")
    del group["provenance_population"]
    errors = validate_construction_contract(
        mutated, model, schema_index_a=index_a, schema_index_b=index_b, canonical_id_contract=canonical_id
    )
    assert any("provenance_population" in error.detail for error in errors)


def test_canonical_id_contract_rejects_unknown_algorithm() -> None:
    canonical_id = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    errors = validate_identity_algorithm(
        {"subject_id": {"algorithm": "unknown_algo", "inputs": ["a"]}},
        canonical_id_contract=canonical_id,
        group_id="test_group",
    )
    assert errors


def test_mapping_record_fails_nonexistent_column() -> None:
    model = _load_model()
    entity_fields = extract_entity_fields(model)
    index_a = load_schema_index(REPO_ROOT / "artifacts" / "stage-01" / "schema-profile.json")
    mapping = {
        "source_relation": "magerya_api.appointment_appointment",
        "source_column": "nonexistent_column",
        "canonical_entity": "Encounter",
        "canonical_field": "encounter_id",
        "mapping_status": "CANDIDATE",
        "data_level": "PATIENT_EVENT",
    }
    errors = validate_mapping_record(
        draft_name="test",
        index=0,
        mapping=mapping,
        schema_index=index_a,
        entity_fields=entity_fields,
    )
    assert errors


    assert errors


def _stage03_tree_sha256() -> dict[str, str]:
    return {str(path.relative_to(STAGE03_DIR)): sha256_file(path) for path in sorted(STAGE03_DIR.rglob("*")) if path.is_file()}


def test_verify_without_publish_is_side_effect_free() -> None:
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    before = _stage03_tree_sha256()
    verify_stage_03_design(REPO_ROOT, run_pytest=False, publish_artifacts=False)
    after = _stage03_tree_sha256()
    assert before == after


def test_gate_return_matches_on_disk_design_verification_when_present() -> None:
    verification_path = STAGE03_DIR / DESIGN_VERIFICATION_NAME
    if not verification_path.exists():
        pytest.skip("verification artifact missing")
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    on_disk = json.loads(verification_path.read_text(encoding="utf-8"))
    result = verify_stage_03_design(REPO_ROOT, run_pytest=False, publish_artifacts=False)
    assert result["status"] == on_disk["overall_status"]
    assert result["checks_total"] == on_disk["checks_total"]
    assert result["checks_passed"] == on_disk["checks_passed"]
    assert result["checks_failed"] == on_disk["checks_failed"]
    assert len(result["checks"]) == on_disk["checks_total"]


def test_published_verification_matches_final_report_bytes(isolated_workspace: Path) -> None:
    """Publishing writes a verification whose report_sha256 describes the report it wrote.

    Runs in a throwaway copy: publishing into the working tree is what produced the v0.2
    bundle defect, where a test regenerated the Design evidence that then shipped.
    """
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    stage03 = isolated_workspace / "artifacts" / "stage-03"

    verify_stage_03_design(isolated_workspace, run_pytest=False, publish_artifacts=True)

    payload = json.loads((stage03 / DESIGN_VERIFICATION_NAME).read_text(encoding="utf-8"))
    assert payload["report_sha256"] == sha256_file(stage03 / DESIGN_REPORT_NAME)


def test_full_pytest_suite_preserves_publication_artifacts(isolated_workspace: Path) -> None:
    """A published snapshot survives a full run of this file, byte for byte."""
    if not _prior_stages_ready():
        pytest.skip("Stage 01/02 unavailable")
    stage03 = isolated_workspace / "artifacts" / "stage-03"
    paths = [
        stage03 / DESIGN_REPORT_NAME,
        stage03 / DESIGN_CONTENT_MANIFEST_NAME,
        stage03 / DESIGN_VERIFICATION_NAME,
    ]

    verify_stage_03_design(isolated_workspace, run_pytest=False, publish_artifacts=True)
    before = {path.name: sha256_file(path) for path in paths}

    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_verify_stage_03_design.py",
            "-q",
            "-k",
            # The audited-evidence assertion describes the publisher workspace. This copy has
            # just been republished on purpose, so it cannot hold those bytes.
            f"{gate_pytest_filter_expr()}"
            " and not test_full_pytest_suite_preserves_publication_artifacts"
            " and not test_the_working_tree_carries_the_audited_design_evidence",
        ],
        cwd=isolated_workspace,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    assert {path.name: sha256_file(path) for path in paths} == before
    payload = json.loads((stage03 / DESIGN_VERIFICATION_NAME).read_text(encoding="utf-8"))
    assert payload["report_sha256"] == sha256_file(stage03 / DESIGN_REPORT_NAME)


def test_chronology_fails_when_report_after_verified() -> None:
    checks: list = []

    def add(check: object) -> None:
        checks.append(check)

    report_path = STAGE03_DIR / DESIGN_REPORT_NAME
    verification_path = STAGE03_DIR / DESIGN_VERIFICATION_NAME
    if not report_path.exists() or not verification_path.exists():
        pytest.skip("publication artifacts missing")
    original_report = report_path.read_text(encoding="utf-8")
    original_verification = verification_path.read_text(encoding="utf-8")
    try:
        mutated_report = re.sub(
            r"^Generated: .+$",
            "Generated: 2099-01-01T00:00:00+00:00",
            original_report,
            count=1,
            flags=re.MULTILINE,
        )
        report_path.write_text(mutated_report, encoding="utf-8")
        _check_audit_chronology_from_disk(
            add,
            repo_root=REPO_ROOT,
            report_path=report_path,
            verification_path=verification_path,
            review_bundle_generated_at=None,
        )
        assert any(c.name == "audit_chronology_report_before_verified" and c.status == "FAIL" for c in checks)
    finally:
        report_path.write_text(original_report, encoding="utf-8")
        verification_path.write_text(original_verification, encoding="utf-8")


def test_chronology_fails_when_report_changed_after_verification() -> None:
    if not (STAGE03_DIR / DESIGN_VERIFICATION_NAME).exists():
        pytest.skip("verification json missing")
    payload = json.loads((STAGE03_DIR / DESIGN_VERIFICATION_NAME).read_text(encoding="utf-8"))
    report_path = STAGE03_DIR / DESIGN_REPORT_NAME
    original = report_path.read_text(encoding="utf-8")
    try:
        report_path.write_text(original + "\n", encoding="utf-8")
        assert payload["report_sha256"] != sha256_file(report_path)
    finally:
        report_path.write_text(original, encoding="utf-8")


def test_chronology_skips_review_bundle_checks_without_timestamp() -> None:
    checks: list = []

    def add(check: object) -> None:
        checks.append(check)

    report_path = STAGE03_DIR / DESIGN_REPORT_NAME
    verification_path = STAGE03_DIR / DESIGN_VERIFICATION_NAME
    if not report_path.exists() or not verification_path.exists():
        pytest.skip("publication artifacts missing")

    _check_audit_chronology_from_disk(
        add,
        repo_root=REPO_ROOT,
        report_path=report_path,
        verification_path=verification_path,
        review_bundle_generated_at=None,
        include_review_bundle=True,
    )
    names = {c.name for c in checks}
    assert "audit_chronology_review_bundle_timestamp_present" not in names
    assert "audit_chronology_verified_before_review_bundle" not in names


def test_canonical_id_null_and_empty_serialize_differently() -> None:
    assert null_and_empty_distinct()
    assert length_prefix_utf8(None) != length_prefix_utf8("")


def test_canonical_id_contract_executable_vectors_pass() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    errors = validate_canonical_id_contract_document(contract)
    assert not errors, [error.detail for error in errors]


def test_canonical_id_contract_fails_wrong_expected_hex() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(contract)
    mutated["test_vectors"]["vectors"][0]["expected_hex"] = "0" * 64
    errors = validate_canonical_id_contract_document(mutated)
    assert errors


def test_canonical_id_contract_fails_null_empty_same_encoding() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(contract)
    mutated["canonical_id_contract"]["input_fields"]["null_encoding"] = "empty_utf8_string"
    errors = validate_canonical_id_contract_document(mutated)
    assert any("null" in error.detail.lower() for error in errors)


def test_canonical_id_contract_fails_missing_message_layout() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    mutated = copy.deepcopy(contract)
    del mutated["canonical_id_contract"]["message_layout"]
    errors = validate_canonical_id_contract_document(mutated)
    assert any("message_layout" in error.name for error in errors)


def test_canonical_id_identity_rule_fails_wrong_contract_reference() -> None:
    canonical_id = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    errors = validate_identity_algorithm(
        {
            "subject_id": {
                "algorithm": "HMAC-SHA256",
                "contract": "canonical_id_contract_wrong",
                "key_reference": "canonical_id_key_v1",
                "inputs": ["a"],
            }
        },
        canonical_id_contract=canonical_id,
        group_id="test_group",
    )
    assert any("contract_ref" in error.name for error in errors)


def test_canonical_id_identity_rule_fails_wrong_key_reference() -> None:
    canonical_id = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    errors = validate_identity_algorithm(
        {
            "subject_id": {
                "algorithm": "HMAC-SHA256",
                "contract": "canonical_id_contract_v0.7.4",
                "key_reference": "wrong_key",
                "inputs": ["a"],
            }
        },
        canonical_id_contract=canonical_id,
        group_id="test_group",
    )
    assert any("key_ref" in error.name for error in errors)


def _review_bundle_path() -> Path:
    return REPO_ROOT / "artifacts" / "external-review" / BUNDLE_ZIP_NAME


def test_review_bundle_contains_a_self_consistent_verification() -> None:
    """The archived verification must describe the report archived beside it.

    This used to compare the archived verification against the working tree instead. That
    assumption failed once concurrent test runs rewrote Stage 03 evidence: the v0.7.4 archive in
    this workspace carries a regenerated pair, while the working tree carries the bytes the
    external audit accepted. Whether the archive agrees with the working tree is not what makes
    the evidence valid; internal consistency is. The discrepancy is recorded as an open finding
    in the Changeset 01 v0.2.1 plan, and republishing the Design archive is out of scope.
    """
    bundle = _review_bundle_path()
    if not bundle.exists():
        pytest.skip("review bundle missing")
    import hashlib
    import zipfile

    with zipfile.ZipFile(bundle) as archive:
        report = archive.read(f"artifacts/stage-03/{DESIGN_REPORT_NAME}")
        verification = json.loads(archive.read(f"artifacts/stage-03/{DESIGN_VERIFICATION_NAME}"))
    assert verification["report_sha256"] == hashlib.sha256(report).hexdigest()


def test_the_working_tree_carries_the_audited_design_evidence() -> None:
    """The working tree must hold the accepted bytes, whatever any archive contains."""
    from human_simulator.stage03.frozen_evidence import FROZEN_DESIGN_EVIDENCE_SHA256

    for name, accepted in FROZEN_DESIGN_EVIDENCE_SHA256.items():
        assert sha256_file(STAGE03_DIR / name) == accepted, name


def test_review_bundle_report_sha_matches_embedded_verification() -> None:
    bundle = _review_bundle_path()
    if not bundle.exists():
        pytest.skip("review bundle missing")
    import zipfile

    report_rel = f"artifacts/stage-03/{DESIGN_REPORT_NAME}"
    verification_rel = f"artifacts/stage-03/{DESIGN_VERIFICATION_NAME}"
    with zipfile.ZipFile(bundle) as archive:
        report_sha = __import__("hashlib").sha256(archive.read(report_rel)).hexdigest()
        payload = json.loads(archive.read(verification_rel))
    assert payload["report_sha256"] == report_sha


def test_review_bundle_embedded_chronology_correct() -> None:
    bundle = _review_bundle_path()
    if not bundle.exists():
        pytest.skip("review bundle missing")
    import zipfile

    with zipfile.ZipFile(bundle) as archive:
        payload = json.loads(archive.read(f"artifacts/stage-03/{DESIGN_VERIFICATION_NAME}"))
    assert payload["report_generated_at"] <= payload["verified_at"]
    assert payload["verified_at"] <= payload["review_bundle_generated_at"]


def test_clean_extraction_no_publish_verification_passes() -> None:
    bundle = _review_bundle_path()
    if not bundle.exists():
        pytest.skip("review bundle missing")
    import shutil
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(tmp)
        result = verify_stage_03_design(Path(tmp), run_pytest=False, publish_artifacts=False)
        assert result["status"] == "PASS", result.get("failures")


def test_unpacked_zip_pytest_preserves_publication_artifacts() -> None:
    bundle = _review_bundle_path()
    if not bundle.exists():
        pytest.skip("review bundle missing")
    import shutil
    import subprocess
    import sys
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(bundle) as archive:
            archive.extractall(tmp_path)
        paths = [
            tmp_path / "artifacts/stage-03" / DESIGN_REPORT_NAME,
            tmp_path / "artifacts/stage-03" / DESIGN_CONTENT_MANIFEST_NAME,
            tmp_path / "artifacts/stage-03" / DESIGN_VERIFICATION_NAME,
        ]
        before = {path.name: sha256_file(path) for path in paths}
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_verify_stage_03_design.py",
                "-q",
                "-k",
                f"{gate_pytest_filter_expr()} and not test_unpacked_zip_pytest_preserves_publication_artifacts",
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        after = {path.name: sha256_file(path) for path in paths}
        assert before == after


def test_document_version_does_not_affect_canonical_id() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    namespace = get_id_namespace_version(contract)
    key_bytes = bytes.fromhex(contract["test_vectors"]["artificial_key_hex"])
    vector = contract["test_vectors"]["vectors"][0]
    baseline = compute_hmac_hex(
        key_bytes=key_bytes,
        entity=vector["entity"],
        id_namespace_version=namespace,
        source_system=vector["source_system"],
        inputs=vector["inputs"],
    )
    mutated = copy.deepcopy(contract)
    mutated["document_version"] = "99.99.99"
    mutated["version"] = "99.99.99"
    assert get_id_namespace_version(mutated) == namespace
    same = compute_hmac_hex(
        key_bytes=key_bytes,
        entity=vector["entity"],
        id_namespace_version=get_id_namespace_version(mutated),
        source_system=vector["source_system"],
        inputs=vector["inputs"],
    )
    assert baseline == same == vector["expected_hex"]


def test_id_namespace_version_change_affects_canonical_id() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    key_bytes = bytes.fromhex(contract["test_vectors"]["artificial_key_hex"])
    vector = contract["test_vectors"]["vectors"][0]
    baseline = compute_hmac_hex(
        key_bytes=key_bytes,
        entity=vector["entity"],
        id_namespace_version=get_id_namespace_version(contract),
        source_system=vector["source_system"],
        inputs=vector["inputs"],
    )
    changed = compute_hmac_hex(
        key_bytes=key_bytes,
        entity=vector["entity"],
        id_namespace_version="0.8.0",
        source_system=vector["source_system"],
        inputs=vector["inputs"],
    )
    assert baseline != changed


def test_key_rotation_rejects_secret_change_without_version_bump() -> None:
    contract = yaml.safe_load((STAGE03_DIR / "canonical-id-contract.yaml").read_text(encoding="utf-8"))
    assert not validate_key_rotation_policy(contract)
    mutated = copy.deepcopy(contract)
    mutated["key_rotation"]["runtime_secret_rotation"]["rule"] = (
        "Rotating runtime HMAC secret without key_version bump must not change canonical IDs"
    )
    errors = validate_key_rotation_policy(mutated)
    assert errors
    mutated2 = copy.deepcopy(contract)
    mutated2["key_rotation"]["runtime_secret_rotation"]["forbidden"] = []
    assert validate_key_rotation_policy(mutated2)


def _load_model() -> dict:
    path = STAGE03_DIR / "canonical-model.yaml"
    if not path.exists():
        pytest.skip("canonical-model.yaml missing")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _prior_stages_ready() -> bool:
    stage01 = REPO_ROOT / "artifacts" / "stage-01" / "stage-01-report.md"
    stage02_verify = REPO_ROOT / "artifacts" / "stage-02" / "verify-stage-02.json"
    if not stage01.exists() or not stage02_verify.exists():
        return False
    verify = json.loads(stage02_verify.read_text(encoding="utf-8"))
    report = stage01.read_text(encoding="utf-8")
    return ("**Report status:** FINAL" in report or "Report status: FINAL" in report) and verify.get("status") == "PASS"
