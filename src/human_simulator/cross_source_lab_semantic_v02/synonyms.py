"""Approved synonym / analyte token dictionary (evidence attachment only — never auto-ACCEPTED)."""

from __future__ import annotations

import re
from typing import Any

# Analyte family codes used for negative controls and compatibility
ANALYTE_FAMILY: dict[str, str] = {
    "ттг": "tsh",
    "tsh": "tsh",
    "тиреотропн": "tsh",
    "т3св": "free_t3",
    "т3свобод": "free_t3",
    "freet3": "free_t3",
    "трийодтиронинсвобод": "free_t3",
    "т3общ": "total_t3",
    "т3общий": "total_t3",
    "totalt3": "total_t3",
    "т4св": "free_t4",
    "т4свобод": "free_t4",
    "freet4": "free_t4",
    "тироксинсвобод": "free_t4",
    "т4общ": "total_t4",
    "т4общий": "total_t4",
    "totalt4": "total_t4",
    "25ohвитаминд": "vit_d_25oh",
    "витаминд": "vit_d_25oh",
    "ферритин": "ferritin",
    "глюкоза": "glucose",
    "холестерин": "cholesterol",
    "креатинин": "creatinine",
    "алт": "alt",
    "аст": "ast",
    "тг": "triglycerides",
    "лдг": "ldh",
    "лпнп": "ldl",
    "лпвп": "hdl",
    "гемоглобин": "hemoglobin",
    "эритроцит": "rbc",
    "лейкоцит": "wbc",
    "тромбоцит": "plt",
    "пролактин": "prolactin",
    "кортизол": "cortisol",
    "инсулин": "insulin",
    "пса": "psa",
    "среактивн": "crp",
    "срб": "crp",
}

# Explicit synonym pairs: A normalized label → acceptable B name tokens
APPROVED_SYNONYMS: dict[str, list[str]] = {
    "т3св.": ["трийодтиронин свободный", "т3 свободный", "free t3", "ft3"],
    "т3св": ["трийодтиронин свободный", "т3 свободный", "free t3", "ft3"],
    "т4св.": ["тироксин свободный", "т4 свободный", "free t4", "ft4"],
    "т4св": ["тироксин свободный", "т4 свободный", "free t4", "ft4"],
    "ттг": ["тиреотропный гормон", "тиреотропин", "tsh"],
    "25(oh)витаминд": ["25-oh витамин d", "25(oh)d", "vitamin d", "витамин d"],
}

# Hard negative controls: (a_family, b_family) must never align as comparable
NEGATIVE_ANALYTE_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("tsh", "free_t4"),
        ("tsh", "total_t4"),
        ("tsh", "free_t3"),
        ("tsh", "total_t3"),
        ("free_t3", "total_t3"),
        ("free_t4", "total_t4"),
        ("free_t3", "free_t4"),
        ("total_t3", "total_t4"),
    }
)

# Units that indicate non-hormone / wrong dimension for thyroid panels
SECONDS_UNITS = frozenset({"сек.", "сек", "s", "sec", "second", "seconds"})


def normalize_label(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"[\s_\-./()]+", "", t)
    return t


def infer_analyte_family(label: str) -> str | None:
    n = normalize_label(label)
    # longest key match
    best = None
    best_len = 0
    for key, fam in ANALYTE_FAMILY.items():
        if key in n and len(key) > best_len:
            best = fam
            best_len = len(key)
    # free vs total markers
    if best in {"free_t3", "total_t3"} or "т3" in n or "t3" in n:
        if "свобод" in n or "св" in n or "free" in n:
            return "free_t3"
        if "общ" in n or "total" in n:
            return "total_t3"
        if best:
            return best
    if best in {"free_t4", "total_t4"} or "т4" in n or "t4" in n or "тироксин" in n:
        if "свобод" in n or "св" in n or "free" in n:
            return "free_t4"
        if "общ" in n or "total" in n:
            return "total_t4"
        if best:
            return best
    return best


def synonym_hits(a_label: str, b_label: str) -> list[str]:
    a_n = normalize_label(a_label)
    b_low = (b_label or "").lower().replace("ё", "е")
    hits = []
    for key, syns in APPROVED_SYNONYMS.items():
        if normalize_label(key) == a_n or key.replace(".", "") in a_n:
            for syn in syns:
                if syn.lower() in b_low:
                    hits.append(syn)
    return hits


def negative_control_violation(
    *, a_label: str, b_label: str, b_unit: str
) -> str | None:
    a_f = infer_analyte_family(a_label)
    b_f = infer_analyte_family(b_label)
    if a_f and b_f and (a_f, b_f) in NEGATIVE_ANALYTE_PAIRS:
        return f"negative_control:{a_f}!={b_f}"
    if a_f == "tsh" and (b_unit or "").strip().lower() in SECONDS_UNITS:
        return "negative_control:tsh_neq_seconds"
    return None


def token_overlap_too_weak(a_label: str, b_label: str) -> bool:
    """Single shared generic token is insufficient."""
    stop = {
        "гормон",
        "анализ",
        "кровь",
        "сыворотка",
        "тест",
        "total",
        "free",
        "общий",
        "свободный",
    }
    a_toks = set(re.findall(r"[a-zа-я0-9]+", (a_label or "").lower())) - stop
    b_toks = set(re.findall(r"[a-zа-я0-9]+", (b_label or "").lower())) - stop
    shared = a_toks & b_toks
    if len(shared) <= 1 and not synonym_hits(a_label, b_label):
        # allow if analyte family matches strongly via normalize
        if infer_analyte_family(a_label) and infer_analyte_family(a_label) == infer_analyte_family(
            b_label
        ):
            return False
        return len(shared) < 1 or (
            len(shared) == 1 and next(iter(shared)) in {"d", "oh", "25"}
        )
    return False


def dictionary_snapshot() -> dict[str, Any]:
    return {
        "approved_synonym_keys": sorted(APPROVED_SYNONYMS),
        "n_analyte_family_keys": len(ANALYTE_FAMILY),
        "n_negative_pairs": len(NEGATIVE_ANALYTE_PAIRS),
        "never_auto_accepted": True,
    }
