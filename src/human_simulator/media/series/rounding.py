"""Reproducible public rounding rules."""

from __future__ import annotations


def thousands_sep(value: int) -> str:
    return f"{int(value):,}"


def round_thousands(value: int) -> str:
    return f"{round(int(value) / 1000)}K"


def round_thousands_1_decimal(value: int) -> str:
    return f"{int(value) / 1000:.1f}K"


def round_millions_2(value: int) -> str:
    return f"{int(value) / 1_000_000:.2f}M"


def exact_int(value: int) -> str:
    return str(int(value))


def hash_prefix(value: str, length: int = 10) -> str:
    text = str(value).strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError("expected 64-char lowercase hex digest")
    return text[:length]


ROUNDERS = {
    "thousands_sep": thousands_sep,
    "round_thousands": round_thousands,
    "round_thousands_1_decimal": round_thousands_1_decimal,
    "round_millions_2": round_millions_2,
    "exact_int": exact_int,
    "none": lambda value: value,
}
