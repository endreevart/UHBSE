"""Accept only the exact 64-character pins. The concatenated string is a negative control."""

from __future__ import annotations

import hashlib
from pathlib import Path

from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import PINS, REJECTED_DECISION_RECORDS_SHA


def pin_accepted(actual: str, claimed: str) -> bool:
    if claimed == REJECTED_DECISION_RECORDS_SHA or actual == REJECTED_DECISION_RECORDS_SHA:
        return False
    if len(claimed) != 64 or len(actual) != 64:
        return False
    return actual == claimed


def verify_files(root: Path) -> dict[str, object]:
    files = []
    ok = True
    for relative, expected in PINS.items():
        path = Path(root) / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        accepted = actual is not None and pin_accepted(actual, expected)
        ok = ok and accepted
        files.append({
            "path": relative,
            "expected_sha256": expected,
            "actual_sha256": actual,
            "accepted": accepted,
        })
    return {
        "ok": ok,
        "rejected_concatenated_pin_accepted": pin_accepted(REJECTED_DECISION_RECORDS_SHA, REJECTED_DECISION_RECORDS_SHA),
        "files": files,
    }
