"""YAML integrity helpers for planning artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode


class DuplicateKeyError(ValueError):
    pass


def _construct_mapping_without_duplicates(loader: yaml.SafeLoader, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(None, None, f"duplicate key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


class StrictPlanningYamlLoader(yaml.SafeLoader):
    pass


StrictPlanningYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_without_duplicates,
)


def load_planning_yaml(text: str, *, source: str = "<string>") -> Any:
    try:
        return yaml.load(text, Loader=StrictPlanningYamlLoader)
    except ConstructorError as exc:
        raise DuplicateKeyError(f"{source}: {exc}") from exc


def load_planning_yaml_file(path: Path) -> Any:
    return load_planning_yaml(path.read_text(encoding="utf-8"), source=str(path))
