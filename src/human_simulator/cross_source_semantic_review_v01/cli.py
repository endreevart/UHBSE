"""CLI — cross-source-semantic-review v0.1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.cross_source_semantic_review_v01.policy import ARTIFACT_DIR


def dispatch_cross_source_semantic_review(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1":
        from human_simulator.cross_source_semantic_review_v01.orchestrator import run_full

        result = run_full(root, no_publish=bool(getattr(args, "no_publish", True)))
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if command == "verify-v0.1":
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

    if command == "publish-v0.1":
        from human_simulator.cross_source_semantic_review_v01.publish import publish

        result = publish(root)
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return 0

    print(json.dumps({"ok": False, "error": f"unknown command {command}"}))
    return 1
