"""Read-only SQL validation."""

from __future__ import annotations

import re

_FORBIDDEN = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|TRUNCATE|MERGE|"
    r"CREATE|ALTER|DROP|GRANT|REVOKE|"
    r"COPY\s+\([^)]+\)\s+TO|CALL|EXECUTE"
    r")\b",
    re.IGNORECASE,
)


class ReadOnlyViolationError(ValueError):
    """Raised when SQL is not read-only."""


def assert_readonly(sql: str) -> None:
    """Raise ReadOnlyViolationError if sql contains forbidden statements."""
    stripped = _strip_comments_and_strings(sql)
    if _FORBIDDEN.search(stripped):
        raise ReadOnlyViolationError("SQL contains forbidden write/DDL operations")


def _strip_comments_and_strings(sql: str) -> str:
    """Remove comments and string literals before pattern matching."""
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    no_line = re.sub(r"--[^\n]*", " ", no_block)
    no_strings = re.sub(r"'(?:''|[^'])*'", "''", no_line)
    return no_strings
