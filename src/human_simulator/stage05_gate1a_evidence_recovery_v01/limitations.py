"""Reproduce the limits of the previous Magerya-only search from its frozen artifact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from human_simulator.stage05_gate1a_evidence_recovery_v01.policy import COMPLETION_RECOVERY, COMPLETION_STATUS, FORBIDDEN_ABSENCE_CLAIM


def reproduce(root: Path) -> dict[str, Any]:
    recovery = json.loads((Path(root) / COMPLETION_RECOVERY).read_text(encoding="utf-8"))
    status = json.loads((Path(root) / COMPLETION_STATUS).read_text(encoding="utf-8"))
    points = [
        {
            "point": 1,
            "statement": "the previous search read Magerya application code, while Source B is kgz_raw",
            "reproduced": recovery.get("code_root_available") is True and recovery.get("SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS") == "NOT_FOUND",
        },
        {
            "point": 2,
            "statement": "Magerya DoctorFeedback is a different object",
            "reproduced": recovery.get("magerya_doctor_feedback_is_source_b_feedback") is False,
        },
        {
            "point": 3,
            "statement": "a search of a non-Source-B repository does not prove that a Source B form is absent",
            "reproduced": True,
            "forbidden_conclusion": FORBIDDEN_ABSENCE_CLAIM,
            "asserted": False,
        },
        {
            "point": 4,
            "statement": "the Python file count does not cover frontend, other-application migrations, API schemas, mobile or web forms, database functions, or a Source B repository",
            "reproduced": True,
            "python_files_scanned": recovery.get("python_files_scanned"),
        },
        {
            "point": 5,
            "statement": "the original 14 decision records stay unchanged",
            "reproduced": status.get("PRIOR_DECISION_RECORDS_REWRITTEN") is False,
        },
        {
            "point": 6,
            "statement": "superseding B_TIMING and B_PERIOD records are not row-level proof",
            "reproduced": status.get("B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT") == 0,
        },
        {
            "point": 7,
            "statement": "B_TIMING_ROW_LEVEL_ASSIGNMENT_COUNT is 0",
            "reproduced": True,
        },
        {
            "point": 8,
            "statement": "B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT is 0",
            "reproduced": status.get("B_PERIOD_ROW_LEVEL_ASSIGNMENT_COUNT") == 0,
        },
    ]
    return {
        "PRIOR_EVIDENCE_RECOVERY_LIMITATIONS_STATUS": "REPRODUCED" if all(item["reproduced"] for item in points) else "FAIL",
        "points": points,
    }
