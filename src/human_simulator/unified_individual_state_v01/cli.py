"""CLI — unified-individual-state v0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_individual_state_v01.policy import ARTIFACT_DIR


def dispatch_unified_individual_state(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1":
        from human_simulator.unified_individual_state_v01.orchestrator import run_full

        result = run_full(root, no_publish=getattr(args, "no_publish", True))
        print(json.dumps({"ok": result.get("ok"), "error": result.get("error")}, indent=2))
        return 0 if result.get("ok") else 1
    if command == "verify-v0.1":
        art = root / ARTIFACT_DIR
        ver = json.loads((art / "verification.json").read_text(encoding="utf-8"))
        st = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
        print(json.dumps({"verification": ver, "status": st}, indent=2, default=str))
        return 0 if ver.get("ok") else 1
    if command == "publish-v0.1":
        from human_simulator.unified_individual_state_v01.publish import publish

        att = publish(root)
        print(json.dumps(att, indent=2))
        return 0 if att.get("ok") else 1
    print(json.dumps({"error": f"unknown command {command}"}))
    return 2
