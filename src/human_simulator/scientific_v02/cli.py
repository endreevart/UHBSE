"""CLI for scientific baseline v0.2 and shadow transfer v0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _print(doc: Any) -> None:
    print(json.dumps(doc, indent=2, default=str))


def dispatch_scientific_v02(root: Path, command: str, args: Any) -> int:
    if command == "run":
        from human_simulator.scientific_v02.orchestrator import run_full

        if not getattr(args, "full", False):
            _print({"error": "pass --full"})
            return 2
        result = run_full(root, no_publish=bool(getattr(args, "no_publish", True)))
        _print(result)
        return 0 if result.get("baseline_ok") else 1
    if command == "verify":
        from human_simulator.scientific_v02.policy import ARTIFACT_DIR

        path = root / ARTIFACT_DIR / "verification.json"
        if not path.is_file():
            _print({"error": "missing verification.json"})
            return 1
        _print(json.loads(path.read_text()))
        return 0
    _print({"error": f"unknown command {command}"})
    return 2


def dispatch_shadow_v01(root: Path, command: str, args: Any) -> int:
    """Shadow uses artifacts produced by scientific-baseline-v02 run."""
    if command == "run":
        return dispatch_scientific_v02(root, "run", args)
    if command == "verify":
        from human_simulator.scientific_v02.policy import ARTIFACT_DIR

        path = root / ARTIFACT_DIR / "technical-shadow-transfer-results.json"
        if not path.is_file():
            _print({"error": "missing technical-shadow-transfer-results.json; run scientific-baseline-v02 first"})
            return 1
        _print(json.loads(path.read_text()))
        return 0
    _print({"error": f"unknown command {command}"})
    return 2


def dispatch_publish_v02_shadow(root: Path) -> int:
    from human_simulator.scientific_v02.publish import PublicationError, publish

    try:
        result = publish(root)
    except PublicationError as exc:
        _print({"error": str(exc)})
        return 1
    _print(result)
    return 0
