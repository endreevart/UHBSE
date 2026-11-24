"""CLI — integrated-runtime v0.1.3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.integrated_research_runtime_v013.policy import ARTIFACT_DIR


def dispatch_integrated_runtime_v013(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1.3":
        from human_simulator.integrated_research_runtime_v013.orchestrator import run_full

        result = run_full(root, no_publish=getattr(args, "no_publish", True))
        print(
            json.dumps(
                {
                    "ok": result.get("ok"),
                    "frozen": result.get("frozen"),
                    "e2e": result.get("e2e"),
                    "artifact_dir": result.get("artifact_dir"),
                }
            )
        )
        return 0 if result.get("ok") else 1
    if command == "open-test-v0.1.3":
        from human_simulator.integrated_research_runtime_v013.orchestrator import open_test

        result = open_test(root)
        print(json.dumps({"ok": result.get("ok"), "artifact_dir": result.get("artifact_dir")}))
        return 0 if result.get("ok") else 1
    if command == "verify-v0.1.3":
        ver = root / ARTIFACT_DIR / "verification.json"
        if not ver.is_file():
            print(json.dumps({"ok": False, "error": "missing verification.json"}))
            return 1
        doc = json.loads(ver.read_text(encoding="utf-8"))
        print(json.dumps(doc, indent=2))
        return 0 if doc.get("ok") else 1
    if command == "publish-v0.1.3":
        from human_simulator.integrated_research_runtime_v013.publish import publish

        result = publish(root)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    print(json.dumps({"ok": False, "error": f"unknown {command}"}))
    return 2
