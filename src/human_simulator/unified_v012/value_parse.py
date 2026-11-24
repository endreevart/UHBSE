"""Deterministic Source B laboratory value parsers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

ParseKind = Literal[
    "empty",
    "plain_integer",
    "plain_decimal_dot",
    "decimal_comma",
    "signed",
    "scientific",
    "less_than",
    "greater_than",
    "range",
    "with_unit_suffix",
    "other",
    "reject_empty",
    "unsupported",
]


@dataclass(frozen=True)
class ParsedValue:
    kind: ParseKind
    raw: str
    numeric_value: float | None
    text_value: str | None
    comparator: str | None = None
    unit_suffix: str | None = None
    accepted: bool = True
    reject_reason: str | None = None

    @property
    def is_numeric(self) -> bool:
        return self.numeric_value is not None and self.text_value is None

    @property
    def is_text(self) -> bool:
        return self.text_value is not None and self.numeric_value is None

    def xor_ok(self) -> bool:
        """Typed value must be numeric XOR text (exactly one)."""
        if not self.accepted:
            return True  # rejects skip XOR
        return (self.numeric_value is None) != (self.text_value is None)


_RE_EMPTY = re.compile(r"^\s*$")
_RE_PLAIN_INT = re.compile(r"^[+-]?\d+$")
_RE_PLAIN_DOT = re.compile(r"^[+-]?\d+\.\d+$")
_RE_DECIMAL_COMMA = re.compile(r"^[+-]?\d+,\d+$")
_RE_SCIENTIFIC = re.compile(r"^[+-]?\d+(?:[.,]\d+)?[eE][+-]?\d+$")
_RE_LT = re.compile(r"^\s*(?:<|>|≤|≥|<=|>=|&lt;|&gt;)\s*(.+)$", re.I)
_RE_RANGE = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*[-–—]\s*([+-]?\d+(?:[.,]\d+)?)\s*$"
)
_RE_UNIT_SUFFIX = re.compile(
    r"^([+-]?\d+(?:[.,]\d+)?)\s*([A-Za-zµμ%‰/·.\-]+)\s*$"
)


def _to_float(token: str) -> float | None:
    t = token.strip().replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def classify_raw(raw: str | None) -> ParseKind:
    if raw is None or _RE_EMPTY.match(str(raw)):
        return "empty"
    s = str(raw).strip()
    if _RE_SCIENTIFIC.match(s):
        return "scientific"
    if _RE_RANGE.match(s):
        return "range"
    if _RE_LT.match(s) and not _RE_PLAIN_INT.match(s) and not _RE_PLAIN_DOT.match(s):
        # comparator prefix
        m = _RE_LT.match(s)
        if m and not (_RE_PLAIN_INT.match(m.group(1)) or _RE_DECIMAL_COMMA.match(m.group(1))
                      or _RE_PLAIN_DOT.match(m.group(1))):
            # might still be inequality with number
            pass
        if s[0] in "<>≤≥" or s.startswith("<=") or s.startswith(">=") or s.startswith("&lt;") or s.startswith("&gt;"):
            if "<" in s or "&lt;" in s.lower() or "≤" in s or s.startswith("<="):
                return "less_than"
            return "greater_than"
    if _RE_DECIMAL_COMMA.match(s):
        return "decimal_comma"
    if _RE_PLAIN_DOT.match(s):
        return "plain_decimal_dot"
    if _RE_PLAIN_INT.match(s):
        return "plain_integer"
    if _RE_UNIT_SUFFIX.match(s):
        return "with_unit_suffix"
    if s.startswith("+") or (s.startswith("-") and any(c.isdigit() for c in s[1:])):
        if _RE_DECIMAL_COMMA.match(s) or _RE_PLAIN_DOT.match(s) or _RE_PLAIN_INT.match(s):
            return "signed"
    return "other"


def parse_lab_value(raw: str | None) -> ParsedValue:
    """Deterministic parser — never silently strip inequalities/ranges into floats."""
    if raw is None or _RE_EMPTY.match(str(raw)):
        return ParsedValue(
            kind="reject_empty",
            raw="" if raw is None else str(raw),
            numeric_value=None,
            text_value=None,
            accepted=False,
            reject_reason="EMPTY_VALUE",
        )
    s = str(raw).strip()
    kind = classify_raw(s)

    if kind == "empty":
        return ParsedValue(
            kind="reject_empty",
            raw=s,
            numeric_value=None,
            text_value=None,
            accepted=False,
            reject_reason="EMPTY_VALUE",
        )

    if kind in ("plain_integer", "plain_decimal_dot", "decimal_comma", "signed", "scientific"):
        num = _to_float(s)
        if num is None:
            return ParsedValue(
                kind="unsupported",
                raw=s,
                numeric_value=None,
                text_value=None,
                accepted=False,
                reject_reason="UNSUPPORTED_NUMERIC_PARSE",
            )
        return ParsedValue(kind=kind, raw=s, numeric_value=num, text_value=None)

    if kind in ("less_than", "greater_than"):
        # Preserve comparator in text — do NOT coerce to plain float
        comp = None
        rest = s
        for token, name in (
            ("&lt;", "<"),
            ("&gt;", ">"),
            ("<=", "<="),
            (">=", ">="),
            ("≤", "≤"),
            ("≥", "≥"),
            ("<", "<"),
            (">", ">"),
        ):
            if rest.lower().startswith(token.lower()):
                comp = name
                rest = rest[len(token) :].strip()
                break
        return ParsedValue(
            kind=kind,
            raw=s,
            numeric_value=None,
            text_value=s,  # full raw preserved as text
            comparator=comp,
            accepted=True,
        )

    if kind == "range":
        return ParsedValue(
            kind="range",
            raw=s,
            numeric_value=None,
            text_value=s,
            accepted=True,
        )

    if kind == "with_unit_suffix":
        m = _RE_UNIT_SUFFIX.match(s)
        assert m
        num = _to_float(m.group(1))
        unit = m.group(2)
        if num is None:
            return ParsedValue(
                kind="with_unit_suffix",
                raw=s,
                numeric_value=None,
                text_value=s,
                unit_suffix=unit,
                accepted=True,
            )
        # Prefer numeric + unit_suffix metadata; typed XOR uses numeric
        return ParsedValue(
            kind="with_unit_suffix",
            raw=s,
            numeric_value=num,
            text_value=None,
            unit_suffix=unit,
            accepted=True,
        )

    # other / categorical
    return ParsedValue(
        kind="other",
        raw=s,
        numeric_value=None,
        text_value=s,
        accepted=True,
    )


def resolve_unit(
    *,
    constructor_weight_id: int | None,
    catalog_weight_id: int | None,
    weight_catalog: dict[int, dict[str, Any]],
    value_unit_suffix: str | None = None,
) -> dict[str, Any]:
    """Unit from analyses_weight via weight_id; suffix only as last-resort evidence."""
    wid = constructor_weight_id if constructor_weight_id is not None else catalog_weight_id
    source = (
        "constructor.weight_id"
        if constructor_weight_id is not None
        else ("catalog.weight_id" if catalog_weight_id is not None else None)
    )
    if wid is not None and wid in weight_catalog:
        row = weight_catalog[wid]
        label = row.get("name") or row.get("code") or row.get("name_en") or row.get("code_en")
        return {
            "unit": label,
            "unit_source": source,
            "weight_id": wid,
            "unit_confidence": "CATALOG",
            "conflict": False,
        }
    if value_unit_suffix:
        return {
            "unit": value_unit_suffix,
            "unit_source": "value_suffix_last_resort",
            "weight_id": wid,
            "unit_confidence": "LOW_SUFFIX",
            "conflict": False,
        }
    return {
        "unit": None,
        "unit_source": None,
        "weight_id": wid,
        "unit_confidence": "MISSING",
        "conflict": False,
    }
