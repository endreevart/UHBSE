"""Application vs infrastructure relation scope for structural comparison."""

from __future__ import annotations

from typing import Any

INFRASTRUCTURE_SCHEMAS: frozenset[str] = frozenset(
    {"tiger", "tiger_data", "topology", "pg_catalog", "information_schema"}
)
INFRASTRUCTURE_RELATION_NAMES: frozenset[str] = frozenset(
    {"spatial_ref_sys", "geography_columns", "geometry_columns"}
)
INFRASTRUCTURE_RELATIONS: frozenset[tuple[str, str]] = frozenset({("public", "spatial_ref_sys")})

SOURCE_A_APPLICATION_SCHEMAS: frozenset[str] = frozenset({"magerya_api"})
SOURCE_B_APPLICATION_SCHEMAS: frozenset[str] = frozenset({"public", "quest_digital"})

PROFILE_EXTENSION_LABELS: frozenset[str] = frozenset(
    {
        "public.users_profile.user_id",
        "public.profilaxys_profile.user_id",
    }
)


def is_infrastructure_relation(schema: str, name: str) -> bool:
    if schema in INFRASTRUCTURE_SCHEMAS or schema.startswith("pg_"):
        return True
    if (schema, name) in INFRASTRUCTURE_RELATIONS:
        return True
    if name in INFRASTRUCTURE_RELATION_NAMES:
        return True
    return False


def application_relations(profile: dict[str, Any], schemas: frozenset[str]) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for relation in profile.get("relations") or []:
        if relation.get("kind") not in {"table", "materialized_view"}:
            continue
        schema = relation["schema"]
        name = relation["name"]
        if is_infrastructure_relation(schema, name):
            continue
        if schema in schemas:
            relations.append(relation)
    return relations


def shared_relation_names(
    profile_a: dict[str, Any],
    profile_b: dict[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    app_a = application_relations(profile_a, SOURCE_A_APPLICATION_SCHEMAS)
    app_b = application_relations(profile_b, SOURCE_B_APPLICATION_SCHEMAS)
    infra_a = [
        r["name"]
        for r in profile_a.get("relations", [])
        if is_infrastructure_relation(r["schema"], r["name"])
    ]
    infra_b = [
        r["name"]
        for r in profile_b.get("relations", [])
        if is_infrastructure_relation(r["schema"], r["name"])
    ]

    names_a = {r["name"] for r in app_a}
    names_b = {r["name"] for r in app_b}
    infra_names_a = set(infra_a)
    infra_names_b = set(infra_b)

    application_shared = sorted(names_a & names_b)
    infrastructure_shared = sorted(infra_names_a & infra_names_b)
    all_shared = sorted(set(application_shared) | set(infrastructure_shared))
    return application_shared, infrastructure_shared, all_shared
