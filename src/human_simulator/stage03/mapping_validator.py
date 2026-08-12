"""Validate source mapping drafts against schema profiles and canonical model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from human_simulator.stage03.constants import DATA_LEVELS, MAPPING_STATUSES
from human_simulator.stage03.model_validator import collect_entity_fields
from human_simulator.stage03.schema_index import SchemaIndex

COLLISION_RESOLUTION_KEYS = frozenset({"combination_rule", "precedence_rule", "grouping_rule"})

FORBIDDEN_CHARACTERISTIC_CODES_WITHOUT_EVIDENCE = frozenset(
    {
        "biological_sex",
        "biological_gender",
        "sex_at_birth",
        "ocp_use",
        "combined_oral_contraceptive",
        "sleep_hours",
        "cigarettes_per_day",
    }
)

CLINICAL_NORMALIZATION_SENSITIVE_COLUMNS = frozenset(
    {"sex", "gender", "kok", "sleep", "cigarettes", "temperature", "pregnant"}
)

FORBIDDEN_CLINICAL_NORMALIZATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"biological[_\s-]?sex", re.IGNORECASE), "biological_sex normalization without evidence"),
    (re.compile(r"biological[_\s-]?gender", re.IGNORECASE), "biological_gender normalization without evidence"),
    (re.compile(r"\bocp\b|combined[_\s-]?oral[_\s-]?contraceptive", re.IGNORECASE), "kok as OCP without semantic confirmation"),
    (re.compile(r"\bhours?\b|hour[_\s-]?count", re.IGNORECASE), "sleep as hours without documentation"),
    (re.compile(r"per[_\s-]?day|daily[_\s-]?count|cigarettes[_\s-]?per", re.IGNORECASE), "cigarettes as per-day count without evidence"),
    (re.compile(r"celsius|°c|deg[_\s-]?c", re.IGNORECASE), "temperature unit °C without storage or conversion evidence"),
)


@dataclass(frozen=True)
class MappingValidationError:
    draft: str
    index: int
    message: str

    def as_text(self) -> str:
        return f"{self.draft}[{self.index}]: {self.message}"


def extract_entity_fields(canonical_model: dict[str, Any]) -> dict[str, frozenset[str]]:
    return collect_entity_fields(canonical_model)


def iter_draft_mappings(draft: dict[str, Any]) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for key in ("mappings", "catalog_mappings"):
        for item in draft.get(key, []):
            if isinstance(item, dict):
                mappings.append(item)
    return mappings


def mapping_source_columns(mapping: dict[str, Any]) -> list[str]:
    if "source_columns" in mapping:
        columns = mapping["source_columns"]
        if isinstance(columns, list):
            return [str(col) for col in columns]
    column = mapping.get("source_column")
    if column is None:
        return []
    return [str(column)]


def _mapping_text_blob(mapping: dict[str, Any]) -> str:
    parts = [
        str(mapping.get("characteristic_code", "")),
        str(mapping.get("transformation", "")),
        str(mapping.get("raw_unit_assignment", "")),
        str(mapping.get("normalized_unit_assignment", "")),
    ]
    return " ".join(parts)


def _clinical_normalization_confirmed(mapping: dict[str, Any]) -> bool:
    return mapping.get("clinical_semantics_confirmed") is True


def validate_clinical_normalization_rules(
    *,
    draft_name: str,
    index: int,
    mapping: dict[str, Any],
) -> list[MappingValidationError]:
    errors: list[MappingValidationError] = []
    columns = mapping_source_columns(mapping)
    entity = mapping.get("canonical_entity")
    characteristic_code = mapping.get("characteristic_code")
    if isinstance(characteristic_code, str) and characteristic_code in FORBIDDEN_CHARACTERISTIC_CODES_WITHOUT_EVIDENCE:
        if not _clinical_normalization_confirmed(mapping):
            errors.append(
                MappingValidationError(
                    draft_name,
                    index,
                    f"characteristic_code {characteristic_code!r} requires confirmed clinical semantics evidence",
                )
            )

    sensitive = any(col in CLINICAL_NORMALIZATION_SENSITIVE_COLUMNS for col in columns)
    if entity == "SubjectCharacteristic" and isinstance(characteristic_code, str):
        if characteristic_code.startswith("biological_") and not _clinical_normalization_confirmed(mapping):
            errors.append(
                MappingValidationError(
                    draft_name,
                    index,
                    f"characteristic_code {characteristic_code!r} implies clinical normalization without evidence",
                )
            )

    if sensitive and not _clinical_normalization_confirmed(mapping):
        blob = _mapping_text_blob(mapping)
        for pattern, message in FORBIDDEN_CLINICAL_NORMALIZATION_PATTERNS:
            if pattern.search(blob):
                errors.append(MappingValidationError(draft_name, index, message))

    if entity == "SubjectCharacteristic":
        field = mapping.get("canonical_field")
        if field == "concept_id" and columns and columns[0] in {"sex", "gender"}:
            if not _clinical_normalization_confirmed(mapping):
                errors.append(
                    MappingValidationError(
                        draft_name,
                        index,
                        "sex/gender concept_id mapping requires separate confirmed normalization evidence",
                    )
                )
        if mapping.get("normalized_unit_assignment") and columns and columns[0] == "temperature":
            if not _clinical_normalization_confirmed(mapping):
                errors.append(
                    MappingValidationError(
                        draft_name,
                        index,
                        "temperature unit assignment forbidden without confirmed storage or conversion evidence",
                    )
                )

    return errors


def validate_mapping_record(
    *,
    draft_name: str,
    index: int,
    mapping: dict[str, Any],
    schema_index: SchemaIndex,
    entity_fields: dict[str, frozenset[str]],
    construction_group_ids: frozenset[str] | None = None,
) -> list[MappingValidationError]:
    errors: list[MappingValidationError] = []

    source_relation = mapping.get("source_relation")
    if not isinstance(source_relation, str) or not source_relation:
        errors.append(MappingValidationError(draft_name, index, "missing source_relation"))
        return errors

    if not schema_index.relation_exists(source_relation):
        errors.append(
            MappingValidationError(draft_name, index, f"unknown source_relation {source_relation!r}")
        )

    columns = mapping_source_columns(mapping)
    if not columns:
        errors.append(MappingValidationError(draft_name, index, "missing source_column or source_columns"))
    for column in columns:
        if column == "*":
            errors.append(MappingValidationError(draft_name, index, "wildcard source_column forbidden"))
        elif not schema_index.column_exists(source_relation, column):
            errors.append(
                MappingValidationError(
                    draft_name,
                    index,
                    f"column {column!r} not in {source_relation}",
                )
            )

    entity = mapping.get("canonical_entity")
    field = mapping.get("canonical_field")
    if not isinstance(entity, str) or entity not in entity_fields:
        errors.append(MappingValidationError(draft_name, index, f"unknown canonical_entity {entity!r}"))
    elif not isinstance(field, str) or field not in entity_fields[entity]:
        errors.append(
            MappingValidationError(
                draft_name,
                index,
                f"canonical_field {field!r} not defined on {entity}",
            )
        )

    record_group = mapping.get("record_group")
    if isinstance(record_group, str) and construction_group_ids is not None:
        if record_group not in construction_group_ids:
            errors.append(
                MappingValidationError(
                    draft_name,
                    index,
                    f"record_group {record_group!r} not in construction contract",
                )
            )

    if entity == "SubjectCharacteristic":
        characteristic_code = mapping.get("characteristic_code")
        if field == "concept_id" and not characteristic_code and mapping.get("concept_id") is None:
            errors.append(
                MappingValidationError(
                    draft_name,
                    index,
                    "SubjectCharacteristic requires characteristic_code or concept_id mapping evidence",
                )
            )
        if field != "concept_id" and not characteristic_code:
            errors.append(
                MappingValidationError(
                    draft_name,
                    index,
                    "SubjectCharacteristic typed value mappings require characteristic_code",
                )
            )

    data_level = mapping.get("data_level")
    if data_level not in DATA_LEVELS:
        errors.append(MappingValidationError(draft_name, index, f"invalid data_level {data_level!r}"))

    status = mapping.get("mapping_status")
    if status not in MAPPING_STATUSES:
        errors.append(MappingValidationError(draft_name, index, f"invalid mapping_status {status!r}"))

    errors.extend(
        validate_clinical_normalization_rules(
            draft_name=draft_name,
            index=index,
            mapping=mapping,
        )
    )

    return errors


def _mapping_collision_key(mapping: dict[str, Any]) -> tuple[str, str, str] | None:
    relation = mapping.get("source_relation")
    entity = mapping.get("canonical_entity")
    field = mapping.get("canonical_field")
    if isinstance(relation, str) and isinstance(entity, str) and isinstance(field, str):
        return relation, entity, field
    return None


def _mapping_has_collision_resolution(mapping: dict[str, Any]) -> bool:
    return bool(COLLISION_RESOLUTION_KEYS & set(mapping.keys()))


def _collision_rule_is_valid(rule: dict[str, Any], actual_columns: set[str], group_ids: frozenset[str]) -> bool:
    if not (COLLISION_RESOLUTION_KEYS & set(rule.keys())):
        return False
    rule_columns = rule.get("source_columns")
    if not isinstance(rule_columns, list):
        return False
    if set(rule_columns) != actual_columns:
        return False
    record_group = rule.get("record_group")
    if not isinstance(record_group, str) or record_group not in group_ids:
        return False
    return True


def validate_mapping_collisions(
    draft_name: str,
    draft: dict[str, Any],
    construction_contract: dict[str, Any] | None = None,
) -> list[MappingValidationError]:
    errors: list[MappingValidationError] = []
    mappings = iter_draft_mappings(draft)

    group_ids: frozenset[str] = frozenset()
    if construction_contract:
        group_ids = frozenset(
            g.get("group_id")
            for g in construction_contract.get("construction_groups", [])
            if isinstance(g, dict) and isinstance(g.get("group_id"), str)
        )

    collision_rules: dict[tuple[str, str, str], dict[str, Any]] = {}
    for rules_source in (
        construction_contract.get("target_collision_rules", []) if construction_contract else [],
        draft.get("target_collision_rules", []) if isinstance(draft.get("target_collision_rules"), list) else [],
    ):
        for rule in rules_source:
            if not isinstance(rule, dict):
                continue
            key = (
                str(rule.get("source_relation", "")),
                str(rule.get("canonical_entity", "")),
                str(rule.get("canonical_field", "")),
            )
            if key[0] and key[1] and key[2]:
                collision_rules[key] = rule

    groups: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = {}
    for index, mapping in enumerate(mappings):
        key = _mapping_collision_key(mapping)
        if key:
            groups.setdefault(key, []).append((index, mapping))

    for key, items in groups.items():
        if len(items) <= 1:
            continue

        actual_columns = set()
        for _, mapping in items:
            actual_columns.update(mapping_source_columns(mapping))

        rule = collision_rules.get(key)
        if rule and _collision_rule_is_valid(rule, actual_columns, group_ids):
            continue

        if all(_mapping_has_collision_resolution(mapping) for _, mapping in items):
            if rule is None:
                continue
            if not _collision_rule_is_valid(rule, actual_columns, group_ids):
                relation, entity, field = key
                indices = [index for index, _ in items]
                if not (COLLISION_RESOLUTION_KEYS & set(rule.keys())):
                    errors.append(
                        MappingValidationError(
                            draft_name,
                            indices[0],
                            f"collision at {relation}.{entity}.{field} indices={indices}: "
                            "target_collision_rule missing resolution rule type",
                        )
                    )
                elif set(rule.get("source_columns", [])) != actual_columns:
                    errors.append(
                        MappingValidationError(
                            draft_name,
                            indices[0],
                            f"collision at {relation}.{entity}.{field} indices={indices}: "
                            f"target_collision_rule source_columns incomplete "
                            f"(expected {sorted(actual_columns)}, got {rule.get('source_columns')})",
                        )
                    )
                elif rule.get("record_group") not in group_ids:
                    errors.append(
                        MappingValidationError(
                            draft_name,
                            indices[0],
                            f"collision at {relation}.{entity}.{field}: "
                            f"record_group {rule.get('record_group')!r} not in construction contract",
                        )
                    )
            continue

        relation, entity, field = key
        indices = [index for index, _ in items]
        if any(mapping.get("record_group") and not _mapping_has_collision_resolution(mapping) for _, mapping in items):
            errors.append(
                MappingValidationError(
                    draft_name,
                    indices[0],
                    f"collision at {relation}.{entity}.{field} indices={indices}: "
                    "record_group alone is not collision resolution; requires "
                    "combination_rule, precedence_rule, grouping_rule, or target_collision_rule",
                )
            )
            continue

        errors.append(
            MappingValidationError(
                draft_name,
                indices[0],
                f"collision at {relation}.{entity}.{field} indices={indices}: "
                "requires combination_rule, precedence_rule, grouping_rule, or target_collision_rule",
            )
        )

    return errors


def validate_mapping_draft(
    draft_name: str,
    draft: dict[str, Any],
    schema_index: SchemaIndex,
    entity_fields: dict[str, frozenset[str]],
    construction_contract: dict[str, Any] | None = None,
) -> list[MappingValidationError]:
    group_ids: frozenset[str] | None = None
    if construction_contract:
        group_ids = frozenset(
            g.get("group_id")
            for g in construction_contract.get("construction_groups", [])
            if isinstance(g, dict) and isinstance(g.get("group_id"), str)
        )

    errors: list[MappingValidationError] = []
    for index, mapping in enumerate(iter_draft_mappings(draft)):
        errors.extend(
            validate_mapping_record(
                draft_name=draft_name,
                index=index,
                mapping=mapping,
                schema_index=schema_index,
                entity_fields=entity_fields,
                construction_group_ids=group_ids,
            )
        )
    errors.extend(validate_mapping_collisions(draft_name, draft, construction_contract))
    return errors
