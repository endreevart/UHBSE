"""Look for a Source B form schema in the Magerya code copy. A miss creates no decision."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from human_simulator.exposure_source_discovery_v022.policy import MAGERYA_CODE_ROOT_DEFAULT, MAGERYA_CODE_ROOT_ENV
from human_simulator.stage05_gate_1a_completion_v01.policy import SOURCE_B_TOKENS

_SKIP = {"_git", "__pycache__", "migrations", "media", "static", "dumps"}


def code_root() -> Path:
    return Path(os.environ.get(MAGERYA_CODE_ROOT_ENV) or MAGERYA_CODE_ROOT_DEFAULT).expanduser()


def search_form_schema(root: Path | None = None) -> dict[str, Any]:
    base = root or code_root()
    apps = base / "apps"
    if not apps.is_dir():
        return {
            "SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS": "CODE_ROOT_UNAVAILABLE",
            "superseding_records_created_from_code": 0,
            "token_hit_count": 0,
        }
    hits: list[dict[str, Any]] = []
    doctor_feedback: list[dict[str, str]] = []
    scanned = 0
    for path in sorted(apps.rglob("*.py")):
        if _SKIP.intersection(path.parts):
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        found = [token for token in SOURCE_B_TOKENS if token in text]
        if found:
            hits.append({"path": path.relative_to(base).as_posix(), "tokens": found})
        if "class DoctorFeedback" in text or "class FeedbackAppointmentSerializer" in text:
            doctor_feedback.append({
                "path": path.relative_to(base).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    return {
        "SOURCE_B_FORM_SCHEMA_RECOVERY_STATUS": "NOT_FOUND" if not hits else "TOKENS_FOUND_NOT_ACCEPTED",
        "code_root_available": True,
        "python_files_scanned": scanned,
        "tokens": list(SOURCE_B_TOKENS),
        "token_hit_count": len(hits),
        "token_hits": hits,
        "magerya_doctor_feedback_files": doctor_feedback,
        "magerya_doctor_feedback_is_source_b_feedback": False,
        "superseding_records_created_from_code": 0,
    }
