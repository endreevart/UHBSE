"""CLI — medication-reference semantic matcher v0.1.2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dispatch_medication_reference_v012(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1.2":
        from human_simulator.medication_reference_v012.orchestrator import (
            run_semantic_matcher_v012,
        )

        result = run_semantic_matcher_v012(root)
        print(json.dumps(result.get("public") or result, indent=2, ensure_ascii=False, default=str))
        return 0
    if command == "verify-v0.1.2":
        path = (
            root
            / "artifacts/stage-03-medication-semantic-matcher-v0.1.2"
            / "semantic-matcher-summary.json"
        )
        if not path.is_file():
            print(json.dumps({"ok": False, "reason": "summary_missing"}))
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0
    print(json.dumps({"ok": False, "reason": f"unknown_command:{command}"}))
    return 2
