"""Redaction helpers for credentials and PHI-like values."""

from __future__ import annotations

import re
from re import Pattern

REDACTED = "***REDACTED***"

_CREDENTIAL_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"(postgresql(?:\+[\w]+)?://[^:]+:)([^@]+)(@)", re.IGNORECASE),
    re.compile(r"(password\s*[=:]\s*)(\S+)", re.IGNORECASE),
)

_PHI_PATTERNS: tuple[Pattern[str], ...] = (
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    re.compile(r"\b\+?\d[\d\s\-()]{8,}\d\b"),
    re.compile(r"\b[A-ZА-Я][a-zа-я]+ [A-ZА-Я][a-zа-я]+(?: [A-ZА-Я][a-zа-я]+)?\b"),
)


def redact_credentials(text: str) -> str:
    result = text
    result = _CREDENTIAL_PATTERNS[0].sub(r"\1" + REDACTED + r"\3", result)
    result = _CREDENTIAL_PATTERNS[1].sub(r"\1" + REDACTED, result)
    return result


def redact_phi(text: str) -> str:
    result = text
    for pattern in _PHI_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def redact_dsn(dsn: str) -> str:
    return redact_credentials(dsn)
