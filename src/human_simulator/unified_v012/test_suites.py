"""Collect regression suite results for Unified Source Expansion v0.1.2 artifacts."""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

SUITES: tuple[tuple[str, str], ...] = (
    (
        "unit/static",
        "uv run --frozen pytest tests/test_unified_source_expansion_v012_unit.py -q",
    ),
    (
        "core regression",
        "uv run --frozen pytest tests/test_core_vertical_slice_v0121.py tests/test_core_vertical_slice_unit.py -q --tb=no",
    ),
    (
        "scientific regression",
        "uv run --frozen pytest tests/test_scientific_data_readiness_unit.py tests/test_scientific_v0111_evidence.py -q --tb=no",
    ),
    (
        "unified regression",
        "uv run --frozen pytest tests/test_unified_source_expansion_unit.py tests/test_unified_source_expansion_v011_unit.py tests/test_unified_source_expansion_v012_unit.py -q --tb=no",
    ),
)


def _parse_pytest_summary(output: str) -> dict[str, Any]:
    # Example: "11 passed in 0.02s" or "2 failed, 9 passed in 1.2s"
    passed = failed = skipped = deselected = collected = selected = 0
    m = re.search(r"(\d+)\s+passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+)\s+failed", output)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+)\s+skipped", output)
    if m:
        skipped = int(m.group(1))
    m = re.search(r"(\d+)\s+deselected", output)
    if m:
        deselected = int(m.group(1))
    m = re.search(r"collected\s+(\d+)", output)
    if m:
        collected = int(m.group(1))
    selected = passed + failed + skipped
    return {
        "collected": collected or selected,
        "selected": selected,
        "deselected": deselected,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }


def run_suite(root: Path, name: str, command: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=root,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    summary = _parse_pytest_summary(out)
    return {
        "suite": name,
        "literal_command": command,
        "exit_code": proc.returncode,
        "duration_s": round(time.perf_counter() - t0, 3),
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        **summary,
        "output_tail": out[-1500:],
    }


def collect_all(root: Path) -> dict[str, Any]:
    suites = [run_suite(root, name, cmd) for name, cmd in SUITES]
    return {
        "suites": {s["suite"]: s for s in suites},
        "all_pass": all(s["exit_code"] == 0 for s in suites),
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    doc = collect_all(root)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "output_tail"} for k, v in doc["suites"].items()}, indent=2))
    raise SystemExit(0 if doc["all_pass"] else 1)
