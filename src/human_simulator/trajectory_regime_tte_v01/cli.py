"""CLI — trajectory-regime-tte v0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.trajectory_regime_tte_v01.policy import ARTIFACT_DIR


def dispatch_trajectory_regime_tte(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1":
        from human_simulator.trajectory_regime_tte_v01.orchestrator import run_full

        result = run_full(root, no_publish=getattr(args, "no_publish", True))
        print(json.dumps({"ok": result.get("ok"), "artifact_dir": result.get("artifact_dir")}))
        return 0 if result.get("ok") else 1
    if command == "verify-v0.1":
        ver = root / ARTIFACT_DIR / "verification.json"
        if not ver.is_file():
            print(json.dumps({"ok": False, "error": "missing verification.json"}))
            return 1
        doc = json.loads(ver.read_text(encoding="utf-8"))
        print(json.dumps(doc, indent=2))
        return 0 if doc.get("ok") else 1
    if command == "publish-v0.1":
        from human_simulator.trajectory_regime_tte_v01.publish import publish

        result = publish(root)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    print(json.dumps({"ok": False, "error": f"unknown {command}"}))
    return 2
