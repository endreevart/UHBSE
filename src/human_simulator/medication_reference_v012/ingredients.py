"""Ingredient lexicon, hard veto families, zero-weight marketing tokens."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from human_simulator.medication_reference_v012.policy import MARKETING_ZERO_WEIGHT_TOKENS

# Canonical ingredient key -> aliases (normalized later)
_INGREDIENT_ALIASES: dict[str, tuple[str, ...]] = {
    "magnesium": ("магний", "magnesium", "глицинат магния", "магне", "magne"),
    "zinc": ("цинк", "zinc", "пиколинат цинка", "цинка"),
    "vitamin_d": (
        "витамин d",
        "витамин d3",
        "vitamin d",
        "vitamin d3",
        "холекальциферол",
        "аквадетрим",
        "aquadetrim",
        "колекальциферол",
    ),
    "vitamin_a": (
        "витамин a",
        "vitamin a",
        "ретинол",
        "ретинола",
        "ретинола ацетат",
    ),
    "vitamin_e": ("витамин e", "vitamin e", "токоферол"),
    "vitamin_c": ("витамин c", "vitamin c", "аскорбин"),
    "iodine": ("йод", "iodine", "йодид", "йодин", "калия йодид"),
    "nitrofural": ("нитрофурал", "фурациллин", "nitrofural", "furacillin"),
    "ursodeoxycholic_acid": (
        "урсодезоксихолевая",
        "урсофальк",
        "урсосан",
        "урдокса",
        "udca",
        "ursodeoxycholic",
    ),
    "levothyroxine": ("эутирокс", "левтотроксин", "левотироксин", "l-тироксин"),
    "desloratadine": ("дезлоратадин", "эриус", "desloratadine"),
    "thiamazole": ("тиамазол", "тирозол"),
    "omeprazole": ("омепразол", "омез"),
    "metformin": ("метформин", "сиофор", "глюкофаж"),
    "iron": ("железо", "мальтофер", "феррум", "железа"),
    "selenium": ("селен", "selenium"),
    "omega3": ("омега-3", "омега 3", "омакор", "omega"),
    "levomekol": ("левомеколь", "диоксометилтетрагидропиримидин", "хлорамфеникол"),
    "mometasone": ("мометазон", "назонекс", "нозефрин"),
    "fluticasone": ("флутиказон", "фликсоназе", "назарел"),
    "albendazole": ("албендазол", "немозол"),
    "magne_b6": ("магне b6", "магне в6", "пиридоксин"),
    "taurine": ("таурин",),
    "inositol": ("инозитол", "инозит"),
    "methylfolate": ("метилфолат", "фолат", "метилтетрагидрофолат"),
    "carnitine": ("карнитин", "l-карнитин", "левокарнитин"),
    "pineamine": ("пинеамин",),
    "monural": ("монурал", "фосфомицин"),
    "augmentin": ("аугментин", "амоксициллин", "клавуланат"),
    "berodual": ("беродуал", "ипратропиум", "фенотерол"),
    "budesonide": ("будесонид", "пульмикорт"),
    "amixin": ("амиксин", "тилорон"),
    "estriol": ("эстриол", "овестин"),
    "vibrocil": ("виброцил",),
    "combinil": ("комбинил",),
    "spectracef": ("спектрацеф", "цефдиторен"),
    "piascledine": ("пиаскледин",),
    "maltofer": ("мальтофер",),
}

# Pairwise incompatible ingredient families (hard veto)
_INCOMPATIBLE_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"vitamin_a", "vitamin_d"}),
        frozenset({"vitamin_a", "vitamin_e"}),
        frozenset({"vitamin_d", "vitamin_e"}),
        frozenset({"magnesium", "zinc"}),
        frozenset({"magnesium", "vitamin_d"}),
        frozenset({"zinc", "vitamin_d"}),
        frozenset({"iodine", "vitamin_d"}),
        frozenset({"carnitine", "ursodeoxycholic_acid"}),
    }
)

_RE_STRENGTH = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>мг|mg|мкг|mcg|г|g|мл|ml|%|МЕ|IU|ме|ед)\b",
    re.IGNORECASE,
)
_RE_FORM = re.compile(
    r"\b(таблетк\w*|капсул\w*|сироп\w*|мазь|крем|гель|спрей|раствор\w*|"
    r"порошок\w*|капли|суспенз\w*|ампул\w*|лиофилизат\w*|гранул\w*|"
    r"инъекц\w*|ингаляц\w*)\b",
    re.IGNORECASE,
)


def normalize_term(s: str) -> str:
    t = unicodedata.normalize("NFKC", str(s)).replace("ё", "е").replace("Ё", "Е")
    t = t.casefold()
    t = re.sub(r"[\"'`«»“”]", "", t)
    t = re.sub(r"[^\w\s+/.-]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def tokenize(s: str) -> list[str]:
    return [t for t in normalize_term(s).split() if t]


def identity_tokens(s: str) -> list[str]:
    """Tokens with marketing/zero-weight tokens removed."""
    return [t for t in tokenize(s) if t not in MARKETING_ZERO_WEIGHT_TOKENS and len(t) >= 2]


def marketing_token_identity_weight(token: str) -> float:
    return 0.0 if normalize_term(token) in MARKETING_ZERO_WEIGHT_TOKENS else 1.0


def detect_ingredients(text: str) -> list[str]:
    nt = normalize_term(text)
    found: list[str] = []
    for key, aliases in _INGREDIENT_ALIASES.items():
        for a in aliases:
            na = normalize_term(a)
            if na and na in nt:
                found.append(key)
                break
    # preserve order, unique
    out: list[str] = []
    seen: set[str] = set()
    for k in found:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def ingredients_incompatible(a: set[str] | list[str], b: set[str] | list[str]) -> bool:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return False
    # different sets that share no overlap and both non-empty may still be OK
    # if they are compatible supplements — hard veto only known incompatible pairs
    for pair in _INCOMPATIBLE_PAIRS:
        if pair <= (sa | sb) and len(pair & sa) == 1 and len(pair & sb) == 1:
            # one side has one member, other side has the other
            if (pair & sa) != (pair & sb):
                return True
    # if disjoint and both have vitamin/mineral keys that conflict pairwise
    for x in sa:
        for y in sb:
            if frozenset({x, y}) in _INCOMPATIBLE_PAIRS:
                return True
    return False


def ingredient_sets_equal(a: list[str], b: list[str]) -> bool:
    return set(a) == set(b) and bool(a)


def ingredient_sets_compatible(src: list[str], prov: list[str]) -> str:
    if not src:
        return "UNKNOWN"
    if not prov:
        return "UNKNOWN"
    if ingredients_incompatible(src, prov):
        return "CONFLICT"
    if set(src) == set(prov):
        return "COMPATIBLE"
    if set(src) <= set(prov) or set(prov) <= set(src):
        # subset — combination vs mono stratification later
        return "PARTIAL"
    if set(src) & set(prov):
        return "PARTIAL"
    return "CONFLICT"


def extract_strengths(text: str) -> list[dict[str, str]]:
    out = []
    for m in _RE_STRENGTH.finditer(text or ""):
        out.append(
            {
                "value": m.group("value").replace(",", "."),
                "unit": m.group("unit").casefold(),
            }
        )
    return out


def extract_forms(text: str) -> list[str]:
    return [m.group(0).casefold() for m in _RE_FORM.finditer(text or "")]


def infer_route(text: str, forms: list[str] | None = None) -> str | None:
    nt = normalize_term(text)
    forms = forms or extract_forms(text)
    if any(
        x in nt
        for x in (
            "наружн",
            "местн",
            "мазь",
            "крем",
            "гель",
            "спрей назальн",
            "для наружного",
        )
    ) or any(
        f.startswith(("мазь", "крем", "гель")) for f in forms
    ):
        if any(x in nt for x in ("внутрь", "перораль", "таблет", "капсул", "капли из пипетки")):
            # mixed — prefer explicit oral drops over topical if oral dosing described
            if "капли" in nt and ("растворить" in nt or "внутрь" in nt or "пипетк" in nt):
                return "oral"
        return "topical"
    if any(x in nt for x in ("инъекц", "внутримышеч", "внутривен", "ампул")):
        return "injectable"
    if any(x in nt for x in ("ингаляц", "небул", "пульмикорт")):
        return "inhalation"
    if any(x in nt for x in ("внутрь", "перораль", "капсул", "таблет", "сироп", "суспенз")):
        return "oral"
    if forms:
        if any(f.startswith(("мазь", "крем", "гель", "спрей")) for f in forms):
            return "topical"
        if any(f.startswith(("таблет", "капсул", "сироп", "суспенз", "капли")) for f in forms):
            return "oral"
    return None


def route_compatible(src: str | None, prov_form: str | None, prov_route: str | None) -> str:
    if not src:
        return "UNKNOWN"
    blob = normalize_term(" ".join(x for x in (prov_form, prov_route) if x))
    if src == "oral":
        if any(x in blob for x in ("наружн", "местн", "мазь", "крем", "гель")) and not any(
            x in blob for x in ("внутрь", "таблет", "капсул", "перораль", "капли для приема")
        ):
            return "CONFLICT"
        return "COMPATIBLE" if blob else "UNKNOWN"
    if src == "topical":
        if any(x in blob for x in ("внутрь", "перораль", "инфуз", "инъекц")) and not any(
            x in blob for x in ("наружн", "местн", "мазь", "крем")
        ):
            return "CONFLICT"
        return "COMPATIBLE" if blob else "UNKNOWN"
    return "UNKNOWN"


def strength_compatible(src: list[dict[str, str]], prov_strength: str | None) -> str:
    if not src or not prov_strength:
        return "UNKNOWN"
    pv = normalize_term(prov_strength)
    for h in src:
        val = normalize_term(h["value"])
        unit = normalize_term(h["unit"])
        if val and val in pv:
            # unit soft check
            if unit and unit[:2] in pv:
                return "COMPATIBLE"
            return "COMPATIBLE"
    return "CONFLICT"


def form_compatible(src_forms: list[str], prov_form: str | None) -> str:
    if not src_forms or not prov_form:
        return "UNKNOWN"
    pf = normalize_term(prov_form)
    # family buckets
    def family(f: str) -> str:
        f = normalize_term(f)
        if f.startswith(("таблет", "таб")):
            return "tablet"
        if f.startswith("капсул"):
            return "capsule"
        if f.startswith(("мазь", "крем", "гель")):
            return "topical_semisolid"
        if f.startswith("спрей"):
            return "spray"
        if f.startswith("капл"):
            return "drops"
        if f.startswith(("раствор", "суспенз", "сироп")):
            return "liquid"
        if f.startswith(("порошок", "гранул", "лиофил")):
            return "powder"
        return f[:8]

    pfam = family(pf)
    for f in src_forms:
        if family(f) == pfam:
            return "COMPATIBLE"
        nf = normalize_term(f)
        if nf and (nf in pf or pf in nf):
            return "COMPATIBLE"
    return "CONFLICT"


def provider_text_ingredients(trade: str | None, inn: str | None, *extra: str) -> list[str]:
    blob = " ".join(x for x in (trade, inn, *extra) if x)
    return detect_ingredients(blob)


def alias_lookup_keys() -> dict[str, list[str]]:
    """canonical -> normalized alias strings for index probing."""
    out: dict[str, list[str]] = {}
    for key, aliases in _INGREDIENT_ALIASES.items():
        out[key] = [normalize_term(a) for a in aliases if normalize_term(a)]
    return out


def hard_veto_explanation(
    *,
    src_ings: list[str],
    prov_ings: list[str],
    route_c: str,
    form_c: str,
    strength_c: str,
) -> list[str]:
    reasons: list[str] = []
    if ingredients_incompatible(src_ings, prov_ings):
        reasons.append(
            f"ingredient_family_conflict:source={sorted(src_ings)}:provider={sorted(prov_ings)}"
        )
    if route_c == "CONFLICT":
        reasons.append("route_incompatible")
    if form_c == "CONFLICT":
        reasons.append("form_incompatible")
    if strength_c == "CONFLICT":
        reasons.append("strength_incompatible")
    return reasons


def lexicon_snapshot() -> dict[str, Any]:
    return {
        "n_canonical_ingredients": len(_INGREDIENT_ALIASES),
        "n_incompatible_pairs": len(_INCOMPATIBLE_PAIRS),
        "marketing_zero_weight_n": len(MARKETING_ZERO_WEIGHT_TOKENS),
        "pro_token_weight": marketing_token_identity_weight("про"),
    }
