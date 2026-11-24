"""In-memory text classification. No source values are returned."""

from __future__ import annotations

import hashlib
import re
import statistics
from collections import Counter
from typing import Any, Iterable

PATTERNS: dict[str, re.Pattern[str]] = {
    "dose_like": re.compile(
        r"\d+[.,]?\d*\s*(мг|mg|мкг|mcg|мл|ml|ме\b|iu\b|капс|таб|капл)",
        re.I,
    ),
    "frequency_like": re.compile(
        r"(раз[а]?\s*(в|за)\s*(день|сутки|недел)|\d\s*р\s*/\s*д|натощак|перед\s*сн|"
        r"во\s*время\s*еды|после\s*еды|до\s*еды|once|twice|daily)",
        re.I,
    ),
    "duration_like": re.compile(r"(\d+\s*(дн|дней|день|нед|недел|мес|месяц)|курс|week|month)", re.I),
    "route_like": re.compile(r"(внутрь|перорал|в/м|в/в|внутривен|внутримыш|подкож|наружно|местно)", re.I),
    "supplement_like": re.compile(
        r"(бад|витамин|vitamin|омега|omega|магни|цинк|селен|d3|д3|b12|фолиев|пробиот|коэнзим)",
        re.I,
    ),
}

_NEGATIVE = {"нет", "не", "не принимаю", "не пью", "no", "none", "n", "н", "-", "—", "–"}
_AFFIRMATIVE = {"да", "yes", "есть", "принимаю", "пью"}
_PLACEHOLDER = {"н/д", "нд", "не указано", "нет данных", "не знаю", "...", ".", "x", "х", "xxx", "n/a", "na"}
_COMMON = {
    "и", "в", "на", "с", "по", "для", "от", "до", "или", "это", "как", "при", "без", "the", "and", "for",
}
_FORM = {"таблетки", "таблетка", "капсулы", "капсула", "раствор", "сироп", "мазь", "гель", "капли", "порошок"}
_NONWORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize(text: str) -> str:
    if not text:
        return ""
    return _NONWORD.sub(" ", text.lower().replace("ё", "е")).strip()


def pattern_hits(text: str) -> set[str]:
    return {name for name, pattern in PATTERNS.items() if pattern.search(text)}


