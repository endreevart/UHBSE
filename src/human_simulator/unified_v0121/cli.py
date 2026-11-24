"""CLI for Unified Source Expansion v0.1.2.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _print(doc: Any) -> None:
    print(json.dumps(doc, indent=2, default=str))


def cmd_run(root: Path, *, full: bool, no_publish: bool) -> int:
    from human_simulator.unified_v0121.orchestrator import run_v0121

    if not full:
        _print({"error": "full mode required; pass --full"})
        return 2
    result = run_v0121(root, no_publish=no_publish)
    _print(result)
    if result.get("baseline_ok") is False:
        return 1
    return 0


def cmd_verify(root: Path) -> int:
    from human_simulator.unified_v0121.policy import ARTIFACT_DIR, REQUIRED_ARTIFACTS

    art = root / ARTIFACT_DIR
    path = art / "verification.json"
    if not path.is_file():
        _print(
            {
                "error": (
                    "missing verification.json; run "
                    "unified-source-expansion-v0121 run --full first"
                )
            }
        )
        return 1
    doc = json.loads(path.read_text(encoding="utf-8"))
    missing = [n for n in REQUIRED_ARTIFACTS if not (art / n).is_file()]
    doc["verify_missing_artifacts"] = missing
    _print(doc)
    if missing:
        return 1
    return 0


def cmd_publish(root: Path) -> int:
    from human_simulator.unified_v0121.publish import PublicationError, publish_unified_v0121

    try:
        result = publish_unified_v0121(root)
    except PublicationError as exc:
        _print({"error": str(exc)})
        return 1
    _print(result)
    return 0


def dispatch_unified_v0121(root: Path, command: str, args: Any) -> int:
    if command == "run":
        return cmd_run(
            root,
            full=bool(getattr(args, "full", False)),
            no_publish=bool(getattr(args, "no_publish", True)),
        )
    if command == "verify":
        return cmd_verify(root)
    if command == "publish":
        return cmd_publish(root)
    _print({"error": f"unknown unified-source-expansion-v0121 command: {command}"})
    return 2
