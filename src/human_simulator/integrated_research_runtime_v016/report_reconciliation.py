"""Reconcile duplicated statuses between FINAL stage-report and JSON artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_STATUS_LINE = re.compile(r"^- `([A-Z0-9_]+)`=(.*)$")
FORBIDDEN_IN_FINAL = ("PENDING_SCAN", "PENDING_PUBLISH", "Report status: DRAFT")
COMPARE_KEYS = (
    "PUBLIC_DATA_MINIMIZATION_STATUS",
    "PUBLICATION_INTEGRITY_STATUS",
    "FALSEY_FUTURE_FIELD_REJECTION_STATUS",
    "FUTURE_FIELD_PRESENCE_CONTRACT_STATUS",
    "HTTP_EXPLICIT_FIELD_PRESENCE_STATUS",
    "HTTP_FROZEN_ORDINARY_FUTURE_FIELD_MATRIX_STATUS",
    "HTTP_PRESENCE_SCENARIO_IDENTITY_STATUS",
    "FORBIDDEN_REQUEST_MODEL_EXECUTION_AUDIT_STATUS",
    "FINAL_REPORT_STATUS_RECONCILIATION_STATUS",
    "STATE_CONDITIONED_LEP_STATUS",
    "D1_JOINT_DEPENDENCE_STATUS",
    "CROSS_HORIZON_DEPENDENCE_STATUS",
    "PRODUCTION_READINESS",
    "END_TO_END_STATE_CONDITIONED_RUNTIME_STATUS",
    "V015_RUNTIME_FUTURE_FIELD_CONTRACT_STATUS",
    "V015_REVIEW_EVIDENCE_STATUS",
)


def parse_stage_report(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _STATUS_LINE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
        if line.startswith("Report status:"):
            out["Report status"] = line.split(":", 1)[1].strip()
    return out


def reconcile_final_report(
    *,
    report_text: str,
    status: dict[str, Any],
    scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = parse_stage_report(report_text)
    mismatches: list[dict[str, Any]] = []
    pending: list[str] = []
    report_status = parsed.get("Report status") or status.get("Report status")
    if report_status == "FINAL":
        for token in FORBIDDEN_IN_FINAL:
            if token in report_text:
                pending.append(token)
    for key in COMPARE_KEYS:
        if key not in parsed:
            continue
        expected = status.get(key)
        if key == "PUBLIC_DATA_MINIMIZATION_STATUS" and scan:
            expected = scan.get("PUBLIC_DATA_MINIMIZATION_STATUS", expected)
        got = parsed.get(key)
        if expected is not None and str(got) != str(expected):
            mismatches.append({"key": key, "report": got, "authoritative": expected})
    ok = not mismatches and not pending
    return {
        "ok": ok,
        "FINAL_REPORT_STATUS_RECONCILIATION_STATUS": "PASS" if ok else "FAIL",
        "report_status": report_status,
        "mismatches": mismatches,
        "forbidden_tokens_in_final": pending,
        "parsed": parsed,
    }


def assert_artifact_dir_reconciled(art: Path) -> dict[str, Any]:
    report = (art / "stage-report.md").read_text(encoding="utf-8")
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    scan = None
    scan_path = art / "public-privacy-scan.json"
    if scan_path.is_file():
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
    return reconcile_final_report(report_text=report, status=status, scan=scan)
