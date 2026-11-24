"""CLI — cross-source-lab-semantic (v0.2 / v0.2.1 / v0.2.1.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dispatch_cross_source_lab_semantic(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()

    if command == "run-v0.2.1.1":
        from human_simulator.cross_source_lab_semantic_v0211.orchestrator import run_full

        result = run_full(root, no_publish=bool(getattr(args, "no_publish", True)))
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if command == "verify-v0.2.1.1":
        from human_simulator.cross_source_lab_semantic_v0211.policy import ARTIFACT_DIR

        path = root / ARTIFACT_DIR / "verification.json"
        if not path.is_file():
            print(json.dumps({"ok": False, "error": "verification.json missing"}))
            return 1
        doc = json.loads(path.read_text(encoding="utf-8"))
        st_path = root / ARTIFACT_DIR / "status-contract.json"
        st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.is_file() else {}
        print(
            json.dumps(
                {"ok": bool(doc.get("ok")), "verification": doc, "status_contract": st},
                indent=2,
                default=str,
                ensure_ascii=False,
            )
        )
        return 0 if doc.get("ok") else 1

    if command == "publish-v0.2.1.1":
        from human_simulator.cross_source_lab_semantic_v0211.publish import publish

        result = publish(root)
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    # Delegate older commands
    from human_simulator.cross_source_lab_semantic_v021.cli import (
        dispatch_cross_source_lab_semantic as dispatch_v021,
    )

    return dispatch_v021(root, command, args)
