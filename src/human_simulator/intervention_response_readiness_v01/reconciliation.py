"""Full-key reconciliation between FINAL stage-report and status-contract.

Compares every shared uppercase status key. A whitelist is forbidden.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_STATUS_LINE = re.compile(r"^- `([A-Z][A-Z0-9_]+)`=(.*)$")
FORBIDDEN_IN_FINAL = ("PENDING_SCAN", "PENDING_PUBLISH", "Report status: DRAFT")


def parse_stage_report(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        match = _STATUS_LINE.match(stripped)
        if match:
            out[match.group(1)] = match.group(2).strip()
        if stripped.startswith("Report status:"):
            out["Report status"] = stripped.split(":", 1)[1].strip()
    return out


def is_status_key(key: Any) -> bool:
    return isinstance(key, str) and bool(re.fullmatch(r"[A-Z][A-Z0-9_]+", key))


def canon(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return str(value)


def status_keys(status: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in status.items() if is_status_key(k)}


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

    authoritative = dict(status)
    if scan and "PUBLIC_DATA_MINIMIZATION_STATUS" in scan:
        authoritative["PUBLIC_DATA_MINIMIZATION_STATUS"] = scan["PUBLIC_DATA_MINIMIZATION_STATUS"]

    common = sorted(set(parsed) & set(status_keys(authoritative)))
    missing_in_report: list[str] = []
    for key in sorted(status_keys(authoritative)):
        if key not in parsed:
            missing_in_report.append(key)
            continue
        expected = canon(authoritative.get(key))
        got = parsed.get(key, "")
        if got != expected:
            mismatches.append({"key": key, "report": got, "authoritative": expected})

    extra_in_report = sorted(
        k for k in parsed if is_status_key(k) and k not in authoritative and k != "Report status"
    )
    ok = not mismatches and not pending and not missing_in_report
    return {
        "ok": ok,
        "FINAL_REPORT_STATUS_RECONCILIATION_STATUS": "PASS" if ok else "FAIL",
        "report_status": report_status,
        "compared_key_count": len(common),
        "compared_keys": common,
        "mismatches": mismatches,
        "missing_in_report": missing_in_report,
        "extra_in_report": extra_in_report,
        "forbidden_tokens_in_final": pending,
        "comparison_mode": "ALL_COMMON_UPPERCASE_STATUS_KEYS",
    }


def assert_artifact_dir_reconciled(art: Path) -> dict[str, Any]:
    report = (art / "stage-report.md").read_text(encoding="utf-8")
    status = json.loads((art / "status-contract.json").read_text(encoding="utf-8"))
    scan = None
    scan_path = art / "privacy-scan.json"
    if scan_path.is_file():
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
    return reconcile_final_report(report_text=report, status=status, scan=scan)
