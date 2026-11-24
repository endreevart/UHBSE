"""DB connections — reuse v0.3 helpers + canonical."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v03.connections import (
    connect_source_a,
    connect_source_b,
)

__all__ = ["connect_source_a", "connect_source_b", "connect_canonical"]


def connect_canonical(root: Path) -> Any:
    from human_simulator.canonical.connection import canonical_connection
    from human_simulator.canonical.settings import load_canonical_settings

    _ = root  # settings load from repo env
    return canonical_connection(load_canonical_settings())
