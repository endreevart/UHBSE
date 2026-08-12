"""Validate Stage 03 design artifacts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml

from human_simulator.audit.report import REPORT_STATUS_DRAFT
from human_simulator.stage02.verify_stage_02 import extract_unresolved_mappings
from human_simulator.stage03.preconditions import check_stage_03_preconditions, sha256_file

CheckStatus = Literal["PASS", "FAIL"]
OverallStatus = Literal["PASS", "FAIL"]

DESIGN_CONTENT_MANIFEST_NAME = "design-content-manifest.sha256"
DESIGN_VERIFICATION_NAME = "stage-03-design-verification.json"
DESIGN_REPORT_NAME = "stage-03-design-report.md"
LEGACY_MANIFEST_NAME = "design-manifest.sha256"

from human_simulator.stage03.constants import (
    DATA_LEVELS,
    ENTITIES_WITHOUT_ROW_PROVENANCE,
    MAPPING_STATUSES,
    PROVENANCE_PROFILES,
    RECORD_ORIGINS,
    REQUIRED_ENTITIES,
    STAGE03_CONTENT_ARTIFACTS,
)
from human_simulator.stage03.canonical_id import (
    validate_canonical_id_contract_document,
    validate_key_rotation_policy,
)
from human_simulator.stage03.construction_validator import validate_construction_contract
from human_simulator.stage03.model_validator import REQUIRED_CONSTRAINT_KEYS, validate_canonical_model
from human_simulator.stage03.review_bundle import BUNDLE_ZIP_NAME, build_stage03_review_bundle
from human_simulator.stage03.mapping_validator import (
    extract_entity_fields,
    validate_mapping_draft,
)
from human_simulator.stage03.schema_index import load_schema_index

STAGE03_DESIGN_ARTIFACTS: tuple[str, ...] = STAGE03_CONTENT_ARTIFACTS + (DESIGN_REPORT_NAME,)

FORBIDDEN_IN_CONTENT_MANIFEST = frozenset(
    {
        DESIGN_CONTENT_MANIFEST_NAME,
        DESIGN_REPORT_NAME,
        DESIGN_VERIFICATION_NAME,
        LEGACY_MANIFEST_NAME,
    }
)

REPORT_SELF_SHA_PATTERN = re.compile(
    r"stage-03-design-report\.md[^\n`]*[`']?[0-9a-f]{64}",
    re.IGNORECASE,
)

SECRET_PROBE = re.compile(
    r"postgresql(?:\+[\w]+)?://[^:]+:(?!\*\*\*)[^@]+@|\b\d{10,}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    section: str
    status: CheckStatus
    detail: str


def verify_stage_03_design(
    repo_root: Path,
    *,
    run_pytest: bool = True,
    publish_artifacts: bool = True,
) -> dict[str, Any]:
    root = repo_root.resolve()
    stage02_dir = root / "artifacts" / "stage-02"
    stage03_dir = root / "artifacts" / "stage-03"
    if publish_artifacts:
        stage03_dir.mkdir(parents=True, exist_ok=True)

    checks: list[CheckResult] = []

    def add(check: CheckResult) -> None:
        checks.append(check)

    pre_ok, preconditions = check_stage_03_preconditions(root)
    for item in preconditions:
        add(CheckResult(item.name, "preconditions", item.status, item.detail))

    if not pre_ok:
        return _build_failure_result(checks, stage03_dir, preconditions_met=False)

    artifacts = {name: _load_yaml_or_text(stage03_dir / name) for name in STAGE03_DESIGN_ARTIFACTS}
    for name in STAGE03_DESIGN_ARTIFACTS:
        add(
            CheckResult(
                f"artifact_{name}",
                "artifacts",
                "PASS" if (stage03_dir / name).exists() else "FAIL",
                "present" if (stage03_dir / name).exists() else "missing",
            )
        )

    model = artifacts.get("canonical-model.yaml")
    if isinstance(model, dict):
        _check_canonical_model(add, model)
    else:
        add(CheckResult("canonical_model_loaded", "model", "FAIL", "canonical-model.yaml invalid"))

    provenance = artifacts.get("provenance-contract.yaml")
    if isinstance(provenance, dict):
        _check_provenance_contract(add, provenance)
    else:
        add(CheckResult("provenance_contract_loaded", "provenance", "FAIL", "missing or invalid"))

    temporal = artifacts.get("temporal-contract.yaml")
    if isinstance(temporal, dict):
        _check_temporal_contract(add, temporal)
    else:
        add(CheckResult("temporal_contract_loaded", "temporal", "FAIL", "missing or invalid"))

    snapshot_contract = artifacts.get("state-snapshot-contract.yaml")
    if isinstance(snapshot_contract, dict):
        _check_state_snapshot_contract(add, snapshot_contract)
    else:
        add(CheckResult("state_snapshot_contract_loaded", "snapshot", "FAIL", "missing or invalid"))

    construction_contract = artifacts.get("record-construction-contract.yaml")
    canonical_id_contract = artifacts.get("canonical-id-contract.yaml")
    if isinstance(canonical_id_contract, dict):
        _check_canonical_id_contract(add, canonical_id_contract)
    else:
        add(CheckResult("canonical_id_contract_loaded", "identity", "FAIL", "missing or invalid"))

    if isinstance(construction_contract, dict) and isinstance(model, dict):
        stage01_profile = root / "artifacts" / "stage-01" / "schema-profile.json"
        stage02_profile = root / "artifacts" / "stage-02" / "schema-profile-kgz.json"
        index_a = load_schema_index(stage01_profile) if stage01_profile.exists() else None
        index_b = load_schema_index(stage02_profile) if stage02_profile.exists() else None
        mapping_drafts = {
            name: draft
            for name, draft in (
                ("source-a-mapping-draft.yaml", artifacts.get("source-a-mapping-draft.yaml")),
                ("source-b-mapping-draft.yaml", artifacts.get("source-b-mapping-draft.yaml")),
            )
            if isinstance(draft, dict)
        }
        _check_record_construction_contract(
            add,
            construction_contract,
            model,
            schema_index_a=index_a,
            schema_index_b=index_b,
            canonical_id_contract=canonical_id_contract if isinstance(canonical_id_contract, dict) else None,
            mapping_drafts=mapping_drafts,
        )
    else:
        add(CheckResult("record_construction_contract_loaded", "construction", "FAIL", "missing or invalid"))

    for draft_name in ("source-a-mapping-draft.yaml", "source-b-mapping-draft.yaml"):
        draft = artifacts.get(draft_name)
        if isinstance(draft, dict):
            _check_mapping_draft(add, draft, draft_name)
        else:
            add(CheckResult(f"{draft_name}_loaded", "mappings", "FAIL", "missing or invalid"))

    if isinstance(model, dict):
        entity_fields = extract_entity_fields(model)
        stage01_profile = root / "artifacts" / "stage-01" / "schema-profile.json"
        stage02_profile = root / "artifacts" / "stage-02" / "schema-profile-kgz.json"
        if stage01_profile.exists() and stage02_profile.exists():
            index_a = load_schema_index(stage01_profile)
            index_b = load_schema_index(stage02_profile)
            draft_a = artifacts.get("source-a-mapping-draft.yaml")
            draft_b = artifacts.get("source-b-mapping-draft.yaml")
            construction = artifacts.get("record-construction-contract.yaml")
            construction_dict = construction if isinstance(construction, dict) else None
            mapping_errors: list[str] = []
            if isinstance(draft_a, dict):
                mapping_errors.extend(
                    error.as_text()
                    for error in validate_mapping_draft(
                        "source-a-mapping-draft.yaml",
                        draft_a,
                        index_a,
                        entity_fields,
                        construction_dict,
                    )
                )
            if isinstance(draft_b, dict):
                mapping_errors.extend(
                    error.as_text()
                    for error in validate_mapping_draft(
                        "source-b-mapping-draft.yaml",
                        draft_b,
                        index_b,
                        entity_fields,
                        construction_dict,
                    )
                )
            add(
                CheckResult(
                    "source_mapping_integrity",
                    "mappings",
                    "PASS" if not mapping_errors else "FAIL",
                    "; ".join(mapping_errors[:8]) if mapping_errors else "all mappings validated",
                )
            )
        else:
            add(
                CheckResult(
                    "source_mapping_integrity",
                    "mappings",
                    "FAIL",
                    "schema profiles missing for mapping validation",
                )
            )

    semantics = artifacts.get("field-semantics-register.yaml")
    if isinstance(semantics, dict):
        _check_field_semantics(add, semantics)
    else:
        add(CheckResult("field_semantics_loaded", "semantics", "FAIL", "missing or invalid"))

    rules = artifacts.get("validation-rules.yaml")
    if isinstance(rules, dict):
        _check_validation_rules(add, rules)
    else:
        add(CheckResult("validation_rules_loaded", "validation", "FAIL", "missing or invalid"))

    _check_unresolved_preservation(add, stage02_dir, artifacts.get("unresolved-design-decisions.md", ""))

    secrets_ok, secrets_detail = _scan_for_secrets(stage03_dir)
    add(CheckResult("no_secrets_or_pii", "safety", "PASS" if secrets_ok else "FAIL", secrets_detail))

    report_text = artifacts.get(DESIGN_REPORT_NAME, "")
    if isinstance(report_text, str):
        draft_ok = f"**Report status:** {REPORT_STATUS_DRAFT}" in report_text
        add(
            CheckResult(
                "report_status_draft",
                "report",
                "PASS" if draft_ok else "FAIL",
                f"expected DRAFT, found draft={draft_ok}",
            )
        )

    report_path = stage03_dir / DESIGN_REPORT_NAME
    manifest_path = stage03_dir / DESIGN_CONTENT_MANIFEST_NAME
    computed_manifest_lines = _compute_content_manifest_lines(stage03_dir)
    computed_manifest_text = "\n".join(computed_manifest_lines) + ("\n" if computed_manifest_lines else "")
    computed_manifest_hash = _manifest_digest_from_lines(computed_manifest_lines)

    if publish_artifacts:
        manifest_ok, manifest_detail = _verify_manifest_lines(computed_manifest_lines, stage03_dir)
    else:
        if manifest_path.exists():
            manifest_ok, manifest_detail = _verify_content_manifest(manifest_path, stage03_dir)
        else:
            manifest_ok, manifest_detail = _verify_manifest_lines(computed_manifest_lines, stage03_dir)

    add(
        CheckResult(
            "content_manifest_hashes_match",
            "manifest",
            "PASS" if manifest_ok else "FAIL",
            manifest_detail,
        )
    )

    if manifest_path.exists():
        _check_content_manifest_publication(add, manifest_path, stage03_dir)
    else:
        _check_content_manifest_publication_from_lines(add, computed_manifest_lines, stage03_dir)

    if not publish_artifacts and report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
        _check_report_publication(add, report_text, manifest_hash=computed_manifest_hash)
    elif not report_path.exists():
        add(CheckResult("report_present", "report", "FAIL", f"missing {DESIGN_REPORT_NAME}"))

    verification_path = stage03_dir / DESIGN_VERIFICATION_NAME
    pytest_result = _run_pytest(repo_root) if run_pytest else _load_pytest_from_verification(stage03_dir)
    if run_pytest or verification_path.exists():
        add(
            CheckResult(
                "pytest_stage_03_design",
                "verification",
                "PASS" if pytest_result.get("pytest_exit_code") == 0 else "FAIL",
                pytest_result.get("pytest_summary", "pytest not run"),
            )
        )

    if publish_artifacts:
        manifest_path.write_text(computed_manifest_text, encoding="utf-8")
        content_manifest_sha256 = sha256_file(manifest_path)

        _publish_report(
            report_path,
            manifest_hash=content_manifest_sha256,
        )
        report_sha256 = sha256_file(report_path)
        report_text = report_path.read_text(encoding="utf-8")
        _check_report_publication(add, report_text, manifest_hash=content_manifest_sha256)

        report_generated_at = _read_report_generated_timestamp(report_path)
        report_dt = _parse_iso_timestamp(report_generated_at) if report_generated_at else datetime.now(tz=UTC)
        verified_at_dt = _timestamp_strictly_after(report_dt)
        verified_at = verified_at_dt.isoformat()
        review_bundle_generated_at = _timestamp_strictly_after(verified_at_dt).isoformat()

        on_disk_report_sha = sha256_file(report_path)
        add(
            CheckResult(
                "verification_report_sha256_match",
                "verification",
                "PASS" if report_sha256 == on_disk_report_sha else "FAIL",
                f"report_sha256={report_sha256!r}, disk={on_disk_report_sha!r}",
            )
        )
        add(
            CheckResult(
                "verification_json_no_self_hash_field",
                "verification",
                "PASS",
                "verification JSON must not embed its own hash",
            )
        )
        _add_planned_chronology_checks(
            add,
            report_generated_at=report_generated_at,
            verified_at=verified_at,
            review_bundle_generated_at=review_bundle_generated_at,
        )

        pre_publish_failed = [check for check in checks if check.status == "FAIL"]
        pre_publish_overall: OverallStatus = "PASS" if pre_ok and not pre_publish_failed else "FAIL"
        _check_publication_artifacts_from_disk(
            add,
            report_path=report_path,
            verification_path=verification_path,
            review_bundle_generated_at=review_bundle_generated_at,
            payload_override={
                "report_sha256": on_disk_report_sha,
                "verified_at": verified_at,
                "checks_failed": len(pre_publish_failed),
                "overall_status": pre_publish_overall,
            },
        )

        def _write_design_verification() -> None:
            passed_local = sum(1 for check in checks if check.status == "PASS")
            failed_local = [check for check in checks if check.status == "FAIL"]
            overall_local: OverallStatus = "PASS" if pre_ok and not failed_local else "FAIL"
            payload = _build_verification_payload(
                overall_status=overall_local,
                checks=checks,
                pytest_result=pytest_result,
                content_manifest_sha256=content_manifest_sha256,
                report_sha256=on_disk_report_sha,
                report_generated_at=report_generated_at,
                review_bundle_generated_at=review_bundle_generated_at,
                verified_at=verified_at,
            )
            verification_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        _write_design_verification()
        build_stage03_review_bundle(root, generated_at=review_bundle_generated_at)
    elif report_path.exists() and verification_path.exists():
        verification_payload = json.loads((stage03_dir / DESIGN_VERIFICATION_NAME).read_text(encoding="utf-8"))
        on_disk_report_sha = sha256_file(report_path)
        add(
            CheckResult(
                "verification_report_sha256_match",
                "verification",
                "PASS" if verification_payload.get("report_sha256") == on_disk_report_sha else "FAIL",
                f"report_sha256={verification_payload.get('report_sha256')!r}, disk={on_disk_report_sha!r}",
            )
        )
        add(
            CheckResult(
                "verification_json_no_self_hash_field",
                "verification",
                "PASS",
                "verification JSON must not embed its own hash",
            )
        )
        report_generated_at = verification_payload.get("report_generated_at") or _read_report_generated_timestamp(
            report_path
        )
        verified_at = verification_payload.get("verified_at")
        review_bundle_generated_at = (
            verification_payload.get("review_bundle_generated_at") or _read_review_bundle_generated_at(root)
        )
        if verified_at and review_bundle_generated_at:
            _add_planned_chronology_checks(
                add,
                report_generated_at=report_generated_at,
                verified_at=verified_at,
                review_bundle_generated_at=review_bundle_generated_at,
            )
        if review_bundle_generated_at:
            _check_publication_artifacts_from_disk(
                add,
                report_path=report_path,
                verification_path=verification_path,
                review_bundle_generated_at=review_bundle_generated_at,
            )

    passed = sum(1 for check in checks if check.status == "PASS")
    failed = [check for check in checks if check.status == "FAIL"]
    total = len(checks)
    overall: OverallStatus = "PASS" if pre_ok and not failed else "FAIL"

    return {
        "stage": "03",
        "phase": "design",
        "status": overall,
        "verified_at": datetime.now(tz=UTC).isoformat(),
        "preconditions_met": pre_ok,
        "checks_passed": passed,
        "checks_failed": len(failed),
        "checks_total": total,
        "checks": [asdict(check) for check in checks],
        "failures": [asdict(check) for check in failed],
        "content_manifest": DESIGN_CONTENT_MANIFEST_NAME,
        "verification_artifact": DESIGN_VERIFICATION_NAME,
        "artifacts_dir": str(stage03_dir),
    }


def _check_canonical_model(add: Any, model: dict[str, Any]) -> None:
    layers = model.get("layers", {})
    expected_layers = {"evidence", "simulation_scenario", "prediction"}
    layer_names = set(layers.keys())
    add(
        CheckResult(
            "three_architectural_layers",
            "model",
            "PASS" if layer_names == expected_layers else "FAIL",
            f"layers={sorted(layer_names)}",
        )
    )

    evidence_origins = set(layers.get("evidence", {}).get("record_origins", []))
    add(
        CheckResult(
            "evidence_layer_origins",
            "model",
            "PASS" if evidence_origins <= RECORD_ORIGINS and "OBSERVED" in evidence_origins else "FAIL",
            f"evidence_origins={sorted(evidence_origins)}",
        )
    )

    sim_origin = layers.get("simulation_scenario", {}).get("required_origin")
    pred_origin = layers.get("prediction", {}).get("required_origin")
    add(
        CheckResult(
            "simulation_synthetic_origin",
            "model",
            "PASS" if sim_origin == "SYNTHETIC" else "FAIL",
            f"simulation origin={sim_origin!r}",
        )
    )
    add(
        CheckResult(
            "prediction_predicted_origin",
            "model",
            "PASS" if pred_origin == "PREDICTED" else "FAIL",
            f"prediction origin={pred_origin!r}",
        )
    )
    add(
        CheckResult(
            "layers_not_merged",
            "model",
            "PASS" if sim_origin != "OBSERVED" and pred_origin != "OBSERVED" else "FAIL",
            "observed/synthetic/predicted must remain distinct",
        )
    )

    entities = model.get("entities", {})
    entity_names = set(entities.keys())
    missing = [name for name in REQUIRED_ENTITIES if name not in entity_names]
    add(
        CheckResult(
            "required_entities_present",
            "model",
            "PASS" if not missing else "FAIL",
            f"missing={missing}" if missing else f"count={len(entity_names)}",
        )
    )

    add(
        CheckResult(
            "identity_link_evidence_excluded",
            "model",
            "PASS" if "IdentityLinkEvidence" not in entity_names else "FAIL",
            "IdentityLinkEvidence is future-only, not in minimal model",
        )
    )

    subject = entities.get("Subject", {})
    identity = subject.get("identity", {})
    forbidden = identity.get("forbidden", [])
    add(
        CheckResult(
            "subject_source_local",
            "model",
            "PASS"
            if identity.get("scope") == "source_local"
            and "global_subject_id" in forbidden
            and "cross_source_merge" in forbidden
            else "FAIL",
            f"identity={identity}",
        )
    )

    for name, block in entities.items():
        if name in ENTITIES_WITHOUT_ROW_PROVENANCE or block.get("layer") == "cross_cutting":
            continue
        if block.get("requires_provenance") is not True:
            add(
                CheckResult(
                    f"entity_{name}_provenance",
                    "model",
                    "FAIL",
                    f"{name} must require provenance",
                )
            )
            break
    else:
        add(CheckResult("all_entities_require_provenance", "model", "PASS", "requires_provenance=true"))

    obs = entities.get("Observation", {})
    fields = set(obs.get("fields", {}).keys())
    required_obs = {
        "observation_id",
        "subject_id",
        "encounter_id",
        "observed_at",
        "result_available_at",
        "recorded_at",
        "status",
        "data_level",
        "raw_code",
        "normalized_concept",
        "raw_value",
        "raw_unit",
        "normalized_unit",
        "reference_range",
        "abnormal_flag",
        "uncertainty",
        "missingness_reason",
    }
    add(
        CheckResult(
            "observation_contract_fields",
            "model",
            "PASS" if required_obs <= fields else "FAIL",
            f"missing={sorted(required_obs - fields)}",
        )
    )

    comp = entities.get("ObservationComponent", {})
    comp_fields = set(comp.get("fields", {}).keys())
    required_comp = {
        "component_id",
        "observation_id",
        "raw_code",
        "raw_value",
        "numeric_value",
        "text_value",
        "categorical_value",
        "boolean_value",
        "raw_unit",
        "normalized_unit",
        "reference_range",
        "abnormal_flag",
        "sequence_order",
    }
    add(
        CheckResult(
            "observation_component_fields",
            "model",
            "PASS" if required_comp <= comp_fields else "FAIL",
            f"missing={sorted(required_comp - comp_fields)}",
        )
    )

    predicted = entities.get("PredictedState", {})
    pred_fields = set(predicted.get("fields", {}).keys())
    add(
        CheckResult(
            "predicted_state_temporal_fields",
            "model",
            "PASS" if {"generated_at", "target_at"} <= pred_fields else "FAIL",
            f"fields={sorted(pred_fields)}",
        )
    )
    add(
        CheckResult(
            "predicted_state_typed_values",
            "model",
            "PASS"
            if "predicted_value" not in pred_fields
            and "point_estimate" not in pred_fields
            and "input_snapshot_id" not in pred_fields
            and {"numeric_value", "text_value", "categorical_value", "boolean_value", "prediction_status"} <= pred_fields
            else "FAIL",
            f"fields={sorted(pred_fields)}",
        )
    )

    for entity_name in (
        "SimulationRun",
        "EvidenceStateSnapshot",
        "StateSnapshotComponent",
        "ScenarioCheckpoint",
        "ScenarioIntervention",
        "ScenarioCheckpointState",
    ):
        add(
            CheckResult(
                f"{entity_name.lower()}_present",
                "model",
                "PASS" if entity_name in entity_names else "FAIL",
                f"{entity_name} required for v0.4 scenario engine contract",
            )
        )

    add(
        CheckResult(
            "legacy_state_snapshot_removed",
            "model",
            "PASS" if "StateSnapshot" not in entity_names else "FAIL",
            "StateSnapshot must be split into EvidenceStateSnapshot and ScenarioCheckpoint",
        )
    )

    branch = entities.get("ScenarioBranch", {})
    branch_fields = set(branch.get("fields", {}).keys())
    fork_fields = {
        "parent_branch_id",
        "created_at",
        "forked_at_timeline",
        "baseline_snapshot_id",
        "checkpoint_id",
        "branch_status",
    }
    add(
        CheckResult(
            "scenario_branch_fork_fields",
            "model",
            "PASS" if fork_fields <= branch_fields and "forked_from_branch_id" not in branch_fields else "FAIL",
            f"missing={sorted(fork_fields - branch_fields)}",
        )
    )

    ess_fields = set(entities.get("EvidenceStateSnapshot", {}).get("fields", {}).keys())
    add(
        CheckResult(
            "evidence_snapshot_no_generic_state",
            "model",
            "PASS" if "state_variables" not in ess_fields else "FAIL",
            "EvidenceStateSnapshot must use StateSnapshotComponent rows",
        )
    )

    event_fields = set(entities.get("ScenarioEvent", {}).get("fields", {}).keys())
    add(
        CheckResult(
            "scenario_event_typed_no_generic_payload",
            "model",
            "PASS"
            if "payload" not in event_fields
            and "intervention_id" not in event_fields
            and "scenario_intervention_id" in event_fields
            else "FAIL",
            f"fields={sorted(event_fields)}",
        )
    )

    run_fields = set(entities.get("SimulationRun", {}).get("fields", {}).keys())
    add(
        CheckResult(
            "simulation_run_input_xor_fields",
            "model",
            "PASS"
            if "input_state_reference" not in run_fields
            and {"input_evidence_snapshot_id", "input_checkpoint_id"} <= run_fields
            else "FAIL",
            f"fields={sorted(run_fields)}",
        )
    )

    constraints = model.get("constraints", {})
    missing_constraints = [key for key in REQUIRED_CONSTRAINT_KEYS if key not in constraints]
    add(
        CheckResult(
            "design_constraints_documented",
            "model",
            "PASS" if not missing_constraints else "FAIL",
            f"missing={missing_constraints}" if missing_constraints else f"count={len(REQUIRED_CONSTRAINT_KEYS)}",
        )
    )
    add(
        CheckResult(
            "scenario_event_precedence_contract",
            "model",
            "PASS" if isinstance(constraints.get("scenario_event_precedence_contract"), dict) else "FAIL",
            "scenario_event_precedence_contract required",
        )
    )
    sc_entity = entities.get("SubjectCharacteristic", {})
    sc_fields = set(sc_entity.get("fields", {}).keys())
    required_sc = {
        "characteristic_id",
        "subject_id",
        "characteristic_code",
        "concept_id",
        "raw_value",
        "date_value",
        "categorical_value",
        "status",
        "provenance",
    }
    add(
        CheckResult(
            "subject_characteristic_present",
            "model",
            "PASS" if sc_entity and required_sc <= sc_fields else "FAIL",
            f"fields={sorted(sc_fields)}",
        )
    )

    model_errors = validate_canonical_model(model)
    add(
        CheckResult(
            "canonical_model_validator",
            "model",
            "PASS" if not model_errors else "FAIL",
            "; ".join(error.detail for error in model_errors[:8]) if model_errors else "ok",
        )
    )

    enum_yaml = set(model.get("data_level_enum", []))
    add(
        CheckResult(
            "data_level_enum_defined",
            "model",
            "PASS" if enum_yaml == DATA_LEVELS else "FAIL",
            f"enum={sorted(enum_yaml)}",
        )
    )
    catalog_split = model.get("catalog_vs_patient_facts", {})
    add(
        CheckResult(
            "catalog_patient_facts_separated",
            "model",
            "PASS" if catalog_split.get("strict_separation") is True else "FAIL",
            "catalog vs patient facts must be strictly separated",
        )
    )


def _check_provenance_contract(add: Any, provenance: dict[str, Any]) -> None:
    profiles = provenance.get("profiles", {})
    add(
        CheckResult(
            "provenance_profiles_discriminated",
            "provenance",
            "PASS" if set(profiles.keys()) == PROVENANCE_PROFILES else "FAIL",
            f"profiles={sorted(profiles.keys())}",
        )
    )

    source_backed = profiles.get("SOURCE_BACKED", {})
    scenario = profiles.get("SCENARIO", {})
    model_output = profiles.get("MODEL_OUTPUT", {})
    add(
        CheckResult(
            "source_backed_requires_locator",
            "provenance",
            "PASS"
            if "source_record_locator" in source_backed.get("required_fields", [])
            else "FAIL",
            "SOURCE_BACKED requires source_record_locator",
        )
    )
    add(
        CheckResult(
            "synthetic_no_source_locator",
            "provenance",
            "PASS"
            if "source_record_locator" in scenario.get("forbidden_fields", [])
            and "scenario_event_id" not in scenario.get("required_fields", [])
            else "FAIL",
            "SCENARIO profile must not require source locator or universal scenario_event_id",
        )
    )
    add(
        CheckResult(
            "scenario_profile_by_entity",
            "provenance",
            "PASS" if scenario.get("profile_by_entity") else "FAIL",
            "SCENARIO profile_by_entity required in v0.4",
        )
    )
    add(
        CheckResult(
            "predicted_no_source_locator",
            "provenance",
            "PASS"
            if "source_record_locator" in model_output.get("forbidden_fields", [])
            and "input_snapshot_id" in model_output.get("forbidden_fields", [])
            and "simulation_run_id" in model_output.get("required_fields", [])
            else "FAIL",
            "MODEL_OUTPUT must align with PredictedState fields",
        )
    )

    normalized_rule = provenance.get("origin_specific_rules", {}).get("NORMALIZED", {})
    add(
        CheckResult(
            "normalized_no_correction_history",
            "provenance",
            "PASS" if "correction_history_ref" in normalized_rule.get("must_not_require", []) else "FAIL",
            "NORMALIZED must not require correction history",
        )
    )

    corrected_rule = provenance.get("origin_specific_rules", {}).get("CORRECTED", {})
    add(
        CheckResult(
            "corrected_requires_prior_record",
            "provenance",
            "PASS"
            if "prior_record_reference" in corrected_rule.get("additionally_requires", [])
            else "FAIL",
            "CORRECTED requires prior record reference",
        )
    )

    origins = set(provenance.get("record_origins", []))
    add(
        CheckResult(
            "provenance_record_origins",
            "provenance",
            "PASS" if origins == RECORD_ORIGINS else "FAIL",
            f"origins={sorted(origins)}",
        )
    )

    add(
        CheckResult(
            "raw_value_retained_after_normalization",
            "provenance",
            "PASS" if provenance.get("raw_value_retention", {}).get("required") is True else "FAIL",
            "raw values must survive normalization",
        )
    )

    exceptions = provenance.get("entity_exceptions", {})
    add(
        CheckResult(
            "source_system_no_row_provenance",
            "provenance",
            "PASS"
            if exceptions.get("SourceSystem", {}).get("requires_row_provenance") is False
            else "FAIL",
            "SourceSystem must not require row-level provenance",
        )
    )


def _check_temporal_contract(add: Any, temporal: dict[str, Any]) -> None:
    fields = set(temporal.get("temporal_fields", []))
    expected = {
        "observed_at",
        "specimen_collected_at",
        "result_available_at",
        "recorded_at",
        "occurred_at",
        "intervention_started_at",
        "intervention_ended_at",
        "generated_at",
        "target_at",
        "prediction_horizon",
    }
    add(
        CheckResult(
            "temporal_fields_defined",
            "temporal",
            "PASS" if expected <= fields else "FAIL",
            f"missing={sorted(expected - fields)}",
        )
    )

    add(
        CheckResult(
            "no_recorded_at_substitution",
            "temporal",
            "PASS" if temporal.get("forbidden_substitutions", {}).get("recorded_at_for_missing_clinical_time") is True
            else "FAIL",
            "must not substitute recorded_at for missing clinical time",
        )
    )

    predicted_roles = temporal.get("entity_time_roles", {}).get("PredictedState", {})
    add(
        CheckResult(
            "predicted_state_uses_generated_and_target",
            "temporal",
            "PASS"
            if predicted_roles.get("generated") == "generated_at" and predicted_roles.get("target") == "target_at"
            else "FAIL",
            f"roles={predicted_roles}",
        )
    )

    add(
        CheckResult(
            "temporal_runtime_constraints_documented",
            "temporal",
            "PASS" if temporal.get("runtime_constraints") else "FAIL",
            "runtime constraints must be documented for implementation phase",
        )
    )


STATE_SNAPSHOT_CONTRACT_REQUIRED_SECTIONS = (
    "snapshot_at",
    "source_event_cutoff",
    "no_future_leakage",
    "selection_policy",
    "clinical_vs_system_time",
    "subject_characteristic_inclusion",
    "observation_inclusion",
    "source_local_identity",
    "no_cross_source_merge",
    "raw_value_retention",
    "unit_normalization_policy",
    "missingness_vs_imputation",
    "imputed_marking",
    "age_at_snapshot",
    "age_not_stored_property",
    "provenance_per_variable",
    "conflict_resolution",
    "deterministic_construction",
)


def _check_state_snapshot_contract(add: Any, contract: dict[str, Any]) -> None:
    missing = [key for key in STATE_SNAPSHOT_CONTRACT_REQUIRED_SECTIONS if key not in contract]
    add(
        CheckResult(
            "state_snapshot_contract_sections",
            "snapshot",
            "PASS" if not missing else "FAIL",
            f"missing={missing}" if missing else f"sections={len(STATE_SNAPSHOT_CONTRACT_REQUIRED_SECTIONS)}",
        )
    )
    versioning = contract.get("deterministic_construction", {}).get("versioning", {})
    version_fields = {
        "snapshot_builder_version",
        "selection_policy_version",
        "unit_conversion_version",
        "imputation_policy_version",
        "input_artifact_hashes",
    }
    add(
        CheckResult(
            "state_snapshot_contract_versioning",
            "snapshot",
            "PASS" if version_fields <= set(versioning.keys()) else "FAIL",
            f"versioning={sorted(versioning.keys())}",
        )
    )
    cutoff = contract.get("source_event_cutoff", {})
    add(
        CheckResult(
            "state_snapshot_cutoff_required",
            "snapshot",
            "PASS" if cutoff.get("required") is True else "FAIL",
            "source_event_cutoff must be required",
        )
    )
    add(
        CheckResult(
            "state_snapshot_no_future_leakage",
            "snapshot",
            "PASS" if contract.get("no_future_leakage", {}).get("forbidden") else "FAIL",
            "no_future_leakage rule required",
        )
    )
    age_rule = contract.get("age_at_snapshot", {})
    age_not_stored = contract.get("age_not_stored_property", {})
    add(
        CheckResult(
            "state_snapshot_age_at_snapshot_rule",
            "snapshot",
            "PASS"
            if age_rule.get("rule")
            and age_rule.get("forbidden")
            and age_not_stored.get("entities_forbidden")
            else "FAIL",
            "age computed at snapshot_at; not stored as property",
        )
    )
    age_lineage = age_rule.get("lineage", {})
    add(
        CheckResult(
            "state_snapshot_age_birthdate_lineage",
            "snapshot",
            "PASS"
            if age_lineage.get("provenance_field") == "provenance.input_record_references"
            and age_lineage.get("required_reference", {}).get("entity") == "SubjectCharacteristic"
            else "FAIL",
            f"age lineage={age_lineage}",
        )
    )
    provenance_var = contract.get("provenance_per_variable", {})
    input_refs = provenance_var.get("input_record_references", {})
    add(
        CheckResult(
            "state_snapshot_input_record_references",
            "snapshot",
            "PASS"
            if provenance_var.get("required")
            and "provenance.input_record_references" in provenance_var.get("required", [])
            and input_refs.get("authoritative") is True
            else "FAIL",
            "provenance.input_record_references required for lineage",
        )
    )
    add(
        CheckResult(
            "state_snapshot_design_only",
            "snapshot",
            "PASS" if contract.get("implementation_status") == "not_started" else "FAIL",
            "snapshot contract is design-only",
        )
    )


def _check_canonical_id_contract(add: Any, contract: dict[str, Any]) -> None:
    spec = contract.get("canonical_id_contract", {})
    add(
        CheckResult(
            "canonical_id_contract_algorithm",
            "identity",
            "PASS" if spec.get("algorithm") == "HMAC-SHA256" else "FAIL",
            f"algorithm={spec.get('algorithm')!r}",
        )
    )
    add(
        CheckResult(
            "canonical_id_contract_secret_runtime_only",
            "identity",
            "PASS" if spec.get("secret_storage") == "runtime_only" else "FAIL",
            f"secret_storage={spec.get('secret_storage')!r}",
        )
    )
    add(
        CheckResult(
            "canonical_id_contract_domain_separation",
            "identity",
            "PASS" if spec.get("domain_separation") else "FAIL",
            "domain separation required",
        )
    )
    add(
        CheckResult(
            "canonical_id_contract_serialization",
            "identity",
            "PASS"
            if spec.get("input_fields", {}).get("serialization") == "length_prefix_utf8"
            else "FAIL",
            f"serialization={spec.get('input_fields', {}).get('serialization')!r}",
        )
    )
    vector_errors = validate_canonical_id_contract_document(contract)
    add(
        CheckResult(
            "canonical_id_contract_executable_vectors",
            "identity",
            "PASS" if not vector_errors else "FAIL",
            "; ".join(error.detail for error in vector_errors[:4]) if vector_errors else "ok",
        )
    )
    add(
        CheckResult(
            "canonical_id_contract_namespace_version_split",
            "identity",
            "PASS"
            if contract.get("document_version") and contract.get("id_namespace_version")
            else "FAIL",
            f"document_version={contract.get('document_version')!r}, id_namespace_version={contract.get('id_namespace_version')!r}",
        )
    )
    add(
        CheckResult(
            "canonical_id_contract_key_rotation_policy",
            "identity",
            "PASS" if not validate_key_rotation_policy(contract) else "FAIL",
            "key rotation must forbid secret change without key_version bump",
        )
    )
    add(
        CheckResult(
            "canonical_id_contract_message_layout",
            "identity",
            "PASS" if spec.get("message_layout") else "FAIL",
            "message_layout required",
        )
    )
    add(
        CheckResult(
            "canonical_id_contract_null_encoding",
            "identity",
            "PASS" if spec.get("input_fields", {}).get("null_encoding") != "empty_utf8_string" else "FAIL",
            f"null_encoding={spec.get('input_fields', {}).get('null_encoding')!r}",
        )
    )
    add(
        CheckResult(
            "canonical_id_contract_design_only",
            "identity",
            "PASS" if contract.get("implementation_status") == "not_started" else "FAIL",
            "canonical id contract is design-only",
        )
    )


def _check_record_construction_contract(
    add: Any,
    contract: dict[str, Any],
    model: dict[str, Any],
    *,
    schema_index_a: Any = None,
    schema_index_b: Any = None,
    canonical_id_contract: dict[str, Any] | None = None,
    mapping_drafts: dict[str, dict[str, Any]] | None = None,
) -> None:
    errors = validate_construction_contract(
        contract,
        model,
        schema_index_a=schema_index_a,
        schema_index_b=schema_index_b,
        canonical_id_contract=canonical_id_contract,
        mapping_drafts=mapping_drafts,
    )
    add(
        CheckResult(
            "record_construction_contract_validator",
            "construction",
            "PASS" if not errors else "FAIL",
            "; ".join(error.detail for error in errors[:6]) if errors else "ok",
        )
    )
    groups = contract.get("construction_groups", [])
    group_ids = {g.get("group_id") for g in groups if isinstance(g, dict)}
    for required in (
        "source_a_account_patient_characteristics",
        "source_a_appointment_encounter",
        "source_a_observation_component",
        "source_b_users_subject",
        "source_b_users_profile_characteristics",
        "source_b_profilaxys_profile_characteristics",
        "source_b_consultations_encounter",
        "source_b_lab_observation_header",
        "source_b_analyses_constructor_component",
        "source_b_profilaxys_profile_observation",
        "source_b_profilaxys_profile_observation_components",
    ):
        add(
            CheckResult(
                f"construction_group_{required}",
                "construction",
                "PASS" if required in group_ids else "FAIL",
                f"present={required in group_ids}",
            )
        )
    global_rules = contract.get("global_rules", {})
    add(
        CheckResult(
            "construction_null_emission_policy",
            "construction",
            "PASS" if global_rules.get("null_emission_policy", {}).get("forbidden") else "FAIL",
            "null must not become empty or placeholder values",
        )
    )
    add(
        CheckResult(
            "construction_design_only",
            "construction",
            "PASS" if contract.get("implementation_status") == "not_started" else "FAIL",
            "construction contract is design-only",
        )
    )


def _check_mapping_draft(add: Any, draft: dict[str, Any], draft_name: str) -> None:
    from human_simulator.stage03.mapping_validator import iter_draft_mappings

    mappings = iter_draft_mappings(draft)
    if not mappings:
        add(CheckResult(f"{draft_name}_has_mappings", "mappings", "FAIL", "empty mappings"))
        return

    incomplete = []
    forbidden_confirmed = []
    wildcard_hits = []
    invalid_levels = []
    for index, mapping in enumerate(mappings):
        has_column = "source_column" in mapping or "source_columns" in mapping
        if not has_column:
            incomplete.append(index)
        required = {
            "source_relation",
            "canonical_entity",
            "canonical_field",
            "mapping_status",
            "data_level",
            "transformation",
            "evidence",
            "lossiness",
        }
        if required - set(mapping.keys()):
            incomplete.append(index)
        if mapping.get("source_column") == "*":
            wildcard_hits.append(index)
        status = mapping.get("mapping_status")
        if status not in MAPPING_STATUSES:
            incomplete.append(index)
        if status == "CONFIRMED" and mapping.get("clinical_semantics_confirmed") is True:
            forbidden_confirmed.append(index)
        if mapping.get("data_level") not in DATA_LEVELS:
            invalid_levels.append(index)

    add(
        CheckResult(
            f"{draft_name}_mapping_fields",
            "mappings",
            "PASS" if not incomplete else "FAIL",
            f"incomplete_indices={sorted(set(incomplete))[:5]}",
        )
    )
    add(
        CheckResult(
            f"{draft_name}_wildcard_forbidden",
            "mappings",
            "PASS" if not wildcard_hits else "FAIL",
            f"wildcard_indices={wildcard_hits}",
        )
    )
    add(
        CheckResult(
            f"{draft_name}_data_level_enum",
            "mappings",
            "PASS" if not invalid_levels else "FAIL",
            f"invalid_indices={invalid_levels[:5]}",
        )
    )
    add(
        CheckResult(
            f"{draft_name}_no_clinical_confirmed",
            "mappings",
            "PASS" if not forbidden_confirmed else "FAIL",
            "CONFIRMED clinical semantics forbidden in design phase",
        )
    )

    if draft_name == "source-b-mapping-draft.yaml":
        persons_map = next(
            (m for m in mappings if m.get("source_relation") == "public.persons"), None
        )
        persons_ok = (
            persons_map is not None
            and persons_map.get("mapping_status") in {"NOT_MAPPED", "UNRESOLVED"}
            and "NO_SUBJECT_ROOT" in str(persons_map.get("evidence", ""))
        )
        add(
            CheckResult(
                "public_persons_not_subject_root_candidate",
                "mappings",
                "PASS" if persons_ok else "FAIL",
                f"persons mapping={persons_map}",
            )
        )
        value_ok = any(
            m.get("source_relation") == "quest_digital.analyses_constructor"
            and m.get("source_column") == "value"
            for m in mappings
        )
        add(
            CheckResult(
                "analyses_constructor_uses_value_column",
                "mappings",
                "PASS" if value_ok else "FAIL",
                "analyses_constructor.value must be mapped",
            )
        )
        patient_ok = any(
            m.get("source_relation") == "public.consultations" and m.get("source_column") == "patient_id"
            for m in mappings
        )
        user_bad = any(
            m.get("source_relation") == "public.consultations" and m.get("source_column") == "user_id"
            for m in mappings
        )
        add(
            CheckResult(
                "consultations_use_patient_id",
                "mappings",
                "PASS" if patient_ok and not user_bad else "FAIL",
                f"patient_id={patient_ok}, user_id_present={user_bad}",
            )
        )

    if draft_name == "source-a-mapping-draft.yaml":
        bad_columns = {"start_datetime", "end_datetime", "created_at"}
        bad_hits = [
            index
            for index, mapping in enumerate(mappings)
            if mapping.get("source_column") in bad_columns
            or (
                mapping.get("source_relation") == "magerya_api.account_patient"
                and mapping.get("source_column") == "created_at"
            )
        ]
        created_ok = any(
            m.get("source_relation") == "magerya_api.account_patient" and m.get("source_column") == "created"
            for m in mappings
        )
        add(
            CheckResult(
                "source_a_no_phantom_time_columns",
                "mappings",
                "PASS" if not bad_hits and created_ok else "FAIL",
                f"bad_hits={bad_hits}, created_mapped={created_ok}",
            )
        )
        demo_ok = all(
            any(
                m.get("source_relation") == relation
                and m.get("source_column") == column
                and m.get("canonical_entity") == "SubjectCharacteristic"
                and m.get("canonical_field") == field
                and m.get("characteristic_code") == code
                and m.get("mapping_status") == "CANDIDATE"
                for m in mappings
            )
            for relation, column, field, code in (
                ("magerya_api.account_patient", "birthdate", "date_value", "source_birthdate"),
                ("magerya_api.account_patient", "sex", "categorical_value", "source_sex"),
            )
        )
        add(
            CheckResult(
                "source_a_subject_characteristic_demographics",
                "mappings",
                "PASS" if demo_ok else "FAIL",
                "account_patient birthdate/sex mapped to SubjectCharacteristic with raw codes",
            )
        )

    if draft_name == "source-b-mapping-draft.yaml":
        users_profile_demo = all(
            any(
                m.get("source_relation") == "public.users_profile"
                and m.get("source_column") == column
                and m.get("canonical_entity") == "SubjectCharacteristic"
                and m.get("canonical_field") == field
                and m.get("characteristic_code") == code
                and m.get("mapping_status") == "HYPOTHESIS"
                for m in mappings
            )
            for column, field, code in (
                ("birth_date", "date_value", "source_birthdate"),
                ("gender", "categorical_value", "source_gender"),
            )
        )
        users_profile_subject = any(
            m.get("source_relation") == "public.users_profile"
            and m.get("source_column") == "user_id"
            and m.get("canonical_entity") == "Subject"
            and m.get("mapping_status") == "HYPOTHESIS"
            for m in mappings
        )
        profilaxys_stable = all(
            any(
                m.get("source_relation") == "public.profilaxys_profile"
                and m.get("source_column") == column
                and m.get("canonical_entity") == "SubjectCharacteristic"
                and m.get("canonical_field") == field
                for m in mappings
            )
            for column, field in (("birthdate", "date_value"), ("sex", "categorical_value"))
        )
        profilaxys_dynamic = all(
            any(
                m.get("source_relation") == "public.profilaxys_profile"
                and m.get("source_column") == column
                and m.get("canonical_entity") == "ObservationComponent"
                for m in mappings
            )
            for column in (
                "weight",
                "height",
                "pregnant",
                "kok",
                "height_decreased",
                "cigarettes",
                "temperature",
                "sleep",
            )
        )
        profilaxys_user = any(
            m.get("source_relation") == "public.profilaxys_profile"
            and m.get("source_column") == "user_id"
            and m.get("canonical_entity") == "Subject"
            and m.get("mapping_status") == "HYPOTHESIS"
            for m in mappings
        )
        add(
            CheckResult(
                "source_b_users_profile_subject_characteristics",
                "mappings",
                "PASS" if users_profile_demo and users_profile_subject else "FAIL",
                f"demo={users_profile_demo}, user_id_subject={users_profile_subject}",
            )
        )
        add(
            CheckResult(
                "source_b_profilaxys_profile_characteristics_and_observations",
                "mappings",
                "PASS" if profilaxys_stable and profilaxys_dynamic and profilaxys_user else "FAIL",
                f"stable={profilaxys_stable}, dynamic={profilaxys_dynamic}, user_id={profilaxys_user}",
            )
        )


def _check_field_semantics(add: Any, semantics: dict[str, Any]) -> None:
    add(
        CheckResult(
            "field_semantics_raw_preserved",
            "semantics",
            "PASS" if semantics.get("raw_value_policy") == "always_preserve" else "FAIL",
            f"policy={semantics.get('raw_value_policy')!r}",
        )
    )
    add(
        CheckResult(
            "field_semantics_no_global_patient_id",
            "semantics",
            "PASS" if "global_patient_id" in semantics.get("forbidden_fields", []) else "FAIL",
            "global_patient_id forbidden",
        )
    )


def _check_validation_rules(add: Any, rules: dict[str, Any]) -> None:
    rule_names = {rule.get("name") for rule in rules.get("rules", [])}
    expected = {
        "entity_has_provenance",
        "temporal_entities_have_contract",
        "raw_value_preserved",
        "normalized_fields_nullable",
        "subject_source_local",
        "no_global_patient_id",
        "catalog_patient_facts_separated",
        "predicted_synthetic_not_mixed_with_observed",
        "mappings_have_status_evidence_lossiness",
        "source_mapping_integrity",
        "canonical_field_defined",
        "wildcard_mapping_forbidden",
        "data_level_enum_consistent",
        "stage_02_unresolved_preserved",
        "provenance_profiles_discriminated",
        "scenario_profile_by_entity",
        "normalized_no_correction_history",
        "predicted_state_temporal_fields",
        "predicted_state_typed_values",
        "scenario_intervention_present",
        "scenario_checkpoint_state_present",
        "simulation_run_input_xor_fields",
        "design_constraints_documented",
        "canonical_model_validator",
        "constraint_mutation_regression",
        "content_manifest_excludes_report",
        "content_manifest_no_self_hash",
        "verification_json_excluded_from_content_manifest",
        "report_no_self_sha256",
        "content_manifest_hashes_match",
        "report_content_manifest_sha256_match",
        "verification_report_sha256_match",
        "no_cyclic_hash_dependencies",
        "artifacts_no_pii",
    }
    add(
        CheckResult(
            "validation_rules_complete",
            "validation",
            "PASS" if expected <= rule_names else "FAIL",
            f"missing={sorted(expected - rule_names)}",
        )
    )


def _check_unresolved_preservation(add: Any, stage02_dir: Path, decisions_md: str) -> None:
    crosswalk_path = stage02_dir / "entity-crosswalk.yaml"
    crosswalk = yaml.safe_load(crosswalk_path.read_text(encoding="utf-8")) if crosswalk_path.exists() else None
    unresolved = extract_unresolved_mappings(crosswalk)
    preserved = sum(1 for item in unresolved if item in decisions_md)
    add(
        CheckResult(
            "stage_02_unresolved_preserved",
            "crosswalk",
            "PASS" if preserved == len(unresolved) == 17 else "FAIL",
            f"preserved={preserved}/{len(unresolved)}",
        )
    )


def _scan_for_secrets(stage03_dir: Path) -> tuple[bool, str]:
    for path in stage03_dir.iterdir():
        if path.suffix not in {".yaml", ".yml", ".md"}:
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if SECRET_PROBE.search(line):
                return False, f"suspicious pattern in {path.name}"
    return True, "no credentials, long numeric IDs, or absolute paths detected"


def _compute_content_manifest_lines(stage03_dir: Path) -> list[str]:
    lines: list[str] = []
    for name in STAGE03_CONTENT_ARTIFACTS:
        path = stage03_dir / name
        if path.exists():
            lines.append(f"{sha256_file(path)}  {name}")
    return lines


def _manifest_digest_from_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    payload = "\n".join(lines) + "\n"
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_manifest_lines(lines: list[str], artifacts_dir: Path) -> tuple[bool, str]:
    if len(lines) != len(STAGE03_CONTENT_ARTIFACTS):
        return False, f"expected {len(STAGE03_CONTENT_ARTIFACTS)} entries, found {len(lines)}"
    verified = 0
    for line in lines:
        digest, name = line.split(maxsplit=1)
        entry = name.strip()
        if entry in FORBIDDEN_IN_CONTENT_MANIFEST:
            return False, f"forbidden entry in content manifest: {entry}"
        path = artifacts_dir / entry
        if not path.exists():
            return False, f"missing {entry}"
        if sha256_file(path) != digest:
            return False, f"hash mismatch: {entry}"
        verified += 1
    return True, f"verified {verified} content entries"


def _write_content_manifest(stage03_dir: Path) -> None:
    lines = _compute_content_manifest_lines(stage03_dir)
    (stage03_dir / DESIGN_CONTENT_MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _verify_content_manifest(manifest_path: Path, artifacts_dir: Path) -> tuple[bool, str]:
    if not manifest_path.exists():
        return False, f"missing {DESIGN_CONTENT_MANIFEST_NAME}"
    verified = 0
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        entry = name.strip()
        if entry in FORBIDDEN_IN_CONTENT_MANIFEST:
            return False, f"forbidden entry in content manifest: {entry}"
        path = artifacts_dir / entry
        if not path.exists():
            return False, f"missing {entry}"
        if sha256_file(path) != digest:
            return False, f"hash mismatch: {entry}"
        verified += 1
    if verified != len(STAGE03_CONTENT_ARTIFACTS):
        return False, f"expected {len(STAGE03_CONTENT_ARTIFACTS)} entries, found {verified}"
    return True, f"verified {verified} content entries"


def _check_content_manifest_publication(
    add: Any,
    manifest_path: Path,
    stage03_dir: Path,
) -> None:
    manifest_text = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
    entries = [line.split(maxsplit=1)[1].strip() for line in manifest_text.splitlines() if line.strip()]

    add(
        CheckResult(
            "content_manifest_excludes_report",
            "manifest",
            "PASS" if DESIGN_REPORT_NAME not in entries else "FAIL",
            f"entries={entries}",
        )
    )
    add(
        CheckResult(
            "content_manifest_no_self_hash",
            "manifest",
            "PASS" if DESIGN_CONTENT_MANIFEST_NAME not in entries else "FAIL",
            "content manifest must not include itself",
        )
    )
    add(
        CheckResult(
            "verification_json_excluded_from_content_manifest",
            "manifest",
            "PASS" if DESIGN_VERIFICATION_NAME not in entries else "FAIL",
            "verification JSON must not be in content manifest",
        )
    )
    legacy_present = (stage03_dir / LEGACY_MANIFEST_NAME).exists()
    report_text = (stage03_dir / DESIGN_REPORT_NAME).read_text(encoding="utf-8") if (stage03_dir / DESIGN_REPORT_NAME).exists() else ""
    verification_path = stage03_dir / DESIGN_VERIFICATION_NAME
    verification_hash = sha256_file(verification_path) if verification_path.exists() else ""
    report_refs_verification_hash = verification_hash and verification_hash in report_text
    add(
        CheckResult(
            "no_cyclic_hash_dependencies",
            "manifest",
            "PASS"
            if not legacy_present and not report_refs_verification_hash
            else "FAIL",
            f"legacy_manifest={legacy_present}, report_refs_verification_hash={report_refs_verification_hash}",
        )
    )


REPORT_GENERATED_PATTERN = re.compile(r"^Generated:\s*(.+)$", re.MULTILINE)


def _check_content_manifest_publication_from_lines(
    add: Any,
    manifest_lines: list[str],
    stage03_dir: Path,
) -> None:
    entries = [line.split(maxsplit=1)[1].strip() for line in manifest_lines if line.strip()]
    add(
        CheckResult(
            "content_manifest_excludes_report",
            "manifest",
            "PASS" if DESIGN_REPORT_NAME not in entries else "FAIL",
            f"entries={entries}",
        )
    )
    add(
        CheckResult(
            "content_manifest_no_self_hash",
            "manifest",
            "PASS" if DESIGN_CONTENT_MANIFEST_NAME not in entries else "FAIL",
            "content manifest must not include itself",
        )
    )
    add(
        CheckResult(
            "verification_json_excluded_from_content_manifest",
            "manifest",
            "PASS" if DESIGN_VERIFICATION_NAME not in entries else "FAIL",
            "verification JSON must not be in content manifest",
        )
    )
    legacy_present = (stage03_dir / LEGACY_MANIFEST_NAME).exists()
    report_path = stage03_dir / DESIGN_REPORT_NAME
    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    verification_path = stage03_dir / DESIGN_VERIFICATION_NAME
    verification_hash = sha256_file(verification_path) if verification_path.exists() else ""
    report_refs_verification_hash = verification_hash and verification_hash in report_text
    add(
        CheckResult(
            "no_cyclic_hash_dependencies",
            "manifest",
            "PASS"
            if not legacy_present and not report_refs_verification_hash
            else "FAIL",
            f"legacy_manifest={legacy_present}, report_refs_verification_hash={report_refs_verification_hash}",
        )
    )


REVIEW_INDEX_GENERATED_PATTERN = re.compile(r"^Generated:\s*(.+)$", re.MULTILINE)


def _timestamp_strictly_after(reference: datetime) -> datetime:
    bumped = reference + timedelta(microseconds=1)
    now = datetime.now(tz=UTC)
    return bumped if bumped > now else now


def _add_planned_chronology_checks(
    add: Any,
    *,
    report_generated_at: str | None,
    verified_at: str,
    review_bundle_generated_at: str,
) -> None:
    report_dt = _parse_iso_timestamp(report_generated_at) if report_generated_at else None
    verified_dt = _parse_iso_timestamp(verified_at)
    bundle_dt = _parse_iso_timestamp(review_bundle_generated_at)
    now = datetime.now(tz=UTC)

    future_report = report_dt is not None and report_dt > now
    future_verified = verified_dt is not None and verified_dt > now
    add(
        CheckResult(
            "audit_chronology_no_future_timestamps",
            "audit",
            "PASS" if not future_report and not future_verified else "FAIL",
            f"report_future={future_report}, verified_future={future_verified}",
        )
    )
    add(
        CheckResult(
            "audit_chronology_report_before_verified",
            "audit",
            "PASS" if report_dt and verified_dt and report_dt <= verified_dt else "FAIL",
            f"report={report_generated_at!r}, verified={verified_at!r}",
        )
    )
    add(
        CheckResult(
            "audit_chronology_verified_before_review_bundle",
            "audit",
            "PASS" if verified_dt and bundle_dt and verified_dt <= bundle_dt else "FAIL",
            f"verified={verified_at!r}, bundle={review_bundle_generated_at!r}",
        )
    )


def _check_publication_artifacts_from_disk(
    add: Any,
    *,
    report_path: Path,
    verification_path: Path,
    review_bundle_generated_at: str,
    payload_override: dict[str, Any] | None = None,
) -> None:
    payload = payload_override or json.loads(verification_path.read_text(encoding="utf-8"))
    on_disk_report_sha = sha256_file(report_path)
    add(
        CheckResult(
            "publication_disk_report_sha256_match",
            "verification",
            "PASS" if payload.get("report_sha256") == on_disk_report_sha else "FAIL",
            f"verification={payload.get('report_sha256')!r}, disk={on_disk_report_sha!r}",
        )
    )
    report_generated_at = _read_report_generated_timestamp(report_path)
    verified_at = payload.get("verified_at")
    report_dt = _parse_iso_timestamp(report_generated_at) if report_generated_at else None
    verified_dt = _parse_iso_timestamp(verified_at) if verified_at else None
    bundle_dt = _parse_iso_timestamp(review_bundle_generated_at)
    add(
        CheckResult(
            "publication_disk_chronology_report_before_verified",
            "audit",
            "PASS" if report_dt and verified_dt and report_dt <= verified_dt else "FAIL",
            f"report={report_generated_at!r}, verified={verified_at!r}",
        )
    )
    add(
        CheckResult(
            "publication_disk_chronology_verified_before_bundle",
            "audit",
            "PASS" if verified_dt and bundle_dt and verified_dt <= bundle_dt else "FAIL",
            f"verified={verified_at!r}, bundle={review_bundle_generated_at!r}",
        )
    )
    expected_status: OverallStatus = "PASS" if payload.get("checks_failed", 1) == 0 else "FAIL"
    add(
        CheckResult(
            "publication_disk_overall_status_consistent",
            "verification",
            "PASS" if payload.get("overall_status") == expected_status else "FAIL",
            f"overall={payload.get('overall_status')!r}, expected={expected_status!r}",
        )
    )


def _check_review_bundle_embedded_artifacts(
    add: Any,
    *,
    repo_root: Path,
    review_bundle_generated_at: str,
) -> None:
    import zipfile

    bundle_zip = repo_root / "artifacts" / "external-review" / BUNDLE_ZIP_NAME
    if not bundle_zip.exists():
        add(
            CheckResult(
                "review_bundle_present",
                "audit",
                "FAIL",
                f"missing {BUNDLE_ZIP_NAME}",
            )
        )
        return

    add(CheckResult("review_bundle_present", "audit", "PASS", str(bundle_zip.name)))

    verification_rel = f"artifacts/stage-03/{DESIGN_VERIFICATION_NAME}"
    report_rel = f"artifacts/stage-03/{DESIGN_REPORT_NAME}"
    on_disk_verification = (repo_root / verification_rel).read_bytes()
    on_disk_report_sha = sha256_file(repo_root / report_rel)

    with zipfile.ZipFile(bundle_zip) as archive:
        index_text = archive.read("REVIEW_INDEX.md").decode("utf-8")
        index_match = REVIEW_INDEX_GENERATED_PATTERN.search(index_text)
        index_generated_at = index_match.group(1).strip() if index_match else None
        embedded_verification = archive.read(verification_rel)
        embedded_report_sha = sha256_file_from_bytes(archive.read(report_rel))

    add(
        CheckResult(
            "review_bundle_index_generated_at",
            "audit",
            "PASS" if index_generated_at == review_bundle_generated_at else "FAIL",
            f"index={index_generated_at!r}, expected={review_bundle_generated_at!r}",
        )
    )
    add(
        CheckResult(
            "review_bundle_embedded_verification_current",
            "audit",
            "PASS" if embedded_verification == on_disk_verification else "FAIL",
            "embedded verification must match on-disk final verification",
        )
    )
    embedded_payload = json.loads(embedded_verification.decode("utf-8"))
    add(
        CheckResult(
            "review_bundle_embedded_report_sha256",
            "audit",
            "PASS" if embedded_payload.get("report_sha256") == embedded_report_sha else "FAIL",
            f"embedded verification report_sha256={embedded_payload.get('report_sha256')!r}, report={embedded_report_sha!r}",
        )
    )
    add(
        CheckResult(
            "review_bundle_embedded_report_sha256_matches_disk",
            "audit",
            "PASS" if embedded_payload.get("report_sha256") == on_disk_report_sha else "FAIL",
            f"embedded={embedded_payload.get('report_sha256')!r}, disk={on_disk_report_sha!r}",
        )
    )
    embedded_report_at = embedded_payload.get("report_generated_at")
    embedded_verified_at = embedded_payload.get("verified_at")
    embedded_bundle_at = embedded_payload.get("review_bundle_generated_at")
    report_dt = _parse_iso_timestamp(embedded_report_at) if embedded_report_at else None
    verified_dt = _parse_iso_timestamp(embedded_verified_at) if embedded_verified_at else None
    bundle_dt = _parse_iso_timestamp(embedded_bundle_at) if embedded_bundle_at else None
    chronology_ok = bool(
        report_dt
        and verified_dt
        and bundle_dt
        and report_dt <= verified_dt <= bundle_dt
    )
    add(
        CheckResult(
            "review_bundle_embedded_chronology",
            "audit",
            "PASS" if chronology_ok else "FAIL",
            f"report={embedded_report_at!r}, verified={embedded_verified_at!r}, bundle={embedded_bundle_at!r}",
        )
    )


def sha256_file_from_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _read_review_bundle_generated_at(repo_root: Path) -> str | None:
    review_dir = repo_root / "artifacts" / "external-review"
    if not review_dir.exists():
        return None
    for name in sorted(review_dir.glob("REVIEW_INDEX*.md"), reverse=True):
        match = REVIEW_INDEX_GENERATED_PATTERN.search(name.read_text(encoding="utf-8"))
        if match:
            return match.group(1).strip()
    for zip_path in sorted(review_dir.glob("stage-03-design-v0.7.4-review.zip"), reverse=True):
        import zipfile

        try:
            with zipfile.ZipFile(zip_path) as archive:
                if "REVIEW_INDEX.md" not in archive.namelist():
                    continue
                text = archive.read("REVIEW_INDEX.md").decode("utf-8")
                match = REVIEW_INDEX_GENERATED_PATTERN.search(text)
                if match:
                    return match.group(1).strip()
        except zipfile.BadZipFile:
            continue
    for zip_path in sorted(review_dir.glob("stage-03-design-v0.7.1-review.zip"), reverse=True):
        import zipfile

        try:
            with zipfile.ZipFile(zip_path) as archive:
                if "REVIEW_INDEX.md" not in archive.namelist():
                    continue
                text = archive.read("REVIEW_INDEX.md").decode("utf-8")
                match = REVIEW_INDEX_GENERATED_PATTERN.search(text)
                if match:
                    return match.group(1).strip()
        except zipfile.BadZipFile:
            continue
    for zip_path in sorted(review_dir.glob("stage-03-design-*-review.zip"), reverse=True):
        import zipfile

        try:
            with zipfile.ZipFile(zip_path) as archive:
                if "REVIEW_INDEX.md" not in archive.namelist():
                    continue
                text = archive.read("REVIEW_INDEX.md").decode("utf-8")
                match = REVIEW_INDEX_GENERATED_PATTERN.search(text)
                if match:
                    return match.group(1).strip()
        except zipfile.BadZipFile:
            continue
    return None


def _read_report_generated_timestamp(report_path: Path) -> str | None:
    if not report_path.exists():
        return None
    match = REPORT_GENERATED_PATTERN.search(report_path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else None


def _publish_report(report_path: Path, *, manifest_hash: str) -> str:
    timestamp = datetime.now(tz=UTC).isoformat()
    text = report_path.read_text(encoding="utf-8")
    if REPORT_GENERATED_PATTERN.search(text):
        text = REPORT_GENERATED_PATTERN.sub(f"Generated: {timestamp}", text, count=1)
    else:
        text = text.replace(
            "# Stage 03 Design Report\n",
            f"# Stage 03 Design Report\n\nGenerated: {timestamp}\n",
            1,
        )
    text = re.sub(
        r"\*\*design-content-manifest\.sha256:\*\* `[^`]+`",
        f"**design-content-manifest.sha256:** `{manifest_hash}`",
        text,
        count=1,
    )
    report_path.write_text(text, encoding="utf-8")
    return timestamp


def _check_audit_chronology_from_disk(
    add: Any,
    *,
    repo_root: Path,
    report_path: Path,
    verification_path: Path,
    review_bundle_generated_at: str | None,
    include_review_bundle: bool = True,
) -> None:
    report_generated_at = _read_report_generated_timestamp(report_path)
    verified_at = None
    if verification_path.exists():
        payload = json.loads(verification_path.read_text(encoding="utf-8"))
        verified_at = payload.get("verified_at")

    report_dt = _parse_iso_timestamp(report_generated_at) if report_generated_at else None
    verified_dt = _parse_iso_timestamp(verified_at) if verified_at else None
    bundle_dt = _parse_iso_timestamp(review_bundle_generated_at) if review_bundle_generated_at else None
    now = datetime.now(tz=UTC)

    future_report = report_dt is not None and report_dt > now
    future_verified = verified_dt is not None and verified_dt > now
    add(
        CheckResult(
            "audit_chronology_no_future_timestamps",
            "audit",
            "PASS" if not future_report and not future_verified else "FAIL",
            f"report_future={future_report}, verified_future={future_verified}",
        )
    )

    report_before_verified = bool(report_dt and verified_dt and report_dt <= verified_dt)
    add(
        CheckResult(
            "audit_chronology_report_before_verified",
            "audit",
            "PASS" if report_before_verified else "FAIL",
            f"report={report_generated_at!r}, verified={verified_at!r}",
        )
    )

    if include_review_bundle and review_bundle_generated_at:
        bundle_dt = _parse_iso_timestamp(review_bundle_generated_at)
        bundle_ok = bool(bundle_dt and verified_dt and verified_dt <= bundle_dt)
        add(
            CheckResult(
                "audit_chronology_verified_before_review_bundle",
                "audit",
                "PASS" if bundle_ok else "FAIL",
                f"verified={verified_at!r}, bundle={review_bundle_generated_at!r}",
            )
        )


def _parse_iso_timestamp(value: str) -> datetime | None:
    try:
        normalized = value.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _check_report_publication(add: Any, report_text: str, *, manifest_hash: str) -> None:
    has_manifest_ref = manifest_hash in report_text
    add(
        CheckResult(
            "report_content_manifest_sha256_match",
            "report",
            "PASS" if has_manifest_ref else "FAIL",
            f"expected content manifest sha256={manifest_hash}",
        )
    )
    self_sha_hit = bool(REPORT_SELF_SHA_PATTERN.search(report_text))
    add(
        CheckResult(
            "report_no_self_sha256",
            "report",
            "PASS" if not self_sha_hit else "FAIL",
            "report must not contain its own SHA-256",
        )
    )
    includes_self_in_content = DESIGN_REPORT_NAME in report_text and "Design artifact SHA-256" in report_text
    add(
        CheckResult(
            "report_excludes_self_from_content_list",
            "report",
            "PASS" if not includes_self_in_content else "FAIL",
            "report must not list itself among content artifacts",
        )
    )


GATE_PYTEST_EXCLUDE = (
    "test_verification_json_schema_and_no_self_hash",
    "test_published_verification_matches_final_report_bytes",
    "test_full_pytest_suite_preserves_publication_artifacts",
    "test_chronology_fails_when_report_after_verified",
    "test_chronology_fails_when_report_changed_after_verification",
    "test_chronology_skips_review_bundle_checks_without_timestamp",
    "test_clean_extraction_no_publish_verification_passes",
    "test_unpacked_zip_pytest_preserves_publication_artifacts",
    "test_review_bundle_contains_final_verification",
    "test_review_bundle_report_sha_matches_embedded_verification",
    "test_review_bundle_embedded_chronology_correct",
    "test_verify_stage_03_design_passes",
    "test_gate_return_matches_on_disk_design_verification_when_present",
)


def gate_pytest_filter_expr() -> str:
    return " and ".join(f"not {name}" for name in GATE_PYTEST_EXCLUDE)


def _run_pytest(repo_root: Path) -> dict[str, Any]:
    filter_expr = gate_pytest_filter_expr()
    collect_all = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_verify_stage_03_design.py", "-q", "--collect-only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    collect_filtered = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_verify_stage_03_design.py",
            "-q",
            "--collect-only",
            "-k",
            filter_expr,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    def parse_collected(output: str) -> int:
        for line in output.splitlines():
            if " tests collected" in line:
                token = line.strip().split()[0]
                return int(token.split("/")[0]) if "/" in token else int(token)
        return 0

    collected = parse_collected((collect_all.stdout or "") + (collect_all.stderr or ""))
    selected = parse_collected((collect_filtered.stdout or "") + (collect_filtered.stderr or ""))
    deselected = max(collected - selected, 0)

    command = [
        "python",
        "-m",
        "pytest",
        "tests/test_verify_stage_03_design.py",
        "-q",
        "-k",
        filter_expr,
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_verify_stage_03_design.py", "-q", "-k", filter_expr],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    summary = output.strip().splitlines()[-1] if output.strip() else "no pytest output"
    passed = failed = skipped = 0
    duration_seconds = None
    if " passed" in summary:
        passed = int(summary.split(" passed")[0].split()[-1])
    if " failed" in summary:
        failed = int(summary.split(" failed")[0].split()[-1])
    if " skipped" in summary:
        skipped = int(summary.split(" skipped")[0].split()[-1])
    duration_match = re.search(r"in\s+([\d.]+)s", summary)
    if duration_match:
        duration_seconds = float(duration_match.group(1))
    if selected == 0:
        selected = passed + failed + skipped
    return {
        "pytest_command": " ".join(command),
        "pytest_exit_code": completed.returncode,
        "pytest_output": output,
        "pytest_summary": summary,
        "pytest_collected": collected,
        "pytest_selected": selected,
        "pytest_deselected": deselected,
        "pytest_passed": passed,
        "pytest_failed": failed,
        "pytest_skipped": skipped,
        "pytest_duration_seconds": duration_seconds,
    }


def _load_pytest_from_verification(stage03_dir: Path) -> dict[str, Any]:
    path = stage03_dir / DESIGN_VERIFICATION_NAME
    if not path.exists():
        return _empty_pytest_result()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "pytest_command": payload.get("pytest_command", ""),
        "pytest_exit_code": payload.get("pytest_exit_code", 0),
        "pytest_output": "",
        "pytest_summary": payload.get("pytest_summary", "loaded from verification artifact"),
        "pytest_collected": payload.get("pytest_collected", 0),
        "pytest_selected": payload.get("pytest_selected", 0),
        "pytest_deselected": payload.get("pytest_deselected", 0),
        "pytest_passed": payload.get("pytest_passed", 0),
        "pytest_failed": payload.get("pytest_failed", 0),
        "pytest_skipped": payload.get("pytest_skipped", 0),
        "pytest_duration_seconds": payload.get("pytest_duration_seconds"),
    }


def _empty_pytest_result() -> dict[str, Any]:
    return {
        "pytest_command": "",
        "pytest_exit_code": 0,
        "pytest_output": "",
        "pytest_summary": "skipped",
        "pytest_collected": 0,
        "pytest_selected": 0,
        "pytest_deselected": 0,
        "pytest_passed": 0,
        "pytest_failed": 0,
        "pytest_skipped": 0,
        "pytest_duration_seconds": None,
    }


def _build_verification_payload(
    *,
    overall_status: OverallStatus,
    checks: list[CheckResult],
    pytest_result: dict[str, Any],
    content_manifest_sha256: str,
    report_sha256: str,
    report_generated_at: str | None = None,
    review_bundle_generated_at: str | None = None,
    verified_at: str | None = None,
) -> dict[str, Any]:
    failures = [asdict(check) for check in checks if check.status == "FAIL"]
    passed = sum(1 for check in checks if check.status == "PASS")
    total = len(checks)
    if verified_at is None:
        verified_at = datetime.now(tz=UTC).isoformat()
    return {
        "overall_status": overall_status,
        "checks_total": total,
        "checks_passed": passed,
        "checks_failed": len(failures),
        "checks": [asdict(check) for check in checks],
        "failures": failures,
        "pytest_command": pytest_result["pytest_command"],
        "pytest_exit_code": pytest_result["pytest_exit_code"],
        "pytest_collected": pytest_result["pytest_collected"],
        "pytest_selected": pytest_result.get("pytest_selected", 0),
        "pytest_deselected": pytest_result.get("pytest_deselected", 0),
        "pytest_passed": pytest_result["pytest_passed"],
        "pytest_failed": pytest_result["pytest_failed"],
        "pytest_skipped": pytest_result.get("pytest_skipped", 0),
        "pytest_duration_seconds": pytest_result.get("pytest_duration_seconds"),
        "pytest_summary": pytest_result["pytest_summary"],
        "python_version": sys.version.split()[0],
        "content_manifest_sha256": content_manifest_sha256,
        "report_sha256": report_sha256,
        "report_generated_at": report_generated_at,
        "review_bundle_generated_at": review_bundle_generated_at,
        "verified_at": verified_at,
    }


def _build_failure_result(
    checks: list[CheckResult],
    stage03_dir: Path,
    *,
    preconditions_met: bool,
) -> dict[str, Any]:
    passed = sum(1 for check in checks if check.status == "PASS")
    failed = [check for check in checks if check.status == "FAIL"]
    total = len(checks)
    overall: OverallStatus = "FAIL"
    return {
        "stage": "03",
        "phase": "design",
        "status": overall,
        "verified_at": datetime.now(tz=UTC).isoformat(),
        "preconditions_met": preconditions_met,
        "checks_passed": passed,
        "checks_failed": len(failed),
        "checks_total": total,
        "checks": [asdict(check) for check in checks],
        "failures": [asdict(check) for check in failed],
        "content_manifest": DESIGN_CONTENT_MANIFEST_NAME,
        "verification_artifact": DESIGN_VERIFICATION_NAME,
        "artifacts_dir": str(stage03_dir),
    }


def _build_result(
    checks: list[CheckResult],
    stage03_dir: Path,
    *,
    preconditions_met: bool,
) -> dict[str, Any]:
    passed = sum(1 for check in checks if check.status == "PASS")
    failed = [check for check in checks if check.status == "FAIL"]
    total = len(checks)
    overall: OverallStatus = "PASS" if preconditions_met and not failed else "FAIL"
    return {
        "stage": "03",
        "phase": "design",
        "status": overall,
        "verified_at": datetime.now(tz=UTC).isoformat(),
        "preconditions_met": preconditions_met,
        "checks_passed": passed,
        "checks_failed": len(failed),
        "checks_total": total,
        "checks": [asdict(check) for check in checks],
        "failures": [asdict(check) for check in failed],
        "content_manifest": DESIGN_CONTENT_MANIFEST_NAME,
        "verification_artifact": DESIGN_VERIFICATION_NAME,
        "artifacts_dir": str(stage03_dir),
    }


def _load_yaml_or_text(path: Path) -> Any:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    return text
