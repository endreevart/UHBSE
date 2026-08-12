"""Candidate clinical entity classification from schema profiles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from human_simulator.classify.data_levels import (
    assign_data_level,
    clinical_domain,
)
from human_simulator.classify.table_roles import (
    APPLICATION_SCHEMAS,
    CURATED_ENTITY_CANDIDATES,
    ROLE_ALLOWED_ENTITY_TYPES,
    assign_table_role,
    is_infrastructure_relation,
    partition_relations,
)

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

CANDIDATE_STATUS = "CANDIDATE"

PROFILE_CANDIDATES: tuple[str, ...] = ("schema-profile.json", "schema-profile-kgz.json")


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
    "patients": _patterns("patient", "patients", "пациент", "client", "persons", "person"),
    "visits": _patterns("visit", "visits", "encounter", "прием", "приём", "osmotr"),
    "doctors": _patterns("doctor", "doctors", "physician", "врач"),
    "specialties": _patterns("specialty", "specialties", "speciality", "spec", "специаль"),
    "laboratory_results": _patterns(
        "lab_result",
        "lab_results",
        "laboratory_result",
        "analyses_constructor",
        "analyses_pool",
        "profilaxys_analyses",
        "analysis_result",
    ),
    "diagnoses": _patterns("diagnosis", "diagnoses", "диагн"),
    "prescriptions": _patterns("prescription", "prescriptions", "recipe", "рецепт", "назнач"),
    "medications": _patterns("medication", "medications", "medicine", "drug", "препарат", "лекар"),
    "procedures": _patterns("procedure", "procedures", "manipulation", "процедур"),
    "ultrasound_examinations": _patterns("ultrasound", "uzi", "usg", "sonograph", "ультразв"),
    "operations": _patterns("operation", "operations", "surgery", "operative", "операц"),
    "medical_documents": _patterns("documents", "medical_document", "заключ", "выписк", "protocol"),
    "measurements": _patterns("measurement", "measurements", "vital", "metric", "измер", "profile"),
    "appointments": _patterns("appointment", "appointments", "schedule", "booking", "запис"),
}

RELATION_ENTITY_BLOCKLIST: dict[str, tuple[re.Pattern[str], ...]] = {
    "laboratory_results": (
        re.compile(r"^lab_addresses$", re.I),
        re.compile(r"^lab_referral", re.I),
        re.compile(r"^analyses_codes$", re.I),
        re.compile(r"^catalog_labs$", re.I),
        re.compile(r"^analyses_labs$", re.I),
        re.compile(r"^analyses_catalog$", re.I),
        re.compile(r"^analyses_weight$", re.I),
        re.compile(r"^profilaxys_analyses$", re.I),
        re.compile(r"^analyses_pool$", re.I),
    ),
    "patients": (re.compile(r"^consultations$", re.I),),
    "doctors": (
        re.compile(r"^consultations$", re.I),
        re.compile(r"^feedback$", re.I),
        re.compile(r"^questionnaire$", re.I),
    ),
    "operations": (
        re.compile(r"^payment_transactions$", re.I),
        re.compile(r"^questionnaire$", re.I),
    ),
    "medical_documents": (
        re.compile(r"^persons$", re.I),
        re.compile(r"^consultations$", re.I),
        re.compile(r"^feedback$", re.I),
        re.compile(r"^questionnaire$", re.I),
        re.compile(r"^payment_transactions$", re.I),
        re.compile(r"^document_types$", re.I),
    ),
    "medications": (
        re.compile(r"^feedback$", re.I),
        re.compile(r"^questionnaire$", re.I),
        re.compile(r"^diagnosis_medicines$", re.I),
    ),
    "diagnoses": (
        re.compile(r"^feedback$", re.I),
        re.compile(r"^questionnaire$", re.I),
        re.compile(r"^diagnosis_", re.I),
    ),
    "visits": (
        re.compile(r"^feedback$", re.I),
        re.compile(r"^questionnaire$", re.I),
        re.compile(r"^users_rating$", re.I),
        re.compile(r"^consultation_service_changes$", re.I),
        re.compile(r"appointmentrequest$", re.I),
        re.compile(r"callbackrequest$", re.I),
        re.compile(r"_appointment_recommendations$", re.I),
    ),
    "appointments": (
        re.compile(r"appointmentrequest$", re.I),
        re.compile(r"callbackrequest$", re.I),
        re.compile(r"_appointment_recommendations$", re.I),
        re.compile(r"^document_", re.I),
        re.compile(r"^chat_", re.I),
        re.compile(r"^payment_", re.I),
        re.compile(r"^notification_", re.I),
        re.compile(r"^diagnosis_", re.I),
    ),
}

COLUMN_ENTITY_EXCLUSIONS: dict[str, tuple[re.Pattern[str], ...]] = {
    "patients": (re.compile(r"^patient_id$", re.I),),
    "doctors": (
        re.compile(r"^doctor_id$", re.I),
        re.compile(r"outside_doctor", re.I),
    ),
    "operations": (re.compile(r"transaction_operation", re.I), re.compile(r"^surgery$", re.I)),
    "medical_documents": (
        re.compile(r"identity_document", re.I),
        re.compile(r"^document_id$", re.I),
        re.compile(r"payment_document", re.I),
    ),
    "laboratory_results": (re.compile(r"^lab_id$", re.I),),
    "visits": (
        re.compile(r"^consultation_id$", re.I),
        re.compile(r"^consultations_id$", re.I),
        re.compile(r"next_consultation_at", re.I),
    ),
    "diagnoses": (re.compile(r"preview_diagnosis", re.I),),
    "medications": (re.compile(r"outside_doctor", re.I),),
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
    *,
    artifact_prefix: str = "",
    application_schemas: frozenset[str] | None = None,
) -> dict[str, Any]:
    relations = _table_relations(schema_profile)
    fk_edges = _foreign_key_edges(schema_profile)
    columns_by_relation = _columns_by_relation(schema_profile)
    row_estimates = _row_estimates_by_relation(schema_profile)

    technical_keys = {
        _relation_ref(rel).key for rel in relations if _is_technical(rel["name"])
    }
    active_application_schemas = application_schemas or APPLICATION_SCHEMAS
    application_relations, infrastructure_relations = partition_relations(
        relations,
        technical_names=technical_keys,
        application_schemas=active_application_schemas,
    )

    table_roles: list[dict[str, Any]] = []
    role_by_key: dict[tuple[str, str], str] = {}
    data_level_by_key: dict[tuple[str, str], str] = {}
    for relation in relations:
        ref = _relation_ref(relation)
        column_names = columns_by_relation.get(ref.key, [])
        role = assign_table_role(
            ref.schema,
            ref.name,
            column_names,
            is_technical_name=ref.key in technical_keys,
        )
        role_by_key[ref.key] = role
        data_level_by_key[ref.key] = assign_data_level(
            ref.schema, ref.name, role, column_names=column_names
        )
        entry: dict[str, Any] = {
            "schema": ref.schema,
            "relation": ref.name,
            "kind": ref.kind,
            "role": role,
            "data_level": data_level_by_key[ref.key],
        }
        domain = clinical_domain(ref.schema, ref.name)
        if domain:
            entry["clinical_domain"] = domain
        table_roles.append(entry)

    assignments: dict[str, list[dict[str, Any]]] = {entity: [] for entity in ENTITY_TYPES}
    matched_keys: set[tuple[str, str]] = set()

    for relation in application_relations:
        ref = _relation_ref(relation)
        role = role_by_key[ref.key]
        if role in {"TECHNICAL", "REFERENCE", "LINK", "WORKFLOW", "UNCLASSIFIED"}:
            curated = CURATED_ENTITY_CANDIDATES.get(ref.key, ())
            entity_hits = [(entity_type, _curated_evidence(entity_type)) for entity_type in curated]
        else:
            entity_hits = _match_entity_types(
                ref.name,
                columns_by_relation.get(ref.key, []),
                role=role,
            )
            curated = CURATED_ENTITY_CANDIDATES.get(ref.key, ())
            existing = {entity_type for entity_type, _ in entity_hits}
            for entity_type in curated:
                if entity_type not in existing:
                    entity_hits.append((entity_type, _curated_evidence(entity_type)))

        if not entity_hits:
            continue

        fk_evidence = _fk_evidence(ref, fk_edges, relations)
        estimated_rows = row_estimates.get(ref.key)
        data_level = data_level_by_key[ref.key]
        domain = clinical_domain(ref.schema, ref.name)
        for entity_type, name_evidence in entity_hits:
            if entity_type not in ROLE_ALLOWED_ENTITY_TYPES.get(role, frozenset()):
                if ref.key not in CURATED_ENTITY_CANDIDATES:
                    continue
            evidence = list(name_evidence)
            evidence.extend(_structural_fk_evidence(ref, fk_edges))
            if fk_evidence:
                evidence.extend(fk_evidence)
            if estimated_rows is not None:
                evidence.append(
                    {
                        "type": "row_estimate",
                        "detail": f"estimated_rows={estimated_rows}",
                    }
                )
                if ref.key == ("quest_digital", "lab_result") and estimated_rows == 0:
                    evidence.append(
                        {
                            "type": "snapshot_note",
                            "detail": "lab_result table empty in current schema snapshot",
                        }
                    )
            candidate: dict[str, Any] = {
                "schema": ref.schema,
                "relation": ref.name,
                "kind": ref.kind,
                "role": role,
                "data_level": data_level,
                "status": CANDIDATE_STATUS,
                "evidence": evidence,
            }
            if domain:
                candidate["clinical_domain"] = domain
            assignments[entity_type].append(candidate)
            matched_keys.add(ref.key)

    unknown_relations = [
        _unknown_entry(relation, role_by_key[_relation_ref(relation).key])
        for relation in application_relations
        if _relation_ref(relation).key not in matched_keys
        and role_by_key[_relation_ref(relation).key] == "UNCLASSIFIED"
    ]
    role_classified_relations = [
        _role_classified_entry(relation, role_by_key, data_level_by_key)
        for relation in application_relations
        if _relation_ref(relation).key not in matched_keys
        and role_by_key[_relation_ref(relation).key] != "UNCLASSIFIED"
    ]
    excluded_relations = [
        {
            "schema": rel["schema"],
            "relation": rel["name"],
            "kind": rel["kind"],
            "role": role_by_key[_relation_ref(rel).key],
            "status": "EXCLUDED",
            "evidence": [{"type": "name_pattern", "detail": "technical relation name"}],
        }
        for rel in relations
        if _relation_ref(rel).key in technical_keys
    ]
    infrastructure_inventory = [
        {
            "schema": rel["schema"],
            "relation": rel["name"],
            "kind": rel.get("kind", "table"),
            "role": "TECHNICAL",
            "status": "INFRASTRUCTURE",
            "evidence": [{"type": "infrastructure", "detail": _infrastructure_reason(rel)}],
        }
        for rel in infrastructure_relations
    ]

    classified_at = datetime.now(UTC).isoformat()
    result = {
        "classified_at": classified_at,
        "application_schemas": sorted(active_application_schemas),
        "table_roles": table_roles,
        "entity_types": assignments,
        "infrastructure_inventory": infrastructure_inventory,
        "role_classified_relations": role_classified_relations,
        "excluded_relations": excluded_relations,
        "unknown_relations": unknown_relations,
    }

    prefix = artifact_prefix
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _write_entity_candidates(artifacts_dir / f"{prefix}entity-candidates.yaml", result)
    _write_relation_graph(
        artifacts_dir / f"{prefix}relation-graph.md",
        application_relations,
        fk_edges,
        assignments,
    )
    _write_unknown_semantics(
        artifacts_dir / f"{prefix}unknown-semantics.md",
        unknown_relations,
        excluded_relations,
        infrastructure_inventory,
        role_classified_relations,
    )
    return result


def classify_from_artifacts(
    repo_root: Path,
    artifacts_dir: Path | None = None,
    *,
    profile_name: str | None = None,
    artifact_prefix: str = "",
) -> dict[str, Any]:
    root = repo_root
    target = artifacts_dir or (root / "artifacts" / "stage-01")
    profile_path = _resolve_profile_path(target, profile_name)
    with profile_path.open(encoding="utf-8") as handle:
        schema_profile = json.load(handle)
    return classify_clinical_entities(
        schema_profile,
        target,
        artifact_prefix=artifact_prefix,
    )


def _resolve_profile_path(target: Path, profile_name: str | None) -> Path:
    if profile_name:
        profile_path = target / profile_name
        if not profile_path.exists():
            raise ClassifyEntitiesError(f"Missing schema profile: {profile_path}")
        return profile_path
    for candidate in PROFILE_CANDIDATES:
        profile_path = target / candidate
        if profile_path.exists():
            return profile_path
    raise ClassifyEntitiesError(
        f"Missing schema profile in {target} (tried: {', '.join(PROFILE_CANDIDATES)})"
    )


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


def _row_estimates_by_relation(schema_profile: dict[str, Any]) -> dict[tuple[str, str], int]:
    grouped: dict[tuple[str, str], int] = {}
    for item in schema_profile.get("row_estimates", []):
        key = (item["schema"], item["relation"])
        grouped[key] = int(item.get("estimated_rows") or 0)
    for item in schema_profile.get("aggregates", []):
        key = (item["schema"], item["relation"])
        if item.get("exact_rows") is not None:
            grouped[key] = int(item["exact_rows"])
        elif key not in grouped:
            grouped[key] = int(item.get("estimated_rows") or 0)
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


def _role_classified_entry(
    relation: dict[str, Any],
    role_by_key: dict[tuple[str, str], str],
    data_level_by_key: dict[tuple[str, str], str],
) -> dict[str, Any]:
    ref = _relation_ref(relation)
    role = role_by_key[ref.key]
    entry: dict[str, Any] = {
        "schema": ref.schema,
        "relation": ref.name,
        "kind": ref.kind,
        "role": role,
        "data_level": data_level_by_key[ref.key],
        "status": role,
        "evidence": [{"type": "table_role", "detail": "classified by table role without entity mapping"}],
    }
    domain = clinical_domain(ref.schema, ref.name)
    if domain:
        entry["clinical_domain"] = domain
    return entry


def _structural_fk_evidence(
    ref: RelationRef,
    fk_edges: list[dict[str, Any]],
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    if ref.key == ("magerya_api", "document_analysisresultitem"):
        for edge in fk_edges:
            if (
                edge["from_schema"] == "magerya_api"
                and edge["from_relation"] == "document_analysisresultitem"
                and edge["from_column"] == "analysis_result_id"
                and edge["to_schema"] == "magerya_api"
                and edge["to_relation"] == "document_analysisresult"
                and edge["to_column"] == "id"
            ):
                evidence.append(
                    {
                        "type": "structural_fk",
                        "detail": (
                            "magerya_api.document_analysisresultitem.analysis_result_id"
                            " -> magerya_api.document_analysisresult.id"
                        ),
                    }
                )
    return evidence


def _curated_evidence(entity_type: str) -> list[dict[str, str]]:
    return [
        {
            "type": "curated_rule",
            "detail": f"curated candidate for {entity_type} based on schema signature",
        }
    ]


def _relation_blocked(relation_name: str, entity_type: str) -> bool:
    blocklist = RELATION_ENTITY_BLOCKLIST.get(entity_type, ())
    normalized = relation_name.replace("-", "_")
    return any(pattern.search(normalized) for pattern in blocklist)


def _column_excluded(column_name: str, entity_type: str) -> bool:
    exclusions = COLUMN_ENTITY_EXCLUSIONS.get(entity_type, ())
    return any(pattern.search(column_name) for pattern in exclusions)


def _is_appointment_link_table(relation_name: str, column_names: list[str]) -> bool:
    normalized = relation_name.replace("-", "_").lower()
    if normalized == "appointment_appointment":
        return False
    column_set = {name.lower() for name in column_names}
    return "appointment_id" in column_set


def _match_entity_types(
    relation_name: str,
    column_names: list[str],
    *,
    role: str,
) -> list[tuple[str, list[dict[str, str]]]]:
    allowed = ROLE_ALLOWED_ENTITY_TYPES.get(role, frozenset())
    hits: list[tuple[str, list[dict[str, str]]]] = []
    for entity_type, patterns in ENTITY_PATTERNS.items():
        if entity_type not in allowed:
            continue
        if _relation_blocked(relation_name, entity_type):
            continue
        if entity_type in {"visits", "appointments"} and _is_appointment_link_table(
            relation_name, column_names
        ):
            continue

        evidence: list[dict[str, str]] = []
        if _matches_any(relation_name, patterns):
            evidence.append(
                {
                    "type": "name_pattern",
                    "detail": f"relation name matches {entity_type} heuristics",
                }
            )
        matching_columns = [
            col
            for col in column_names
            if not _column_excluded(col, entity_type) and _matches_any(col, patterns)
        ]
        if entity_type == "doctors":
            matching_columns = [
                col for col in matching_columns if col.lower() in {"is_doctor"} or col.lower().endswith("_doctor")
            ]
            matching_columns = [
                col for col in matching_columns if not _column_excluded(col, entity_type)
            ]
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
                evidence.append(_fk_detail(edge))
        if edge["to_schema"] == ref.schema and edge["to_relation"] == ref.name:
            if edge["from_relation"] in relation_names:
                evidence.append(_fk_detail(edge))
    return evidence


def _fk_detail(edge: dict[str, Any]) -> dict[str, str]:
    return {
        "type": "foreign_key",
        "detail": (
            f"{edge['from_schema']}.{edge['from_relation']}"
            f".{edge['from_column']} -> "
            f"{edge['to_schema']}.{edge['to_relation']}"
            f".{edge['to_column']}"
        ),
    }


def _unknown_entry(relation: dict[str, Any], role: str) -> dict[str, Any]:
    return {
        "schema": relation["schema"],
        "relation": relation["name"],
        "kind": relation.get("kind", "table"),
        "role": role,
        "status": "UNKNOWN",
        "evidence": [{"type": "insufficient_metadata", "detail": "no entity heuristic match"}],
    }


def _infrastructure_reason(relation: dict[str, Any]) -> str:
    schema = relation["schema"]
    name = relation["name"]
    if is_infrastructure_relation(schema, name):
        if (schema, name) in {("public", "spatial_ref_sys")}:
            return "PostGIS extension table (spatial_ref_sys)"
        if schema in {"tiger", "topology", "tiger_data"}:
            return f"PostGIS extension schema ({schema})"
        if schema.startswith("pg_") or "pg_toast" in name.lower():
            return "PostgreSQL system object"
        return f"infrastructure schema ({schema})"
    return "non-application schema"


def _write_entity_candidates(path: Path, result: dict[str, Any]) -> None:
    payload = {
        "classified_at": result["classified_at"],
        "application_schemas": result["application_schemas"],
        "table_roles": result["table_roles"],
        "entity_types": result["entity_types"],
        "infrastructure_inventory": result["infrastructure_inventory"],
        "role_classified_relations": result["role_classified_relations"],
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
        "Application-schema candidate relations and foreign-key edges (metadata only).",
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
        lines.append('  empty["no candidates identified"]')

    lines.extend(["```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_unknown_semantics(
    path: Path,
    unknown_relations: list[dict[str, Any]],
    excluded_relations: list[dict[str, Any]],
    infrastructure_inventory: list[dict[str, Any]],
    role_classified_relations: list[dict[str, Any]],
) -> None:
    lines = [
        "# Unknown semantics",
        "",
        "Application-schema relations without enough metadata to propose a clinical entity mapping.",
        "Infrastructure/extension objects are tracked separately in `infrastructure_inventory`.",
        "Tables with explicit non-entity roles appear under `role_classified_relations`.",
        "Automatic heuristics never emit CONFIRMED status.",
        "",
        "## Unknown relations (UNCLASSIFIED)",
        "",
    ]
    if unknown_relations:
        for item in unknown_relations:
            lines.append(
                f"- `{item['schema']}.{item['relation']}` ({item['kind']}, role={item['role']}) — **UNKNOWN**"
            )
    else:
        lines.append("- _None._")

    lines.extend(["", "## Role-classified relations (non-entity)", ""])
    if role_classified_relations:
        for item in role_classified_relations:
            lines.append(
                f"- `{item['schema']}.{item['relation']}` ({item['kind']}, role={item['role']}) — **{item['status']}**"
            )
    else:
        lines.append("- _None._")

    lines.extend(["", "## Excluded relations (technical names)", ""])
    if excluded_relations:
        for item in excluded_relations:
            lines.append(
                f"- `{item['schema']}.{item['relation']}` ({item['kind']}, role={item['role']}) — **EXCLUDED**"
            )
    else:
        lines.append("- _None._")

    lines.extend(["", "## Infrastructure inventory", ""])
    if infrastructure_inventory:
        for item in infrastructure_inventory:
            lines.append(
                f"- `{item['schema']}.{item['relation']}` ({item['kind']}) — **INFRASTRUCTURE**"
            )
    else:
        lines.append("- _None._")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
