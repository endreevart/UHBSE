"""CLI — concept-bounded technical medication pilot v0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dispatch_concept_pilot(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1":
        from human_simulator.concept_pilot_v01.orchestrator import run_full

        n_perm = getattr(args, "n_perm", None)
        result = run_full(
            root,
            no_publish=bool(getattr(args, "no_publish", True)),
            n_perm=n_perm,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("ok") else 1
    if command == "verify-v0.1":
        path = (
            root
            / "artifacts/stage-03-first-concept-bounded-technical-medication-pilot-v0.1"
            / "verification.json"
        )
        if not path.is_file():
            print(json.dumps({"ok": False, "reason": "verification_missing"}))
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0
    if command == "publish-v0.1":
        from human_simulator.concept_pilot_v01.publish import publish

        try:
            result = publish(root)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 1
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0
    print(json.dumps({"ok": False, "reason": f"unknown_command:{command}"}))
    return 2
