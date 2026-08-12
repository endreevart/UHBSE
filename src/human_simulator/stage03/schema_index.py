"""Schema profile index for mapping validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchemaIndex:
    """Maps schema.relation keys to column name sets."""

    relations: dict[str, frozenset[str]]
    profile_path: Path

    def relation_exists(self, source_relation: str) -> bool:
        return source_relation in self.relations

    def column_exists(self, source_relation: str, column: str) -> bool:
        return column in self.relations.get(source_relation, frozenset())

    def columns(self, source_relation: str) -> frozenset[str]:
        return self.relations.get(source_relation, frozenset())


def load_schema_index(profile_path: Path) -> SchemaIndex:
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    columns_key = next(
        key
        for key, value in data.items()
        if isinstance(value, list)
        and value
        and isinstance(value[0], dict)
        and "relation" in value[0]
        and "name" in value[0]
    )
    grouped: dict[str, set[str]] = {}
    for entry in data[columns_key]:
        relation_key = f"{entry['schema']}.{entry['relation']}"
        grouped.setdefault(relation_key, set()).add(entry["name"])
    return SchemaIndex(
        relations={key: frozenset(cols) for key, cols in grouped.items()},
        profile_path=profile_path,
    )
