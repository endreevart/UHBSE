"""Candidate slots from one field value. The source text is not returned."""

from __future__ import annotations

import re
from typing import Any, Iterable

from human_simulator.exposure_source_discovery_v02.textutil import classify_sentinel, pattern_hits
from human_simulator.stage05_gate1b_extractor_pilot_v01.policy import FIELDS

_SHORT = {"NULL", "EMPTY", "PLACEHOLDER", "NEGATIVE_SHORT", "AFFIRMATIVE_SHORT", "BOOLEAN_LIKE", "NUMERIC_ONLY"}
_STOP = {
    "и", "в", "на", "с", "по", "для", "от", "до", "или", "это", "как", "при", "без",
    "таблетки", "таблетка", "капсулы", "капсула", "раствор", "сироп", "мазь", "гель", "капли", "порошок",
}
_SPAN = re.compile(
    r"\d+[.,]?\d*\s*(?:мг|mg|мкг|mcg|мл|ml|ме|iu|капс|таб|капл)"
    r"|раз[а]?\s*(?:в|за)\s*(?:день|сутки|недел)"
    r"|\d\s*р\s*/\s*д"
    r"|натощак|перед\s*сн|во\s*время\s*еды|после\s*еды|до\s*еды|once|twice|daily"
    r"|\d+\s*(?:дн|дней|день|нед|недел|мес|месяц)|курс|week|month",
    re.I,
)
_TOKEN = re.compile(r"[0-9a-zа-я]+", re.I)


def _name_candidate(text: str) -> bool:
    residual = _SPAN.sub(" ", text.lower().replace("ё", "е"))
    return any(len(token) >= 4 and token not in _STOP and not token.isdigit() for token in _TOKEN.findall(residual))


def parse_field(value: str | None, role: str) -> dict[str, Any]:
    kind = classify_sentinel(value)
    short = kind in _SHORT
    hits = set() if short or not value else pattern_hits(value)
    event = role in {"REPLACEMENT", "DISCONTINUATION"} and kind in {"FREE_TEXT_SHORT", "FREE_TEXT_LONG", "OTHER"}
    return {
        "sentinel": kind,
        "dose": "dose_like" in hits,
        "frequency": "frequency_like" in hits,
        "duration": "duration_like" in hits,
        "name_candidate": (not short) and bool(value) and _name_candidate(value),
        "short_not_regimen": kind in {"NEGATIVE_SHORT", "AFFIRMATIVE_SHORT", "BOOLEAN_LIKE"},
        "affirmative_not_confirmed": kind == "AFFIRMATIVE_SHORT",
        "event_stated": event,
        "accepted_administration": False,
        "yes_is_confirmed_intake": False,
        "earlier_than_recommended": False,
    }


def _blank() -> dict[str, int]:
    return {
        "rows": 0,
        "dose_candidate_rows": 0,
        "frequency_candidate_rows": 0,
        "duration_candidate_rows": 0,
        "name_candidate_rows": 0,
        "short_not_regimen_rows": 0,
        "affirmative_not_confirmed_rows": 0,
        "event_stated_rows": 0,
        "accepted_administration_rows": 0,
        "NULL": 0,
        "EMPTY": 0,
        "PLACEHOLDER": 0,
        "NEGATIVE_SHORT": 0,
        "AFFIRMATIVE_SHORT": 0,
        "BOOLEAN_LIKE": 0,
        "NUMERIC_ONLY": 0,
        "FREE_TEXT_SHORT": 0,
        "FREE_TEXT_LONG": 0,
        "OTHER": 0,
    }


def accumulate(rows: Iterable[tuple[Any, ...]]) -> dict[str, Any]:
    fields = {name: {**_blank(), "role": role} for name, role in FIELDS}
    total = 0
    for row in rows:
        total += 1
        if len(row) != len(FIELDS):
            raise ValueError("FIELD_WIDTH")
        for (name, role), value in zip(FIELDS, row, strict=True):
            parsed = parse_field(value if isinstance(value, str) or value is None else str(value), role)
            bucket = fields[name]
            bucket["rows"] += 1
            bucket[parsed["sentinel"]] += 1
            bucket["dose_candidate_rows"] += int(parsed["dose"])
            bucket["frequency_candidate_rows"] += int(parsed["frequency"])
            bucket["duration_candidate_rows"] += int(parsed["duration"])
            bucket["name_candidate_rows"] += int(parsed["name_candidate"])
            bucket["short_not_regimen_rows"] += int(parsed["short_not_regimen"])
            bucket["affirmative_not_confirmed_rows"] += int(parsed["affirmative_not_confirmed"])
            bucket["event_stated_rows"] += int(parsed["event_stated"])
            if parsed["accepted_administration"] or parsed["yes_is_confirmed_intake"] or parsed["earlier_than_recommended"]:
                raise ValueError("WIDENED_CLAIM")
    return {
        "rows": total,
        "fields": fields,
        "drugs_merged_with_vitamins": False,
        "positive_changes_extracted": False,
        "timing_rows_assigned": 0,
        "period_rows_assigned": 0,
        "accepted_administration_rows": 0,
        "source_text_retained": False,
    }
