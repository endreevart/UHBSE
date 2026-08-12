"""Derive pilot source read-sets from design construction and mapping contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PILOT_RELATIONS: tuple[str, ...] = (
    "account_patient",
    "appointment_appointment",
    "document_analysisresult",
    "document_analysisresultitem",
)

RELATION_PREFIX = "magerya_api."


@dataclass(frozen=True)
class PilotReadSetValidation:
    relation: str
    read_set: frozenset[str]
    fingerprint_columns: frozenset[str]
    excluded_columns: frozenset[str]
    uncovered: frozenset[str]
    undocumented_fingerprint: frozenset[str]
    undocumented_without_justification: frozenset[str]


def _relation_short(source_relation: str) -> str:
    if source_relation.startswith(RELATION_PREFIX):
        return source_relation.removeprefix(RELATION_PREFIX)
    return source_relation


def _full_relation_name(relation_short: str) -> str:
    return f"{RELATION_PREFIX}{relation_short}"


def _add_subject_resolution_columns(subject_resolution: Any, columns: set[str]) -> None:
    if not isinstance(subject_resolution, dict):
        return
    via_column = subject_resolution.get("via_column")
    if via_column:
        columns.add(str(via_column))
    subject_id = subject_resolution.get("subject_id")
    if isinstance(subject_id, dict):
        nested_via = subject_id.get("via_column")
        if nested_via:
            columns.add(str(nested_via))
        via_field = subject_id.get("via_field")
        if via_field:
            columns.add(str(via_field))


def _add_columns_from_group(group: dict[str, Any], columns: set[str]) -> None:
    columns.add(str(group.get("source_primary_key", "id")))
    for mapped in group.get("mapped_fields", []) or []:
        if isinstance(mapped, dict) and mapped.get("source_column"):
            columns.add(str(mapped["source_column"]))
        if isinstance(mapped, dict):
            for source_column in mapped.get("source_columns", []) or []:
                columns.add(str(source_column))
    _add_subject_resolution_columns(group.get("subject_resolution"), columns)
    relationship_fields = group.get("relationship_fields", {}) or {}
    for spec in relationship_fields.values():
        if isinstance(spec, str) and spec.startswith("via_column."):
            columns.add(spec.split(".", 1)[1])
    collision_policy = group.get("collision_policy")
    if isinstance(collision_policy, dict):
        for policy in collision_policy.values():
            if isinstance(policy, dict):
                for source_column in policy.get("source_columns", []) or []:
                    columns.add(str(source_column))
    timestamp_precedence = group.get("timestamp_precedence", {}) or {}
    for rule in timestamp_precedence.values():
        if isinstance(rule, dict):
            for source_column in rule.get("sources", []) or []:
                columns.add(str(source_column))
    parent_link = group.get("parent_link")
    if isinstance(parent_link, dict) and parent_link.get("field"):
        columns.add(str(parent_link["field"]))


def _extract_read_columns_from_mapping_obj(obj: Any, columns: set[str]) -> None:
    if isinstance(obj, dict):
        for key in ("source_column", "via_column", "via_field", "field"):
            value = obj.get(key)
            if value:
                columns.add(str(value))
        for key in ("source_columns", "sources"):
            for item in obj.get(key) or []:
                columns.add(str(item))
        for value in obj.values():
            _extract_read_columns_from_mapping_obj(value, columns)
    elif isinstance(obj, list):
        for item in obj:
            _extract_read_columns_from_mapping_obj(item, columns)
    elif isinstance(obj, str) and obj.startswith("via_column."):
        columns.add(obj.split(".", 1)[1])


def _columns_from_mapping_draft(source_a_mapping_draft: dict[str, Any]) -> dict[str, set[str]]:
    columns_by_relation: dict[str, set[str]] = {relation: set() for relation in PILOT_RELATIONS}
    for mapping in source_a_mapping_draft.get("mappings", []) or []:
        relation = _relation_short(str(mapping.get("source_relation", "")))
        if relation not in columns_by_relation:
            continue
        _extract_read_columns_from_mapping_obj(mapping, columns_by_relation[relation])
    return columns_by_relation


def _columns_from_pilot_slice(pilot_slice: dict[str, Any]) -> dict[str, set[str]]:
    columns_by_relation: dict[str, set[str]] = {relation: set() for relation in PILOT_RELATIONS}
    for item in pilot_slice.get("source_relation_graph", []) or []:
        relation = _relation_short(str(item.get("source_relation", "")))
        if relation not in columns_by_relation:
            continue
        parent_link = item.get("parent_link")
        if isinstance(parent_link, dict) and parent_link.get("field"):
            columns_by_relation[relation].add(str(parent_link["field"]))
    return columns_by_relation


def compute_pilot_read_set(
    *,
    construction_contract: dict[str, Any],
    source_a_mapping_draft: dict[str, Any],
    pilot_slice: dict[str, Any] | None = None,
) -> dict[str, frozenset[str]]:
    read_sets: dict[str, set[str]] = {relation: set() for relation in PILOT_RELATIONS}
    for group in construction_contract.get("construction_groups", []) or []:
        source_relation = group.get("source_relation", "")
        relation = _relation_short(str(source_relation))
        if relation not in read_sets:
            continue
        if not str(source_relation).startswith(RELATION_PREFIX):
            continue
        _add_columns_from_group(group, read_sets[relation])
    for relation, columns in _columns_from_mapping_draft(source_a_mapping_draft).items():
        read_sets[relation].update(columns)
    if pilot_slice is not None:
        for relation, columns in _columns_from_pilot_slice(pilot_slice).items():
            read_sets[relation].update(columns)
    return {relation: frozenset(columns) for relation, columns in read_sets.items()}


def _excluded_columns_with_justification(exclusions: list[dict[str, Any]] | None) -> tuple[frozenset[str], frozenset[str]]:
    excluded: set[str] = set()
    justified: set[str] = set()
    for item in exclusions or []:
        column = item.get("column")
        if not column:
            continue
        excluded.add(str(column))
        if item.get("reason") and item.get("status"):
            justified.add(str(column))
    undocumented = excluded - justified
    return frozenset(excluded), frozenset(undocumented)


def validate_fingerprint_coverage(
    *,
    construction_contract: dict[str, Any],
    source_a_mapping_draft: dict[str, Any],
    pilot_slice: dict[str, Any],
    fingerprint_contract: dict[str, Any],
) -> list[PilotReadSetValidation]:
    read_sets = compute_pilot_read_set(
        construction_contract=construction_contract,
        source_a_mapping_draft=source_a_mapping_draft,
        pilot_slice=pilot_slice,
    )
    relations = fingerprint_contract.get("relations", {}) or {}
    results: list[PilotReadSetValidation] = []
    for relation in PILOT_RELATIONS:
        relation_spec = relations.get(relation, {})
        fingerprint_columns = frozenset(str(column) for column in relation_spec.get("fingerprint_columns", []) or [])
        excluded_columns, undocumented_exclusions = _excluded_columns_with_justification(
            relation_spec.get("fingerprint_exclusions")
        )
        read_set = read_sets[relation]
        allowed = fingerprint_columns | excluded_columns
        uncovered = read_set - allowed
        undocumented_fingerprint = fingerprint_columns - read_set - excluded_columns
        undocumented_without_justification = undocumented_fingerprint | undocumented_exclusions
        results.append(
            PilotReadSetValidation(
                relation=relation,
                read_set=read_set,
                fingerprint_columns=fingerprint_columns,
                excluded_columns=excluded_columns,
                uncovered=uncovered,
                undocumented_fingerprint=undocumented_fingerprint,
                undocumented_without_justification=undocumented_without_justification,
            )
        )
    return results
