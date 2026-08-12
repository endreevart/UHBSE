"""Sanitized artifact safety checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

FORBIDDEN_VERDICT_WITHOUT_PROOF = "LINKAGE_PROVEN"

# Patterns that should not appear in relationship artifacts.
PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:\+7|8)[\s(-]?\d{3}[)\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b"),
    re.compile(r'"first_name"\s*:\s*"[^"]+"'),
    re.compile(r'"last_name"\s*:\s*"[^"]+"'),
    re.compile(r'"birthdate"\s*:\s*"\d{4}-\d{2}-\d{2}"'),
)

HMAC_DIGEST_PATTERN = re.compile(r"\b[a-f0-9]{64}\b")
RAW_ID_LIST_PATTERN = re.compile(r'"patient_ids"\s*:\s*\[')


def validate_relationship_artifacts(artifacts_dir: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in sorted(artifacts_dir.glob("*relationship*")) + sorted(artifacts_dir.glob("*linkage*")):
        if path.suffix not in {".json", ".md"}:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(_scan_text(path.name, text))
    for name in (
        "subject-root-analysis.json",
        "subject-root-analysis.md",
        "relationship-verification-report.json",
        "relationship-query-log.json",
    ):
        path = artifacts_dir / name
        if path.exists():
            findings.extend(_scan_text(path.name, path.read_text(encoding="utf-8")))
    return findings


def _scan_text(filename: str, text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for pattern in PII_PATTERNS:
        if pattern.search(text):
            issues.append({"file": filename, "issue": f"possible PII pattern: {pattern.pattern}"})
    if filename.endswith(".json"):
        if RAW_ID_LIST_PATTERN.search(text):
            issues.append({"file": filename, "issue": "raw patient id list detected"})
        if FORBIDDEN_VERDICT_WITHOUT_PROOF in text:
            payload = json.loads(text)
            if _contains_linkage_proven(payload):
                issues.append({"file": filename, "issue": "LINKAGE_PROVEN verdict present"})
        # HMAC digests should not be stored; allow sha256 manifest lines only in separate manifest file
        if filename != "relationship-manifest.sha256" and HMAC_DIGEST_PATTERN.search(text):
            issues.append({"file": filename, "issue": "64-char hex digest detected (possible HMAC leak)"})
    return issues


def _contains_linkage_proven(obj: object) -> bool:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "verdict" and value == FORBIDDEN_VERDICT_WITHOUT_PROOF:
                return True
            if _contains_linkage_proven(value):
                return True
    elif isinstance(obj, list):
        return any(_contains_linkage_proven(item) for item in obj)
    return False
