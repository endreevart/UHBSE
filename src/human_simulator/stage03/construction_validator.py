"""Validate record construction contract completeness and mapping collision rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from human_simulator.stage03.canonical_id import (
    validate_canonical_id_contract_document,
    validate_identity_rule_references,
)
from human_simulator.stage03.mapping_validator import iter_draft_mappings, mapping_source_columns
from human_simulator.stage03.model_validator import collect_entity_fields
from human_simulator.stage03.schema_index import SchemaIndex

CONSTRUCTION_GROUP_REQUIRED_KEYS = frozenset(
    {
        "group_id",
        "source_system",
        "source_relation",
        "source_primary_key",
        "target_entity",
        "cardinality",
        "row_filter",
        "identity_rule",
        "subject_resolution",
        "generated_fields",
        "constant_fields",
        "mapped_fields",
        "relationship_fields",
        "provenance_profile",
        "null_policy",
        "collision_policy",
        "mapping_status",
        "implementation_status",
    }
)

V07_REQUIRED_GROUPS = frozenset(
    {
        "source_a_account_patient_characteristics",
        "source_a_appointment_encounter",
        "source_a_observation_header",
        "source_a_observation_component",
        "source_b_users_subject",
        "source_b_users_profile_characteristics",
        "source_b_profilaxys_profile_characteristics",
        "source_b_consultations_encounter",
        "source_b_lab_observation_header",
        "source_b_analyses_constructor_component",
        "source_b_profilaxys_profile_observation",
        "source_b_profilaxys_profile_observation_components",
    }
)

SOURCE_SYSTEM_SCHEMA: dict[str, str] = {
    "magerya_api": "source_a",
    "kgz_raw": "source_b",
}

ALLOWED_ID_ALGORITHMS = frozenset({"HMAC-SHA256"})

FORBIDDEN_ID_ALGORITHMS = frozenset(
    {
        "random_uuid",
        "uuid4",
        "uuid",
        "auto_increment",
        "cross_source_shared_id",
        "hmac_sha256",
    }
)

COLLISION_RESOLUTION_TYPES = frozenset({"combination_rule", "precedence_rule", "grouping_rule"})

PROVENANCE_SOURCE_BACKED_ALGORITHMS = frozenset(
    {
        "record_origin",
        "source_system",
        "source_schema",
        "source_relation",
        "source_record_locator",
        "transformation_id",
        "transformation_version",
        "transformed_at",
        "input_artifact_sha256",
        "confidence",
        "mapping_status",
    }
)

CONSTRUCTION_ENTITY_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "SubjectCharacteristic": frozenset(
        {
            "characteristic_id",
            "subject_id",
            "raw_code",
            "raw_value",
            "status",
            "provenance",
        }
    ),
    "SubjectCharacteristic_identity": frozenset({"characteristic_code", "concept_id"}),
    "Subject": frozenset({"subject_id", "source_system_id", "source_subject_key", "provenance"}),
    "Encounter": frozenset(
        {"encounter_id", "subject_id", "data_level", "provenance"}
    ),
    "Observation": frozenset({"observation_id", "subject_id", "data_level", "provenance"}),
    "ObservationComponent": frozenset(
        {"component_id", "observation_id", "raw_code", "raw_value", "provenance"}
    ),
    "EvidenceStateSnapshot": frozenset(
        {"snapshot_id", "subject_id", "snapshot_at", "snapshot_kind", "provenance"}
    ),
    "StateSnapshotComponent": frozenset(
        {
            "component_id",
            "snapshot_id",
            "provenance",
        }
    ),
}


@dataclass(frozen=True)
class ConstructionValidationError:
    name: str
    detail: str


def collect_entity_required_fields(model: dict[str, Any]) -> dict[str, frozenset[str]]:
    entities = model.get("entities", {})
    required: dict[str, set[str]] = {}

    def merge(name: str, seen: set[str]) -> set[str]:
        if name in required:
            return set(required[name])
        if name in seen:
            return set()
        seen.add(name)
        block = entities.get(name, {})
        fields = block.get("fields", {})
        req = {field for field, spec in fields.items() if isinstance(spec, dict) and spec.get("nullable") is False}
        parent = block.get("extends")
        if isinstance(parent, str):
            req |= merge(parent, seen)
        required[name] = req
        return req

    for name in entities:
        merge(name, set())
    return {name: frozenset(fields) for name, fields in required.items()}


def collect_populated_canonical_fields(group: dict[str, Any]) -> set[str]:
    populated: set[str] = set()
    generated = group.get("generated_fields", {})
    if isinstance(generated, dict):
        populated.update(generated.keys())
    constants = group.get("constant_fields", {})
    if isinstance(constants, dict):
        populated.update(constants.keys())
    for item in group.get("mapped_fields", []):
        if not isinstance(item, dict):
            continue
        for key in ("canonical_field", "typed_field"):
            value = item.get(key)
            if isinstance(value, str):
                populated.add(value)
        if item.get("characteristic_code"):
            populated.add("characteristic_code")
        if item.get("raw_code"):
            populated.add("raw_code")
        populated.add("raw_value")
    relationships = group.get("relationship_fields", {})
    if isinstance(relationships, dict):
        populated.update(relationships.keys())
    if group.get("provenance_profile"):
        populated.add("provenance")
    identity_rule = group.get("identity_rule", {})
    if isinstance(identity_rule, dict):
        pk_map = {
            "characteristic_id": "characteristic_id",
            "subject_id": "subject_id",
            "observation_id": "observation_id",
            "component_id": "component_id",
            "encounter_id": "encounter_id",
            "source_record_id": "source_record_id",
        }
        for key in identity_rule:
            mapped = pk_map.get(key)
            if mapped:
                populated.add(mapped)
    return populated


def validate_construction_group_required_field_coverage(
    group: dict[str, Any],
    *,
    entity_fields: dict[str, frozenset[str]],
    entity_required_fields: dict[str, frozenset[str]],
) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    group_id = group.get("group_id", "<unknown>")
    target = group.get("target_entity")
    if not isinstance(target, str):
        return [ConstructionValidationError(f"construction_group_{group_id}_target", f"{group_id}: missing target_entity")]

    known_fields = entity_fields.get(target, frozenset())
    required_fields = entity_required_fields.get(target, frozenset())
    populated = collect_populated_canonical_fields(group)

    unknown = sorted(populated - known_fields - {"raw_value"})
    if unknown:
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_unknown_fields",
                f"{group_id} populated unknown fields {unknown} for entity {target}",
            )
        )

    missing = sorted(required_fields - populated)
    if missing and not group.get("implementation_blocked"):
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_missing_required_fields",
                f"{group_id} missing required fields {missing}",
            )
        )

    if target == "SubjectCharacteristic":
        identity = CONSTRUCTION_ENTITY_REQUIRED_FIELDS["SubjectCharacteristic_identity"]
        if not (identity & populated):
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_identity",
                    f"{group_id} requires at least one of characteristic_code or concept_id",
                )
            )

    return errors


def _schema_for_source_system(source_system: str) -> str | None:
    return SOURCE_SYSTEM_SCHEMA.get(source_system)


def _schema_index_for_group(
    group: dict[str, Any],
    *,
    schema_index_a: SchemaIndex | None,
    schema_index_b: SchemaIndex | None,
) -> SchemaIndex | None:
    source = group.get("source_system")
    if source == "magerya_api":
        return schema_index_a
    if source == "kgz_raw":
        return schema_index_b
    return None


def _is_unconditional_row_filter(row_filter: Any) -> bool:
    if row_filter == "always":
        return True
    if isinstance(row_filter, dict) and row_filter.get("type") == "always":
        return True
    return False


def _collect_group_column_refs(group: dict[str, Any]) -> set[str]:
    columns: set[str] = set()
    pk = group.get("source_primary_key")
    if isinstance(pk, str):
        columns.add(pk)

    for item in group.get("mapped_fields", []):
        if isinstance(item, dict):
            col = item.get("source_column")
            if isinstance(col, str):
                columns.add(col)

    for _field, spec in group.get("timestamp_precedence", {}).items():
        if isinstance(spec, dict):
            for col in spec.get("sources", []):
                if isinstance(col, str):
                    columns.add(col)

    subject = group.get("subject_resolution")
    if isinstance(subject, dict):
        via = subject.get("via_column")
        if isinstance(via, str):
            columns.add(via)

    row_filter = group.get("row_filter")
    if isinstance(row_filter, dict):
        ref = row_filter.get("reference", {})
        if isinstance(ref, dict):
            col = ref.get("column")
            if isinstance(col, str):
                columns.discard(col)

    collision = group.get("collision_policy")
    if isinstance(collision, dict):
        for _field, policy in collision.items():
            if isinstance(policy, dict):
                for col in policy.get("source_columns", []):
                    if isinstance(col, str):
                        columns.add(col)

    return columns


def _collect_subject_group_refs(group: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    subject = group.get("subject_resolution")
    if isinstance(subject, dict):
        sg = subject.get("subject_group")
        if isinstance(sg, str):
            refs.add(sg)
        fg = subject.get("from_group")
        if isinstance(fg, str):
            refs.add(fg)
    return refs


def _group_field_sources(group: dict[str, Any]) -> dict[str, set[str]]:
    sources: dict[str, set[str]] = {
        "generated": set(),
        "constant": set(),
        "mapped": set(),
        "relationship": set(),
        "inherited": set(),
        "provenance": set(),
    }

    for field in group.get("generated_fields", {}):
        if isinstance(field, str):
            sources["generated"].add(field)

    constant_fields = group.get("constant_fields", {})
    if isinstance(constant_fields, dict):
        sources["constant"].update(constant_fields.keys())

    for item in group.get("mapped_fields", []):
        if not isinstance(item, dict):
            continue
        canonical_field = item.get("canonical_field")
        typed_field = item.get("typed_field")
        if isinstance(canonical_field, str):
            sources["mapped"].add(canonical_field)
        if isinstance(typed_field, str):
            sources["mapped"].add(typed_field)
        if item.get("characteristic_code"):
            sources["mapped"].add("characteristic_code")
        if item.get("raw_code"):
            sources["mapped"].add("raw_code")
        sources["mapped"].add("raw_value")

    relationship_fields = group.get("relationship_fields", {})
    if isinstance(relationship_fields, dict):
        sources["relationship"].update(relationship_fields.keys())

    if group.get("provenance_profile"):
        sources["provenance"].add("provenance")

    identity_rule = group.get("identity_rule", {})
    if isinstance(identity_rule, dict):
        for key in identity_rule:
            pk_field = {
                "characteristic_id": "characteristic_id",
                "subject_id": "subject_id",
                "observation_id": "observation_id",
                "component_id": "component_id",
                "encounter_id": "encounter_id",
            }.get(key)
            if pk_field:
                sources["generated"].add(pk_field)

    timestamp = group.get("timestamp_precedence", {})
    if isinstance(timestamp, dict):
        for field in timestamp:
            sources["mapped"].add(field)

    if group.get("mapping_status"):
        sources["constant"].add("status")

    if group.get("raw_value_serialization"):
        sources["mapped"].add("raw_value")

    return sources


def validate_identity_algorithm(
    identity_rule: dict[str, Any],
    *,
    canonical_id_contract: dict[str, Any] | None,
    group_id: str,
) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    contract_spec = (
        canonical_id_contract.get("canonical_id_contract", {})
        if isinstance(canonical_id_contract, dict)
        else {}
    )
    expected_algorithm = contract_spec.get("algorithm", "HMAC-SHA256")
    forbidden = set(contract_spec.get("forbidden_algorithms", [])) | FORBIDDEN_ID_ALGORITHMS

    for field_name, spec in identity_rule.items():
        if not isinstance(spec, dict):
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_identity_spec",
                    f"{group_id} identity_rule.{field_name} must be mapping",
                )
            )
            continue
        algorithm = spec.get("algorithm")
        if not isinstance(algorithm, str):
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_identity_algorithm",
                    f"{group_id} missing identity algorithm for {field_name}",
                )
            )
            continue
        if algorithm in forbidden or algorithm.lower() in forbidden:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_forbidden_algorithm",
                    f"{group_id} forbidden identity algorithm {algorithm!r}",
                )
            )
        if algorithm not in ALLOWED_ID_ALGORITHMS:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_unknown_algorithm",
                    f"{group_id} unknown or undefined identity algorithm {algorithm!r}",
                )
            )
        if algorithm != expected_algorithm:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_algorithm_mismatch",
                    f"{group_id} algorithm {algorithm!r} != contract {expected_algorithm!r}",
                )
            )
        if not spec.get("contract"):
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_identity_contract_ref",
                    f"{group_id} identity_rule.{field_name} missing contract reference",
                )
            )
        if not spec.get("key_reference"):
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_identity_key_ref",
                    f"{group_id} identity_rule.{field_name} missing key_reference",
                )
            )
        inputs = spec.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_identity_inputs",
                    f"{group_id} identity_rule.{field_name} requires strict input field order",
                )
            )

    input_fields = contract_spec.get("input_fields", {})
    if contract_spec and identity_rule and field_name == next(iter(identity_rule)):
        if not contract_spec.get("message_layout"):
            errors.append(
                ConstructionValidationError(
                    "canonical_id_contract_message_layout",
                    "canonical_id_contract missing message_layout",
                )
            )
        if contract_spec.get("alternate_output_encoding"):
            errors.append(
                ConstructionValidationError(
                    "canonical_id_contract_alternate_encoding",
                    "alternate_output_encoding must not be defined",
                )
            )
        if input_fields.get("null_encoding") == "empty_utf8_string":
            errors.append(
                ConstructionValidationError(
                    "canonical_id_contract_null_encoding",
                    "null must not encode as empty UTF-8 string",
                )
            )

    if isinstance(canonical_id_contract, dict):
        for cid_error in validate_identity_rule_references(
            identity_rule,
            canonical_id_contract=canonical_id_contract,
            group_id=group_id,
        ):
            errors.append(
                ConstructionValidationError(cid_error.name, cid_error.detail)
            )

    return errors


def validate_provenance_population(group: dict[str, Any]) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    group_id = group.get("group_id", "<unknown>")
    if group.get("provenance_profile") != "SOURCE_BACKED":
        return errors

    population = group.get("provenance_population")
    if not isinstance(population, dict):
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_provenance_population",
                f"{group_id} SOURCE_BACKED missing provenance_population",
            )
        )
        return errors

    algorithms = population.get("algorithms", {})
    if not isinstance(algorithms, dict):
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_provenance_algorithms",
                f"{group_id} provenance_population missing algorithms",
            )
        )
        return errors

    missing = PROVENANCE_SOURCE_BACKED_ALGORITHMS - set(algorithms.keys())
    if missing:
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_provenance_incomplete",
                f"{group_id} provenance_population missing algorithms for {sorted(missing)}",
            )
        )
    return errors


def validate_construction_group_completeness(
    group: dict[str, Any],
    entity_fields: dict[str, frozenset[str]],
) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    group_id = group.get("group_id", "<unknown>")
    target = group.get("target_entity")
    if not isinstance(target, str):
        return [ConstructionValidationError("construction_target_entity", f"{group_id}: missing target_entity")]

    required = CONSTRUCTION_ENTITY_REQUIRED_FIELDS.get(target)
    if not required:
        return errors

    sources = _group_field_sources(group)
    covered = set().union(*sources.values())
    missing = required - covered
    if missing and not group.get("implementation_blocked"):
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_incomplete",
                f"{group_id} missing population for {sorted(missing)}",
            )
        )

    if target == "SubjectCharacteristic":
        identity = CONSTRUCTION_ENTITY_REQUIRED_FIELDS["SubjectCharacteristic_identity"]
        if not (identity & covered):
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_identity",
                    f"{group_id} requires at least one of characteristic_code or concept_id",
                )
            )

    if target == "ObservationComponent":
        parent = group.get("parent_group")
        if not parent:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_parent",
                    f"{group_id} ObservationComponent requires parent_group",
                )
            )
        if "observation_id" not in covered:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_observation_id",
                    f"{group_id} missing observation_id relationship",
                )
            )

    identity_rule = group.get("identity_rule", {})
    if not identity_rule:
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_identity_rule",
                f"{group_id} missing identity_rule",
            )
        )

    subject_resolution = group.get("subject_resolution")
    if subject_resolution is None:
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_subject_resolution",
                f"{group_id} missing subject_resolution",
            )
        )

    if not group.get("raw_value_serialization") and target in {
        "SubjectCharacteristic",
        "ObservationComponent",
    }:
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_raw_value",
                f"{group_id} missing raw_value_serialization",
            )
        )

    if not group.get("provenance_profile"):
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_provenance",
                f"{group_id} missing provenance_profile",
            )
        )

    wide = group.get("wide_to_long", {})
    if wide.get("enabled") and target == "ObservationComponent":
        mapped = group.get("mapped_fields", [])
        for item in mapped:
            if isinstance(item, dict) and not item.get("raw_code"):
                errors.append(
                    ConstructionValidationError(
                        f"construction_group_{group_id}_component_raw_code",
                        f"{group_id} wide-to-long component missing raw_code for {item.get('source_column')}",
                    )
                )

    return errors


def validate_group_schema_references(
    group: dict[str, Any],
    *,
    schema_index_a: SchemaIndex | None,
    schema_index_b: SchemaIndex | None,
) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    group_id = group.get("group_id", "<unknown>")
    relation = group.get("source_relation")
    if not isinstance(relation, str):
        return errors

    index = _schema_index_for_group(group, schema_index_a=schema_index_a, schema_index_b=schema_index_b)
    if index is None:
        if schema_index_a is not None or schema_index_b is not None:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_source_system",
                    f"{group_id} unknown source_system {group.get('source_system')!r}",
                )
            )
        return errors

    if not index.relation_exists(relation):
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_source_relation",
                f"{group_id} source_relation {relation!r} not in schema profile",
            )
        )
        return errors

    for column in _collect_group_column_refs(group):
        if not index.column_exists(relation, column):
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_column_{column}",
                    f"{group_id} column {column!r} not in {relation}",
                )
            )

    row_filter = group.get("row_filter")
    if isinstance(row_filter, dict):
        ref = row_filter.get("reference", {})
        if isinstance(ref, dict):
            ref_relation = ref.get("relation")
            ref_column = ref.get("column")
            if isinstance(ref_relation, str):
                ref_index = (
                    schema_index_b
                    if ref_relation.startswith("public.") or ref_relation.startswith("quest_")
                    else schema_index_a
                )
                if ref_index and not ref_index.relation_exists(ref_relation):
                    errors.append(
                        ConstructionValidationError(
                            f"construction_group_{group_id}_row_filter_ref",
                            f"{group_id} row_filter reference relation {ref_relation!r} missing",
                        )
                    )
                elif (
                    ref_index
                    and isinstance(ref_column, str)
                    and not ref_index.column_exists(ref_relation, ref_column)
                ):
                    errors.append(
                        ConstructionValidationError(
                            f"construction_group_{group_id}_row_filter_ref_column",
                            f"{group_id} row_filter reference column {ref_column!r} not in {ref_relation}",
                        )
                    )

    if relation == "public.users" and _is_unconditional_row_filter(row_filter):
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_users_unconditional",
                f"{group_id} public.users SUBJECT_ROOT_CANDIDATE forbids unconditional row_filter",
            )
        )

    return errors


def validate_group_references(
    group: dict[str, Any],
    group_ids: set[str],
) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    group_id = group.get("group_id", "<unknown>")

    parent = group.get("parent_group")
    if isinstance(parent, str) and parent not in group_ids:
        errors.append(
            ConstructionValidationError(
                f"construction_group_{group_id}_parent_group",
                f"{group_id} parent_group {parent!r} not found",
            )
        )

    for child in group.get("child_groups", []):
        if isinstance(child, str) and child not in group_ids:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_child_group",
                    f"{group_id} child_group {child!r} not found",
                )
            )

    for ref in _collect_subject_group_refs(group):
        if ref not in group_ids:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_subject_group",
                    f"{group_id} subject_group/from_group {ref!r} not found",
                )
            )

    return errors


def validate_parent_child_consistency(groups: list[dict[str, Any]]) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    by_id = {g["group_id"]: g for g in groups if isinstance(g.get("group_id"), str)}

    for group in groups:
        group_id = group.get("group_id", "<unknown>")
        parent_id = group.get("parent_group")
        if not isinstance(parent_id, str):
            continue
        parent = by_id.get(parent_id)
        if not parent:
            continue
        children = parent.get("child_groups", [])
        if group_id not in children:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_parent_child_mismatch",
                    f"{group_id} parent {parent_id} missing child_groups entry",
                )
            )

    return errors


def validate_target_collision_rules(
    contract: dict[str, Any],
    group_ids: set[str],
) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    rules = contract.get("target_collision_rules", [])
    if not isinstance(rules, list):
        return [ConstructionValidationError("target_collision_rules", "target_collision_rules must be list")]

    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        name = rule.get("name", f"rule_{index}")
        if not (COLLISION_RESOLUTION_TYPES & set(rule.keys())):
            errors.append(
                ConstructionValidationError(
                    f"collision_rule_{name}_resolution",
                    f"{name} missing combination/precedence/grouping rule",
                )
            )
        record_group = rule.get("record_group")
        if not isinstance(record_group, str) or record_group not in group_ids:
            errors.append(
                ConstructionValidationError(
                    f"collision_rule_{name}_record_group",
                    f"{name} record_group {record_group!r} not found",
                )
            )
        source_columns = rule.get("source_columns")
        if not isinstance(source_columns, list) or not source_columns:
            errors.append(
                ConstructionValidationError(
                    f"collision_rule_{name}_source_columns",
                    f"{name} missing source_columns list",
                )
            )
    return errors


def validate_mapping_record_groups(
    construction_contract: dict[str, Any],
    mapping_drafts: dict[str, dict[str, Any]],
) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    group_ids = {
        g.get("group_id")
        for g in construction_contract.get("construction_groups", [])
        if isinstance(g, dict) and isinstance(g.get("group_id"), str)
    }
    for draft_name, draft in mapping_drafts.items():
        for index, mapping in enumerate(iter_draft_mappings(draft)):
            record_group = mapping.get("record_group")
            if isinstance(record_group, str) and record_group not in group_ids:
                errors.append(
                    ConstructionValidationError(
                        f"mapping_{draft_name}_{index}_record_group",
                        f"{draft_name}[{index}] record_group {record_group!r} not in construction contract",
                    )
                )
    return errors


def validate_construction_contract(
    contract: dict[str, Any],
    canonical_model: dict[str, Any],
    *,
    schema_index_a: SchemaIndex | None = None,
    schema_index_b: SchemaIndex | None = None,
    canonical_id_contract: dict[str, Any] | None = None,
    mapping_drafts: dict[str, dict[str, Any]] | None = None,
) -> list[ConstructionValidationError]:
    errors: list[ConstructionValidationError] = []
    groups = contract.get("construction_groups", [])
    if not isinstance(groups, list) or not groups:
        return [ConstructionValidationError("construction_groups", "construction_groups required")]

    entity_fields = collect_entity_fields(canonical_model)
    seen_ids: set[str] = set()
    group_dicts: list[dict[str, Any]] = []

    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            errors.append(ConstructionValidationError(f"construction_group_{index}", "group must be mapping"))
            continue
        group_id = group.get("group_id")
        if not isinstance(group_id, str):
            errors.append(ConstructionValidationError(f"construction_group_{index}", "missing group_id"))
            continue
        if group_id in seen_ids:
            errors.append(
                ConstructionValidationError("construction_group_duplicate", f"duplicate group_id {group_id!r}")
            )
        seen_ids.add(group_id)
        group_dicts.append(group)

    for group in group_dicts:
        group_id = group.get("group_id", "<unknown>")

        missing_keys = CONSTRUCTION_GROUP_REQUIRED_KEYS - set(group.keys())
        if missing_keys:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_keys",
                    f"missing keys {sorted(missing_keys)}",
                )
            )

        target = group.get("target_entity")
        if isinstance(target, str) and target not in entity_fields:
            errors.append(
                ConstructionValidationError(
                    f"construction_group_{group_id}_entity",
                    f"unknown target_entity {target!r}",
                )
            )

        identity_rule = group.get("identity_rule", {})
        if isinstance(identity_rule, dict):
            errors.extend(
                validate_identity_algorithm(
                    identity_rule,
                    canonical_id_contract=canonical_id_contract,
                    group_id=group_id,
                )
            )

        errors.extend(validate_provenance_population(group))
        errors.extend(
            validate_construction_group_required_field_coverage(
                group,
                entity_fields=entity_fields,
                entity_required_fields=collect_entity_required_fields(canonical_model),
            )
        )
        errors.extend(validate_construction_group_completeness(group, entity_fields))
        errors.extend(
            validate_group_schema_references(
                group,
                schema_index_a=schema_index_a,
                schema_index_b=schema_index_b,
            )
        )
        errors.extend(validate_group_references(group, seen_ids))

    errors.extend(validate_parent_child_consistency(group_dicts))
    errors.extend(validate_target_collision_rules(contract, seen_ids))

    missing_v07 = V07_REQUIRED_GROUPS - seen_ids
    if missing_v07:
        errors.append(
            ConstructionValidationError(
                "construction_v07_required_groups",
                f"missing required groups {sorted(missing_v07)}",
            )
        )

    if mapping_drafts:
        errors.extend(validate_mapping_record_groups(contract, mapping_drafts))

    if canonical_id_contract:
        for cid_error in validate_canonical_id_contract_document(canonical_id_contract):
            errors.append(ConstructionValidationError(cid_error.name, cid_error.detail))

    return errors
