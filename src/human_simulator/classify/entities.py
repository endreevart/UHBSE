"""Candidate clinical entity classification from schema profiles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ENTITY_TYPES: tuple[str, ...] = (
    "patients",
    "visits",
    "doctors",
    "specialties",
    "laboratory_results",
    "diagnoses",
    "prescriptions",
    "medications",
    "procedures",
    "ultrasound_examinations",
    "operations",
    "medical_documents",
    "measurements",
    "appointments",
)


def _patterns(*terms: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rf"(^|_){re.escape(term)}($|_)", re.IGNORECASE) for term in terms)


TECHNICAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"migration",
        r"alembic",
        r"schema_version",
        r"session",
        r"oauth",
        r"token",
        r"job_",
        r"queue",
        r"audit_log",
    )
)

ENTITY_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "patients": _patterns("patient", "patients", "пациент", "client"),
    "visits": _patterns("visit", "visits", "encounter", "прием", "приём", "osmotr"),
    "doctors": _patterns("doctor", "doctors", "physician", "врач", "medic"),
    "specialties": _patterns("specialty", "specialties", "speciality", "spec", "специаль"),
    "laboratory_results": _patterns("lab", "laboratory", "analysis", "analyse", "результат", "laboratory_result"),
    "diagnoses": _patterns("diagnosis", "diagnoses", "diagnostic", "диагн"),
    "prescriptions": _patterns("prescription", "prescriptions", "recipe", "рецепт", "назнач"),
    "medications": _patterns("medication", "medications", "medicine", "drug", "препарат", "лекар"),
    "procedures": _patterns("procedure", "procedures", "manipulation", "процедур"),
    "ultrasound_examinations": _patterns("ultrasound", "uzi", "usg", "sonograph", "ультразв"),
    "operations": _patterns("operation", "operations", "surgery", "operative", "операц"),
    "medical_documents": _patterns("document", "documents", "report", "заключ", "выписк", "protocol"),
    "measurements": _patterns("measurement", "measurements", "vital", "metric", "измер"),
    "appointments": _patterns("appointment", "appointments", "schedule", "booking", "запис"),
}


@dataclass(frozen=True)
class RelationRef:
    schema: str
    name: str
    kind: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.schema, self.name)


class ClassifyEntitiesError(RuntimeError):
    """Raised when classification inputs are missing or invalid."""


def classify_clinical_entities(
    schema_profile: dict[str, Any],
    artifacts_dir: Path,
) -> dict[str, Any]:
    relations = _table_relations(schema_profile)
    fk_edges = _foreign_key_edges(schema_profile)
    columns_by_relation = _columns_by_relation(schema_profile)

    excluded = {_relation_ref(rel).key for rel in relations if _is_technical(rel["name"])}
    assignments: dict[str, list[dict[str, Any]]] = {entity: [] for entity in ENTITY_TYPES}
    matched_keys: set[tuple[str, str]] = set()

    for relation in relations:
        ref = _relation_ref(relation)
        if ref.key in excluded:
            continue

        entity_hits = _match_entity_types(ref.name, columns_by_relation.get(ref.key, []))
        if not entity_hits:
            continue

        fk_evidence = _fk_evidence(ref, fk_edges, relations)
        for entity_type, name_evidence in entity_hits:
            status = "CONFIRMED" if fk_evidence else "LIKELY"
            evidence = list(name_evidence)
            if fk_evidence:
                evidence.extend(fk_evidence)
            assignments[entity_type].append(
                {
                    "schema": ref.schema,
                    "relation": ref.name,
                    "kind": ref.kind,
                    "status": status,
                    "evidence": evidence,
                }
            )
            matched_keys.add(ref.key)

    unknown_relations = [
        _unknown_entry(relation)
        for relation in relations
        if _relation_ref(relation).key not in matched_keys
        and _relation_ref(relation).key not in excluded
    ]
    excluded_relations = [
        {
            "schema": rel["schema"],
            "relation": rel["name"],
            "kind": rel["kind"],
            "status": "EXCLUDED",
            "evidence": [{"type": "name_pattern", "detail": "technical relation name"}],
        }
        for rel in relations
        if _relation_ref(rel).key in excluded
    ]

    result = {
        "classified_at": datetime.now(UTC).isoformat(),
        "entity_types": assignments,
        "excluded_relations": excluded_relations,
        "unknown_relations": unknown_relations,
    }

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _write_entity_candidates(artifacts_dir / "entity-candidates.yaml", result)
    _write_relation_graph(artifacts_dir / "relation-graph.md", relations, fk_edges, assignments)
    _write_unknown_semantics(artifacts_dir / "unknown-semantics.md", unknown_relations, excluded_relations)
    return result


def classify_from_artifacts(repo_root: Path, artifacts_dir: Path | None = None) -> dict[str, Any]:
    root = repo_root
    target = artifacts_dir or (root / "artifacts" / "stage-01")
    profile_path = target / "schema-profile.json"
    if not profile_path.exists():
        raise ClassifyEntitiesError(f"Missing schema profile: {profile_path}")
    with profile_path.open(encoding="utf-8") as handle:
        schema_profile = json.load(handle)
    return classify_clinical_entities(schema_profile, target)


def _table_relations(schema_profile: dict[str, Any]) -> list[dict[str, Any]]:
    relations = schema_profile.get("relations") or []
    return [rel for rel in relations if rel.get("kind") in {"table", "materialized_view"}]


def _relation_ref(relation: dict[str, Any]) -> RelationRef:
    return RelationRef(
        schema=relation["schema"],
        name=relation["name"],
        kind=relation.get("kind", "table"),
    )


def _columns_by_relation(schema_profile: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for column in schema_profile.get("columns", []):
        key = (column["schema"], column["relation"])
        grouped.setdefault(key, []).append(column["name"])
    return grouped


def _foreign_key_edges(schema_profile: dict[str, Any]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for fk in schema_profile.get("foreign_keys", []):
        edges.append(
            {
                "from_schema": fk.get("schema_name") or fk.get("schema"),
                "from_relation": fk.get("relation_name") or fk.get("relation"),
                "from_column": fk.get("column_name") or (fk.get("columns") or [None])[0],
                "to_schema": fk.get("foreign_schema"),
                "to_relation": fk.get("foreign_table"),
                "to_column": fk.get("foreign_column"),
            }
        )
    return [edge for edge in edges if edge["from_relation"] and edge["to_relation"]]


def _is_technical(name: str) -> bool:
    return any(pattern.search(name) for pattern in TECHNICAL_PATTERNS)


def _match_entity_types(
    relation_name: str,
    column_names: list[str],
) -> list[tuple[str, list[dict[str, str]]]]:
    hits: list[tuple[str, list[dict[str, str]]]] = []
    for entity_type, patterns in ENTITY_PATTERNS.items():
        evidence: list[dict[str, str]] = []
        if _matches_any(relation_name, patterns):
            evidence.append(
                {
                    "type": "name_pattern",
                    "detail": f"relation name matches {entity_type} heuristics",
                }
            )
        matching_columns = [col for col in column_names if _matches_any(col, patterns)]
        if matching_columns:
            evidence.append(
                {
                    "type": "column_name_pattern",
                    "detail": f"columns match {entity_type} heuristics: {', '.join(matching_columns[:5])}",
                }
            )
        if evidence:
            hits.append((entity_type, evidence))
    return hits


def _matches_any(value: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    normalized = value.replace("-", "_")
    return any(pattern.search(normalized) for pattern in patterns)


def _fk_evidence(
    ref: RelationRef,
    fk_edges: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    relation_names = {rel["name"] for rel in relations}

    for edge in fk_edges:
        if edge["from_schema"] == ref.schema and edge["from_relation"] == ref.name:
            if edge["to_relation"] in relation_names:
                evidence.append(
                    {
                        "type": "foreign_key",
                        "detail": (
                            f"{edge['from_schema']}.{edge['from_relation']}"
                            f".{edge['from_column']} -> "
                            f"{edge['to_schema']}.{edge['to_relation']}"
                            f".{edge['to_column']}"
                        ),
                    }
                )
        if edge["to_schema"] == ref.schema and edge["to_relation"] == ref.name:
            if edge["from_relation"] in relation_names:
                evidence.append(
                    {
                        "type": "foreign_key",
                        "detail": (
                            f"{edge['from_schema']}.{edge['from_relation']}"
                            f".{edge['from_column']} -> "
                            f"{edge['to_schema']}.{edge['to_relation']}"
                            f".{edge['to_column']}"
                        ),
                    }
                )
    return evidence


def _unknown_entry(relation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": relation["schema"],
        "relation": relation["name"],
        "kind": relation.get("kind", "table"),
        "status": "UNKNOWN",
        "evidence": [{"type": "insufficient_metadata", "detail": "no entity heuristic match"}],
    }


def _write_entity_candidates(path: Path, result: dict[str, Any]) -> None:
    payload = {
        "classified_at": result["classified_at"],
        "entity_types": result["entity_types"],
        "excluded_relations": result["excluded_relations"],
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _write_relation_graph(
    path: Path,
    relations: list[dict[str, Any]],
    fk_edges: list[dict[str, Any]],
    assignments: dict[str, list[dict[str, Any]]],
) -> None:
    candidate_keys = {
        (item["schema"], item["relation"])
        for items in assignments.values()
        for item in items
    }
    lines = [
        "# Relation graph",
        "",
        "Candidate clinical relations and foreign-key edges (schema metadata only).",
        "",
        "```mermaid",
        "flowchart LR",
    ]

    node_ids: dict[tuple[str, str], str] = {}
    for index, key in enumerate(sorted(candidate_keys)):
        node_ids[key] = f"N{index}"
        schema, name = key
        lines.append(f'  {node_ids[key]}["{schema}.{name}"]')

    for edge in fk_edges:
        source = (edge["from_schema"], edge["from_relation"])
        target = (edge["to_schema"], edge["to_relation"])
        if source in node_ids and target in node_ids:
            lines.append(f"  {node_ids[source]} --> {node_ids[target]}")

    if not candidate_keys:
        lines.append("  empty[\"no candidates identified\"]")

    lines.extend(["```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_unknown_semantics(
    path: Path,
    unknown_relations: list[dict[str, Any]],
    excluded_relations: list[dict[str, Any]],
) -> None:
    lines = [
        "# Unknown semantics",
        "",
        "Relations without enough metadata to propose a clinical entity mapping.",
        "Names alone are not treated as confirmed medical meaning.",
        "",
        "## Unknown relations",
        "",
    ]
    if unknown_relations:
        for item in unknown_relations:
            lines.append(f"- `{item['schema']}.{item['relation']}` ({item['kind']}) — **UNKNOWN**")
    else:
        lines.append("- _None._")

    lines.extend(["", "## Excluded relations", ""])
    if excluded_relations:
        for item in excluded_relations:
            lines.append(f"- `{item['schema']}.{item['relation']}` ({item['kind']}) — **EXCLUDED**")
    else:
        lines.append("- _None._")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
