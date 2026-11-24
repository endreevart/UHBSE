"""CLI — unified-research-layer v0.3."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.unified_research_layer_v03.policy import ARTIFACT_DIR


def dispatch_unified_research_layer(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.3":
        from human_simulator.unified_research_layer_v03.orchestrator import run_full

        result = run_full(root, no_publish=bool(getattr(args, "no_publish", True)))
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    if command == "verify-v0.3":
        path = root / ARTIFACT_DIR / "verification.json"
        if not path.is_file():
            print(json.dumps({"ok": False, "error": "verification.json missing"}))
            return 1
        doc = json.loads(path.read_text(encoding="utf-8"))
        st = {}
        st_path = root / ARTIFACT_DIR / "status-contract.json"
        if st_path.is_file():
            st = json.loads(st_path.read_text(encoding="utf-8"))
        print(json.dumps({"ok": bool(doc.get("ok")), "verification": doc, "status_contract": st}, indent=2, default=str))
        return 0 if doc.get("ok") else 1
    if command == "publish-v0.3":
        from human_simulator.unified_research_layer_v03.publish import publish

        result = publish(root)
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    print(json.dumps({"ok": False, "error": f"unknown command {command}"}))
    return 1
