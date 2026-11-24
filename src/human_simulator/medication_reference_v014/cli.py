"""CLI — intervention cohort discovery v0.1.4."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dispatch_medication_reference_v014(root: Path, command: str, args: Any) -> int:
    root = Path(root).resolve()
    if command == "run-v0.1.4":
        from human_simulator.medication_reference_v014.orchestrator import (
            run_cohort_discovery_v014,
        )

        result = run_cohort_discovery_v014(root)
        print(json.dumps(result["public"], indent=2, ensure_ascii=False, default=str))
        return 0
    if command == "verify-v0.1.4":
        path = (
            root
            / "artifacts/stage-03-intervention-cohort-discovery-v0.1.4"
            / "cohort-discovery-summary.json"
        )
        if not path.is_file():
            print(json.dumps({"ok": False, "reason": "summary_missing"}))
            return 1
        print(path.read_text(encoding="utf-8"))
        return 0
    print(json.dumps({"ok": False, "reason": f"unknown_command:{command}"}))
    return 2