def quantiles(values: list[int | float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "p10": None, "p50": None, "p90": None}
    ordered = sorted(values)
    def pick(p: float) -> float:
        return ordered[min(len(ordered) - 1, int(p * (len(ordered) - 1)))]
    return {"n": len(ordered), "p10": pick(0.1), "p50": pick(0.5), "p90": pick(0.9)}


def classify_sentinel(value: str | None) -> str:
    if value is None:
        return "NULL"
    stripped = value.strip()
    if not stripped:
        return "EMPTY"
    norm = normalize(stripped)
    if norm in _PLACEHOLDER or stripped in {".", "-", "—", "–", "..."}:
        return "PLACEHOLDER"
    if norm in _NEGATIVE:
        return "NEGATIVE_SHORT"
    if norm in _AFFIRMATIVE:
        return "AFFIRMATIVE_SHORT"
    if norm in {"true", "false", "0", "1", "да", "нет"}:
        return "BOOLEAN_LIKE"
    if re.fullmatch(r"\d+(?:[.,]\d+)?", stripped):
        return "NUMERIC_ONLY"
    if len(stripped) <= 20:
        return "FREE_TEXT_SHORT"
    if len(stripped) > 20:
        return "FREE_TEXT_LONG"
    return "OTHER"


def sentinel_profile(values: Iterable[str | None]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    total = 0
    for value in values:
        total += 1
        counts[classify_sentinel(value)] += 1
    order = [
        "NULL", "EMPTY", "NEGATIVE_SHORT", "AFFIRMATIVE_SHORT", "BOOLEAN_LIKE",
        "NUMERIC_ONLY", "PLACEHOLDER", "FREE_TEXT_SHORT", "FREE_TEXT_LONG", "OTHER",
    ]
    return {
        "rows": total,
        "classes": {name: counts.get(name, 0) for name in order},
        "fractions": {name: (round(counts.get(name, 0) / total, 4) if total else None) for name in order},
        "semantic_status": "UNKNOWN_PENDING_HUMAN_REVIEW",
    }


def _token_index(names: Iterable[str]) -> dict[str, list[tuple[tuple[str, ...], str]]]:
    index: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    for name in names:
        parts = tuple(name.split())
        if parts:
            index.setdefault(parts[0], []).append((parts, name))
    return index


def _scan_tokens(tokens: list[str], index: dict[str, list[tuple[tuple[str, ...], str]]]) -> list[str]:
    found: list[str] = []
    limit = len(tokens)
    for start, token in enumerate(tokens):
        for parts, name in index.get(token, ()):
            size = len(parts)
            if start + size <= limit and tuple(tokens[start:start + size]) == parts:
                found.append(name)
    return sorted(set(found))


def _alias(name: str) -> str | None:
    tokens = [token for token in name.split() if token not in _FORM]
    alias = " ".join(tokens)
    if alias and alias != name and len(alias) >= 5:
        return alias
    return None


class CatalogMatcher:
    """Candidate matching only. No method accepts a medication identity."""

    def __init__(self, names: list[str]) -> None:
        cleaned = [normalize(name) for name in names if name and normalize(name)]
        self.original_count = len(names)
        groups: dict[str, int] = Counter(cleaned)
        self.collision_groups = sum(1 for count in groups.values() if count > 1)
        self.common_word_terms = sum(1 for name in groups if name in _COMMON or len(name) <= 3)
        self.names = sorted({name for name in groups if len(name) >= 4 and name not in _COMMON})
        self.exact = set(self.names)
        alias_pairs = [(alias, name) for name in self.names if (alias := _alias(name))]
        self.aliases = {alias: name for alias, name in alias_pairs}
        self._names = _token_index(self.names)
        self._alias_index = _token_index(self.aliases)
        payload = "\n".join(sorted(groups)).encode("utf-8")
        self.name_set_sha256 = hashlib.sha256(payload).hexdigest()
        self.normalization = "lower; yo->e; non-letters to space; collapsed whitespace"
        self.provider = "UNKNOWN"
        self.catalog_version = "UNKNOWN"

    def match_text(self, text: str) -> dict[str, Any]:
        norm = normalize(text)
        if not norm:
            return {"exact": False, "boundary": [], "alias": [], "ambiguous": False}
        exact = norm in self.exact
        tokens = norm.split()
        found = _scan_tokens(tokens, self._names)
        alias_hits = _scan_tokens(tokens, self._alias_index)
        short = [name for name in found if len(name) <= 4]
        ambiguous = len(found) > 1 or bool(short)
        return {"exact": exact, "boundary": found, "alias": alias_hits[:5], "ambiguous": ambiguous}

    def summarize(self, texts: Iterable[str]) -> dict[str, Any]:
        exclusive: Counter[str] = Counter()
        method = Counter()
        lengths: list[int] = []
        n = 0
        for text in texts:
            n += 1
            hit = self.match_text(text or "")
            if hit["exact"]:
                method["normalized_exact"] += 1
            if hit["boundary"]:
                method["boundary_aware"] += 1
                lengths.extend(len(name) for name in hit["boundary"])
            if hit["alias"]:
                method["alias_candidate"] += 1
            if hit["ambiguous"]:
                method["ambiguous"] += 1
            if hit["ambiguous"]:
                exclusive["ambiguous"] += 1
            elif hit["exact"]:
                exclusive["normalized_exact"] += 1
            elif hit["boundary"]:
                exclusive["boundary_aware"] += 1
            elif hit["alias"]:
                exclusive["alias_candidate"] += 1
            else:
                exclusive["unmatched"] += 1
        return {
            "texts": n,
            "method_hits": dict(method),
            "exclusive_class": dict(exclusive),
            "matched_term_length": quantiles(lengths),
            "accepted_identity": False,
        }

    def fingerprint(self) -> dict[str, Any]:
        return {
            "entries": self.original_count,
            "matchable_entries": len(self.names),
            "normalization": self.normalization,
            "collision_groups": self.collision_groups,
            "common_word_or_short_terms": self.common_word_terms,
            "provider": self.provider,
            "catalog_version": self.catalog_version,
            "name_set_sha256": self.name_set_sha256,
            "alias_candidates": len(self.aliases),
            "accepted_identity": False,
        }


def empty_profile() -> dict[str, Any]:
    return {"texts": 0, "non_empty": 0, "pattern_texts": {name: 0 for name in PATTERNS}}


def add_profile(profile: dict[str, Any], text: str) -> None:
    profile["texts"] += 1
    if text and text.strip():
        profile["non_empty"] = profile.get("non_empty", 0) + 1
        for name in pattern_hits(text):
            profile["pattern_texts"][name] = profile["pattern_texts"].get(name, 0) + 1


def finish_profile(profile: dict[str, Any]) -> dict[str, Any]:
    texts = profile.get("texts", 0)
    non_empty = profile.get("non_empty", 0)
    return {
        "texts": texts,
        "non_empty": non_empty,
        "non_empty_fraction": round(non_empty / texts, 4) if texts else None,
        "pattern_texts": profile.get("pattern_texts", {}),
        "pattern_fraction_of_non_empty": {
            name: (round(count / non_empty, 4) if non_empty else None)
            for name, count in profile.get("pattern_texts", {}).items()
        },
    }


def mean_or_none(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None
