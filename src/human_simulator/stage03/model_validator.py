"""Validate canonical model structure, layers, relationships, and constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALUE_REPRESENTATION_FIELDS = frozenset(
    {"numeric_value", "text_value", "categorical_value", "boolean_value", "date_value"}
)

VARIABLE_IDENTITY_FIELDS = frozenset({"concept_id", "raw_code", "variable_key"})

REQUIRED_CONSTRAINT_KEYS = frozenset(
    {
        "branch_baseline_xor",
        "simulation_run_input_xor",
        "snapshot_component_value_constraint",
        "predicted_state_value_constraint",
        "variable_identity_required",
        "scenario_intervention_identity",
        "scenario_event_effective_at_required",
        "scenario_event_effective_until_gte_effective_at",
        "predicted_state_target_at_gte_generated_at",
        "uncertainty_bounds_order",
        "simulation_run_completed_requires",
        "simulation_run_random_seed_optional_only_if_deterministic",
        "extension_payload_requires_namespace",
        "subject_characteristic_identity",
        "subject_characteristic_value_constraint",
        "subject_characteristic_no_auto_sex_normalization",
        "subject_characteristic_cross_source_consolidation_forbidden",
        "subject_characteristic_no_cross_source_overwrite",
        "scenario_event_precedence_contract",
        "provenance_profile_by_entity",
        "forbid_derived_in_simulation_scenario",
    }
)

LAYER_ALLOWED_ORIGINS: dict[str, frozenset[str]] = {
    "evidence": frozenset({"OBSERVED", "CORRECTED", "NORMALIZED", "ANNOTATED", "DERIVED", "IMPUTED"}),
    "simulation_scenario": frozenset({"SYNTHETIC"}),
    "prediction": frozenset({"PREDICTED"}),
    "cross_cutting": frozenset(),
}

ENTITY_PRIMARY_KEY_FIELDS: dict[str, frozenset[str]] = {
    "SourceSystem": frozenset({"source_system_id"}),
    "SourceRecord": frozenset({"source_record_id"}),
    "Subject": frozenset({"subject_id"}),
    "SubjectCharacteristic": frozenset({"characteristic_id"}),
    "Provider": frozenset({"provider_id"}),
    "Encounter": frozenset({"encounter_id"}),
    "Observation": frozenset({"observation_id"}),
    "ObservationComponent": frozenset({"component_id"}),
    "ClinicalAssertion": frozenset({"assertion_id"}),
    "Intervention": frozenset({"intervention_id"}),
    "Procedure": frozenset({"procedure_id"}),
    "ClinicalDocument": frozenset({"document_id"}),
    "Concept": frozenset({"concept_id"}),
    "Unit": frozenset({"unit_id"}),
    "Scenario": frozenset({"scenario_id"}),
    "ScenarioBranch": frozenset({"branch_id"}),
    "ScenarioIntervention": frozenset({"scenario_intervention_id"}),
    "ScenarioEvent": frozenset({"scenario_event_id"}),
    "SimulationRun": frozenset({"simulation_run_id"}),
    "EvidenceStateSnapshot": frozenset({"snapshot_id"}),
    "StateSnapshotComponent": frozenset({"component_id"}),
    "ScenarioCheckpoint": frozenset({"checkpoint_id"}),
    "ScenarioCheckpointState": frozenset({"checkpoint_state_id"}),
    "PredictedState": frozenset({"predicted_state_id"}),
}

SCENARIO_ENTITIES_REQUIRING_PROVENANCE_FIELD = frozenset(
    {
        "Scenario",
        "ScenarioBranch",
        "ScenarioIntervention",
        "ScenarioEvent",
        "SimulationRun",
        "ScenarioCheckpoint",
        "ScenarioCheckpointState",
    }
)


@dataclass(frozen=True)
class ModelValidationError:
    name: str
    detail: str


def collect_entity_fields(model: dict[str, Any]) -> dict[str, frozenset[str]]:
    entities = model.get("entities", {})
    resolved: dict[str, set[str]] = {}

    def merge_fields(name: str, seen: set[str]) -> set[str]:
        if name in resolved:
            return set(resolved[name])
        if name in seen:
            return set()
        seen.add(name)
        block = entities.get(name, {})
        fields = set(block.get("fields", {}).keys())
        parent = block.get("extends")
        if isinstance(parent, str):
            fields |= merge_fields(parent, seen)
        resolved[name] = fields
        return fields

    for name in entities:
        merge_fields(name, set())
    return {name: frozenset(fields) for name, fields in resolved.items()}


def detect_inheritance_cycles(model: dict[str, Any]) -> list[str]:
    entities = model.get("entities", {})
    cycles: list[str] = []

    def visit(name: str, stack: list[str]) -> None:
        if name in stack:
            cycles.append(" -> ".join(stack + [name]))
            return
        block = entities.get(name, {})
        parent = block.get("extends")
        if isinstance(parent, str):
            visit(parent, stack + [name])

    for name in entities:
        visit(name, [])
    return cycles


def validate_canonical_model(model: dict[str, Any]) -> list[ModelValidationError]:
    errors: list[ModelValidationError] = []
    entities = model.get("entities", {})
    entity_names = set(entities.keys())
    field_map = collect_entity_fields(model)

    _validate_constraints(model, errors)
    _validate_layers_and_origins(entities, errors)
    _validate_inheritance(entities, entity_names, errors)
    _validate_required_entities(entity_names, entities, field_map, errors)
    _validate_provenance_fields(entities, field_map, errors)
    _validate_entity_shapes(entities, field_map, errors)
    _validate_relationships(model, entity_names, field_map, errors)

    return errors


def _validate_constraints(model: dict[str, Any], errors: list[ModelValidationError]) -> None:
    constraints = model.get("constraints", {})
    if not isinstance(constraints, dict):
        errors.append(ModelValidationError("constraints_section", "constraints must be a mapping"))
        return
    for key in REQUIRED_CONSTRAINT_KEYS:
        if key not in constraints:
            errors.append(ModelValidationError(f"constraint_{key}_missing", f"constraints.{key} is required"))


def _validate_layers_and_origins(entities: dict[str, Any], errors: list[ModelValidationError]) -> None:
    for name, block in entities.items():
        layer = block.get("layer")
        origin = block.get("record_origin")
        if layer in LAYER_ALLOWED_ORIGINS and origin:
            allowed = LAYER_ALLOWED_ORIGINS[layer]
            if origin not in allowed:
                errors.append(
                    ModelValidationError(
                        "record_origin_layer_match",
                        f"{name}.record_origin={origin!r} not allowed for layer={layer!r}",
                    )
                )


def _validate_inheritance(
    entities: dict[str, Any], entity_names: set[str], errors: list[ModelValidationError]
) -> None:
    for name, block in entities.items():
        parent = block.get("extends")
        if parent and parent not in entity_names:
            errors.append(
                ModelValidationError("extends_target_exists", f"{name} extends missing entity {parent!r}")
            )
    for cycle in detect_inheritance_cycles({"entities": entities}):
        errors.append(ModelValidationError("inheritance_cycle", cycle))


def _validate_required_entities(
    entity_names: set[str],
    entities: dict[str, Any],
    field_map: dict[str, frozenset[str]],
    errors: list[ModelValidationError],
) -> None:
    if "StateSnapshot" in entity_names:
        errors.append(ModelValidationError("legacy_state_snapshot", "StateSnapshot must be removed"))
    for required in (
        "EvidenceStateSnapshot",
        "ScenarioCheckpoint",
        "StateSnapshotComponent",
        "ScenarioIntervention",
        "ScenarioCheckpointState",
        "SubjectCharacteristic",
    ):
        if required not in entity_names:
            errors.append(ModelValidationError(f"{required.lower()}_present", f"{required} required"))

    if "ScenarioCheckpoint" in entities:
        cp_fields = field_map.get("ScenarioCheckpoint", frozenset())
        if "predicted_state_ids" in cp_fields:
            errors.append(
                ModelValidationError(
                    "checkpoint_no_opaque_predicted_array",
                    "ScenarioCheckpoint must use ScenarioCheckpointState rows",
                )
            )

    branch_fields = set(entities.get("ScenarioBranch", {}).get("fields", {}).keys())
    if "forked_from_branch_id" in branch_fields:
        errors.append(ModelValidationError("branch_no_duplicate_fork_field", "forked_from_branch_id forbidden"))


def _validate_provenance_fields(
    entities: dict[str, Any],
    field_map: dict[str, frozenset[str]],
    errors: list[ModelValidationError],
) -> None:
    for name, block in entities.items():
        if name in {"SourceSystem", "Provenance"}:
            continue
        if block.get("layer") == "cross_cutting":
            continue
        if block.get("requires_provenance") is not True:
            continue
        if "provenance" not in field_map.get(name, frozenset()):
            errors.append(
                ModelValidationError(
                    "provenance_field_required",
                    f"{name} requires_provenance=true but has no provenance field",
                )
            )

    for name in SCENARIO_ENTITIES_REQUIRING_PROVENANCE_FIELD:
        if name in entities and "provenance" not in field_map.get(name, frozenset()):
            errors.append(ModelValidationError("scenario_entity_provenance", f"{name} missing provenance field"))


def _validate_entity_shapes(
    entities: dict[str, Any],
    field_map: dict[str, frozenset[str]],
    errors: list[ModelValidationError],
) -> None:
    event_fields = field_map.get("ScenarioEvent", frozenset())
    if "intervention_id" in event_fields:
        errors.append(ModelValidationError("scenario_event_no_evidence_intervention", "intervention_id forbidden"))
    if "scenario_intervention_id" not in event_fields:
        errors.append(ModelValidationError("scenario_event_scenario_intervention", "scenario_intervention_id required"))
    if "payload" in event_fields:
        errors.append(ModelValidationError("scenario_event_typed_fields", "generic payload forbidden"))
    for ext_field in ("extension_namespace", "extension_schema_version"):
        if ext_field not in event_fields:
            errors.append(ModelValidationError("scenario_event_extension_metadata", f"{ext_field} required"))

    run_fields = field_map.get("SimulationRun", frozenset())
    if "input_state_reference" in run_fields:
        errors.append(ModelValidationError("simulation_run_no_input_state_reference", "input_state_reference removed"))
    for field in ("input_evidence_snapshot_id", "input_checkpoint_id"):
        if field not in run_fields:
            errors.append(ModelValidationError("simulation_run_input_xor", f"SimulationRun missing {field}"))
    for field in (
        "model_id",
        "model_version",
        "model_artifact_hash",
        "configuration_hash",
        "random_seed",
        "started_at",
        "completed_at",
        "run_status",
        "deterministic_model",
    ):
        if field not in run_fields:
            errors.append(ModelValidationError("simulation_run_reproducibility", f"SimulationRun missing {field}"))

    pred_fields = field_map.get("PredictedState", frozenset())
    for forbidden in ("predicted_value", "point_estimate", "input_snapshot_id"):
        if forbidden in pred_fields:
            errors.append(ModelValidationError("predicted_state_shape", f"PredictedState must not contain {forbidden}"))
    for required in ("prediction_status", "failure_reason"):
        if required not in pred_fields:
            errors.append(ModelValidationError("predicted_state_shape", f"PredictedState missing {required}"))
    if not VARIABLE_IDENTITY_FIELDS & pred_fields:
        errors.append(ModelValidationError("variable_identity_required", "PredictedState missing identity fields"))

    comp_fields = field_map.get("StateSnapshotComponent", frozenset())
    if "state_variables" in comp_fields:
        errors.append(ModelValidationError("snapshot_component_no_generic_state", "state_variables forbidden"))
    if not VARIABLE_IDENTITY_FIELDS & comp_fields:
        errors.append(ModelValidationError("variable_identity_required", "StateSnapshotComponent missing identity fields"))
    if "missingness_reason" not in comp_fields:
        errors.append(ModelValidationError("snapshot_component_value_constraint", "missingness_reason required"))

    si_fields = field_map.get("ScenarioIntervention", frozenset())
    if "ScenarioIntervention" in entities:
        if "intervention_kind" not in si_fields:
            errors.append(ModelValidationError("scenario_intervention_kind", "intervention_kind required"))
        if "concept_id" not in si_fields or "raw_name" not in si_fields:
            errors.append(ModelValidationError("scenario_intervention_identity", "concept_id and raw_name required"))
        if entities["ScenarioIntervention"].get("record_origin") != "SYNTHETIC":
            errors.append(ModelValidationError("scenario_intervention_synthetic", "ScenarioIntervention must be SYNTHETIC"))

    sc_fields = field_map.get("SubjectCharacteristic", frozenset())
    if "SubjectCharacteristic" in entities:
        required_sc = {
            "characteristic_id",
            "subject_id",
            "characteristic_code",
            "concept_id",
            "raw_code",
            "raw_value",
            "date_value",
            "numeric_value",
            "text_value",
            "categorical_value",
            "boolean_value",
            "raw_unit",
            "normalized_unit",
            "effective_at",
            "recorded_at",
            "status",
            "provenance",
        }
        missing_sc = required_sc - sc_fields
        if missing_sc:
            errors.append(
                ModelValidationError(
                    "subject_characteristic_fields",
                    f"SubjectCharacteristic missing fields: {sorted(missing_sc)}",
                )
            )


def _entity_extends_chain(model: dict[str, Any], entity_name: str) -> list[str]:
    entities = model.get("entities", {})
    chain: list[str] = []
    current = entity_name
    seen: set[str] = set()
    while True:
        block = entities.get(current, {})
        parent = block.get("extends")
        if not isinstance(parent, str) or parent in seen:
            break
        seen.add(parent)
        chain.append(parent)
        current = parent
    return chain


def _external_reference_keys(model: dict[str, Any]) -> set[tuple[str, str]]:
    refs = model.get("external_references", {})
    keys: set[tuple[str, str]] = set()
    for qualified, _meta in refs.items():
        if "." not in qualified:
            continue
        entity, field = qualified.split(".", 1)
        keys.add((entity, field))
    return keys


def _is_primary_key_field(
    entity_name: str,
    field: str,
    incoming_targets: set[tuple[str, str]],
    model: dict[str, Any],
) -> bool:
    if (entity_name, field) in incoming_targets:
        return True
    if field in ENTITY_PRIMARY_KEY_FIELDS.get(entity_name, frozenset()):
        return True
    for parent in _entity_extends_chain(model, entity_name):
        if field in ENTITY_PRIMARY_KEY_FIELDS.get(parent, frozenset()):
            return True
    return False


def _validate_relationships(
    model: dict[str, Any],
    entity_names: set[str],
    field_map: dict[str, frozenset[str]],
    errors: list[ModelValidationError],
) -> None:
    relationships = model.get("relationships", [])
    covered: set[tuple[str, str]] = set()
    incoming_targets: set[tuple[str, str]] = set()
    external_refs = _external_reference_keys(model)

    for index, rel in enumerate(relationships):
        from_entity = rel.get("from")
        to_entity = rel.get("to")
        from_field = rel.get("from_field")
        to_field = rel.get("to_field")

        if from_entity not in entity_names:
            errors.append(ModelValidationError("relationship_from_exists", f"relationship[{index}] from={from_entity!r}"))
        if to_entity not in entity_names:
            errors.append(ModelValidationError("relationship_to_exists", f"relationship[{index}] to={to_entity!r}"))

        if from_field and from_entity in field_map and from_field not in field_map[from_entity]:
            errors.append(
                ModelValidationError(
                    "relationship_from_field_exists",
                    f"relationship[{index}] from_field {from_field!r} missing on {from_entity}",
                )
            )
        if to_field and to_entity in field_map and to_field not in field_map[to_entity]:
            errors.append(
                ModelValidationError(
                    "relationship_to_field_exists",
                    f"relationship[{index}] to_field {to_field!r} missing on {to_entity}",
                )
            )
        if from_entity and from_field:
            covered.add((from_entity, from_field))
        if to_entity and to_field:
            incoming_targets.add((to_entity, to_field))

    concept_link_fields = {
        ("Observation", "normalized_concept"),
        ("ClinicalAssertion", "normalized_concept"),
        ("Intervention", "normalized_concept"),
        ("Procedure", "normalized_concept"),
        ("SubjectCharacteristic", "concept_id"),
    }
    unit_link_fields = {
        ("Observation", "normalized_unit"),
        ("ObservationComponent", "normalized_unit"),
        ("StateSnapshotComponent", "normalized_unit"),
        ("PredictedState", "normalized_unit"),
        ("SubjectCharacteristic", "normalized_unit"),
    }
    for entity_name, fields in field_map.items():
        parent_chain = _entity_extends_chain(model, entity_name)
        for field in fields:
            is_fk_like = field.endswith("_id") or field.endswith("_reference") or field == "normalized_concept" or field == "normalized_unit"
            if not is_fk_like:
                continue
            if field.startswith("source_") and field != "source_system_id":
                continue
            if (entity_name, field) in external_refs:
                continue
            if _is_primary_key_field(entity_name, field, incoming_targets, model):
                continue
            if (entity_name, field) in covered:
                continue
            if any((parent, field) in covered for parent in parent_chain):
                continue
            if (entity_name, field) in concept_link_fields | unit_link_fields and (entity_name, field) not in covered:
                errors.append(
                    ModelValidationError(
                        "fk_field_has_relationship",
                        f"{entity_name}.{field} has no relationship coverage",
                    )
                )
                continue
            if field.endswith("_id") or field.endswith("_reference"):
                errors.append(
                    ModelValidationError(
                        "fk_field_has_relationship",
                        f"{entity_name}.{field} has no relationship coverage",
                    )
                )
