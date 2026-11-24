"""CLI for population / multi-outcome / intervention readiness v0.1.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.population_v011.orchestrator import run_full
from human_simulator.population_v011.policy import ARTIFACT_DIR
from human_simulator.population_v011.publish import publish


def dispatch_population_v011(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run":
        if not getattr(args, "full", False):
            print(json.dumps({"error": "require --full"}, indent=2))
            return 2
        result = run_full(root, no_publish=bool(getattr(args, "no_publish", True)))
        print(
            json.dumps(
                {k: v for k, v in result.items() if k != "verification"},
                indent=2,
                default=str,
            )
        )
        return 0 if result.get("ok") else 1
    if command == "verify":
        path = root / ARTIFACT_DIR / "verification.json"
        if not path.is_file():
            print(json.dumps({"error": "verification.json missing"}, indent=2))
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0
    if command == "publish":
        out = publish(root)
        print(json.dumps(out, indent=2))
        return 0
    return 2
