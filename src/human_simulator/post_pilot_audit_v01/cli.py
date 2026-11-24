"""CLI — post-pilot evidence audit v0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dispatch_post_pilot_audit(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1":
        from human_simulator.post_pilot_audit_v01.orchestrator import run_audit

        result = run_audit(root)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("ok") else 1
    if command == "verify-v0.1":
        path = (
            root
            / "artifacts/stage-03-post-pilot-evidence-audit-longitudinal-readiness-v0.1"
            / "verification.json"
        )
        if not path.is_file():
            print(json.dumps({"ok": False, "reason": "verification_missing"}))
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0
    print(json.dumps({"ok": False, "reason": f"unknown_command:{command}"}))
    return 2
